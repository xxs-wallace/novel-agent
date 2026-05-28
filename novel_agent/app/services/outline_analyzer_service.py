from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..schemas.narrative_inquiry_schema import (
    AnalyzerBudget,
    AnalyzerLoopOutput,
    AnalyzerNotebook,
    AnalyzerSeedPacket,
    EvidenceBundle,
    NarrativeInquiryRequest,
)
from ..schemas.narrative_memory_schema import MemoryQueryBudget
from ..utils.json_utils import extract_json_blob
from ..utils.text_utils import clamp_text, normalize_whitespace, safe_excerpt
from .narrative_inquiry_broker import NarrativeInquiryBroker
from .narrative_memory_query_service import NarrativeMemoryQueryService


logger = logging.getLogger(__name__)


ANALYZER_ANALYSIS_QUESTION_POLICY = (
    "对于“评价、分析、推测、可能走向、是否合理、之后会怎样”这类讨论题，"
    "不要因为存在多个可能解释就返回 needs_user_preference；应基于现有证据给出暂定分析，"
    "把结论分别标注为 confirmed fact、reasonable inference 或 uncertain gap。"
    "只有当用户明确要求你替他选择互斥创作方案、授权终局秘密/角色死亡/世界规则突破，"
    "且继续回答必须先知道用户偏好时，才允许返回 needs_user_preference。"
    "如果某个对象证据不足，说明该对象证据不足，并继续回答已有证据能支持的部分。"
    "遇到“男主、女主、主角、核心角色”等未点名的角色职能词时，如果 seed 中存在多个可能候选，"
    "不要静默只选一个，也不要直接说无证据；应先列出候选与选择依据，再给默认分析。"
)


GENERIC_CHARACTER_QUERY_TERMS = (
    "主角",
    "男主",
    "女主",
    "男女主",
    "主人公",
    "核心人物",
    "主要人物",
    "重要人物",
    "人物性格",
    "角色性格",
    "感情线",
    "关系线",
)


def _json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", normalize_whitespace(text)) if token]


@dataclass(frozen=True, slots=True)
class AnalyzerSource:
    source_type: str
    path: str
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source_type": self.source_type,
            "path": self.path,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class AnalyzerChatResult:
    status: str
    answer: str
    sources: list[AnalyzerSource] = field(default_factory=list)
    seed: AnalyzerSeedPacket | None = None
    notebook: AnalyzerNotebook | None = None
    evidence_bundles: list[EvidenceBundle] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    context: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        seed_payload = self.seed.to_dict() if self.seed is not None else {}
        notebook_payload = self.notebook.to_dict() if self.notebook is not None else {}
        return {
            "status": self.status,
            "answer": self.answer,
            "sources": [item.to_dict() for item in self.sources],
            "seed": seed_payload,
            "context": seed_payload,
            "notebook": notebook_payload,
            "evidence_bundles": [item.to_dict() for item in self.evidence_bundles],
            "trace": dict(self.trace),
        }


@dataclass(frozen=True, slots=True)
class EvidenceTriageResult:
    kept_request_ids: list[str] = field(default_factory=list)
    rejected_request_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, candidate_request_ids: Sequence[str]) -> "EvidenceTriageResult":
        valid_ids = {str(item) for item in candidate_request_ids}
        kept = _dedup_strings(data.get("kept_request_ids") or data.get("keep_request_ids") or data.get("relevant_request_ids"))
        rejected = _dedup_strings(data.get("rejected_request_ids") or data.get("irrelevant_request_ids"))
        kept = [item for item in kept if item in valid_ids]
        rejected = [item for item in rejected if item in valid_ids and item not in kept]
        notes = _dedup_strings(data.get("notes") or data.get("reasons"))
        return cls(kept_request_ids=kept, rejected_request_ids=rejected, notes=notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept_request_ids": list(self.kept_request_ids),
            "rejected_request_ids": list(self.rejected_request_ids),
            "notes": list(self.notes),
        }


def _dedup_strings(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Sequence):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = normalize_whitespace(str(item or ""))
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _compact_list(values: Sequence[Any], *, limit: int, text_limit: int) -> list[Any]:
    result = []
    for value in values[:limit]:
        if isinstance(value, Mapping):
            result.append(_compact_mapping(value, text_limit=text_limit))
        else:
            result.append(safe_excerpt(normalize_whitespace(str(value or "")), text_limit))
    return result


def _compact_mapping(value: Mapping[str, Any], *, text_limit: int) -> dict[str, Any]:
    keep_scalar = (
        "id",
        "page_id",
        "page_type",
        "event_id",
        "card_id",
        "card_type",
        "chapter_id",
        "chapter_ref",
        "document_title_index",
        "doc_id",
        "title",
        "label",
        "scene_type",
        "canonical_name",
        "character_id",
        "concept",
        "term",
        "type",
        "path",
        "status",
        "evidence_level",
        "source_range",
        "source_doc_range",
        "source_chapter_range",
        "outcome",
        "summary",
        "summary_sufficiency",
        "summary_hint",
        "summary_short",
        "profile_summary",
        "trigger",
        "turning_point",
        "read_reason",
        "expected_confirmation",
        "affects_analysis",
        "raw_read_reason",
        "future_consequence",
        "confidence",
    )
    result: dict[str, Any] = {}
    for key in keep_scalar:
        if key not in value:
            continue
        item = value[key]
        if isinstance(item, str):
            result[key] = safe_excerpt(item, text_limit)
        elif isinstance(item, (int, float, bool)) or item is None:
            result[key] = item
    for key, limit in (
        ("aliases", 8),
        ("participants", 8),
        ("source_doc_ids", 12),
        ("chapter_refs", 12),
        ("query_facets", 8),
        ("importance_facets", 8),
        ("consumer_hints", 6),
        ("character_pressure", 6),
        ("relationship_movements", 6),
        ("world_or_mystery_signals", 6),
    ):
        item = value.get(key)
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            result[key] = list(item[:limit])
    payload = value.get("payload")
    if isinstance(payload, Mapping):
        result["payload"] = _compact_mapping(payload, text_limit=min(text_limit, 220))
    for key in ("relationships", "recent_activity", "story_events", "excerpts"):
        item = value.get(key)
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            result[key] = _compact_list(list(item), limit=2, text_limit=min(text_limit, 180))
    return result


def _compact_evidence_bundle(bundle: EvidenceBundle, *, item_text_limit: int = 360) -> dict[str, Any]:
    return {
        "request_id": bundle.request_id,
        "request_type": bundle.request_type,
        "query": safe_excerpt(bundle.query, 180),
        "status": bundle.status,
        "fact_status": bundle.fact_status,
        "evidence_items": [_compact_mapping(item, text_limit=item_text_limit) for item in bundle.evidence_items[:3]],
        "chapter_refs": list(bundle.chapter_refs[:12]),
        "source_doc_ids": list(bundle.source_doc_ids[:12]),
        "excerpts": [_compact_mapping(item, text_limit=min(item_text_limit, 260)) for item in bundle.excerpts[:2]],
        "sources": [_compact_mapping(item, text_limit=180) for item in bundle.sources[:4]],
        "missing_facets": list(bundle.missing_facets[:6]),
    }


