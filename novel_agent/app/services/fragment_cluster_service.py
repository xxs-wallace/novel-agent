from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from itertools import combinations
import re

from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..repos.fragment_clusters_repo import FragmentClustersRepo
from ..schemas.creative_kb_schema import FragmentCard, FragmentCluster

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")
DEPENDENCY_WEIGHTS = {"low": 1.0, "medium": 0.6, "high": 0.25}
LITERARY_STYLE_HINTS = ("意象", "隐喻", "留白", "抒情", "诗性", "象征")


@dataclass(slots=True)
class NearDuplicateDecision:
    left_fragment_id: str
    right_fragment_id: str
    merge: bool
    merge_score: float
    lexical_similarity: float
    preferred_tags_overlap: float
    content_summary_similarity: float
    emotion_similarity: float
    style_similarity: float
    narrative_overlap: float
    event_overlap: float
    relationship_overlap: float
    boundary_reason: str = ""


@dataclass(slots=True)
class FragmentClusteringResult:
    fragment_cards: list[FragmentCard]
    fragment_clusters: list[FragmentCluster]
    decisions: list[NearDuplicateDecision]


class FragmentClusterService:
    """Rule-based near-duplicate clustering for creative fragment cards."""

    def __init__(
        self,
        *,
        fragment_cards_repo: FragmentCardsRepo | None = None,
        fragment_clusters_repo: FragmentClustersRepo | None = None,
        candidate_similarity_threshold: float = 0.18,
        merge_score_threshold: float = 0.60,
    ) -> None:
        self.fragment_cards_repo = fragment_cards_repo or FragmentCardsRepo()
        self.fragment_clusters_repo = fragment_clusters_repo or FragmentClustersRepo()
        self.candidate_similarity_threshold = candidate_similarity_threshold
        self.merge_score_threshold = merge_score_threshold

    def evaluate_pair(self, left: FragmentCard, right: FragmentCard) -> NearDuplicateDecision:
        lexical_similarity = self._token_overlap(
            self._collect_text_parts(left),
            self._collect_text_parts(right),
        )
        preferred_tags_overlap = self._list_overlap(left.preferred_tags, right.preferred_tags)
        content_summary_similarity = self._token_overlap([left.content_summary], [right.content_summary])
        emotion_similarity = self._token_overlap(
            [left.emotion_mechanism_text, " ".join(left.emotion_tags)],
            [right.emotion_mechanism_text, " ".join(right.emotion_tags)],
        )
        style_similarity = self._token_overlap([left.style_profile_text], [right.style_profile_text])
        narrative_overlap = self._list_overlap(left.narrative_function, right.narrative_function)
        event_overlap = self._list_overlap(left.event_tags, right.event_tags)
        relationship_overlap = self._list_overlap(left.relationship_state, right.relationship_state)

        candidate_score = max(
            lexical_similarity,
            content_summary_similarity,
            preferred_tags_overlap,
            emotion_similarity,
            style_similarity,
            narrative_overlap,
            event_overlap,
        )
        if candidate_score < self.candidate_similarity_threshold:
            return NearDuplicateDecision(
                left_fragment_id=left.fragment_id,
                right_fragment_id=right.fragment_id,
                merge=False,
                merge_score=0.0,
                lexical_similarity=lexical_similarity,
                preferred_tags_overlap=preferred_tags_overlap,
                content_summary_similarity=content_summary_similarity,
                emotion_similarity=emotion_similarity,
                style_similarity=style_similarity,
                narrative_overlap=narrative_overlap,
                event_overlap=event_overlap,
                relationship_overlap=relationship_overlap,
                boundary_reason="below_candidate_threshold",
            )

        boundary_reason = self._get_boundary_reason(
            left=left,
            right=right,
            lexical_similarity=lexical_similarity,
            content_summary_similarity=content_summary_similarity,
            emotion_similarity=emotion_similarity,
            style_similarity=style_similarity,
            preferred_tags_overlap=preferred_tags_overlap,
            narrative_overlap=narrative_overlap,
            event_overlap=event_overlap,
            relationship_overlap=relationship_overlap,
        )
        merge_score = self._merge_score(
            lexical_similarity=lexical_similarity,
            preferred_tags_overlap=preferred_tags_overlap,
            content_summary_similarity=content_summary_similarity,
            emotion_similarity=emotion_similarity,
            style_similarity=style_similarity,
            narrative_overlap=narrative_overlap,
            event_overlap=event_overlap,
            relationship_overlap=relationship_overlap,
        )
        should_merge = not boundary_reason and (
            merge_score >= self.merge_score_threshold
            or self._has_strong_alignment(
                preferred_tags_overlap=preferred_tags_overlap,
                content_summary_similarity=content_summary_similarity,
                emotion_similarity=emotion_similarity,
                style_similarity=style_similarity,
                narrative_overlap=narrative_overlap,
                event_overlap=event_overlap,
                relationship_overlap=relationship_overlap,
            )
        )
        if not should_merge and not boundary_reason:
            boundary_reason = "score_below_threshold"
        return NearDuplicateDecision(
            left_fragment_id=left.fragment_id,
            right_fragment_id=right.fragment_id,
            merge=should_merge,
            merge_score=round(merge_score, 4),
            lexical_similarity=round(lexical_similarity, 4),
            preferred_tags_overlap=round(preferred_tags_overlap, 4),
            content_summary_similarity=round(content_summary_similarity, 4),
            emotion_similarity=round(emotion_similarity, 4),
            style_similarity=round(style_similarity, 4),
            narrative_overlap=round(narrative_overlap, 4),
            event_overlap=round(event_overlap, 4),
            relationship_overlap=round(relationship_overlap, 4),
            boundary_reason=boundary_reason,
        )

    def cluster_cards(self, fragment_cards: list[FragmentCard]) -> FragmentClusteringResult:
        normalized_cards = [
            replace(card, cluster_id=None, is_cluster_representative=False)
            for card in sorted(fragment_cards, key=lambda item: item.fragment_id)
        ]
        if not normalized_cards:
            return FragmentClusteringResult(fragment_cards=[], fragment_clusters=[], decisions=[])

        by_id = {card.fragment_id: card for card in normalized_cards}
        disjoint_set = _DisjointSet(card.fragment_id for card in normalized_cards)
        decisions: list[NearDuplicateDecision] = []

        for left, right in combinations(normalized_cards, 2):
            decision = self.evaluate_pair(left, right)
            decisions.append(decision)
            if decision.merge:
                disjoint_set.union(left.fragment_id, right.fragment_id)

        grouped_ids: dict[str, list[str]] = defaultdict(list)
        for card in normalized_cards:
            grouped_ids[disjoint_set.find(card.fragment_id)].append(card.fragment_id)

        updated_cards: list[FragmentCard] = []
        clusters: list[FragmentCluster] = []
        decisions_by_pair = {
            frozenset((decision.left_fragment_id, decision.right_fragment_id)): decision for decision in decisions
        }
        for member_ids in sorted(grouped_ids.values(), key=lambda items: items[0]):
            members = [by_id[fragment_id] for fragment_id in sorted(member_ids)]
            cluster_id = self._build_cluster_id(members)
            representative = self._select_representative(members)
            cluster = FragmentCluster(
                cluster_id=cluster_id,
                cluster_theme=self._build_cluster_theme(members, representative),
                representative_fragment_id=representative.fragment_id,
                member_count=len(members),
                dedup_reason=self._build_dedup_reason(members, decisions_by_pair),
            )
            clusters.append(cluster)
            for member in members:
                updated_cards.append(
                    replace(
                        member,
                        cluster_id=cluster_id,
                        is_cluster_representative=member.fragment_id == representative.fragment_id,
                    )
                )

        updated_cards.sort(key=lambda item: item.fragment_id)
        clusters.sort(key=lambda item: item.cluster_id)
        return FragmentClusteringResult(
            fragment_cards=updated_cards,
            fragment_clusters=clusters,
            decisions=decisions,
        )

    def cluster_and_persist(
        self,
        conn: sqlite3.Connection,
        *,
        fragment_cards: list[FragmentCard],
    ) -> FragmentClusteringResult:
        result = self.cluster_cards(fragment_cards)
        fragment_ids = [card.fragment_id for card in result.fragment_cards]
        previous_rows = self.fragment_cards_repo.list_by_fragment_ids(conn, fragment_ids=fragment_ids)
        stale_cluster_ids = {card.cluster_id for card in previous_rows if card.cluster_id}

        self.fragment_cards_repo.mark_many_cluster_memberships(
            conn,
            memberships=[
                (
                    card.fragment_id,
                    card.cluster_id,
                    card.is_cluster_representative,
                )
                for card in result.fragment_cards
            ],
        )
        self.fragment_clusters_repo.upsert_clusters(conn, result.fragment_clusters)
        self._cleanup_stale_clusters(
            conn,
            stale_cluster_ids=stale_cluster_ids,
            active_cluster_ids={cluster.cluster_id for cluster in result.fragment_clusters},
        )
        return result

    def _cleanup_stale_clusters(
        self,
        conn: sqlite3.Connection,
        *,
        stale_cluster_ids: set[str],
        active_cluster_ids: set[str],
    ) -> None:
        deletable_cluster_ids: list[str] = []
        for cluster_id in sorted(stale_cluster_ids - active_cluster_ids):
            if not self.fragment_cards_repo.list_by_cluster_id(conn, cluster_id=cluster_id):
                deletable_cluster_ids.append(cluster_id)
        self.fragment_clusters_repo.delete_by_cluster_ids(conn, cluster_ids=deletable_cluster_ids)

    def _get_boundary_reason(
        self,
        *,
        left: FragmentCard,
        right: FragmentCard,
        lexical_similarity: float,
        content_summary_similarity: float,
        emotion_similarity: float,
        style_similarity: float,
        preferred_tags_overlap: float,
        narrative_overlap: float,
        event_overlap: float,
        relationship_overlap: float,
    ) -> str:
        if (
            event_overlap >= 0.50
            and narrative_overlap == 0.0
            and max(emotion_similarity, style_similarity) < 0.30
        ):
            return "same_event_but_different_narrative_function"
        if (
            max(lexical_similarity, content_summary_similarity) < 0.30
            and preferred_tags_overlap >= 0.50
            and event_overlap >= 0.50
            and narrative_overlap < 0.50
            and max(emotion_similarity, style_similarity) < 0.35
        ):
            return "topical_overlap_without_textual_support"
        if (
            left.relationship_state
            and right.relationship_state
            and relationship_overlap == 0.0
            and max(content_summary_similarity, emotion_similarity) < 0.55
        ):
            return "relationship_state_conflict"
        if (
            left.continuity_phase
            and right.continuity_phase
            and left.continuity_phase != right.continuity_phase
            and max(content_summary_similarity, emotion_similarity, style_similarity) < 0.45
        ):
            return "continuity_phase_conflict"
        return ""

    def _merge_score(
        self,
        *,
        lexical_similarity: float,
        preferred_tags_overlap: float,
        content_summary_similarity: float,
        emotion_similarity: float,
        style_similarity: float,
        narrative_overlap: float,
        event_overlap: float,
        relationship_overlap: float,
    ) -> float:
        return (
            lexical_similarity * 0.20
            + preferred_tags_overlap * 0.10
            + content_summary_similarity * 0.25
            + emotion_similarity * 0.18
            + style_similarity * 0.12
            + narrative_overlap * 0.08
            + event_overlap * 0.04
            + relationship_overlap * 0.03
        )

    def _has_strong_alignment(
        self,
        *,
        preferred_tags_overlap: float,
        content_summary_similarity: float,
        emotion_similarity: float,
        style_similarity: float,
        narrative_overlap: float,
        event_overlap: float,
        relationship_overlap: float,
    ) -> bool:
        text_alignment_count = sum(
            1
            for value in (
                content_summary_similarity,
                emotion_similarity,
                style_similarity,
            )
            if value >= 0.22
        )
        return (
            preferred_tags_overlap >= 0.50
            and narrative_overlap >= 0.50
            and event_overlap >= 0.50
            and relationship_overlap >= 0.50
            and text_alignment_count >= 1
            and max(content_summary_similarity, emotion_similarity, style_similarity) >= 0.18
        )

    def _select_representative(self, members: list[FragmentCard]) -> FragmentCard:
        scored: list[tuple[float, FragmentCard]] = []
        for member in members:
            info_completeness = self._info_completeness(member)
            style_representativeness = self._style_representativeness(member, members)
            dependency_weight = DEPENDENCY_WEIGHTS.get(member.context_dependency_level, 0.25)
            literary_penalty = self._literary_dependency_penalty(member)
            score = (
                member.transferability_score * 0.48
                + dependency_weight * 0.22
                + info_completeness * 0.18
                + style_representativeness * 0.12
                - literary_penalty
            )
            scored.append((score, member))
        scored.sort(
            key=lambda item: (
                item[0],
                item[1].transferability_score,
                DEPENDENCY_WEIGHTS.get(item[1].context_dependency_level, 0.0),
                self._info_completeness(item[1]),
                item[1].fragment_id,
            ),
            reverse=True,
        )
        return scored[0][1]

    def _info_completeness(self, member: FragmentCard) -> float:
        signals = [
            member.content_summary,
            member.narrative_function_text,
            member.emotion_mechanism_text,
            member.character_relation_text,
            member.style_profile_text,
            " ".join(member.narrative_function),
            " ".join(member.preferred_tags),
            " ".join(member.relationship_state),
        ]
        present = sum(1 for item in signals if item.strip())
        return present / len(signals)

    def _style_representativeness(self, member: FragmentCard, members: list[FragmentCard]) -> float:
        if len(members) == 1:
            return 1.0
        pair_scores: list[float] = []
        for other in members:
            if other.fragment_id == member.fragment_id:
                continue
            pair_scores.append(
                (
                    self._token_overlap([member.style_profile_text], [other.style_profile_text]) * 0.55
                    + self._token_overlap([member.content_summary], [other.content_summary]) * 0.30
                    + self._token_overlap([member.emotion_mechanism_text], [other.emotion_mechanism_text]) * 0.15
                )
            )
        return sum(pair_scores) / len(pair_scores) if pair_scores else 1.0

    def _literary_dependency_penalty(self, member: FragmentCard) -> float:
        if member.context_dependency_level != "high":
            return 0.0
        richness = 0.0
        style_text = member.style_profile_text
        source_excerpt = member.source_excerpt
        if any(hint in style_text for hint in LITERARY_STYLE_HINTS):
            richness += 0.08
        if member.style_features.imagery_density in {"高", "中高", "high"}:
            richness += 0.08
        if len(style_text) >= 24:
            richness += 0.04
        if len(source_excerpt) >= 180:
            richness += 0.03
        return richness

    def _build_cluster_id(self, members: list[FragmentCard]) -> str:
        key = "|".join(member.fragment_id for member in members)
        return f"cluster-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"

    def _build_cluster_theme(self, members: list[FragmentCard], representative: FragmentCard) -> str:
        parts = [
            *self._most_common_terms(member.preferred_tags for member in members),
            *self._most_common_terms(member.event_tags for member in members),
            *self._most_common_terms(member.narrative_function for member in members),
        ]
        unique_parts = []
        seen: set[str] = set()
        for part in parts:
            if not part or part in seen:
                continue
            unique_parts.append(part)
            seen.add(part)
            if len(unique_parts) >= 3:
                break
        if unique_parts:
            return " / ".join(unique_parts)
        summary = representative.content_summary.strip()
        return summary[:36] if summary else representative.fragment_id

    def _build_dedup_reason(
        self,
        members: list[FragmentCard],
        decisions_by_pair: dict[frozenset[str], NearDuplicateDecision],
    ) -> str:
        if len(members) == 1:
            return "singleton_cluster:no near-duplicate peers"
        merged_pairs: list[NearDuplicateDecision] = []
        for left, right in combinations(members, 2):
            decision = decisions_by_pair.get(frozenset((left.fragment_id, right.fragment_id)))
            if decision is not None and decision.merge:
                merged_pairs.append(decision)
        if not merged_pairs:
            return "connected_component_cluster:transitive near-duplicate chain"
        avg_merge_score = sum(item.merge_score for item in merged_pairs) / len(merged_pairs)
        avg_summary = sum(item.content_summary_similarity for item in merged_pairs) / len(merged_pairs)
        avg_emotion = sum(item.emotion_similarity for item in merged_pairs) / len(merged_pairs)
        avg_style = sum(item.style_similarity for item in merged_pairs) / len(merged_pairs)
        return (
            "near_duplicate_cluster:"
            f"summary={avg_summary:.2f},emotion={avg_emotion:.2f},style={avg_style:.2f},merge={avg_merge_score:.2f}"
        )

    def _most_common_terms(self, groups: list[list[str]]) -> list[str]:
        counter: Counter[str] = Counter()
        for group in groups:
            for item in group:
                text = item.strip()
                if text:
                    counter[text] += 1
        return [item for item, _ in counter.most_common(3)]

    def _collect_text_parts(self, card: FragmentCard) -> list[str]:
        return [
            card.content_summary,
            card.narrative_function_text,
            card.emotion_mechanism_text,
            card.style_profile_text,
        ]

    def _list_overlap(self, left: list[str], right: list[str]) -> float:
        left_set = {item.strip() for item in left if item and item.strip()}
        right_set = {item.strip() for item in right if item and item.strip()}
        if not left_set or not right_set:
            return 0.0
        return len(left_set & right_set) / max(len(left_set), len(right_set))

    def _token_overlap(self, left_parts: list[str], right_parts: list[str]) -> float:
        left_tokens = self._tokenize_parts(left_parts)
        right_tokens = self._tokenize_parts(right_parts)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))

    def _tokenize_parts(self, parts: list[str]) -> set[str]:
        tokens: set[str] = set()
        for part in parts:
            normalized_part = part.lower()
            for token in TOKEN_PATTERN.findall(normalized_part):
                if len(token) <= 1:
                    continue
                tokens.add(token)
            for match in re.finditer(r"[\u4e00-\u9fff]{2,}", normalized_part):
                segment = match.group(0)
                for index in range(len(segment) - 1):
                    tokens.add(segment[index : index + 2])
        return tokens


class _DisjointSet:
    def __init__(self, items: list[str] | tuple[str, ...] | set[str] | object) -> None:
        values = [str(item) for item in items]
        self.parents = {value: value for value in values}

    def find(self, item: str) -> str:
        parent = self.parents[item]
        if parent != item:
            self.parents[item] = self.find(parent)
        return self.parents[item]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            self.parents[right_root] = left_root
            return
        self.parents[left_root] = right_root
