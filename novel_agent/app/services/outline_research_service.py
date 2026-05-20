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
from ..schemas.narrative_memory_schema import (
    MemoryCandidateSelection,
    MemoryEvidenceBundle,
    MemoryQueryBudget,
    MemoryQueryState,
)
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
from .narrative_memory_query_service import NarrativeMemoryQueryService


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
        names = self.mention_service.clean_names([str(item) for item in (payload.get("major_characters") or [])])

        mentions: list[ExtractedCharacterMention] = []
        seen: set[str] = set()
        raw_names = list(names)
        ordered_names = sorted(
            enumerate(raw_names),
            key=lambda item: (-len(_normalize_text(item[1])), item[0]),
        )
        for _, name in ordered_names:
            text = _normalize_text(name)
            if not text or text in seen:
                continue
            if any(len(existing) > len(text) and text in existing for existing in seen):
                continue
            seen.add(text)
            source_text = self._source_snippet_for(text, segments)
            mentions.append(
                ExtractedCharacterMention(
                    text=text,
                    mention_type="name",
                    source_text=source_text,
                    confidence=0.86,
                    possible_role_hint=self._role_hint(text, source_text),
                )
            )
        return ExtractedCharacterMentions(mentions=mentions)

    def _payload_segments(self, payload: Mapping[str, Any]) -> list[str]:
        segments = []
        for key in ("user_story_overview", "preferred_outcome"):
            text = _normalize_text(payload.get(key))
            if text:
                segments.append(text)
        for key in ("desired_actions", "major_characters"):
            for item in payload.get(key) or []:
                text = _normalize_text(item)
                if text:
                    segments.append(text)
        return segments

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
        event_summary_path = self.repo_root / ".memory" / "outlines" / f"{book_id}.event_summaries.json"
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
            ]
            + self._event_summary_index(event_summary_path, book_id=book_id),
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
                *(
                    [
                        TraceableSource(
                            type="event_summaries",
                            path=str(event_summary_path),
                            evidence_level="structured_state",
                        )
                    ]
                    if event_summary_path.exists()
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

    def _event_summary_index(self, path: Path, *, book_id: str) -> list[dict[str, Any]]:
        payload = self._load_json_payload(path)
        segments = payload.get("segments") or []
        items: list[dict[str, Any]] = []
        for segment in segments if isinstance(segments, list) else []:
            if not isinstance(segment, Mapping):
                continue
            summary = _normalize_text(segment.get("summary"))
            if not summary:
                continue
            items.append(
                {
                    "work_id": book_id,
                    "summary_id": str(segment.get("summary_id") or ""),
                    "summary_level": str(segment.get("event_summary_level") or "event_group"),
                    "summary": _safe_excerpt(summary, limit=900),
                    "source_event_ids": [str(value) for value in (segment.get("event_ids") or [])],
                    "source_doc_ids": [int(value) for value in (segment.get("source_doc_ids") or []) if str(value).isdigit()],
                    "source_doc_range": str(segment.get("source_doc_range") or ""),
                    "starts_at": self._first_title_hint(segment),
                    "ends_at": self._last_title_hint(segment),
                }
            )
        return items[-8:]

    def _first_title_hint(self, segment: Mapping[str, Any]) -> str:
        indexes = [int(value) for value in (segment.get("source_title_indexes") or []) if str(value).isdigit()]
        return f"document_title_index={indexes[0]}" if indexes else ""

    def _last_title_hint(self, segment: Mapping[str, Any]) -> str:
        indexes = [int(value) for value in (segment.get("source_title_indexes") or []) if str(value).isdigit()]
        return f"document_title_index={indexes[-1]}" if indexes else ""

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
        repo_root: Path | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        chapters_repo: ChaptersRepo | None = None,
        documents_repo: DocumentsRepo | None = None,
        memory_query_service: NarrativeMemoryQueryService | None = None,
    ) -> None:
        self.repo_root = repo_root or Path.cwd()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.documents_repo = documents_repo or DocumentsRepo()
        self.memory_query_service = memory_query_service or NarrativeMemoryQueryService(repo_root=self.repo_root)

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
        selection_adapter: object | None = None,
    ) -> ResearchResult:
        btree_result = self._resolve_with_memory_query(
            conn,
            book_id=book_id,
            request=request,
            max_chars=max_chars,
            selection_adapter=selection_adapter,
        )
        if btree_result is not None:
            return btree_result
        return self._resolve_legacy(conn, book_id=book_id, request=request, max_chars=max_chars)

    def _resolve_legacy(
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
                "source_doc_ids": list(event.source_doc_ids),
                "source_doc_range": event.source_doc_range,
                "source_path": event.source_path,
                "event_summary_level": event.event_summary_level,
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

    def _resolve_with_memory_query(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: ResearchRequest,
        max_chars: int,
        selection_adapter: object | None,
    ) -> ResearchResult | None:
        understood = self.understand_query(conn, book_id=book_id, query=request.query)
        budget = MemoryQueryBudget(
            max_root_candidates=8,
            max_child_candidates=10,
            max_candidate_chars=max(700, max_chars),
            excerpt_budget=max_chars,
        )
        state = self.memory_query_service.root_scan(conn, book_id=book_id, query=request.query, budget=budget)
        if not state.current_candidates:
            return None
        decision_log: list[dict[str, Any]] = []
        model_reasoning_debug: list[dict[str, Any]] = []
        final_state = state
        evidence_bundle: MemoryEvidenceBundle | None = None
        levels_to_visit = {"event_summary", "event", "chapter"}
        while final_state.current_level in levels_to_visit and final_state.current_candidates:
            selection = self._select_memory_candidates(
                state=final_state,
                request=request,
                selection_adapter=selection_adapter,
            )
            decision_payload = {
                "request_id": request.request_id,
                "current_level": final_state.current_level,
                "candidate_ids": [str(item.get("id") or item.get("page_id")) for item in final_state.current_candidates],
                **selection.to_dict(),
                "budget_state": dict(final_state.budget_used),
            }
            decision_log.append(decision_payload)
            if selection.model_reasoning_debug:
                model_reasoning_debug.append(
                    {
                        "request_id": request.request_id,
                        "current_level": final_state.current_level,
                        **selection.model_reasoning_debug,
                    }
                )
            if not selection.selected_ids:
                break
            if final_state.current_level == "event" and not selection.need_drill_down:
                evidence_bundle = self.memory_query_service.resolve_event_ids(
                    conn,
                    book_id=book_id,
                    event_ids=selection.selected_ids,
                )
                break
            if final_state.current_level == "chapter" and not selection.need_drill_down:
                evidence_bundle = self.memory_query_service.resolve_chapter_refs(
                    conn,
                    book_id=book_id,
                    chapter_refs=selection.selected_ids,
                )
                break
            final_state = self.memory_query_service.drill_down(
                conn,
                book_id=book_id,
                state=final_state,
                selected_ids=selection.selected_ids,
                query_suffix=selection.query_suffix,
                selection_reason=selection.reason,
                confidence=selection.confidence,
                need_sibling_scan=selection.need_sibling_scan,
            )
            if final_state.current_level == "document":
                doc_ids = [
                    int(item.get("doc_id") or 0)
                    for item in final_state.current_candidates
                    if str(item.get("doc_id") or "").isdigit()
                ]
                evidence_bundle = self.memory_query_service.resolve_document_refs(
                    conn,
                    book_id=book_id,
                    doc_ids=doc_ids,
                    excerpt_budget=max_chars,
                )
                break
        if evidence_bundle is None:
            if final_state.current_level == "event":
                ids = [str(item.get("event_id") or item.get("id")) for item in final_state.current_candidates[:3]]
                evidence_bundle = self.memory_query_service.resolve_event_ids(conn, book_id=book_id, event_ids=ids)
            elif final_state.current_level == "chapter":
                ids = [str(item.get("chapter_ref") or item.get("id")) for item in final_state.current_candidates[:3]]
                evidence_bundle = self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=ids)
            elif final_state.current_level == "document":
                doc_ids = [
                    int(item.get("doc_id") or 0)
                    for item in final_state.current_candidates[:3]
                    if str(item.get("doc_id") or "").isdigit()
                ]
                evidence_bundle = self.memory_query_service.resolve_document_refs(
                    conn,
                    book_id=book_id,
                    doc_ids=doc_ids,
                    excerpt_budget=max_chars,
                )
        matches = [
            self._memory_evidence_to_match(item, max_chars=max_chars)
            for item in evidence_bundle.evidence_items[:5]
        ] if evidence_bundle is not None else []
        if not matches:
            return None
        trace = {
            "protocol": "btree_memory_query",
            "fallback": False,
            "memory_query_trace": [*state.trace, *final_state.trace, *((evidence_bundle.trace if evidence_bundle else []))],
            "memory_query_decision_log": decision_log,
            "model_reasoning_debug": model_reasoning_debug,
            "final_evidence_ids": {
                "event_ids": list(evidence_bundle.event_ids) if evidence_bundle else [],
                "chapter_refs": list(evidence_bundle.chapter_refs) if evidence_bundle else [],
                "source_doc_ids": list(evidence_bundle.source_doc_ids) if evidence_bundle else [],
            },
        }
        for match in matches:
            match["memory_query_trace"] = trace["memory_query_trace"]
            match["memory_query_decision_log"] = decision_log
            match["model_reasoning_debug"] = model_reasoning_debug
            match["memory_query_protocol"] = "btree"
        sources = [
            TraceableSource(
                type=str(item.get("type") or "memory"),
                path=str(item.get("path") or ""),
                evidence_level="structured_state",
                snippet=_safe_excerpt(str(item), limit=180),
            )
            for item in (evidence_bundle.sources if evidence_bundle else [])
        ]
        detail = StoryDetailResult(
            request_id=request.request_id,
            matches=matches,
            confidence=max([float(item.get("confidence") or 0.75) for item in matches] or [0.0]),
            covered_facets=self._covered_facets(matches, request.facets_needed or understood.facets_needed),
            missing_facets=[
                facet for facet in (request.facets_needed or understood.facets_needed)
                if facet not in self._covered_facets(matches, request.facets_needed or understood.facets_needed)
            ],
            fact_status="confirmed" if evidence_bundle and evidence_bundle.status == "committed" else "candidate",
            sources=sources,
        )
        result = ResearchResult.from_story_detail(detail, request_type="story_detail", query=request.query)
        result.results.append(
            {
                "memory_query_trace": trace["memory_query_trace"],
                "memory_query_decision_log": decision_log,
                "model_reasoning_debug": model_reasoning_debug,
                "final_evidence_ids": trace["final_evidence_ids"],
                "source_scope": "prefix_memory_only",
            }
        )
        return result

    def _select_memory_candidates(
        self,
        *,
        state: MemoryQueryState,
        request: ResearchRequest,
        selection_adapter: object | None,
    ) -> MemoryCandidateSelection:
        selector = getattr(selection_adapter, "select_memory_candidates", None)
        if callable(selector):
            raw = selector(state=state, request=request)
            if isinstance(raw, MemoryCandidateSelection):
                return raw
            if isinstance(raw, Mapping):
                return MemoryCandidateSelection.from_mapping(raw)
        return self._heuristic_memory_selection(state=state, request=request)

    def _heuristic_memory_selection(self, *, state: MemoryQueryState, request: ResearchRequest) -> MemoryCandidateSelection:
        query_tokens = _tokenize_query(" ".join([request.query, *state.query_suffix_chain]))
        scored: list[tuple[str, float]] = []
        for order, candidate in enumerate(state.current_candidates):
            candidate_id = str(candidate.get("id") or candidate.get("page_id") or "")
            haystack = json.dumps(candidate, ensure_ascii=False)
            score = sum(1.0 for token in query_tokens if token in haystack)
            score += 0.05 / (order + 1)
            if candidate_id:
                scored.append((candidate_id, score))
        selected = [item[0] for item in sorted(scored, key=lambda item: item[1], reverse=True)[:2]]
        if not selected and state.current_candidates:
            selected = [str(state.current_candidates[0].get("id") or state.current_candidates[0].get("page_id"))]
        return MemoryCandidateSelection(
            need_drill_down=state.current_level != "chapter",
            selected_ids=selected,
            query_suffix=_safe_excerpt(request.query, limit=120),
            reason="heuristic_keyword_selection",
            confidence=0.65 if selected else 0.0,
            need_sibling_scan=False,
        )

    def _memory_evidence_to_match(self, item: Mapping[str, Any], *, max_chars: int) -> dict[str, Any]:
        page_type = str(item.get("page_type") or item.get("type") or "")
        return {
            "event_id": str(item.get("event_id") or item.get("id") or item.get("page_id") or ""),
            "title": str(item.get("label") or item.get("chapter_title") or item.get("page_id") or ""),
            "summary": _safe_excerpt(str(item.get("summary") or ""), limit=max(120, max_chars // 2)),
            "outcome": str(item.get("outcome") or item.get("result") or item.get("summary") or ""),
            "characters": [str(value) for value in (item.get("participants") or item.get("characters") or [])],
            "source_doc_ids": [int(value) for value in (item.get("source_doc_ids") or []) if str(value).isdigit()],
            "source_doc_range": str(item.get("source_doc_range") or ""),
            "source_path": f"memory:{page_type}:{item.get('id') or item.get('page_id')}",
            "event_summary_level": page_type or "memory_page",
            "status": str(item.get("status") or "provisional"),
        }

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
                        outline_update=_json_dict(row["outline_update_json"]),
                        source_doc_ids=self._source_doc_ids_from_chapter_row(row),
                        source_doc_range=self._source_doc_range_from_chapter_row(row),
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
                    outline_update={},
                    source_doc_ids=[doc.doc_id],
                    source_doc_range=str(doc.doc_id),
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
                    source_doc_ids=list(entry.source_doc_ids),
                    source_doc_range=entry.source_doc_range,
                    event_summary_level="chapter_summary",
                    fact_status="confirmed" if entry.summary_status == "committed" else "candidate",
                )
            )
            for event in self._timeline_events_from_entry(entry):
                events.append(event)
        return HistoricalOutlineEventIndex(events=events)

    def _source_doc_ids_from_chapter_row(self, row: sqlite3.Row) -> list[int]:
        start = int(row["source_doc_start_id"] or 0)
        end = int(row["source_doc_end_id"] or 0)
        if start <= 0 or end <= 0:
            return []
        if end < start:
            return [start]
        if end - start > 512:
            return [start, end]
        return list(range(start, end + 1))

    def _source_doc_range_from_chapter_row(self, row: sqlite3.Row) -> str:
        source_doc_ids = self._source_doc_ids_from_chapter_row(row)
        if not source_doc_ids:
            return ""
        return str(source_doc_ids[0]) if len(source_doc_ids) == 1 else f"{source_doc_ids[0]}-{source_doc_ids[-1]}"

    def _timeline_events_from_entry(self, entry: ChapterSummaryIndexEntry) -> list[HistoricalOutlineEventCard]:
        events: list[HistoricalOutlineEventCard] = []
        outline_update = getattr(entry, "outline_update", None)
        if not isinstance(outline_update, Mapping):
            return events
        for index, item in enumerate(outline_update.get("timeline_events") or [], start=1):
            if not isinstance(item, Mapping):
                continue
            event_id = _normalize_text(item.get("event_id")) or f"chapter-{entry.document_title_index}:event-{index:02d}"
            label = _normalize_text(item.get("label")) or f"chapter {entry.document_title_index} event {index}"
            summary = _normalize_text(item.get("summary")) or label
            source_doc_ids = [int(value) for value in item.get("source_doc_ids") or [] if str(value).isdigit()]
            source_doc_range = _normalize_text(item.get("source_doc_range"))
            events.append(
                HistoricalOutlineEventCard(
                    event_id=event_id,
                    title=label,
                    characters=[str(value) for value in item.get("participants") or []],
                    concepts=entry.concepts,
                    event_intent=summary,
                    outcome=_normalize_text(item.get("outcome")),
                    time_hint=f"document_title_index={entry.document_title_index}",
                    source_chapter_id=entry.chapter_id,
                    source_path=entry.source_document,
                    source_doc_ids=source_doc_ids,
                    source_doc_range=source_doc_range,
                    event_summary_level=_normalize_text(item.get("event_summary_level")) or "chapter_event",
                    fact_status="confirmed" if entry.summary_status == "committed" else "candidate",
                )
            )
        return events

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
            repo_root=repo_root,
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
        selection_adapter: object | None = None,
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
            result = self._resolve_one(
                conn,
                book_id=book_id,
                request=request,
                max_chars=max_chars,
                selection_adapter=selection_adapter,
            )
            result.downgraded = downgraded
            result.summary_size = sum(len(str(item)) for item in result.results)
            result.token_estimate = max(1, result.summary_size // 4)
            if result.summary_size > max_chars:
                memory_debug = self._memory_debug_from_result_items(result.results)
                compact_item: dict[str, Any] = {
                    "summary": _safe_excerpt(json.dumps(result.results, ensure_ascii=False), limit=max_chars)
                }
                compact_item.update(memory_debug)
                result.results = [compact_item]
                result.summary_size = max_chars
                result.token_estimate = max(1, max_chars // 4)
            results.append(result)
        return results

    def _memory_debug_from_result_items(self, items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        reasoning: list[dict[str, Any]] = []
        final_ids: dict[str, Any] = {}
        for item in items:
            trace.extend([dict(value) for value in (item.get("memory_query_trace") or []) if isinstance(value, Mapping)])
            decisions.extend([dict(value) for value in (item.get("memory_query_decision_log") or []) if isinstance(value, Mapping)])
            reasoning.extend([dict(value) for value in (item.get("model_reasoning_debug") or []) if isinstance(value, Mapping)])
            if isinstance(item.get("final_evidence_ids"), Mapping):
                final_ids = dict(item["final_evidence_ids"])
        payload: dict[str, Any] = {}
        if trace:
            payload["memory_query_trace"] = trace
        if decisions:
            payload["memory_query_decision_log"] = decisions
        if reasoning:
            payload["model_reasoning_debug"] = reasoning
        if final_ids:
            payload["final_evidence_ids"] = final_ids
        return payload

    def _resolve_one(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: ResearchRequest,
        max_chars: int,
        selection_adapter: object | None = None,
    ) -> ResearchResult:
        if request.request_type == "story_detail":
            return self.story_detail_resolver.resolve(
                conn,
                book_id=book_id,
                request=request,
                max_chars=max_chars,
                selection_adapter=selection_adapter,
            )
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
                    "story_events": _json_list(row["story_events_json"]),
                    "recent_changes": _json_list(row["recent_activity_json"]),
                    "mentioned_doc_ids": _json_list(row["mentioned_doc_ids_json"]),
                    "speaking_doc_ids": _json_list(row["speaking_doc_ids_json"]),
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

    def select_memory_candidates(
        self,
        *,
        state: MemoryQueryState,
        request: ResearchRequest,
    ) -> MemoryCandidateSelection | Mapping[str, Any]:
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
        user_named_major_characters = {
            _normalize_text(item)
            for item in (seed_packet.user_intent.get("major_characters") or [])
            if _normalize_text(item)
        }
        unresolved_people = [
            resolution.mention_text
            for resolution in seed_packet.character_resolutions
            if resolution.status in {"ambiguous", "missing"}
            and not resolution.confirmed_new_character
            and resolution.mention_text not in user_named_major_characters
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
        outline_nodes = []
        for action in desired_actions[:8]:
            overview = re.sub(r"^根据用户授权概述重建后续大纲[:：]\s*", "", action).strip()
            overview = overview.removeprefix("用户授权概述：").strip()
            segments = [item.strip(" ；;。") for item in re.split(r"[；;\n]+", overview) if item.strip(" ；;。")]
            if len(segments) <= 1:
                segments = [action]
            for segment in segments[:8 - len(outline_nodes)]:
                outline_nodes.append(
                    {
                        "order": len(outline_nodes) + 1,
                        "source": "authorized_user_intent",
                        "summary": segment,
                    }
                )
            if len(outline_nodes) >= 8:
                break
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

    def select_memory_candidates(
        self,
        *,
        state: MemoryQueryState,
        request: ResearchRequest,
    ) -> MemoryCandidateSelection:
        tokens = _tokenize_query(" ".join([request.query, *state.query_suffix_chain]))
        scored: list[tuple[str, float]] = []
        for order, candidate in enumerate(state.current_candidates):
            candidate_id = str(candidate.get("id") or candidate.get("page_id") or "")
            haystack = json.dumps(candidate, ensure_ascii=False)
            score = sum(1.0 for token in tokens if token in haystack) + 0.05 / (order + 1)
            if candidate_id:
                scored.append((candidate_id, score))
        selected = [item[0] for item in sorted(scored, key=lambda item: item[1], reverse=True)[:2]]
        if not selected and state.current_candidates:
            selected = [str(state.current_candidates[0].get("id") or state.current_candidates[0].get("page_id"))]
        return MemoryCandidateSelection(
            need_drill_down=state.current_level != "chapter",
            selected_ids=selected,
            query_suffix=_safe_excerpt(request.query, limit=120),
            reason="heuristic_keyword_selection",
            confidence=0.65 if selected else 0.0,
            need_sibling_scan=False,
        )


class ModelOutlineResearchModelAdapter(HeuristicOutlineResearchModelAdapter):
    def __init__(self, *, model_client: Any) -> None:
        self.model_client = model_client

    def _generate_json(self, *, system_prompt: str, payload: Mapping[str, Any], fallback: Mapping[str, Any]) -> dict[str, Any]:
        if self.model_client is None:
            raise RuntimeError("Outline research model adapter requires an available model_client")
        result, raw = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=False, indent=2),
            fallback_factory=lambda: dict(fallback),
            use_fallback_on_error=bool(getattr(getattr(self.model_client, "settings", None), "dry_run", False)),
        )
        if not isinstance(result, Mapping):
            raise RuntimeError("Outline research model returned a non-object JSON payload")
        output = dict(result)
        if raw:
            output.setdefault("model_reasoning_debug", {"raw_visible_output": raw[:4000]})
        return output

    def propose_research_requests(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        prior_results: Sequence[ResearchResult],
        budget_state: Mapping[str, Any],
    ) -> Sequence[ResearchRequest | Mapping[str, Any]]:
        fallback_requests = [item.to_dict() for item in super().propose_research_requests(
            seed_packet=seed_packet,
            notebook=notebook,
            prior_results=prior_results,
            budget_state=budget_state,
        )]
        payload = self._generate_json(
            system_prompt=(
                "你是大纲研究 Agent。只返回 JSON。基于轻量 seed、notebook 和上一轮结果，"
                "提出下一轮 research requests。请求类型只能是 story_detail、character_profile、world_concept、structure_pattern。"
                "不要编造本地资料中不存在的事实。"
            ),
            payload={
                "seed_packet": seed_packet.to_dict(),
                "planning_notebook": notebook.to_dict(),
                "prior_results": [item.to_dict() for item in prior_results],
                "budget_state": dict(budget_state),
                "output_schema": {"requests": [{"request_type": "story_detail", "query": "...", "purpose": "...", "priority": "high"}]},
            },
            fallback={"requests": fallback_requests},
        )
        requests = payload.get("requests")
        if not isinstance(requests, list):
            raise RuntimeError("Outline research model returned invalid requests field")
        normalized = []
        for item in requests:
            if not isinstance(item, Mapping):
                raise RuntimeError("Outline research model returned a non-object request item")
            normalized.append(dict(item))
        initial_round = not prior_results and not budget_state.get("total_requests_used")
        if initial_round and not any(str(item.get("request_type") or item.get("type")) == "story_detail" for item in normalized):
            desired_actions = [
                str(item)
                for item in (seed_packet.user_intent.get("desired_actions") or [])
                if str(item).strip()
            ]
            if desired_actions:
                raise RuntimeError("Outline research model omitted required story_detail request")
        return normalized

    def decide_sufficiency(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        budget_state: Mapping[str, Any],
    ) -> SufficiencyDecision | Mapping[str, Any]:
        fallback = super().decide_sufficiency(seed_packet=seed_packet, notebook=notebook, budget_state=budget_state).to_dict()
        return self._generate_json(
            system_prompt=(
                "你是大纲研究 Sufficiency Gate。只返回 JSON。判断现有 evidence 是否足够生成大纲。"
                "高风险缺口必须 needs_user_input 或 blocked，不得伪造用户答案。"
            ),
            payload={
                "seed_packet": seed_packet.to_dict(),
                "planning_notebook": notebook.to_dict(),
                "budget_state": dict(budget_state),
                "allowed_status": ["enough", "needs_user_input", "proceed_with_assumptions", "blocked"],
            },
            fallback=fallback,
        )

    def generate_outline(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        sufficiency_decision: SufficiencyDecision,
    ) -> Mapping[str, Any]:
        fallback = dict(super().generate_outline(
            seed_packet=seed_packet,
            notebook=notebook,
            sufficiency_decision=sufficiency_decision,
        ))
        return self._generate_json(
            system_prompt=(
                "你是分层 Writer 的全书大纲草案 Agent。只返回 JSON。"
                "只能使用用户授权概述、prefix Memory research evidence、明确 assumptions。"
                "不得引用 hidden reference outline、future raw text 或 reference-only character set。"
            ),
            payload={
                "seed_packet": seed_packet.to_dict(),
                "planning_notebook": notebook.to_dict(),
                "sufficiency_decision": sufficiency_decision.to_dict(),
                "output_hint": "返回 outline_status、outline_nodes、confirmed_facts、candidate_facts、assumptions、remaining_risks。",
            },
            fallback=fallback,
        )

    def select_memory_candidates(
        self,
        *,
        state: MemoryQueryState,
        request: ResearchRequest,
    ) -> MemoryCandidateSelection:
        fallback = super().select_memory_candidates(state=state, request=request).to_dict()
        payload = self._generate_json(
            system_prompt=(
                "你是 Writer Outline Research 的 Memory candidate selector。只返回 JSON。"
                "你只能基于当前层候选选择 selected_ids，并给出短 query_suffix、reason、confidence、need_sibling_scan。"
                "不要引入候选中没有的信息。"
            ),
            payload={
                "original_query": state.original_query,
                "request": request.to_dict(),
                "query_suffix_chain": list(state.query_suffix_chain),
                "path_context": [item.to_dict() for item in state.path_context],
                "current_level": state.current_level,
                "current_candidates": state.current_candidates,
                "output_schema": {
                    "need_drill_down": True,
                    "selected_ids": ["..."],
                    "query_suffix": "...",
                    "reason": "...",
                    "confidence": 0.0,
                    "need_sibling_scan": False,
                },
            },
            fallback=fallback,
        )
        return MemoryCandidateSelection.from_mapping(payload)


@dataclass(slots=True)
class OutlineResearchRunResult:
    seed_packet: OutlineSeedPacket
    trace: dict[str, Any]
    planning_notebook: PlanningNotebook
    sufficiency_decision: SufficiencyDecision
    generated_outline: Mapping[str, Any] = field(default_factory=dict)
    memory_query_trace: list[dict[str, Any]] = field(default_factory=list)
    memory_query_decision_log: list[dict[str, Any]] = field(default_factory=list)
    model_reasoning_debug: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_packet": self.seed_packet.to_dict(),
            "trace": dict(self.trace),
            "planning_notebook": self.planning_notebook.to_dict(),
            "sufficiency_decision": self.sufficiency_decision.to_dict(),
            "generated_outline": dict(self.generated_outline),
            "memory_query_trace": [dict(item) for item in self.memory_query_trace],
            "memory_query_decision_log": [dict(item) for item in self.memory_query_decision_log],
            "model_reasoning_debug": [dict(item) for item in self.model_reasoning_debug],
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
        memory_query_trace: list[dict[str, Any]] = []
        memory_query_decision_log: list[dict[str, Any]] = []
        model_reasoning_debug: list[dict[str, Any]] = []
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
                selection_adapter=self.model_adapter,
            )
            total_requests_used += len(results)
            extracted_debug = self._extract_memory_debug(results)
            memory_query_trace.extend(extracted_debug["memory_query_trace"])
            memory_query_decision_log.extend(extracted_debug["memory_query_decision_log"])
            model_reasoning_debug.extend(extracted_debug["model_reasoning_debug"])
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
            "memory_query_rounds": len(memory_query_decision_log),
            "memory_query_final_evidence_ids": self._final_evidence_ids(memory_query_trace, memory_query_decision_log, prior_results),
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
            memory_query_trace=memory_query_trace,
            memory_query_decision_log=memory_query_decision_log,
            model_reasoning_debug=model_reasoning_debug or [
                {
                    "source": "structured_decision_trace",
                    "note": "Model provider did not return a separate visible reasoning/debug field; no hidden chain-of-thought was fabricated.",
                    "decision_count": len(memory_query_decision_log),
                }
            ],
        )

    def _extract_memory_debug(self, results: Sequence[ResearchResult]) -> dict[str, list[dict[str, Any]]]:
        trace: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        reasoning: list[dict[str, Any]] = []
        for result in results:
            for item in result.results:
                if not isinstance(item, Mapping):
                    continue
                trace.extend([dict(value) for value in (item.get("memory_query_trace") or []) if isinstance(value, Mapping)])
                decisions.extend([dict(value) for value in (item.get("memory_query_decision_log") or []) if isinstance(value, Mapping)])
                reasoning.extend([dict(value) for value in (item.get("model_reasoning_debug") or []) if isinstance(value, Mapping)])
        return {
            "memory_query_trace": trace,
            "memory_query_decision_log": decisions,
            "model_reasoning_debug": reasoning,
        }

    def _final_evidence_ids(
        self,
        memory_query_trace: Sequence[Mapping[str, Any]],
        memory_query_decision_log: Sequence[Mapping[str, Any]],
        prior_results: Sequence[ResearchResult],
    ) -> dict[str, list[Any]]:
        event_ids: list[str] = []
        chapter_refs: list[str] = []
        source_doc_ids: list[int] = []
        for result in prior_results:
            for item in result.results:
                if not isinstance(item, Mapping):
                    continue
                final = item.get("final_evidence_ids") if isinstance(item.get("final_evidence_ids"), Mapping) else {}
                event_ids.extend(str(value) for value in (final.get("event_ids") or []))
                chapter_refs.extend(str(value) for value in (final.get("chapter_refs") or []))
                for value in final.get("source_doc_ids") or []:
                    if str(value).isdigit():
                        source_doc_ids.append(int(value))
        for entry in memory_query_trace:
            for value in entry.get("source_doc_ids") or []:
                if str(value).isdigit():
                    source_doc_ids.append(int(value))
            for value in entry.get("resolved_ids") or []:
                text = str(value)
                if ":event-" in text or text.startswith("chapter-") and ":event" in text:
                    event_ids.append(text)
        for entry in memory_query_decision_log:
            if entry.get("current_level") == "event":
                event_ids.extend(str(value) for value in (entry.get("selected_ids") or []))
            if entry.get("current_level") == "chapter":
                chapter_refs.extend(str(value) for value in (entry.get("selected_ids") or []))
        return {
            "event_ids": list(dict.fromkeys(event_ids))[:20],
            "chapter_refs": list(dict.fromkeys(chapter_refs))[:20],
            "source_doc_ids": list(dict.fromkeys(source_doc_ids))[:50],
        }

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
        item = self._normalize_sufficiency_decision_status(item)
        try:
            return SufficiencyDecision.from_dict(item)
        except ValueError as exc:
            data = dict(item)
            if data.get("status") == "needs_user_input" and not data.get("user_questions"):
                gaps = [
                    str(value)
                    for value in (data.get("blocking_gaps") or data.get("required_actions") or ["缺少大纲规划所需的授权边界"])
                    if str(value).strip()
                ]
                data["user_questions"] = [f"请补充确认：{gap}" for gap in gaps[:3]]
                return SufficiencyDecision.from_dict(data)
            if data.get("status") == "proceed_with_assumptions" and not data.get("assumptions"):
                data["assumptions"] = [
                    {
                        "claim": "模型未明确列出低风险假设，需在后续审阅中复核剩余缺口。",
                        "fact_status": "assumption",
                        "confidence": 0.2,
                    }
                ]
                return SufficiencyDecision.from_dict(data)
            raise ValueError(
                "status must be enough, needs_user_input, proceed_with_assumptions, or blocked; "
                f"got {data.get('status')!r}"
            ) from exc

    def _normalize_sufficiency_decision_status(self, item: Mapping[str, Any]) -> Mapping[str, Any]:
        raw_status = str(item.get("status") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not raw_status:
            data = dict(item)
            if data.get("user_questions") or data.get("blocking_gaps") or data.get("required_actions"):
                data["status"] = "needs_user_input"
                return data
            if data.get("assumptions"):
                data["status"] = "proceed_with_assumptions"
                return data
            data["status"] = "needs_user_input"
            data.setdefault("user_questions", ["请补充确认：缺少大纲规划所需的授权边界"])
            return data
        status_aliases = {
            "sufficient": "enough",
            "ready": "enough",
            "complete": "enough",
            "completed": "enough",
            "ok": "enough",
            "proceed": "proceed_with_assumptions",
            "proceed_with_assumption": "proceed_with_assumptions",
            "needs_input": "needs_user_input",
            "need_user_input": "needs_user_input",
            "requires_user_input": "needs_user_input",
            "require_user_input": "needs_user_input",
            "need_more_info": "needs_user_input",
            "needs_more_info": "needs_user_input",
            "need_more_information": "needs_user_input",
            "needs_more_information": "needs_user_input",
            "insufficient": "needs_user_input",
            "insufficient_information": "needs_user_input",
            "not_enough": "needs_user_input",
            "incomplete": "needs_user_input",
            "questions": "needs_user_input",
            "blocked_by_gap": "blocked",
        }
        normalized_status = status_aliases.get(raw_status)
        if not normalized_status:
            return item
        data = dict(item)
        data["status"] = normalized_status
        return data