def _compact_evidence_bundles(bundles: Sequence[EvidenceBundle]) -> list[dict[str, Any]]:
    return [_compact_evidence_bundle(bundle) for bundle in bundles]


def _compact_final_evidence_bundles(bundles: Sequence[EvidenceBundle]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    seen_bundle_keys: set[str] = set()
    for bundle in bundles:
        if bundle.status != "found":
            continue
        source_key = ",".join(map(str, bundle.source_doc_ids[:8])) or ",".join(bundle.chapter_refs[:8])
        bundle_key = f"{bundle.request_type}:{source_key}:{safe_excerpt(normalize_whitespace(bundle.query), 48)}"
        if bundle_key in seen_bundle_keys:
            continue
        seen_bundle_keys.add(bundle_key)
        evidence_items = []
        for item in bundle.evidence_items[:3]:
            summary = normalize_whitespace(str(item.get("summary") or item.get("summary_short") or item.get("title") or ""))
            item_key = safe_excerpt(summary, 120)
            if not item_key or item_key in seen_items:
                continue
            seen_items.add(item_key)
            compact = _compact_mapping(item, text_limit=220)
            if compact:
                evidence_items.append(compact)
            if len(evidence_items) >= 2:
                break
        excerpts = []
        for item in bundle.excerpts[:1]:
            compact = _compact_mapping(item, text_limit=180)
            if compact:
                excerpts.append(compact)
        result.append(
            {
                "request_id": bundle.request_id,
                "request_type": bundle.request_type,
                "query": safe_excerpt(bundle.query, 120),
                "fact_status": bundle.fact_status,
                "evidence_items": evidence_items,
                "chapter_refs": list(bundle.chapter_refs[:6]),
                "source_doc_ids": list(bundle.source_doc_ids[:8]),
                "excerpts": excerpts,
                "sources": [_compact_mapping(item, text_limit=120) for item in bundle.sources[:2]],
            }
        )
    return result[:6]


def _prompt_bytes(system_prompt: str, user_prompt: str) -> int:
    return len(system_prompt.encode("utf-8")) + len(user_prompt.encode("utf-8"))


def _json_prompt_budget_note(stage: str, max_prompt_bytes: int) -> str:
    return (
        f"Prompt was compacted to stay under {max_prompt_bytes} UTF-8 bytes for the {stage} model call. "
        "Treat truncated fields as evidence digests, not full source text."
    )


def _clamp_json_strings(value: Any, *, text_limit: int) -> Any:
    if isinstance(value, str):
        return safe_excerpt(value, text_limit)
    if isinstance(value, list):
        return [_clamp_json_strings(item, text_limit=text_limit) for item in value]
    if isinstance(value, dict):
        return {str(key): _clamp_json_strings(item, text_limit=text_limit) for key, item in value.items()}
    return value


def _shrink_prompt_lists(value: Any, *, max_items: int) -> Any:
    shrink_keys = {
        "committed_evidence_digests",
        "candidate_evidence_digests",
        "evidence_items",
        "excerpts",
        "sources",
        "memory_page_roots",
        "character_index",
        "world_concept_index",
        "confirmed_facts",
        "reasonable_inferences",
        "uncertain_gaps",
        "candidate_directions",
        "chapters_worth_raw_read",
    }
    if isinstance(value, list):
        return [_shrink_prompt_lists(item, max_items=max_items) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in shrink_keys and isinstance(item, list) and len(item) > max_items:
            selected = item[-max_items:]
            result[key] = [_shrink_prompt_lists(child, max_items=max_items) for child in selected]
        else:
            result[key] = _shrink_prompt_lists(item, max_items=max_items)
    return result


def _notebook_prompt_payload(notebook: AnalyzerNotebook) -> dict[str, Any]:
    def strings(values: Sequence[str], *, limit: int = 8) -> list[str]:
        return [safe_excerpt(value, 240) for value in values[:limit]]

    return {
        "confirmed_facts": strings(notebook.confirmed_facts),
        "reasonable_inferences": strings(notebook.reasonable_inferences),
        "uncertain_gaps": strings(notebook.uncertain_gaps),
        "open_threads": strings(notebook.open_threads),
        "candidate_directions": strings(notebook.candidate_directions),
        "blocked_directions": strings(notebook.blocked_directions),
        "chapters_worth_raw_read": [_compact_mapping(item, text_limit=220) for item in notebook.chapters_worth_raw_read[:8]],
        "user_preferences": strings(notebook.user_preferences),
    }


def _notebook_final_payload(notebook: AnalyzerNotebook) -> dict[str, Any]:
    def strings(values: Sequence[str], *, limit: int = 5) -> list[str]:
        return [safe_excerpt(value, 160) for value in values[:limit]]

    return {
        "confirmed_facts": strings(notebook.confirmed_facts),
        "reasonable_inferences": strings(notebook.reasonable_inferences),
        "uncertain_gaps": strings(notebook.uncertain_gaps),
        "candidate_directions": strings(notebook.candidate_directions, limit=4),
        "chapters_worth_raw_read": [_compact_mapping(item, text_limit=140) for item in notebook.chapters_worth_raw_read[:4]],
    }


def _seed_prompt_payload(seed: AnalyzerSeedPacket) -> dict[str, Any]:
    payload = seed.to_dict()
    payload["character_index"] = [
        {
            "character_id": str(item.get("character_id") or ""),
            "canonical_name": str(item.get("canonical_name") or ""),
            "aliases": list(item.get("aliases") or [])[:4] if isinstance(item.get("aliases"), Sequence) and not isinstance(item.get("aliases"), (str, bytes)) else [],
            "role_hint": safe_excerpt(str(item.get("role_hint") or ""), 120),
            "status_hint": str(item.get("status_hint") or ""),
        }
        for item in seed.character_index[:8]
    ]
    payload["sources"] = [
        {
            "source_type": str(item.get("source_type") or item.get("type") or ""),
            "label": str(item.get("label") or ""),
        }
        for item in seed.sources[:6]
    ]
    return payload


def _seed_final_payload(seed: AnalyzerSeedPacket) -> dict[str, Any]:
    return {
        "book_id": seed.book_id,
        "user_question": seed.user_question,
        "conversation_brief": safe_excerpt(seed.conversation_brief, 240),
        "modeling_status": dict(seed.modeling_status),
        "story_overview_hint": safe_excerpt(seed.story_overview, 420),
        "world_concept_index": [
            {
                "term": safe_excerpt(str(item.get("term") or item.get("concept") or ""), 70),
                "scope_hint": safe_excerpt(str(item.get("scope_hint") or item.get("summary") or ""), 120),
            }
            for item in seed.world_concept_index[:4]
        ],
        "memory_page_roots": [
            {
                "page_id": str(item.get("page_id") or ""),
                "source_range": str(item.get("source_range") or ""),
                "summary": safe_excerpt(str(item.get("summary") or ""), 140),
            }
            for item in seed.memory_page_roots[:4]
        ],
    }


class AnalyzerSeedBuilder:
    """Builds the lightweight query map for Analyzer without reading full source text."""

    def __init__(
        self,
        *,
        repo_root: Path,
        assets_repo: AssetsRepo | None = None,
        chapters_repo: ChaptersRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        memory_query_service: NarrativeMemoryQueryService | None = None,
        max_story_overview_chars: int = 1000,
        max_root_pages: int = 128,
        max_characters: int = 8,
        max_character_aliases: int = 4,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.assets_repo = assets_repo or AssetsRepo()
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.memory_query_service = memory_query_service or NarrativeMemoryQueryService(repo_root=self.repo_root)
        self.max_story_overview_chars = max_story_overview_chars
        self.max_root_pages = max_root_pages
        self.max_characters = max_characters
        self.max_character_aliases = max_character_aliases

    def build(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        question: str,
        conversation_history: Sequence[Mapping[str, str]] | None = None,
    ) -> AnalyzerSeedPacket:
        assets = self._assets(conn, book_id=book_id)
        world_path = self._asset_path(assets, "world_summary_path") or self._asset_path(assets, "world_markdown_path")
        world_text = self._read_text(world_path)
        profiles = self._profiles(conn, book_id=book_id)
        roots = self._memory_roots(conn, book_id=book_id, question=question)
        outline_segments_path = self.repo_root / ".memory" / "outlines" / f"{book_id}.outline_segments.json"
        source_arc_path = self.repo_root / ".memory" / "arcs" / f"{book_id}.source_arc_map.json"
        scene_cards_path = self.repo_root / ".memory" / "index_cards" / f"{book_id}.scene_cards.json"

        sources = []
        if outline_segments_path.exists():
            sources.append({"source_type": "outline_segments", "path": str(outline_segments_path), "label": "故事大纲索引"})
        if world_path:
            sources.append({"source_type": "world", "path": str(world_path), "label": "世界观摘要"})
        if profiles:
            sources.append({"source_type": "character_profile", "path": "sqlite:character_profiles", "label": "人物档案索引"})
        if roots:
            sources.append({"source_type": "memory_page_root", "path": "memory:outline_root", "label": "Memory Page root"})
        if scene_cards_path.exists():
            sources.append({"source_type": "narrative_scene_card", "path": str(scene_cards_path), "label": "叙事场景索引"})

        story_overview = clamp_text(self._story_overview(roots), self.max_story_overview_chars)
        return AnalyzerSeedPacket(
            book_id=book_id,
            user_question=question,
            conversation_brief=self._conversation_brief(conversation_history or []),
            modeling_status={
                "documents_ready": bool(roots),
                "close_read_ready": bool(roots),
                "character_profiles_ready": bool(profiles),
                "world_summary_ready": bool(world_text),
                "story_outline_ready": bool(roots),
                "source_arc_map_ready": source_arc_path.exists(),
                "narrative_scene_cards_ready": scene_cards_path.exists(),
            },
            story_overview=story_overview,
            outline_index=[],
            source_arc_index=[],
            character_index=self._character_index(profiles, story_overview=story_overview, question=question),
            world_concept_index=self._world_concept_index(world_text),
            chapter_index=[],
            memory_page_roots=roots,
            sources=sources,
        )

    def _assets(self, conn: sqlite3.Connection, *, book_id: str) -> sqlite3.Row | None:
        try:
            return self.assets_repo.get(conn, book_id=book_id)
        except sqlite3.OperationalError:
            return None

    def _asset_path(self, assets: sqlite3.Row | None, field_name: str) -> Path | None:
        if assets is None:
            return None
        value = str(assets[field_name] or "").strip()
        if not value:
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else (self.repo_root / path).resolve()

    def _read_text(self, path: Path | None) -> str:
        if path is None or not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _chapters(self, conn: sqlite3.Connection, *, book_id: str) -> list[sqlite3.Row]:
        try:
            return self.chapters_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            return []

    def _profiles(self, conn: sqlite3.Connection, *, book_id: str) -> list[sqlite3.Row]:
        try:
            return self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            return []

    def _memory_roots(self, conn: sqlite3.Connection, *, book_id: str, question: str) -> list[dict[str, Any]]:
        _ = question
        try:
            items = self.memory_query_service.root_map(
                conn,
                book_id=book_id,
                budget=MemoryQueryBudget(max_root_candidates=self.max_root_pages, max_candidate_chars=1000),
            )
        except (AttributeError, sqlite3.OperationalError):
            return []
        return [
            {
                "page_id": str(item.get("page_id") or item.get("id") or ""),
                "page_type": str(item.get("page_type") or "outline_root"),
                "source_range": str(item.get("source_doc_range") or ""),
                "summary": safe_excerpt(str(item.get("summary") or ""), 220),
                "status": str(item.get("status") or "provisional"),
            }
            for item in items[: self.max_root_pages]
        ]

    def _story_overview(self, roots: Sequence[Mapping[str, Any]]) -> str:
        root_overview = " ".join(str(item.get("summary") or "") for item in roots[:4]).strip()
        if root_overview:
            return safe_excerpt(root_overview, self.max_story_overview_chars)
        return ""

    def _outline_index(self, outline_text: str) -> list[dict[str, Any]]:
        threads: list[dict[str, Any]] = []
        in_unresolved = False
        for line in outline_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("##"):
                in_unresolved = bool(re.search(r"未解|未决|问题|伏笔|悬念", stripped))
                continue
            if in_unresolved and stripped.startswith("-"):
                title = stripped.lstrip("- ").strip()
                if title:
                    threads.append(
                        {
                            "thread_id": f"thread-{len(threads) + 1:03d}",
                            "title": safe_excerpt(title, 100),
                            "status_hint": "unresolved",
                        }
                    )
        return threads[:20]

    def _source_arc_index(self, path: Path) -> list[dict[str, Any]]:
        payload = self._load_json(path)
        arcs = payload.get("arcs") or payload.get("source_arcs") or []
        items = []
        for index, arc in enumerate(arcs if isinstance(arcs, list) else [], start=1):
            if not isinstance(arc, Mapping):
                continue
            items.append(
                {
                    "arc_id": str(arc.get("source_arc_id") or arc.get("id") or f"arc-{index:03d}"),
                    "title": str(arc.get("source_arc_title") or arc.get("title") or ""),
                    "chapter_range": f"{arc.get('start_document_title_index', '')}-{arc.get('end_document_title_index', '')}",
                    "function_hint": str(arc.get("source_arc_role") or arc.get("role") or ""),
                }
            )
        return items[:24]

    def _character_index(self, rows: Sequence[sqlite3.Row], *, story_overview: str, question: str) -> list[dict[str, Any]]:
        context = f"{story_overview}\n{question}"
        tokens = set(_tokens(context))
        generic_character_question = self._is_generic_character_question(question)
        scored: dict[int, tuple[int, int, sqlite3.Row]] = {}
        for row in rows:
            canonical = str(row["canonical_name"] or "")
            aliases = [str(item) for item in _json_list(row["aliases_json"])]
            name_hit = 0
            if canonical and canonical in context:
                name_hit += 20
            name_hit += 12 * sum(1 for alias in aliases if alias and alias in context)
            haystack = " ".join([canonical, *aliases, self._profile_hint(row)])
            token_hit = sum(1 for token in tokens if token in haystack)
            centrality = self._character_centrality_score(row)
            if name_hit > 0 or token_hit >= 2:
                score = 1000 + name_hit * 10 + token_hit + centrality
                scored[int(row["character_id"])] = (score, centrality, row)
            elif generic_character_question and centrality > 0:
                scored[int(row["character_id"])] = (centrality, centrality, row)
        ranked = [
            row
            for _, _, row in sorted(
                scored.values(),
                key=lambda item: (-item[0], -item[1], str(item[2]["canonical_name"] or "")),
            )
        ]
        return [
            {
                "character_id": str(row["character_id"]),
                "canonical_name": str(row["canonical_name"] or ""),
                "aliases": [str(item) for item in _json_list(row["aliases_json"])][: self.max_character_aliases],
                "role_hint": safe_excerpt(self._profile_hint(row), 70),
                "status_hint": str(row["evidence_level"] or "inferred"),
            }
            for row in ranked[: self.max_characters]
        ]

    def _is_generic_character_question(self, question: str) -> bool:
        text = normalize_whitespace(question)
        return any(term in text for term in GENERIC_CHARACTER_QUERY_TERMS)

    def _character_centrality_score(self, row: sqlite3.Row) -> int:
        def json_count(field_name: str) -> int:
            return len(_json_list(row[field_name]))

        doc_span = 0
        try:
            first_doc = int(row["first_seen_doc_id"] or 0)
            last_doc = int(row["last_seen_doc_id"] or 0)
        except (TypeError, ValueError):
            first_doc = 0
            last_doc = 0
        if first_doc > 0 and last_doc >= first_doc:
            doc_span = last_doc - first_doc + 1
        title_span = 0
        try:
            first_title = int(row["first_seen_title_index"] or 0)
            last_title = int(row["last_seen_title_index"] or 0)
        except (TypeError, ValueError):
            first_title = 0
            last_title = 0
        if first_title > 0 and last_title >= first_title:
            title_span = last_title - first_title + 1
        speaking_bonus = 4 if str(row["speaking_character_status"] or "") == "confirmed_speaking" else 0
        explicit_bonus = 3 if str(row["evidence_level"] or "") == "explicit" else 0
        profile_bonus = min(len(self._profile_hint(row)) // 400, 6)
        return (
            int(row["importance_score"] or 0) * 4
            + json_count("mentioned_doc_ids_json") * 4
            + json_count("speaking_doc_ids_json") * 5
            + json_count("chapter_indexes_json") * 6
            + max(doc_span, title_span)
            + speaking_bonus
            + explicit_bonus
            + profile_bonus
        )

    def _profile_hint(self, row: sqlite3.Row) -> str:
        text = normalize_whitespace(str(row["profile_summary_md"] or ""))
        canonical = re.escape(str(row["canonical_name"] or ""))
        text = re.sub(rf"^#\s*{canonical}\s*-\s*", "", text)
        text = re.sub(r"相关章节：[^-#]+-\s*", "", text)
        text = re.sub(r"别名：[^-#]+-\s*", "", text)
        text = re.sub(r"证据级别：[^-#]+-\s*", "", text)
        text = re.sub(r"发言状态：[^-#]+-\s*", "", text)
        text = text.replace("人物性证据：", "")
        return normalize_whitespace(text)

    def _world_concept_index(self, world_text: str) -> list[dict[str, Any]]:
        concepts: list[dict[str, Any]] = []
        for line in world_text.splitlines():
            stripped = line.strip("#- ")
            if not stripped:
                continue
            if line.startswith("##") or re.search(r"规则|限制|代价|禁忌|体系|势力", stripped):
                concepts.append(
                    {
                        "concept_id": f"world-{len(concepts) + 1:03d}",
                        "term": safe_excerpt(stripped, 50),
                        "kind": "rule",
                        "scope_hint": safe_excerpt(stripped, 100),
                    }
                )
            if len(concepts) >= 16:
                break
        return concepts

    def _chapter_index(self, rows: Sequence[sqlite3.Row], *, question: str) -> list[dict[str, Any]]:
        tokens = set(_tokens(question))
        ranked = sorted(
            rows,
            key=lambda row: (
                -sum(
                    1
                    for token in tokens
                    if token in " ".join([str(row["chapter_title"] or ""), str(row["summary_short"] or ""), str(row["summary_md"] or "")])
                ),
                -int(row["importance_score"] or 0),
                int(row["document_title_index"] or 0),
            ),
        )
        selected = sorted(ranked[: self.max_chapters], key=lambda row: int(row["document_title_index"] or 0))
        return [
            {
                "chapter_id": f"chapter-{int(row['document_title_index'] or 0)}",
                "document_title_index": int(row["document_title_index"] or 0),
                "title": str(row["chapter_title"] or ""),
                "summary_hint": safe_excerpt(str(row["summary_short"] or row["summary_md"] or ""), 120),
                "importance_hint": str(row["importance_score"] or 0),
                "summary_status": str(row["summary_status"] or "provisional"),
            }
            for row in selected
        ]

    def _conversation_brief(self, history: Sequence[Mapping[str, str]]) -> str:
        parts = []
        for item in history[-6:]:
            role = str(item.get("role") or "")
            content = normalize_whitespace(str(item.get("content") or ""))
            if role and content:
                parts.append(f"{role}: {safe_excerpt(content, 160)}")
        return "\n".join(parts)

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}


class OutlineAnalyzerService:
    """Read-only model-driven outline analyzer.

    The service owns no private retrieval path. It builds a seed packet, accepts
    model-issued Narrative Inquiry requests, sends them to the shared broker,
    records evidence in a temporary notebook, and asks the model for the final
    user-facing answer.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        model_client: Any | None = None,
        seed_builder: AnalyzerSeedBuilder | None = None,
        inquiry_broker: NarrativeInquiryBroker | None = None,
        budget: AnalyzerBudget | None = None,
        **legacy_budget_kwargs: Any,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.model_client = model_client
        self.seed_builder = seed_builder or AnalyzerSeedBuilder(repo_root=self.repo_root)
        self.inquiry_broker = inquiry_broker or NarrativeInquiryBroker(repo_root=self.repo_root)
        self.budget = budget or AnalyzerBudget()
        # Kept for compatibility with older callers that configured prompt-slice
        # sizes. The new loop budgets live in AnalyzerBudget.
        self.legacy_budget_kwargs = dict(legacy_budget_kwargs)

    def chat(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        question: str,
        conversation_history: Sequence[Mapping[str, str]] | None = None,
    ) -> AnalyzerChatResult:
        normalized_question = normalize_whitespace(question)
        if not normalized_question:
            raise ValueError("Analyzer question is required")
        seed = self.seed_builder.build(
            conn,
            book_id=book_id,
            question=normalized_question,
            conversation_history=conversation_history or [],
        )
        sources = [AnalyzerSource(str(item.get("source_type") or item.get("type") or ""), str(item.get("path") or ""), str(item.get("label") or "")) for item in seed.sources]
        notebook = AnalyzerNotebook()
        if self.model_client is None:
            return AnalyzerChatResult(
                status="needs_model",
                answer=(
                    "Analyzer 需要可用模型才能进行剧情分析。当前只完成了只读 seed 装配，"
                    "没有生成语义判断；请配置模型后重试。"
                ),
                sources=sources,
                seed=seed,
                notebook=notebook,
                trace={"failure": "missing_model"},
            )

        trace: dict[str, Any] = {"rounds": []}
        budget_state = {"total_requests_used": 0, "raw_requests_used": 0, "exhausted": False}
        evidence_history: list[EvidenceBundle] = []
        for round_index in range(1, self.budget.max_rounds + 1):
            loop_output = self._call_loop_model(
                book_id=book_id,
                round_index=round_index,
                seed=seed,
                notebook=notebook,
                evidence_history=evidence_history,
                budget_state=budget_state,
            )
            if loop_output.status in {"failed", "blocked"}:
                return AnalyzerChatResult(
                    status=loop_output.status,
                    answer=loop_output.message or "Analyzer 模型输出无法解析，已停止本轮分析。",
                    sources=sources,
                    seed=seed,
                    notebook=notebook,
                    evidence_bundles=evidence_history,
                    trace={**trace, "failure": loop_output.to_dict()},
                )
            notebook.apply_delta(loop_output.notebook_delta)
            if loop_output.status == "ready_to_answer":
                try:
                    answer = loop_output.final_answer or self._call_final_answer_model(book_id=book_id, seed=seed, notebook=notebook, evidence_history=evidence_history)
                except RuntimeError as exc:
                    return AnalyzerChatResult(
                        status="failed",
                        answer=f"Analyzer 最终回答模型调用失败：{exc}",
                        sources=sources,
                        seed=seed,
                        notebook=notebook,
                        evidence_bundles=evidence_history,
                        trace={**trace, "failure": str(exc), "final_budget_state": budget_state},
                    )
                return AnalyzerChatResult(
                    status="ok",
                    answer=answer,
                    sources=sources,
                    seed=seed,
                    notebook=notebook,
                    evidence_bundles=evidence_history,
                    trace={**trace, "final_budget_state": budget_state},
                )
            if loop_output.status in {"needs_user_preference", "insufficient_memory", "budget_exhausted"}:
                answer = loop_output.final_answer or loop_output.message or self._status_answer(loop_output.status, notebook=notebook)
                return AnalyzerChatResult(
                    status=loop_output.status,
                    answer=answer,
                    sources=sources,
                    seed=seed,
                    notebook=notebook,
                    evidence_bundles=evidence_history,
                    trace={**trace, "final_budget_state": budget_state},
                )

            requests = self._filter_requests(loop_output.requests, budget_state=budget_state)
            if not requests:
                budget_state["exhausted"] = True
                return AnalyzerChatResult(
                    status="budget_exhausted",
                    answer=self._status_answer("budget_exhausted", notebook=notebook),
                    sources=sources,
                    seed=seed,
                    notebook=notebook,
                    evidence_bundles=evidence_history,
                    trace={**trace, "final_budget_state": budget_state},
                )
            bundles, used = self.inquiry_broker.resolve_requests(
                conn,
                book_id=book_id,
                requests=requests,
                budget=self.budget,
                total_requests_used=int(budget_state["total_requests_used"]),
                raw_requests_used=int(budget_state["raw_requests_used"]),
            )
            budget_state.update(used)
            try:
                triage = self._call_triage_model(
                    book_id=book_id,
                    round_index=round_index,
                    seed=seed,
                    notebook=notebook,
                    requests=requests,
                    candidate_bundles=bundles,
                    budget_state=budget_state,
                )
            except RuntimeError as exc:
                return AnalyzerChatResult(
                    status="failed",
                    answer=f"Analyzer evidence triage 模型调用失败：{exc}",
                    sources=sources,
                    seed=seed,
                    notebook=notebook,
                    evidence_bundles=evidence_history,
                    trace={**trace, "failure": str(exc), "final_budget_state": budget_state},
                )
            kept_ids = set(triage.kept_request_ids)
            kept_bundles = [bundle for bundle in bundles if bundle.request_id in kept_ids]
            notebook.add_evidence(kept_bundles)
            evidence_history.extend(kept_bundles)
            trace["rounds"].append(
                {
                    "round": round_index,
                    "loop_output": loop_output.to_dict(),
                    "triage": triage.to_dict(),
                    "candidate_evidence_digests": _compact_evidence_bundles(bundles),
                    "committed_evidence_digests": _compact_evidence_bundles(kept_bundles),
                    "budget_state": dict(budget_state),
                }
            )
            if int(budget_state["total_requests_used"]) >= self.budget.max_total_requests:
                budget_state["exhausted"] = True
                break

        try:
            answer = self._call_final_answer_model(book_id=book_id, seed=seed, notebook=notebook, evidence_history=evidence_history, budget_limited=True)
        except RuntimeError as exc:
            return AnalyzerChatResult(
                status="failed",
                answer=f"Analyzer 最终回答模型调用失败：{exc}",
                sources=sources,
                seed=seed,
                notebook=notebook,
                evidence_bundles=evidence_history,
                trace={**trace, "failure": str(exc), "final_budget_state": budget_state},
            )
        return AnalyzerChatResult(
            status="budget_exhausted" if budget_state["exhausted"] else "ok",
            answer=answer,
            sources=sources,
            seed=seed,
            notebook=notebook,
            evidence_bundles=evidence_history,
            trace={**trace, "final_budget_state": budget_state},
        )

    def _filter_requests(
        self,
        requests: Sequence[NarrativeInquiryRequest],
        *,
        budget_state: Mapping[str, Any],
    ) -> list[NarrativeInquiryRequest]:
        remaining = self.budget.max_total_requests - int(budget_state.get("total_requests_used") or 0)
        if remaining <= 0:
            return []
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        selected = sorted(requests, key=lambda item: priority_rank[item.priority])
        return selected[: min(self.budget.max_requests_per_round, remaining)]

    def _call_loop_model(
        self,
        *,
        book_id: str,
        round_index: int,
        seed: AnalyzerSeedPacket,
        notebook: AnalyzerNotebook,
        evidence_history: Sequence[EvidenceBundle],
        budget_state: Mapping[str, Any],
    ) -> AnalyzerLoopOutput:
        system_prompt, user_prompt = self.build_loop_prompt(
            seed=seed,
            notebook=notebook,
            evidence_history=evidence_history,
            budget_state=budget_state,
        )
        last_error = ""
        for attempt in range(self.budget.max_json_retries + 1):
            system_prompt, user_prompt = self._fit_prompt_to_budget(
                system_prompt,
                user_prompt,
                stage="loop",
                book_id=book_id,
                round_index=round_index,
            )
            self._log_model_prompt_stats(
                book_id=book_id,
                stage="loop",
                round_index=round_index,
                attempt_index=attempt + 1,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                evidence_bundle_count=len(evidence_history),
            )
            try:
                raw = self.model_client.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)
                parsed = extract_json_blob(str(raw))
                if not isinstance(parsed, Mapping):
                    raise ValueError("Analyzer loop output must be a JSON object")
                return AnalyzerLoopOutput.from_mapping(parsed)
            except Exception as exc:  # noqa: BLE001 - surfaced as explicit Analyzer failure.
                last_error = str(exc)
                system_prompt = (
                    f"{system_prompt}\n\n上一次输出无法解析为指定 JSON。请只返回 JSON 对象。"
                    f"\n解析错误：{safe_excerpt(last_error, 300)}\n重试次数：{attempt + 1}"
                )
        return AnalyzerLoopOutput(status="failed", message=f"Analyzer 模型 JSON 输出解析失败：{last_error}")

    def _call_triage_model(
        self,
        *,
        book_id: str,
        round_index: int,
        seed: AnalyzerSeedPacket,
        notebook: AnalyzerNotebook,
        requests: Sequence[NarrativeInquiryRequest],
        candidate_bundles: Sequence[EvidenceBundle],
        budget_state: Mapping[str, Any],
    ) -> EvidenceTriageResult:
        if not candidate_bundles:
            return EvidenceTriageResult()
        kept: list[str] = []
        rejected: list[str] = []
        notes: list[str] = []
        request_by_id = {request.request_id: request for request in requests}
        for bundle_index, bundle in enumerate(candidate_bundles, start=1):
            request = request_by_id.get(bundle.request_id)
            result = self._call_single_triage_model(
                book_id=book_id,
                round_index=round_index,
                bundle_index=bundle_index,
                seed=seed,
                notebook=notebook,
                request=request,
                candidate_bundle=bundle,
                budget_state=budget_state,
                kept_request_ids=kept,
            )
            kept.extend(item for item in result.kept_request_ids if item not in kept)
            rejected.extend(item for item in result.rejected_request_ids if item not in rejected and item not in kept)
            notes.extend(item for item in result.notes if item not in notes)
        return EvidenceTriageResult(kept_request_ids=kept, rejected_request_ids=rejected, notes=notes)

    def _call_single_triage_model(
        self,
        *,
        book_id: str,
        round_index: int,
        bundle_index: int,
        seed: AnalyzerSeedPacket,
        notebook: AnalyzerNotebook,
        request: NarrativeInquiryRequest | None,
        candidate_bundle: EvidenceBundle,
        budget_state: Mapping[str, Any],
        kept_request_ids: Sequence[str],
    ) -> EvidenceTriageResult:
        system_prompt, user_prompt = self.build_single_triage_prompt(
            seed=seed,
            notebook=notebook,
            request=request,
            candidate_bundle=candidate_bundle,
            budget_state=budget_state,
            kept_request_ids=kept_request_ids,
        )
        last_error = ""
        candidate_ids = [candidate_bundle.request_id]
        for attempt in range(self.budget.max_json_retries + 1):
            system_prompt, user_prompt = self._fit_prompt_to_budget(
                system_prompt,
                user_prompt,
                stage="triage",
                book_id=book_id,
                round_index=round_index,
            )
            self._log_model_prompt_stats(
                book_id=book_id,
                stage="triage",
                round_index=round_index,
                attempt_index=(bundle_index * 100) + attempt + 1,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                evidence_bundle_count=1,
            )
            try:
                raw = self.model_client.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)
                parsed = extract_json_blob(str(raw))
                if not isinstance(parsed, Mapping):
                    raise ValueError("Analyzer triage output must be a JSON object")
                return EvidenceTriageResult.from_mapping(parsed, candidate_request_ids=candidate_ids)
            except Exception as exc:  # noqa: BLE001 - surfaced as explicit Analyzer failure.
                last_error = str(exc)
                system_prompt = (
                    f"{system_prompt}\n\n上一次 triage 输出无法解析为指定 JSON。请只返回 JSON 对象。"
                    f"\n解析错误：{safe_excerpt(last_error, 300)}\n重试次数：{attempt + 1}"
                )
        raise RuntimeError(f"Analyzer triage JSON 输出解析失败：{last_error}")

    def _call_final_answer_model(
        self,
        *,
        book_id: str,
        seed: AnalyzerSeedPacket,
        notebook: AnalyzerNotebook,
        evidence_history: Sequence[EvidenceBundle],
        budget_limited: bool = False,
    ) -> str:
        system_prompt, user_prompt = self.build_final_prompt(
            seed=seed,
            notebook=notebook,
            evidence_history=evidence_history,
            budget_limited=budget_limited,
        )
        system_prompt, user_prompt = self._fit_prompt_to_budget(
            system_prompt,
            user_prompt,
            stage="final",
            book_id=book_id,
            round_index=None,
        )
        self._log_model_prompt_stats(
            book_id=book_id,
            stage="final",
            round_index=None,
            attempt_index=1,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            evidence_bundle_count=len(evidence_history),
            budget_limited=budget_limited,
        )
        try:
            answer = str(self.model_client.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)).strip()
        except Exception as exc:  # noqa: BLE001 - no local semantic fallback.
            raise RuntimeError(f"Outline Analyzer final answer model call failed: {exc}") from exc
        if not answer:
            raise RuntimeError("Outline Analyzer final answer model returned empty text")
        return answer

    def _fit_prompt_to_budget(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        stage: str,
        book_id: str,
        round_index: int | None,
    ) -> tuple[str, str]:
        max_prompt_bytes = int(self.budget.max_prompt_bytes)
        if _prompt_bytes(system_prompt, user_prompt) <= max_prompt_bytes:
            return system_prompt, user_prompt

        original_bytes = _prompt_bytes(system_prompt, user_prompt)
        try:
            payload = json.loads(user_prompt)
        except json.JSONDecodeError:
            available = max(256, max_prompt_bytes - len(system_prompt.encode("utf-8")) - 256)
            compact_user_prompt = safe_excerpt(user_prompt, available)
            logger.warning(
                "outline_analyzer.prompt_compacted book_id=%s stage=%s round=%s original_bytes=%s compacted_bytes=%s max_prompt_bytes=%s mode=text",
                book_id,
                stage,
                round_index if round_index is not None else "-",
                original_bytes,
                _prompt_bytes(system_prompt, compact_user_prompt),
                max_prompt_bytes,
            )
            return system_prompt, compact_user_prompt

        if isinstance(payload, dict):
            payload["_prompt_budget_note"] = _json_prompt_budget_note(stage, max_prompt_bytes)
        compact_payload: Any = payload
        for max_items in (6, 4, 3, 2, 1):
            compact_payload = _shrink_prompt_lists(compact_payload, max_items=max_items)
            for text_limit in (900, 700, 520, 360, 240, 160, 100, 64):
                candidate_payload = _clamp_json_strings(compact_payload, text_limit=text_limit)
                candidate_prompt = json.dumps(candidate_payload, ensure_ascii=False, indent=2)
                if _prompt_bytes(system_prompt, candidate_prompt) <= max_prompt_bytes:
                    logger.warning(
                        "outline_analyzer.prompt_compacted book_id=%s stage=%s round=%s original_bytes=%s compacted_bytes=%s max_prompt_bytes=%s mode=json max_items=%s text_limit=%s",
                        book_id,
                        stage,
                        round_index if round_index is not None else "-",
                        original_bytes,
                        _prompt_bytes(system_prompt, candidate_prompt),
                        max_prompt_bytes,
                        max_items,
                        text_limit,
                    )
                    return system_prompt, candidate_prompt

        available = max(256, max_prompt_bytes - len(system_prompt.encode("utf-8")) - 256)
        fallback_prompt = safe_excerpt(json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":")), available)
        logger.warning(
            "outline_analyzer.prompt_compacted book_id=%s stage=%s round=%s original_bytes=%s compacted_bytes=%s max_prompt_bytes=%s mode=json_fallback",
            book_id,
            stage,
            round_index if round_index is not None else "-",
            original_bytes,
            _prompt_bytes(system_prompt, fallback_prompt),
            max_prompt_bytes,
        )
        return system_prompt, fallback_prompt

    def _log_model_prompt_stats(
        self,
        *,
        book_id: str,
        stage: str,
        round_index: int | None,
        attempt_index: int,
        system_prompt: str,
        user_prompt: str,
        evidence_bundle_count: int,
        budget_limited: bool = False,
    ) -> None:
        system_chars = len(system_prompt)
        user_chars = len(user_prompt)
        total_chars = system_chars + user_chars
        system_bytes = len(system_prompt.encode("utf-8"))
        user_bytes = len(user_prompt.encode("utf-8"))
        logger.info(
            "outline_analyzer.model_prompt_stats book_id=%s stage=%s round=%s attempt=%s "
            "system_chars=%s user_chars=%s total_chars=%s system_bytes=%s user_bytes=%s "
            "total_bytes=%s evidence_bundles=%s budget_limited=%s model=%s",
            book_id,
            stage,
            round_index if round_index is not None else "-",
            attempt_index,
            system_chars,
            user_chars,
            total_chars,
            system_bytes,
            user_bytes,
            system_bytes + user_bytes,
            evidence_bundle_count,
            budget_limited,
            self._model_label(),
        )

    def _model_label(self) -> str:
        settings = getattr(self.model_client, "settings", None)
        for source in (settings, self.model_client):
            for attr in ("model", "model_id", "model_name"):
                value = getattr(source, attr, None)
                if value:
                    return str(value)
        return type(self.model_client).__name__

    def build_loop_prompt(
        self,
        *,
        seed: AnalyzerSeedPacket,
        notebook: AnalyzerNotebook,
        evidence_history: Sequence[EvidenceBundle],
        budget_state: Mapping[str, Any],
    ) -> tuple[str, str]:
        system_prompt = (
            "你是只读 Outline Analyzer。你只能分析和建议，不能写 Memory、Writer artifact 或推进 workflow。\n"
            "不要声称已经读完整本书；先使用 seed 判断信息需求，再请求补充 evidence。\n"
            "必须区分 confirmed fact、reasonable inference、uncertain gap、user preference、speculative option。\n"
            "如果需要读原文，必须说明为什么摘要不足、要确认什么、会影响哪个分析判断。\n"
            "优先使用 Narrative Index compact cards，尤其是 narrative_scene_card_search 来定位关键场景、情绪转折、"
            "关系变化、设定揭示和后续影响；只有 compact cards 不足时，再请求 chapter_summary/story_detail/raw_excerpt。\n"
            "重大剧情转向保持保守，不替用户授权终局秘密、角色死亡或世界规则突破。\n"
            f"{ANALYZER_ANALYSIS_QUESTION_POLICY}\n"
            "除非用户只是在询问当前索引/建模状态，第一轮不要直接 ready_to_answer；"
            "请先请求 1-3 条与用户问题直接相关的 evidence，让后续回答有可审计依据。\n"
            "need_more_info 时 requests 不得为空；每个 request 必须至少填写 query、name、concept、"
            "chapter_refs、document_ids 或 source_doc_ids 中的一个目标字段。"
            "如果无法确定专名，请用 query 描述要查的具体信息需求。\n"
            "每轮只返回 JSON：status、requests、notebook_delta、可选 final_answer/message。"
        )
        payload = {
            "analyzer_seed_packet": _seed_prompt_payload(seed),
            "analyzer_notebook": _notebook_prompt_payload(notebook),
            "committed_evidence_digests": _compact_evidence_bundles(evidence_history[-6:]),
            "remaining_budget": {
                **self.budget.to_dict(),
                "total_requests_used": int(budget_state.get("total_requests_used") or 0),
                "raw_requests_used": int(budget_state.get("raw_requests_used") or 0),
            },
            "available_request_types": [
                "index_card_search",
                "factual_event_card_search",
                "narrative_scene_card_search",
                "character_state_card_search",
                "mystery_card_search",
                "theme_signal_card_search",
                "world_concept_card_search",
                "creative_reference_card_search",
                "story_detail",
                "fact_check",
                "related_documents",
                "chapter_summary",
                "character_profile",
                "world_concept",
                "source_arc",
                "open_threads",
                "raw_excerpt",
                "structure_pattern",
            ],
            "output_schema": {
                "status": "need_more_info | ready_to_answer | needs_user_preference | insufficient_memory | budget_exhausted",
                "requests": [
                    {
                        "type": "narrative_scene_card_search",
                        "query": "语义查询，优先定位与用户问题相关的关键场景/转折/关系变化",
                        "purpose": "为什么需要此类 scene card evidence",
                        "priority": "high | medium | low",
                        "expected_depth": "index_card_summary",
                    }
                ],
                "notebook_delta": {
                    "confirmed_facts": [],
                    "reasonable_inferences": [],
                    "uncertain_gaps": [],
                    "candidate_directions": [],
                    "chapters_worth_raw_read": [],
                    "questions_for_user": [],
                },
                "final_answer": "ready_to_answer 时可直接给用户可读回答",
            },
        }
        return system_prompt, json.dumps(payload, ensure_ascii=False, indent=2)

    def build_triage_prompt(
        self,
        *,
        seed: AnalyzerSeedPacket,
        notebook: AnalyzerNotebook,
        requests: Sequence[NarrativeInquiryRequest],
        candidate_bundles: Sequence[EvidenceBundle],
        budget_state: Mapping[str, Any],
    ) -> tuple[str, str]:
        system_prompt = (
            "你是 Outline Analyzer 的 evidence triage 子步骤，只判断候选证据是否值得进入后续上下文。\n"
            "不要给用户最终建议，不要补写剧情。只根据用户问题、request purpose、当前 notebook 和候选 evidence digest 判断相关性。\n"
            "保留直接支撑回答、暴露关键缺口、或能防止错误推断的 evidence；剔除只因关键词偶然命中、过宽、重复或无法改变判断的 evidence。\n"
            "只返回 JSON：kept_request_ids、rejected_request_ids、notes。"
        )
        payload = {
            "user_question": seed.user_question,
            "story_overview": seed.story_overview,
            "analyzer_notebook": _notebook_prompt_payload(notebook),
            "requests": [request.to_dict() for request in requests],
            "candidate_evidence_digests": _compact_evidence_bundles(candidate_bundles),
            "budget_state": {
                "total_requests_used": int(budget_state.get("total_requests_used") or 0),
                "raw_requests_used": int(budget_state.get("raw_requests_used") or 0),
            },
            "output_schema": {
                "kept_request_ids": ["req-001"],
                "rejected_request_ids": ["req-002"],
                "notes": ["简短说明保留/剔除依据"],
            },
        }
        return system_prompt, json.dumps(payload, ensure_ascii=False, indent=2)

    def build_single_triage_prompt(
        self,
        *,
        seed: AnalyzerSeedPacket,
        notebook: AnalyzerNotebook,
        request: NarrativeInquiryRequest | None,
        candidate_bundle: EvidenceBundle,
        budget_state: Mapping[str, Any],
        kept_request_ids: Sequence[str],
    ) -> tuple[str, str]:
        system_prompt = (
            "你是 Outline Analyzer 的逐条 evidence triage 子步骤。\n"
            "本轮只评估一个候选 evidence 是否值得进入后续上下文；不要给用户最终建议，不要补写剧情。\n"
            "只保留能直接支撑回答、暴露关键缺口、或防止错误推断的 evidence。"
            "遇到 narrative_scene index card 时，重点看 scene_type、turning_point、outcome、relationship_movements、"
            "future_consequence、summary_sufficiency 和 raw_read_reason；摘要充分则不要求回读原文。"
            "关键词偶然命中、过宽、重复或无法改变判断的 evidence 必须剔除。\n"
            "只返回 JSON：kept_request_ids、rejected_request_ids、notes。"
        )
        payload = {
            "user_question": seed.user_question,
            "story_overview_hint": safe_excerpt(seed.story_overview, 360),
            "analyzer_notebook_brief": {
                "confirmed_facts": [safe_excerpt(item, 120) for item in notebook.confirmed_facts[-4:]],
                "reasonable_inferences": [safe_excerpt(item, 120) for item in notebook.reasonable_inferences[-4:]],
                "uncertain_gaps": [safe_excerpt(item, 120) for item in notebook.uncertain_gaps[-4:]],
            },
            "request": request.to_dict() if request is not None else {"request_id": candidate_bundle.request_id, "type": candidate_bundle.request_type, "query": candidate_bundle.query},
            "candidate_evidence_digest": _compact_evidence_bundle(candidate_bundle, item_text_limit=260),
            "already_kept_request_ids": list(kept_request_ids),
            "budget_state": {
                "total_requests_used": int(budget_state.get("total_requests_used") or 0),
                "raw_requests_used": int(budget_state.get("raw_requests_used") or 0),
            },
            "output_schema": {
                "kept_request_ids": [candidate_bundle.request_id],
                "rejected_request_ids": [],
                "notes": ["一句话说明保留/剔除依据"],
            },
        }
        return system_prompt, json.dumps(payload, ensure_ascii=False, indent=2)

    def build_final_prompt(
        self,
        *,
        seed: AnalyzerSeedPacket,
        notebook: AnalyzerNotebook,
        evidence_history: Sequence[EvidenceBundle],
        budget_limited: bool,
    ) -> tuple[str, str]:
        system_prompt = (
            "你是只读 Outline Analyzer。请基于 seed、notebook 和 evidence 给出用户可读中文分析。\n"
            "先给结论，再说明文学分析、事实依据、风险、可选走向、建议回读章节和需要用户确认的问题。\n"
            f"{ANALYZER_ANALYSIS_QUESTION_POLICY}\n"
            "如果 evidence 中包含 narrative_scene card，请把它当作场景级结构证据使用：说明对应场景如何支撑人物性格、"
            "关系推进、世界观揭示、主题表达或后续行动推测。"
            "如果证据只能支持暂定判断，请直接给暂定判断，并在同一份回答中列出证据缺口和非阻塞追问。\n"
            "不要输出 JSON。不得夸大证据覆盖范围，不得把推断写成已确认事实。"
        )
        payload = {
            "user_question": seed.user_question,
            "seed_brief": _seed_final_payload(seed),
            "notebook": _notebook_final_payload(notebook),
            "committed_evidence_digests": _compact_final_evidence_bundles(evidence_history),
            "budget_limited": budget_limited,
            "rubric": [
                "Canon fit",
                "Causal strength",
                "Character pressure",
                "Tension growth",
                "Clue resolution rhythm",
                "Pacing fit",
                "Thematic resonance",
                "Reader promise",
            ],
        }
        return system_prompt, json.dumps(payload, ensure_ascii=False, indent=2)

    def _status_answer(self, status: str, *, notebook: AnalyzerNotebook) -> str:
        if status == "budget_exhausted":
            gaps = "；".join(notebook.uncertain_gaps[:4]) or "仍有证据缺口"
            return f"本轮 Analyzer 查询预算已经用完，只能给出带限制的暂定分析。未充分确认：{gaps}。"
        if status == "insufficient_memory":
            return "当前 Memory 建模不足，Analyzer 无法做可靠剧情分析。请先补齐粗读、精读、人物档案、世界观或故事大纲。"
        if status == "needs_user_preference":
            return (
                "现有证据可支持多个互斥创作方向，且继续判断需要用户确认偏好或授权边界。"
                "如果只是做剧情评价或可能走向分析，Analyzer 应先给带证据边界的暂定结论。"
            )
        return "Analyzer 本轮未能继续推进分析。"

    # Compatibility helper retained for older tests and callers. It now returns
    # only the seed map, not a full prompt context or raw document excerpts.
    def build_context(self, conn: sqlite3.Connection, *, book_id: str, question: str = "") -> AnalyzerSeedPacket:
        normalized_question = normalize_whitespace(question) or "当前故事大纲分析"
        return self.seed_builder.build(conn, book_id=book_id, question=normalized_question)

    def build_prompt(
        self,
        *,
        question: str,
        context: AnalyzerSeedPacket,
        conversation_history: Sequence[Mapping[str, str]],
    ) -> tuple[str, str]:
        _ = question, conversation_history
        return self.build_loop_prompt(
            seed=context,
            notebook=AnalyzerNotebook(),
            evidence_history=[],
            budget_state={"total_requests_used": 0, "raw_requests_used": 0},
        )
