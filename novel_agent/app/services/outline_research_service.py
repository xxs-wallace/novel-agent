from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.documents_repo import DocumentsRepo
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..schemas.orchestration_schema import (
    ChapterSummaryIndex,
    ChapterSummaryIndexEntry,
    CharacterMentionResolution,
    ContinuationIntent,
    ExtractedCharacterMention,
    ExtractedCharacterMentions,
    HistoricalOutlineEventCard,
    HistoricalOutlineEventIndex,
    OutlineSeedPacket,
    PlanningFact,
    PlanningNotebook,
    ResearchBudget,
    ResearchRequest,
    ResearchResult,
    StoryDetailResult,
    SufficiencyDecision,
    TraceableSource,
)
from .character_mention_service import CharacterMentionService


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, *, limit: int = 360) -> str:
    normalized = re.sub(r"\s+", " ", _normalize_text(text))
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _tokenize_query(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", _normalize_text(text))
    cleaned: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


class CharacterMentionExtractor:
    """Extracts user-mentioned characters before the seed packet is assembled."""

    def __init__(self, mention_service: CharacterMentionService | None = None) -> None:
        self.mention_service = mention_service or CharacterMentionService()

    def extract(self, payload: Mapping[str, Any]) -> ExtractedCharacterMentions:
        segments = self._payload_segments(payload)
        raw_text = "\n".join(text for text in segments if text)
        names = self.mention_service.clean_names([str(item) for item in (payload.get("major_characters") or [])])
        names.extend(self.mention_service.extract_local_candidates(raw_text, limit=24))
        hints = self._extract_new_character_hints(raw_text)

        mentions: list[ExtractedCharacterMention] = []
        seen: set[str] = set()
        for name in [*names, *hints]:
            text = _normalize_text(name)
            if not text or text in seen:
                continue
            seen.add(text)
            source_text = self._source_snippet_for(text, segments)
            mention_type = "new_character_hint" if text in hints else "name"
            mentions.append(
                ExtractedCharacterMention(
                    text=text,
                    mention_type=mention_type,  # type: ignore[arg-type]
                    source_text=source_text,
                    confidence=0.86 if mention_type == "name" else 0.72,
                    possible_role_hint=self._role_hint(text, source_text),
                )
            )
        return ExtractedCharacterMentions(mentions=mentions)

    def _payload_segments(self, payload: Mapping[str, Any]) -> list[str]:
        segments = []
        for key in ("user_story_overview", "preferred_outcome", "notes"):
            text = _normalize_text(payload.get(key))
            if text:
                segments.append(text)
        for key in ("desired_actions", "avoidances", "major_characters"):
            for item in payload.get(key) or []:
                text = _normalize_text(item)
                if text:
                    segments.append(text)
        return segments

    def _extract_new_character_hints(self, text: str) -> list[str]:
        hints: list[str] = []
        patterns = (
            r"(?:新角色|新人物|新增人物|大反派|幕后黑手|反派)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,12})",
            r"([A-Za-z0-9_\-\u4e00-\u9fff]{1,12})\s*(?:作为|担任)(?:新角色|反派|幕后黑手)",
        )
        for pattern in patterns:
            for match in re.findall(pattern, text):
                hint = _normalize_text(match)
                if hint and hint not in {"作为", "担任", "压力位", "功能位", "角色", "人物"}:
                    hints.append(hint)
        return hints

    def _source_snippet_for(self, name: str, segments: Sequence[str]) -> str:
        for segment in segments:
            if name in segment:
                return _safe_excerpt(segment, limit=160)
        return _safe_excerpt(segments[0] if segments else name, limit=160)

    def _role_hint(self, name: str, source_text: str) -> str:
        if re.search(r"反派|幕后|黑手", source_text):
            return "对抗/压力位"
        if re.search(r"合作|支援|接应|协助", source_text):
            return "行动支援/关系推进对象"
        if re.search(r"不要|避免|暂时", source_text):
            return "受限登场对象"
        return ""


class CharacterMentionResolver:
    """Aligns extracted mentions with existing Character Memory and aliases."""

    def __init__(self, repo: CharacterProfilesRepo | None = None) -> None:
        self.repo = repo or CharacterProfilesRepo()

    def resolve(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        mentions: ExtractedCharacterMentions,
        user_new_character_confirmations: Mapping[str, bool] | None = None,
    ) -> list[CharacterMentionResolution]:
        confirmations = {str(key): bool(value) for key, value in (user_new_character_confirmations or {}).items()}
        try:
            rows = self.repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            rows = []
        index: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            character_id = str(row["character_id"])
            canonical_name = _normalize_text(row["canonical_name"])
            aliases = [_normalize_text(item) for item in _json_list(row["aliases_json"])]
            entries = [(canonical_name, "canonical_name"), *[(alias, "alias") for alias in aliases if alias]]
            for key, matched_by in entries:
                if not key:
                    continue
                index.setdefault(key, []).append(
                    {
                        "character_id": character_id,
                        "canonical_name": canonical_name,
                        "matched_by": matched_by,
                    }
                )

        resolutions: list[CharacterMentionResolution] = []
        for mention in mentions.mentions:
            matches = list(index.get(mention.text, []))
            if len(matches) == 1:
                match = matches[0]
                resolutions.append(
                    CharacterMentionResolution(
                        mention_text=mention.text,
                        status="resolved",
                        character_id=str(match["character_id"]),
                        canonical_name=str(match["canonical_name"]),
                        matched_by=[str(match["matched_by"])],
                    )
                )
                continue
            if len(matches) > 1:
                resolutions.append(
                    CharacterMentionResolution(
                        mention_text=mention.text,
                        status="ambiguous",
                        candidate_matches=[
                            {
                                "character_id": str(match["character_id"]),
                                "canonical_name": str(match["canonical_name"]),
                                "matched_by": [str(match["matched_by"])],
                            }
                            for match in matches
                        ],
                        user_question=f"“{mention.text}”可能指向多个人物，请选择已有角色或确认这是新人物。",
                    )
                )
                continue
            resolutions.append(
                CharacterMentionResolution(
                    mention_text=mention.text,
                    status="missing",
                    confirmed_new_character=confirmations.get(mention.text, False),
                    user_question=f"“{mention.text}”未命中 Character Memory，是否确认新增人物？",
                )
            )
        return resolutions


class OutlineSeedPacketBuilder:
    def __init__(
        self,
        *,
        repo_root: Path,
        assets_repo: AssetsRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        documents_repo: DocumentsRepo | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.assets_repo = assets_repo or AssetsRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.documents_repo = documents_repo or DocumentsRepo()

    def build(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        intent: ContinuationIntent,
        mentions: ExtractedCharacterMentions,
        resolutions: list[CharacterMentionResolution],
    ) -> OutlineSeedPacket:
        try:
            assets = self.assets_repo.get(conn, book_id=book_id)
        except sqlite3.OperationalError:
            assets = None
        world_path = self._asset_path(assets, "world_summary_path")
        outline_path = self._asset_path(assets, "outline_markdown_path")
        world_text = self._read_text(world_path)
        outline_text = self._read_text(outline_path)
        source_arc_path = self.repo_root / ".memory" / "arcs" / f"{book_id}.source_arc_map.json"
        pattern_paths = [
            self.repo_root / ".memory" / "structure_patterns" / f"{book_id}.narrative_structure_patterns.json",
            self.repo_root / ".memory" / "structure_patterns" / f"{book_id}.arc_pattern_cards.json",
        ]
        try:
            last_doc = self.documents_repo.fetch_last_document(conn, book_id=book_id)
        except sqlite3.OperationalError:
            last_doc = None

        return OutlineSeedPacket(
            packet_id=f"{book_id}-outline-seed",
            book_id=book_id,
            user_intent=intent.to_dict(),
            story_scale=dict(intent.story_scale),
            climax_input=dict(intent.climax_plan),
            extracted_character_mentions=mentions.mentions,
            character_resolutions=resolutions,
            character_index=self._character_index(conn, book_id=book_id),
            world_overview=self._world_overview(world_text),
            world_concept_index=self._world_concept_index(world_text),
            historical_story_overview=[
                {
                    "work_id": book_id,
                    "summary": _safe_excerpt(outline_text, limit=1000),
                    "starts_at": "已入库故事开端",
                    "ends_at": f"document_title_index={last_doc.document_title_index}" if last_doc else "",
                }
            ],
            current_continuation_anchor=(
                f"{last_doc.document_title or last_doc.title or last_doc.path}: "
                f"{_safe_excerpt(last_doc.content, limit=220)}"
                if last_doc is not None
                else ""
            ),
            optional_open_thread_index=self._open_thread_index(outline_text),
            source_arc_index=self._source_arc_index(source_arc_path),
            structure_pattern_index=self._structure_pattern_index(pattern_paths),
            sources=[
                *(
                    [
                        TraceableSource(
                            type="world_summary",
                            path=str(world_path),
                            evidence_level="structured_state",
                        )
                    ]
                    if world_path
                    else []
                ),
                *(
                    [
                        TraceableSource(
                            type="story_outline",
                            path=str(outline_path),
                            evidence_level="structured_state",
                        )
                    ]
                    if outline_path
                    else []
                ),
            ],
        )

    def _asset_path(self, assets: sqlite3.Row | None, field_name: str) -> Path | None:
        if assets is None:
            return None
        value = _normalize_text(assets[field_name])
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else self.repo_root / path

    def _read_text(self, path: Path | None) -> str:
        if path is None or not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _character_index(self, conn: sqlite3.Connection, *, book_id: str) -> list[dict[str, Any]]:
        try:
            rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            rows = []
        index = []
        for row in rows:
            index.append(
                {
                    "character_id": str(row["character_id"]),
                    "name": str(row["canonical_name"]),
                    "aliases": [str(item) for item in _json_list(row["aliases_json"])],
                    "role_hint": _safe_excerpt(str(row["profile_summary_md"] or ""), limit=30),
                    "status_hint": "canon_active",
                }
            )
        return index

    def _world_concept_index(self, world_text: str) -> list[dict[str, Any]]:
        concepts: list[dict[str, Any]] = []
        for line in world_text.splitlines():
            text = _normalize_text(line.strip("#- "))
            if not text or len(text) > 80:
                continue
            if line.startswith("##") or re.search(r"规则|限制|代价|禁忌|体系|势力", text):
                concepts.append({"term": text[:40], "kind": "rule", "scope_hint": _safe_excerpt(text, limit=80)})
            if len(concepts) >= 8:
                break
        return concepts

    def _world_overview(self, world_text: str) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for raw_line in world_text.splitlines():
            text = _safe_excerpt(raw_line.strip("#- "), limit=120)
            if not text or text in seen:
                continue
            seen.add(text)
            lines.append(text)
            if len(lines) >= 10:
                break
        return _safe_excerpt(" ".join(lines), limit=600)

    def _open_thread_index(self, outline_text: str) -> list[dict[str, Any]]:
        threads = []
        in_unresolved = False
        for line in outline_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                in_unresolved = "未解" in stripped or "未决" in stripped
                continue
            if in_unresolved and stripped.startswith("- "):
                title = stripped[2:].strip()
                if title:
                    threads.append(
                        {
                            "thread_id": f"thread-{len(threads) + 1:02d}",
                            "title": _safe_excerpt(title, limit=80),
                            "status_hint": "unresolved",
                        }
                    )
        return threads[:8]

    def _source_arc_index(self, path: Path) -> list[dict[str, Any]]:
        payload = self._load_json_payload(path)
        arcs = payload.get("arcs") or payload.get("source_arcs") or payload.get("data") or []
        if isinstance(arcs, Mapping):
            arcs = arcs.get("arcs") or []
        return [
            {
                "source_arc_id": str(item.get("source_arc_id") or item.get("id") or f"arc-{index:02d}"),
                "title": str(item.get("source_arc_title") or item.get("title") or ""),
                "role": str(item.get("source_arc_role") or item.get("role") or ""),
            }
            for index, item in enumerate(arcs, start=1)
            if isinstance(item, Mapping)
        ][:8]

    def _structure_pattern_index(self, paths: Sequence[Path]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in paths:
            payload = self._load_json_payload(path)
            patterns = payload.get("patterns") or payload.get("arc_pattern_cards") or payload.get("cards") or []
            for pattern in patterns if isinstance(patterns, list) else []:
                if not isinstance(pattern, Mapping):
                    continue
                items.append(
                    {
                        "pattern_id": str(pattern.get("pattern_id") or pattern.get("card_id") or f"pattern-{len(items) + 1:02d}"),
                        "title": str(pattern.get("title") or pattern.get("name") or ""),
                        "function_hint": str(pattern.get("narrative_function") or pattern.get("role") or ""),
                    }
                )
        return items[:8]

    def _load_json_payload(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            return dict(raw["data"])
        return dict(raw) if isinstance(raw, dict) else {}


@dataclass(slots=True)
class StoryDetailQuery:
    characters: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    event_intent: str = ""
    time_hints: list[str] = field(default_factory=list)
    facets_needed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "characters": list(self.characters),
            "concepts": list(self.concepts),
            "event_intent": self.event_intent,
            "time_hints": list(self.time_hints),
            "facets_needed": list(self.facets_needed),
        }


class StoryDetailResolver:
    def __init__(
        self,
        *,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        chapters_repo: ChaptersRepo | None = None,
        documents_repo: DocumentsRepo | None = None,
    ) -> None:
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.documents_repo = documents_repo or DocumentsRepo()

    def understand_query(self, conn: sqlite3.Connection, *, book_id: str, query: str) -> StoryDetailQuery:
        try:
            profile_rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            profile_rows = []
        profile_names = [str(row["canonical_name"]) for row in profile_rows]
        characters = [name for name in profile_names if name and name in query]
        concepts = [token for token in _tokenize_query(query) if token not in characters and len(token) >= 2]
        time_hints = [hint for hint in ("最近", "上一次", "第一次", "来源", "结果", "后果") if hint in query]
        facets = []
        if re.search(r"谁|哪些人|人物|在场", query):
            facets.append("participants")
        if re.search(r"结果|后果|造成|结束", query):
            facets.append("outcome")
        if re.search(r"关系|信任|冲突", query):
            facets.append("relationship_state")
        if re.search(r"来源|伏笔|线索", query):
            facets.append("source")
        return StoryDetailQuery(
            characters=characters,
            concepts=concepts[:8],
            event_intent=self._event_intent(query),
            time_hints=time_hints,
            facets_needed=facets or ["event_summary"],
        )

    def resolve(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: ResearchRequest,
        max_chars: int,
    ) -> ResearchResult:
        understood = self.understand_query(conn, book_id=book_id, query=request.query)
        summary_index = self.build_chapter_summary_index(conn, book_id=book_id)
        event_index = self.build_historical_event_index(summary_index)
        ranked = self._rank_events(event_index.events, query=request.query, understood=understood)
        matches = [
            {
                "event_id": event.event_id,
                "title": event.title,
                "summary": _safe_excerpt(event.event_intent, limit=max_chars // 3),
                "outcome": _safe_excerpt(event.outcome, limit=max_chars // 4),
                "characters": list(event.characters),
                "concepts": list(event.concepts),
                "time_hint": event.time_hint,
            }
            for event, _score in ranked[:3]
        ]
        covered = self._covered_facets(matches, understood.facets_needed)
        missing = [facet for facet in understood.facets_needed if facet not in covered]
        fact_status = "confirmed" if matches and any(event.fact_status == "confirmed" for event, _ in ranked[:1]) else "candidate"
        if not matches:
            fact_status = "missing"
        sources = [
            TraceableSource(
                type="chapter_summary",
                path=event.source_path or f"sqlite:chapters:{event.source_chapter_id}",
                evidence_level="structured_state",
                snippet=_safe_excerpt(event.event_intent, limit=180),
            )
            for event, _ in ranked[:3]
        ]
        detail = StoryDetailResult(
            request_id=request.request_id,
            matches=matches,
            confidence=ranked[0][1] if ranked else 0.0,
            covered_facets=covered,
            missing_facets=missing,
            fact_status=fact_status,  # type: ignore[arg-type]
            sources=sources,
        )
        return ResearchResult.from_story_detail(detail, request_type="story_detail", query=request.query)

    def build_chapter_summary_index(self, conn: sqlite3.Connection, *, book_id: str) -> ChapterSummaryIndex:
        try:
            rows = self.chapters_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            rows = []
        entries = []
        if rows:
            for row in rows:
                mentioned = [str(item) for item in _json_list(row["mentioned_characters_json"])]
                world_update = _json_dict(row["world_update_json"])
                concepts = [str(key) for key in world_update.keys()]
                entries.append(
                    ChapterSummaryIndexEntry(
                        chapter_id=str(row["chapter_id"]),
                        document_title_index=int(row["document_title_index"]),
                        title=str(row["chapter_title"] or ""),
                        characters=mentioned,
                        concepts=concepts,
                        event_summary=str(row["summary_short"] or row["summary_md"] or ""),
                        outcome=self._outline_outcome(_json_dict(row["outline_update_json"])),
                        source_document=f"sqlite:chapters:{row['chapter_id']}",
                        source_segment=str(row["summary_target_range"] or ""),
                        summary_status=str(row["summary_status"] or "provisional"),
                    )
                )
            return ChapterSummaryIndex(entries=entries)
        try:
            docs = self.documents_repo.fetch_after_doc_id(conn, book_id=book_id)
        except sqlite3.OperationalError:
            docs = []
        for doc in docs:
            entries.append(
                ChapterSummaryIndexEntry(
                    chapter_id=str(doc.doc_id),
                    document_title_index=doc.document_title_index,
                    title=doc.document_title or doc.title or "",
                    characters=doc.character_keywords,
                    concepts=doc.content_tags,
                    event_summary=_safe_excerpt(doc.content, limit=420),
                    outcome="",
                    source_document=doc.source_path or doc.path,
                    source_segment=f"{doc.source_start_offset}-{doc.source_end_offset}",
                    summary_status="provisional",
                )
            )
        return ChapterSummaryIndex(entries=entries)

    def build_historical_event_index(self, index: ChapterSummaryIndex) -> HistoricalOutlineEventIndex:
        events = []
        for entry in index.entries:
            events.append(
                HistoricalOutlineEventCard(
                    event_id=f"chapter-{entry.document_title_index}",
                    title=entry.title or f"chapter {entry.document_title_index}",
                    characters=entry.characters,
                    concepts=entry.concepts,
                    event_intent=entry.event_summary,
                    outcome=entry.outcome,
                    time_hint=f"document_title_index={entry.document_title_index}",
                    source_chapter_id=entry.chapter_id,
                    source_path=entry.source_document,
                    fact_status="confirmed" if entry.summary_status == "committed" else "candidate",
                )
            )
        return HistoricalOutlineEventIndex(events=events)

    def _event_intent(self, query: str) -> str:
        if re.search(r"信任|关系|冲突", query):
            return "relationship_conflict"
        if re.search(r"伏笔|来源|线索|证据", query):
            return "foreshadowing_source"
        if re.search(r"结果|后果|造成", query):
            return "event_outcome"
        return "story_detail"

    def _outline_outcome(self, outline_update: Mapping[str, Any]) -> str:
        for key in ("outcome", "result", "summary", "outline_summary"):
            text = _normalize_text(outline_update.get(key))
            if text:
                return text
        return ""

    def _rank_events(
        self,
        events: Sequence[HistoricalOutlineEventCard],
        *,
        query: str,
        understood: StoryDetailQuery,
    ) -> list[tuple[HistoricalOutlineEventCard, float]]:
        tokens = set(_tokenize_query(query))
        ranked: list[tuple[HistoricalOutlineEventCard, float]] = []
        for event in events:
            haystack = " ".join(
                [event.title, event.event_intent, event.outcome, *event.characters, *event.concepts]
            )
            score = 0.0
            score += sum(0.12 for token in tokens if token and token in haystack)
            score += sum(0.2 for character in understood.characters if character in event.characters or character in haystack)
            score += sum(0.08 for concept in understood.concepts if concept in haystack)
            if "最近" in understood.time_hints or "上一次" in understood.time_hints:
                score += min(0.25, int(re.sub(r"\D", "", event.time_hint) or 0) / 1000)
            if understood.event_intent == "relationship_conflict" and re.search(r"信任|冲突|关系", haystack):
                score += 0.25
            if understood.event_intent == "foreshadowing_source" and re.search(r"伏笔|线索|证据|来源", haystack):
                score += 0.25
            if score > 0:
                ranked.append((event, min(score, 1.0)))
        return sorted(ranked, key=lambda item: item[1], reverse=True)

    def _covered_facets(self, matches: Sequence[Mapping[str, Any]], facets: Sequence[str]) -> list[str]:
        covered = []
        joined = json.dumps(list(matches), ensure_ascii=False)
        for facet in facets:
            if facet == "participants" and re.search(r"characters|人物", joined):
                covered.append(facet)
            elif facet == "outcome" and re.search(r"outcome|结果|后果", joined):
                covered.append(facet)
            elif facet == "relationship_state" and re.search(r"关系|信任|冲突", joined):
                covered.append(facet)
            elif facet == "source" and re.search(r"source|来源|伏笔|线索|证据", joined):
                covered.append(facet)
            elif facet == "event_summary" and matches:
                covered.append(facet)
        return covered


class OutlineResearchContextBroker:
    def __init__(
        self,
        *,
        repo_root: Path,
        assets_repo: AssetsRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        story_detail_resolver: StoryDetailResolver | None = None,
        fragment_cards_repo: FragmentCardsRepo | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.assets_repo = assets_repo or AssetsRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.story_detail_resolver = story_detail_resolver or StoryDetailResolver(
            character_profiles_repo=self.character_profiles_repo
        )
        self.fragment_cards_repo = fragment_cards_repo or FragmentCardsRepo()

    def resolve_requests(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        requests: Sequence[ResearchRequest],
        budget: ResearchBudget,
        total_requests_used: int = 0,
    ) -> list[ResearchResult]:
        deduped: list[ResearchRequest] = []
        seen: set[str] = set()
        remaining = max(0, budget.max_total_requests - total_requests_used)
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        for request in sorted(requests, key=lambda item: priority_rank[item.priority]):
            if request.dedupe_key in seen:
                continue
            seen.add(request.dedupe_key)
            deduped.append(request)
        results: list[ResearchResult] = []
        for index, request in enumerate(deduped[:remaining]):
            downgraded = request.priority == "low" and index >= max(1, remaining - 1)
            max_chars = max(160, budget.max_return_tokens_per_request * 3)
            if downgraded:
                max_chars = 180
            result = self._resolve_one(conn, book_id=book_id, request=request, max_chars=max_chars)
            result.downgraded = downgraded
            result.summary_size = sum(len(str(item)) for item in result.results)
            result.token_estimate = max(1, result.summary_size // 4)
            if result.summary_size > max_chars:
                result.results = [{"summary": _safe_excerpt(json.dumps(result.results, ensure_ascii=False), limit=max_chars)}]
                result.summary_size = max_chars
                result.token_estimate = max(1, max_chars // 4)
            results.append(result)
        return results

    def _resolve_one(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: ResearchRequest,
        max_chars: int,
    ) -> ResearchResult:
        if request.request_type == "story_detail":
            return self.story_detail_resolver.resolve(conn, book_id=book_id, request=request, max_chars=max_chars)
        if request.request_type == "character_profile":
            return self._resolve_character_profile(conn, book_id=book_id, request=request, max_chars=max_chars)
        if request.request_type == "world_concept":
            return self._resolve_world_concept(conn, book_id=book_id, request=request, max_chars=max_chars)
        return self._resolve_structure_pattern(conn, request=request, max_chars=max_chars)

    def _resolve_character_profile(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: ResearchRequest,
        max_chars: int,
    ) -> ResearchResult:
        target = request.name or request.query
        try:
            rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            rows = []
        matches = []
        for row in rows:
            aliases = [str(item) for item in _json_list(row["aliases_json"])]
            canonical = str(row["canonical_name"])
            if target and target not in canonical and target not in aliases and canonical not in request.query:
                continue
            evidence_level = str(row["evidence_level"] or "inferred")
            matches.append(
                {
                    "character_id": str(row["character_id"]),
                    "canonical_name": canonical,
                    "aliases": aliases,
                    "current_status": _safe_excerpt(str(row["profile_summary_md"] or ""), limit=max_chars // 3),
                    "ability_boundary": _json_list(row["abilities_json"]),
                    "relationship_state": _json_list(row["relationships_json"]),
                    "recent_changes": _json_list(row["recent_activity_json"]),
                    "fact_status": "candidate" if evidence_level in {"inferred", "candidate"} else "confirmed",
                }
            )
        status = "missing" if not matches else ("confirmed" if all(item["fact_status"] == "confirmed" for item in matches) else "candidate")
        return ResearchResult(
            request_id=request.request_id,
            request_type="character_profile",
            query=request.query or request.name,
            results=matches[:3],
            fact_status=status,  # type: ignore[arg-type]
            sources=[
                TraceableSource(
                    type="character_profile",
                    path=f"sqlite:character_profiles:{item['character_id']}",
                    evidence_level="structured_state",
                    snippet=str(item["canonical_name"]),
                )
                for item in matches[:3]
            ],
            confidence=0.9 if matches else 0.0,
            covered_facets=["identity", "ability_boundary", "relationship_state"] if matches else [],
            missing_facets=[] if matches else ["character_profile"],
        )

    def _resolve_world_concept(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: ResearchRequest,
        max_chars: int,
    ) -> ResearchResult:
        try:
            assets = self.assets_repo.get(conn, book_id=book_id)
        except sqlite3.OperationalError:
            assets = None
        paths = []
        for field_name in ("world_summary_path", "world_markdown_path"):
            if assets is None:
                continue
            path_text = _normalize_text(assets[field_name])
            if path_text:
                paths.append(Path(path_text))
        concept = request.concept or request.query
        matches = []
        sources = []
        for path in paths:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            relevant = [line for line in lines if concept and concept in line]
            if not relevant:
                relevant = [line for line in lines if any(token in line for token in _tokenize_query(request.query)[:4])]
            if relevant:
                summary = _safe_excerpt(" ".join(relevant[:4]), limit=max_chars)
                matches.append(
                    {
                        "concept": concept,
                        "rules": summary,
                        "limits": [line for line in relevant if re.search(r"限制|不能|不得|代价|禁忌", line)][:4],
                        "exceptions": [line for line in relevant if re.search(r"例外|除非|曾经", line)][:3],
                        "forbidden_breakpoints": [line for line in relevant if re.search(r"不得|不能|禁忌", line)][:3],
                    }
                )
                sources.append(
                    TraceableSource(
                        type="world_memory",
                        path=str(path),
                        evidence_level="structured_state",
                        snippet=summary[:180],
                    )
                )
        if not matches:
            try:
                chapter_rows = ChaptersRepo().list_by_book(conn, book_id=book_id)
            except sqlite3.OperationalError:
                chapter_rows = []
            for row in chapter_rows:
                world_update = _json_dict(row["world_update_json"])
                for key, value in world_update.items():
                    if concept and concept not in str(key) and concept not in str(value):
                        continue
                    summary = _safe_excerpt(f"{key}: {value}", limit=max_chars)
                    matches.append(
                        {
                            "concept": str(key),
                            "rules": summary,
                            "limits": [summary] if re.search(r"不能|不得|限制|代价|禁忌", summary) else [],
                            "exceptions": [],
                            "forbidden_breakpoints": [summary] if re.search(r"不能|不得|禁忌", summary) else [],
                        }
                    )
                    sources.append(
                        TraceableSource(
                            type="chapter_world_update",
                            path=f"sqlite:chapters:{row['chapter_id']}",
                            evidence_level="structured_state",
                            snippet=summary[:180],
                        )
                    )
        return ResearchResult(
            request_id=request.request_id,
            request_type="world_concept",
            query=request.query or concept,
            results=matches[:2],
            fact_status="confirmed" if matches else "missing",
            sources=sources,
            confidence=0.85 if matches else 0.0,
            covered_facets=["rules", "limits"] if matches else [],
            missing_facets=[] if matches else ["world_concept"],
        )

    def _resolve_structure_pattern(
        self,
        conn: sqlite3.Connection,
        *,
        request: ResearchRequest,
        max_chars: int,
    ) -> ResearchResult:
        try:
            hits = self.fragment_cards_repo.search_fts(
                conn,
                query_text=request.query,
                limit=5,
                representatives_only=True,
            )
            cards = self.fragment_cards_repo.list_by_fragment_ids(
                conn,
                fragment_ids=[hit.fragment_id for hit in hits],
            )
        except sqlite3.OperationalError:
            cards = []
        results = [
            {
                "pattern_id": card.fragment_id,
                "title": card.content_summary,
                "structure_function": card.narrative_function_text,
                "rhythm": _safe_excerpt(card.emotion_mechanism_text, limit=max_chars // 4),
                "source_kind": "creative_kb.fragment_card",
            }
            for card in cards
        ]
        if not results:
            for path in sorted((self.repo_root / ".memory" / "structure_patterns").glob("*.json"))[:4]:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                results.append({"pattern_id": path.stem, "title": path.stem, "summary": _safe_excerpt(str(payload), limit=max_chars)})
        return ResearchResult(
            request_id=request.request_id,
            request_type="structure_pattern",
            query=request.query,
            results=results[:5],
            fact_status="candidate" if results else "missing",
            sources=[
                TraceableSource(
                    type="creative_kb",
                    path=f"sqlite:fragment_cards:{item['pattern_id']}",
                    evidence_level="reasonable_inference",
                )
                for item in results[:5]
            ],
            confidence=0.7 if results else 0.0,
            covered_facets=["structure_candidates"] if results else [],
            missing_facets=[] if results else ["structure_pattern"],
        )


class OutlineResearchModelAdapter(Protocol):
    def propose_research_requests(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        prior_results: Sequence[ResearchResult],
        budget_state: Mapping[str, Any],
    ) -> Sequence[ResearchRequest | Mapping[str, Any]]:
        ...

    def decide_sufficiency(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        budget_state: Mapping[str, Any],
    ) -> SufficiencyDecision | Mapping[str, Any]:
        ...

    def generate_outline(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        sufficiency_decision: SufficiencyDecision,
    ) -> Mapping[str, Any]:
        ...


class HeuristicOutlineResearchModelAdapter:
    """Deterministic fallback adapter used by tests and dry-run Writer flows."""

    def propose_research_requests(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        prior_results: Sequence[ResearchResult],
        budget_state: Mapping[str, Any],
    ) -> Sequence[ResearchRequest]:
        if prior_results or budget_state.get("total_requests_used"):
            return []
        requests: list[ResearchRequest] = []
        desired = seed_packet.user_intent.get("desired_actions") or []
        if desired:
            requests.append(
                ResearchRequest(
                    request_id="research-story-01",
                    request_type="story_detail",
                    query=str(desired[0]),
                    purpose="确认续写目标与历史剧情的承接关系。",
                    priority="high",
                )
            )
        for resolution in seed_packet.character_resolutions:
            if resolution.status != "resolved":
                continue
            requests.append(
                ResearchRequest(
                    request_id=f"research-character-{len(requests) + 1:02d}",
                    request_type="character_profile",
                    name=resolution.canonical_name or resolution.mention_text,
                    query="了解当前身份、能力边界、关系状态和最近变化。",
                    purpose="判断人物是否适合承担用户指定行动。",
                    priority="high",
                )
            )
            if len(requests) >= 3:
                break
        if seed_packet.world_concept_index:
            first = seed_packet.world_concept_index[0]
            requests.append(
                ResearchRequest(
                    request_id="research-world-01",
                    request_type="world_concept",
                    concept=str(first.get("term") or ""),
                    query="需要了解规则、限制、代价、例外和禁止突破点。",
                    purpose="避免大纲突破既有世界观。",
                    priority="medium",
                )
            )
        requests.append(
            ResearchRequest(
                request_id="research-structure-01",
                request_type="structure_pattern",
                query=str((seed_packet.user_intent.get("desired_actions") or ["承接现有主线"])[0]),
                purpose="检索可参考的结构节奏候选。",
                priority="low",
            )
        )
        return requests[: int(budget_state.get("max_requests_per_round") or 4)]

    def decide_sufficiency(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        budget_state: Mapping[str, Any],
    ) -> SufficiencyDecision:
        user_answer_text = "\n".join(fact.claim for fact in notebook.confirmed_facts if fact.fact_status == "user_authorized")
        unresolved_people = [
            resolution.mention_text
            for resolution in seed_packet.character_resolutions
            if resolution.status in {"ambiguous", "missing"}
            and not resolution.confirmed_new_character
            and not (resolution.mention_text in user_answer_text and re.search(r"不|否|拒绝|不是|不新增|不要", user_answer_text))
        ]
        if unresolved_people:
            return SufficiencyDecision(
                decision_id=f"{seed_packet.book_id}-sufficiency",
                status="needs_user_input",
                blocking_gaps=[f"人物提及未确认：{name}" for name in unresolved_people[:3]],
                user_questions=[f"“{name}”是否为新增人物？如果不是，请说明对应已有角色。" for name in unresolved_people[:3]],
                required_actions=[],
            )
        if notebook.confirmed_facts or notebook.candidate_facts:
            return SufficiencyDecision(
                decision_id=f"{seed_packet.book_id}-sufficiency",
                status="enough",
                known_enough=["已获得可用于全书规划的历史剧情、人物或世界观 evidence。"],
                optional_gaps=list(notebook.open_questions[:3]),
            )
        if budget_state.get("exhausted"):
            return SufficiencyDecision(
                decision_id=f"{seed_packet.book_id}-sufficiency",
                status="proceed_with_assumptions",
                known_enough=["用户续写意图和索引级资料可支持低风险草案。"],
                optional_gaps=["本地资料未能补足全部细节。"],
                assumptions=[
                    PlanningFact(
                        claim="未检索到的低风险桥接细节仅作为草案假设，不写成 confirmed fact。",
                        fact_status="assumption",
                        confidence=0.4,
                    )
                ],
                remaining_risks=["需在后续批次前复核关键人物关系和世界规则。"],
            )
        return SufficiencyDecision(
            decision_id=f"{seed_packet.book_id}-sufficiency",
            status="enough",
            known_enough=["当前索引和用户意图足以进入保守规划。"],
        )

    def generate_outline(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        sufficiency_decision: SufficiencyDecision,
    ) -> Mapping[str, Any]:
        desired_actions = [str(item) for item in (seed_packet.user_intent.get("desired_actions") or []) if str(item)]
        preferred_outcome = _normalize_text(seed_packet.user_intent.get("preferred_outcome"))
        outline_nodes = [
            {
                "order": index,
                "source": "authorized_user_intent",
                "summary": action,
            }
            for index, action in enumerate(desired_actions[:8], start=1)
        ]
        if preferred_outcome and preferred_outcome not in {str(item.get("summary")) for item in outline_nodes}:
            outline_nodes.append(
                {
                    "order": len(outline_nodes) + 1,
                    "source": "authorized_user_intent",
                    "summary": preferred_outcome,
                }
            )
        return {
            "seed_packet_id": seed_packet.packet_id,
            "notebook_id": notebook.notebook_id,
            "sufficiency_status": sufficiency_decision.status,
            "outline_status": "draft" if sufficiency_decision.status in {"enough", "proceed_with_assumptions"} else "not_generated",
            "status_reason": (
                "ready_for_formal_planning"
                if sufficiency_decision.status in {"enough", "proceed_with_assumptions"}
                else "waiting_for_user_or_modeling"
            ),
            "outline_nodes": outline_nodes,
            "confirmed_facts": [item.to_dict() for item in notebook.confirmed_facts],
            "candidate_facts": [item.to_dict() for item in notebook.candidate_facts[:8]],
            "assumptions": [item.to_dict() for item in sufficiency_decision.assumptions],
            "blocking_gaps": list(sufficiency_decision.blocking_gaps),
            "remaining_risks": list(sufficiency_decision.remaining_risks),
        }


@dataclass(slots=True)
class OutlineResearchRunResult:
    seed_packet: OutlineSeedPacket
    trace: dict[str, Any]
    planning_notebook: PlanningNotebook
    sufficiency_decision: SufficiencyDecision
    generated_outline: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_packet": self.seed_packet.to_dict(),
            "trace": dict(self.trace),
            "planning_notebook": self.planning_notebook.to_dict(),
            "sufficiency_decision": self.sufficiency_decision.to_dict(),
            "generated_outline": dict(self.generated_outline),
        }


class OutlineResearchLoopController:
    def __init__(
        self,
        *,
        broker: OutlineResearchContextBroker,
        model_adapter: OutlineResearchModelAdapter | None = None,
    ) -> None:
        self.broker = broker
        self.model_adapter = model_adapter or HeuristicOutlineResearchModelAdapter()

    def run(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        seed_packet: OutlineSeedPacket,
        budget: ResearchBudget | None = None,
        notebook: PlanningNotebook | None = None,
        user_answers: Mapping[str, str] | None = None,
    ) -> OutlineResearchRunResult:
        budget = budget or ResearchBudget()
        notebook = notebook or PlanningNotebook(notebook_id=f"{book_id}-planning-notebook")
        for question, answer in (user_answers or {}).items():
            notebook.add_user_answer(question=question, answer=answer)

        rounds: list[dict[str, Any]] = []
        prior_results: list[ResearchResult] = []
        total_requests_used = 0
        exhausted = False
        for round_index in range(1, budget.max_rounds + 1):
            budget_state = self._budget_state(
                budget=budget,
                round_index=round_index,
                total_requests_used=total_requests_used,
                exhausted=False,
            )
            proposed = self.model_adapter.propose_research_requests(
                seed_packet=seed_packet,
                notebook=notebook,
                prior_results=prior_results,
                budget_state=budget_state,
            )
            requests = self._validated_requests(proposed)
            remaining = max(0, budget.max_total_requests - total_requests_used)
            if remaining <= 0:
                exhausted = True
                break
            requests = requests[: min(budget.max_requests_per_round, remaining)]
            if not requests:
                break
            results = self.broker.resolve_requests(
                conn,
                book_id=book_id,
                requests=requests,
                budget=budget,
                total_requests_used=total_requests_used,
            )
            total_requests_used += len(results)
            for result in results:
                notebook.add_research_result(result)
            rounds.append(
                {
                    "round_index": round_index,
                    "requests": [item.to_dict() for item in requests],
                    "results": [item.to_dict() for item in results],
                    "budget_state": self._budget_state(
                        budget=budget,
                        round_index=round_index,
                        total_requests_used=total_requests_used,
                        exhausted=total_requests_used >= budget.max_total_requests,
                    ),
                }
            )
            prior_results = results
            if total_requests_used >= budget.max_total_requests:
                exhausted = True
                break

        budget_state = self._budget_state(
            budget=budget,
            round_index=min(len(rounds) + 1, budget.max_rounds),
            total_requests_used=total_requests_used,
            exhausted=exhausted or total_requests_used >= budget.max_total_requests,
        )
        decision = self._validated_decision(
            self.model_adapter.decide_sufficiency(
                seed_packet=seed_packet,
                notebook=notebook,
                budget_state=budget_state,
            )
        )
        if decision.status == "proceed_with_assumptions":
            for assumption in decision.assumptions:
                if assumption not in notebook.assumptions:
                    notebook.assumptions.append(assumption)
        trace = {
            "book_id": book_id,
            "seed_packet_id": seed_packet.packet_id,
            "budget": budget.to_dict(),
            "rounds": rounds,
            "final_budget_state": budget_state,
            "sufficiency_status": decision.status,
        }
        generated_outline = dict(
            self.model_adapter.generate_outline(
                seed_packet=seed_packet,
                notebook=notebook,
                sufficiency_decision=decision,
            )
        )
        return OutlineResearchRunResult(
            seed_packet=seed_packet,
            trace=trace,
            planning_notebook=notebook,
            sufficiency_decision=decision,
            generated_outline=generated_outline,
        )

    def _budget_state(
        self,
        *,
        budget: ResearchBudget,
        round_index: int,
        total_requests_used: int,
        exhausted: bool,
    ) -> dict[str, Any]:
        return {
            "round_index": round_index,
            "max_rounds": budget.max_rounds,
            "max_requests_per_round": budget.max_requests_per_round,
            "max_total_requests": budget.max_total_requests,
            "total_requests_used": total_requests_used,
            "remaining_requests": max(0, budget.max_total_requests - total_requests_used),
            "max_return_tokens_per_request": budget.max_return_tokens_per_request,
            "exhausted": bool(exhausted or total_requests_used >= budget.max_total_requests),
        }

    def _validated_requests(self, items: Sequence[ResearchRequest | Mapping[str, Any]]) -> list[ResearchRequest]:
        requests: list[ResearchRequest] = []
        for item in items:
            try:
                request = item if isinstance(item, ResearchRequest) else ResearchRequest.from_dict(item)
            except (TypeError, ValueError):
                continue
            requests.append(request)
        return requests

    def _validated_decision(self, item: SufficiencyDecision | Mapping[str, Any]) -> SufficiencyDecision:
        if isinstance(item, SufficiencyDecision):
            return item
        return SufficiencyDecision.from_dict(item)
