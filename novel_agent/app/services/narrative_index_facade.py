from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..constants import DEFAULT_MEMORY_ROOT
from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..schemas.creative_kb_schema import FragmentCard
from ..schemas.narrative_index_schema import (
    CARD_TYPES,
    IndexCard,
    IndexCardHit,
    IndexEvidenceBundle,
    IndexQueryBudget,
    IndexQueryIntent,
    IndexQueryResult,
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, *, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", _text(text))
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", _text(text))
        if token
    ]


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class NarrativeIndexFacade:
    """Read-only facade over Narrative Index card families.

    The first implementation is intentionally adapter-based: it maps existing
    Memory and Creative KB artifacts into compact IndexCard objects without a
    new index_cards table. This keeps the migration reversible while Analyzer
    and Writer learn to consume card-shaped evidence.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        chapters_repo: ChaptersRepo | None = None,
        assets_repo: AssetsRepo | None = None,
        fragment_cards_repo: FragmentCardsRepo | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.assets_repo = assets_repo or AssetsRepo()
        self.fragment_cards_repo = fragment_cards_repo or FragmentCardsRepo()

    def search_cards(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        intent: IndexQueryIntent,
        budget: IndexQueryBudget | None = None,
    ) -> IndexQueryResult:
        budget = budget or IndexQueryBudget()
        cards = self._collect_cards(conn, book_id=book_id, intent=intent)
        hits = self._rank_cards(cards=cards, intent=intent)
        trimmed_hits = [
            IndexCardHit(
                card=self._trim_card(hit.card, limit=budget.max_card_summary_chars),
                score=hit.score,
                matched_by=hit.matched_by,
            )
            for hit in hits[: budget.max_candidate_cards]
        ]
        raw_read_recommendations = [
            {
                "card_id": hit.card.card_id,
                "card_type": hit.card.card_type,
                "reason": hit.card.raw_read_reason or hit.card.summary_sufficiency,
                "source_doc_ids": list(hit.card.source_doc_ids),
                "source_doc_range": hit.card.source_doc_range,
            }
            for hit in trimmed_hits
            if hit.card.summary_sufficiency != "sufficient" or hit.card.raw_read_reason
        ]
        return IndexQueryResult(
            intent=intent,
            candidate_cards=trimmed_hits,
            raw_read_recommendations=raw_read_recommendations,
            trace=[
                {
                    "operation": "narrative_index_search",
                    "book_id": book_id,
                    "consumer": intent.consumer,
                    "candidate_count": len(cards),
                    "returned_count": len(trimmed_hits),
                    "target_card_types": list(intent.target_card_types),
                }
            ],
        )

    def resolve_card_sources(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        cards: Sequence[IndexCard],
    ) -> IndexEvidenceBundle:
        source_doc_ids: set[int] = set()
        chapter_refs: set[str] = set()
        sources: list[dict[str, Any]] = []
        for card in cards:
            for raw_doc_id in card.source_doc_ids:
                doc_id = _int(raw_doc_id)
                if doc_id > 0:
                    source_doc_ids.add(doc_id)
            for title_index in card.source_title_indexes:
                chapter_refs.add(str(title_index))
            sources.append(
                {
                    "source_type": "index_card",
                    "card_id": card.card_id,
                    "card_type": card.card_type,
                    "source_doc_ids": list(card.source_doc_ids),
                    "source_doc_range": card.source_doc_range,
                }
            )
        return IndexEvidenceBundle(
            cards=list(cards),
            source_doc_ids=sorted(source_doc_ids),
            chapter_refs=sorted(chapter_refs),
            sources=sources,
            trace=[{"operation": "resolve_card_sources", "book_id": book_id, "card_count": len(cards)}],
        )

    def _collect_cards(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        intent: IndexQueryIntent,
    ) -> list[IndexCard]:
        target_types = set(intent.target_card_types or CARD_TYPES)
        cards: list[IndexCard] = []
        if "narrative_scene" in target_types:
            cards.extend(self._cards_from_scene_artifact(book_id=book_id))
        if target_types.intersection({"factual_event", "world_concept", "mystery_foreshadow", "theme_signal"}):
            cards.extend(self._cards_from_chapters(conn, book_id=book_id, target_types=target_types))
        if "world_concept" in target_types:
            cards.extend(self._cards_from_world_summary(conn, book_id=book_id))
        if "creative_reference" in target_types:
            cards.extend(self._cards_from_creative_kb(conn, book_id=book_id))
        return cards

    def _scene_cards_artifact(self, book_id: str) -> Path:
        return self.repo_root / DEFAULT_MEMORY_ROOT / "index_cards" / f"{book_id}.scene_cards.json"

    def _cards_from_scene_artifact(self, *, book_id: str) -> list[IndexCard]:
        path = self._scene_cards_artifact(book_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        raw_cards = payload.get("scene_cards") if isinstance(payload, Mapping) else payload
        if not isinstance(raw_cards, list):
            return []
        cards: list[IndexCard] = []
        for item in raw_cards:
            if not isinstance(item, Mapping):
                continue
            try:
                card = IndexCard.from_mapping({**dict(item), "card_type": "narrative_scene"})
            except (TypeError, ValueError):
                continue
            if card.book_id == book_id:
                cards.append(card)
        return cards

    def _cards_from_chapters(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        target_types: set[str],
    ) -> list[IndexCard]:
        cards: list[IndexCard] = []
        for row in self.chapters_repo.list_by_book(conn, book_id=book_id):
            title_index = _int(row["document_title_index"])
            source_doc_start = _int(row["source_doc_start_id"])
            source_doc_end = _int(row["source_doc_end_id"])
            source_doc_ids = [str(item) for item in range(source_doc_start, source_doc_end + 1) if item > 0]
            source_doc_range = f"{source_doc_start}-{source_doc_end}" if source_doc_start and source_doc_end else ""
            chapter_title = _text(row["chapter_title"])
            outline_update = _json_dict(row["outline_update_json"])
            outline_segment = _text(outline_update.get("outline_segment"))
            outline_segment_id = _text(outline_update.get("outline_segment_id"))
            summary = outline_segment or _text(row["summary_short"]) or _safe_excerpt(_text(row["summary_md"]), limit=600)
            mentioned = _string_list(_json_list(row["mentioned_characters_json"]))
            importance_score = _int(row["importance_score"])
            importance_reason = _text(row["importance_reason"])
            if "factual_event" in target_types and summary:
                cards.append(
                    IndexCard(
                        card_id=f"chapter-summary:{book_id}:{title_index}",
                        card_type="factual_event",
                        book_id=book_id,
                        summary=summary,
                        source_doc_ids=source_doc_ids,
                        source_title_indexes=[title_index],
                        source_doc_range=source_doc_range,
                        outline_segment_ids=[outline_segment_id] if outline_segment_id else [],
                        query_facets=[chapter_title, *mentioned, "chapter_summary"],
                        importance_facets=self._importance_facets(importance_score, importance_reason),
                        consumer_hints=["analyzer", "writer", "outline_research", "reviewer"],
                        summary_sufficiency="sufficient",
                        status=_text(row["summary_status"]) or "provisional",
                        confidence=min(1.0, max(0.2, importance_score / 100.0 if importance_score else 0.45)),
                        payload={
                            "chapter_title": chapter_title,
                            "document_title_index": title_index,
                            "importance_score": importance_score,
                            "importance_reason": importance_reason,
                            "summary_source": "outline_segment" if outline_segment else "chapter_summary",
                        },
                    )
                )
            if "world_concept" in target_types:
                cards.extend(
                    self._world_cards_from_chapter_update(
                        book_id=book_id,
                        row=row,
                        source_doc_ids=source_doc_ids,
                        source_doc_range=source_doc_range,
                        title_index=title_index,
                    )
                )
        return cards

    def _world_cards_from_chapter_update(
        self,
        *,
        book_id: str,
        row: sqlite3.Row,
        source_doc_ids: list[str],
        source_doc_range: str,
        title_index: int,
    ) -> list[IndexCard]:
        update = _json_dict(row["world_update_json"])
        if not bool(update.get("should_update")):
            return []
        cards: list[IndexCard] = []
        for index, item in enumerate(_json_list(update.get("changes")), start=1):
            if not isinstance(item, Mapping):
                continue
            section = _text(item.get("section")) or "world"
            summary = _text(item.get("summary"))
            if not summary:
                continue
            evidence = _text(item.get("evidence"))
            cards.append(
                IndexCard(
                    card_id=f"world-concept:{book_id}:{title_index}:{index}",
                    card_type="world_concept",
                    book_id=book_id,
                    summary=summary,
                    source_doc_ids=source_doc_ids,
                    source_title_indexes=[title_index],
                    source_doc_range=source_doc_range,
                    query_facets=[section, "world", "world_concept"],
                    importance_facets=["worldbuilding"],
                    consumer_hints=["analyzer", "writer", "reviewer"],
                    summary_sufficiency="sufficient",
                    status=_text(row["summary_status"]) or "provisional",
                    confidence=0.72,
                    payload={"kind": self._world_kind(section), "section": section, "evidence": evidence},
                )
            )
        return cards

    def _cards_from_world_summary(self, conn: sqlite3.Connection, *, book_id: str) -> list[IndexCard]:
        row = self.assets_repo.get(conn, book_id=book_id)
        if row is None:
            return []
        summary_path = Path(str(row["world_summary_path"] or "")).expanduser()
        if not summary_path.is_absolute():
            summary_path = (self.repo_root / summary_path).resolve()
        if not summary_path.exists():
            return []
        summary = _safe_excerpt(summary_path.read_text(encoding="utf-8", errors="replace"), limit=1000)
        if not summary:
            return []
        return [
            IndexCard(
                card_id=f"world-summary:{book_id}",
                card_type="world_concept",
                book_id=book_id,
                summary=summary,
                query_facets=["world_summary", "world", "setting"],
                importance_facets=["worldbuilding"],
                consumer_hints=["analyzer", "writer", "reviewer"],
                summary_sufficiency="sufficient",
                status="provisional",
                confidence=0.55,
                payload={"kind": "summary", "path": str(summary_path)},
            )
        ]

    def _cards_from_creative_kb(self, conn: sqlite3.Connection, *, book_id: str) -> list[IndexCard]:
        try:
            fragment_cards = self.fragment_cards_repo.list_all(conn)
        except sqlite3.OperationalError:
            return []
        book_doc_ids = self._book_doc_ids(conn, book_id=book_id)
        cards: list[IndexCard] = []
        for fragment in fragment_cards:
            if book_doc_ids and fragment.doc_id not in book_doc_ids:
                continue
            cards.append(self._creative_reference_card(book_id=book_id, fragment=fragment))
        return cards

    def _creative_reference_card(self, *, book_id: str, fragment: FragmentCard) -> IndexCard:
        title_index = _int(fragment.document_title_index)
        facets = [
            *fragment.preferred_tags,
            *fragment.narrative_function,
            *fragment.event_tags,
            *fragment.emotion_tags,
            *fragment.character_focus,
            fragment.narrative_function_text,
            fragment.emotion_mechanism_text,
            fragment.style_profile_text,
        ]
        return IndexCard(
            card_id=f"creative-reference:{fragment.fragment_id}",
            card_type="creative_reference",
            book_id=book_id,
            summary=fragment.content_summary or _safe_excerpt(fragment.source_excerpt, limit=600),
            source_doc_ids=[fragment.doc_id] if fragment.doc_id else [],
            source_title_indexes=[title_index] if title_index else [],
            source_doc_range=fragment.doc_id,
            query_facets=facets,
            importance_facets=["creative_reference"],
            consumer_hints=["writer", "analyzer"],
            summary_sufficiency="sufficient",
            status="committed" if not fragment.context_dependency_level == "high" else "provisional",
            confidence=max(0.0, min(1.0, fragment.transferability_score)),
            payload={
                "fragment_id": fragment.fragment_id,
                "cluster_id": fragment.cluster_id,
                "is_cluster_representative": fragment.is_cluster_representative,
                "narrative_function_text": fragment.narrative_function_text,
                "emotion_mechanism_text": fragment.emotion_mechanism_text,
                "character_relation_text": fragment.character_relation_text,
                "style_profile_text": fragment.style_profile_text,
                "transferability_score": fragment.transferability_score,
                "context_dependency_level": fragment.context_dependency_level,
                "source_excerpt": _safe_excerpt(fragment.source_excerpt, limit=800),
            },
        )

    def _book_doc_ids(self, conn: sqlite3.Connection, *, book_id: str) -> set[str]:
        try:
            rows = conn.execute("SELECT doc_id FROM documents WHERE book_id = ?", (book_id,)).fetchall()
        except sqlite3.OperationalError:
            return set()
        return {str(row["doc_id"]) for row in rows}

    def _rank_cards(self, *, cards: Sequence[IndexCard], intent: IndexQueryIntent) -> list[IndexCardHit]:
        query_parts = [
            intent.original_query,
            " ".join(intent.query_facets),
            " ".join(intent.must_include_characters),
        ]
        query_tokens = set(_tokens(" ".join(query_parts)))
        target_types = set(intent.target_card_types)
        hits: list[IndexCardHit] = []
        for card in cards:
            score = 0.0
            matched_by: list[str] = []
            if target_types and card.card_type in target_types:
                score += 2.0
                matched_by.append("target_card_type")
            if intent.consumer in card.consumer_hints:
                score += 0.5
                matched_by.append("consumer_hint")
            card_text = self._card_search_text(card)
            card_tokens = set(_tokens(card_text))
            overlap = sorted(query_tokens.intersection(card_tokens))
            if overlap:
                score += len(overlap) * 2.0
                matched_by.extend(f"token:{token}" for token in overlap[:8])
            for facet in intent.query_facets:
                if facet and facet in card_text:
                    score += 1.5
                    matched_by.append(f"facet:{facet}")
            for character in intent.must_include_characters:
                if character and character in card_text:
                    score += 2.0
                    matched_by.append(f"character:{character}")
            score += card.confidence
            if card.status == "committed":
                score += 0.25
            if score > 0 or not query_tokens:
                hits.append(IndexCardHit(card=card, score=score, matched_by=matched_by or ["default"]))
        return sorted(hits, key=lambda item: (-item.score, item.card.card_type, item.card.card_id))

    def _trim_card(self, card: IndexCard, *, limit: int) -> IndexCard:
        if len(card.summary) <= limit:
            return card
        payload = dict(card.payload)
        payload["summary_trimmed_from_chars"] = len(card.summary)
        return IndexCard(
            card_id=card.card_id,
            card_type=card.card_type,
            book_id=card.book_id,
            summary=_safe_excerpt(card.summary, limit=limit),
            source_doc_ids=list(card.source_doc_ids),
            source_title_indexes=list(card.source_title_indexes),
            source_doc_range=card.source_doc_range,
            outline_segment_ids=list(card.outline_segment_ids),
            query_facets=list(card.query_facets),
            importance_facets=list(card.importance_facets),
            consumer_hints=list(card.consumer_hints),
            summary_sufficiency=card.summary_sufficiency,
            raw_read_reason=card.raw_read_reason,
            status=card.status,
            confidence=card.confidence,
            payload=payload,
        )

    def _card_search_text(self, card: IndexCard) -> str:
        payload_values = []
        for value in card.payload.values():
            if isinstance(value, (str, int, float)):
                payload_values.append(str(value))
            elif isinstance(value, list):
                payload_values.extend(str(item) for item in value)
        return " ".join(
            [
                card.summary,
                " ".join(card.query_facets),
                " ".join(card.importance_facets),
                " ".join(card.source_doc_ids),
                " ".join(str(item) for item in card.source_title_indexes),
                " ".join(payload_values),
            ]
        )

    def _importance_facets(self, importance_score: int, importance_reason: str) -> list[str]:
        facets = []
        if importance_score >= 80:
            facets.append("high_importance")
        elif importance_score >= 50:
            facets.append("medium_importance")
        if importance_reason:
            facets.append(importance_reason)
        return facets or ["chapter_summary"]

    def _world_kind(self, section: str) -> str:
        normalized = section.lower()
        if any(key in normalized for key in ["rule", "规则", "禁忌", "限制", "代价"]):
            return "rule"
        if any(key in normalized for key in ["faction", "组织", "势力", "学院"]):
            return "faction"
        if any(key in normalized for key in ["artifact", "物品", "武器", "道具"]):
            return "artifact"
        if any(key in normalized for key in ["ability", "能力", "血统", "言灵"]):
            return "ability_system"
        if any(key in normalized for key in ["place", "地点", "地理", "城市"]):
            return "place"
        return "concept"
