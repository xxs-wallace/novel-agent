from __future__ import annotations

import json
import re
import sqlite3
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ...runs.writer import RunWriter
from ...schemas.continuity import ContinuityIssue, ContinuityReport
from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.documents_repo import DocumentsRepo
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..repos.fragment_clusters_repo import FragmentClustersRepo
from ..repos.semantic_aliases_repo import SemanticAliasesRepo
from ..schemas.creative_kb_schema import SceneBrief
from ..schemas.orchestration_schema import FreezeRecord, StateChange, StateDelta
from ..services.character_mention_service import CharacterMentionService
from ..services.character_profile_service import CharacterProfileService
from ..services.coarse_retrieval_service import CoarseRetrievalService
from ..services.outline_service import OutlineService
from ..services.rerank_service import RerankService
from ..services.world_state_service import WorldStateService


NARRATION_CONSISTENCY_RULES = (
    "必须识别并延续原作已建立的叙事视角、叙述者身份、信息可见性和视角切换习惯。",
    "如果原作采用固定第一人称或固定限知视角，续写不得擅自更换第一人称叙述者或改成另一名角色自述。",
    "如果原作采用全知视角、多视角或可进入多人内心的写法，续写可以沿用该习惯，但不得新增原作没有建立过的视角机制。",
    "角色内心、现场细节和离场事件的呈现方式必须与原作的信息来源习惯一致。",
    "当冻结事实、风格参考和用户输入发生冲突时，优先保持原作叙事契约与已冻结事实。",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_string_list(items: object) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        text = items.strip()
        return [text] if text else []
    if not isinstance(items, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _safe_excerpt(text: str, *, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def build_authorized_synopsis_execution_input(
    *,
    base_execution_data: Mapping[str, Any],
    authorized_synopsis: Mapping[str, Any],
    story_outline: Mapping[str, Any] | None = None,
    story_context: Mapping[str, Any] | None = None,
    target_chars: int | None = None,
    synopsis_source: str = "authorized_story_synopsis",
) -> dict[str, Any]:
    """Build a Writer execution input from an authorized synopsis without re-planning prose generation."""
    story_outline = story_outline or {}
    story_context = story_context or {}
    execution_input = deepcopy(dict(base_execution_data))
    chapter_id = _normalize_text(execution_input.get("chapter_id")) or "authorized-synopsis-expansion"
    chapter_title = (
        _normalize_text(story_outline.get("next_outline_node"))
        or _normalize_text(execution_input.get("chapter_title"))
        or "授权梗概扩写"
    )
    source_chars = _positive_int(authorized_synopsis.get("source_chars"), fallback=target_chars or 0)
    target_length = _positive_int(target_chars, fallback=source_chars or 1800)
    plot_beats = _normalize_string_list(authorized_synopsis.get("plot_beats"))
    coverage_plot_beats = _normalize_string_list(authorized_synopsis.get("must_preserve")) or plot_beats
    continuity_must_include = _continuity_requirements_from_plot_beats(coverage_plot_beats or plot_beats)
    combined_synopsis = _normalize_text(authorized_synopsis.get("combined_synopsis"))
    document_synopses = [
        dict(item)
        for item in authorized_synopsis.get("document_synopses", [])
        if isinstance(item, Mapping)
    ]
    tone_and_style = _normalize_text(authorized_synopsis.get("tone_and_style"))
    chapter_brief = {
        "chapter_id": chapter_id,
        "title": chapter_title,
        "goal": _safe_excerpt(combined_synopsis, limit=360) or chapter_title,
        "chapter_role": "expansion from authorized synopsis",
        "plot_function": _normalize_text(story_outline.get("next_outline_node")) or chapter_title,
        "emotional_goal": tone_and_style,
        "conflict_goal": _safe_excerpt("; ".join(plot_beats[:2]), limit=240),
        "relationship_targets": [],
        "must_include": continuity_must_include,
        "coverage_plot_beats": coverage_plot_beats,
        "forbidden": _normalize_string_list(authorized_synopsis.get("must_avoid")),
        "structure_hint": {
            "theory": "authorized synopsis event chain",
            "beats": plot_beats,
            "coverage_plot_beats": coverage_plot_beats,
            "continuity_check_anchors": continuity_must_include,
            "document_synopses": document_synopses,
        },
        "ending_hook": plot_beats[-1] if plot_beats else "",
        "target_word_count": target_length,
        "combined_synopsis": combined_synopsis,
        "reference_document_synopses": document_synopses,
        "sources": [
            {
                "type": synopsis_source,
                "evidence_level": "authorized_synopsis",
                "note": "Execution input built by Writer from an authorized synopsis; no reference truth text is included.",
            }
        ],
    }
    execution_input["chapter_title"] = chapter_title
    execution_input["chapter_brief"] = chapter_brief
    execution_input["length_budget"] = build_external_length_budget(
        chapter_id=chapter_id,
        target_chars=target_length,
        reason="authorized_synopsis_length",
        note=(
            "覆盖 chapter_brief.combined_synopsis 与 coverage_plot_beats 中的核心事件；"
            "不得引入授权梗概未覆盖的大剧情或替代性主线。"
        ),
        source_chapter_target_chars=source_chars or target_length,
    )
    execution_input["fact_inputs"] = {
        "input_synopsis_source": synopsis_source,
        "story_outline": dict(story_outline),
        "reference_document_synopses": document_synopses,
        "recent_story_synopses": story_context.get("recent_story_synopses", []),
        "character_docs": story_context.get("character_docs", []),
        "history_usage_policy": (
            "story_outline.current_position、timeline 中 scope=past 的节点、recent_story_synopses "
            "都是已发生剧情的承接上下文；正文开头必须进入本次 authorized synopsis 的目标事件，"
            "不得复述、改写或重新生成历史章节正文。"
        ),
        "creative_kb_note": "Style and continuity references are inherited from the prepared Writer execution input; they cannot override authorized facts.",
    }
    execution_input["relation_state_gate"] = {
        "blocked": False,
        "targets": [],
        "source": f"{synopsis_source}_expansion",
        "note": (
            "Authorized-synopsis expansion replaces the prior planned chapter brief, so stale "
            "relationship gates from the discarded brief are not applicable."
        ),
    }
    execution_input["planned_character_constraints"] = _authorized_planned_character_constraints(
        authorized_synopsis=authorized_synopsis,
        story_context=story_context,
    )
    forbidden_inputs = _normalize_string_list(execution_input.get("forbidden_inputs"))
    execution_input["forbidden_inputs"] = [
        *forbidden_inputs,
        *_normalize_string_list(authorized_synopsis.get("must_avoid")),
        "不得使用未授权原文；只能根据授权梗概扩写。",
    ]
    writer_rules = _normalize_string_list(execution_input.get("writer_rules"))
    execution_input["writer_rules"] = [
        *writer_rules,
        "正文扩写事实源以 chapter_brief.combined_synopsis、coverage_plot_beats 与 reference_document_synopses 为准。",
        "若 fact_inputs、风格参考或 Creative KB 与 chapter_brief 冲突，必须优先遵守 chapter_brief。",
        "历史上下文只允许用于承接状态，不得把上一章/current_position/recent_story_synopses 当作本章正文重新输出。",
    ]
    return execution_input


def build_external_length_budget(
    *,
    chapter_id: str,
    target_chars: int,
    min_chars: int | None = None,
    max_chars: int | None = None,
    reason: str = "external_length_override",
    note: str = "",
    source_chapter_target_chars: int = 0,
) -> dict[str, Any]:
    """Build a normalized Writer length budget from an external caller's character target."""
    target, normalized_min, normalized_max = _normalized_length_bounds(
        target_chars=target_chars,
        min_chars=min_chars,
        max_chars=max_chars,
    )
    expansion_notes = [
        (
            f"外部长度预算：目标 {target} 个中文字符，允许区间 "
            f"{normalized_min}-{normalized_max}；不得为了凑字补前情、旁支或后续设定解释。"
        )
    ]
    if note:
        expansion_notes.append(_normalize_text(note))
    return {
        "chapter_id": _normalize_text(chapter_id),
        "target_chars": target,
        "min_chars": normalized_min,
        "max_chars": normalized_max,
        "is_focus_chapter": True,
        "focus_reason": _normalize_text(reason) or "external_length_override",
        "expansion_notes": expansion_notes,
        "source_chapter_target_word_count": int(source_chapter_target_chars or target),
        "length_source": "external",
    }


def apply_external_length_budget(
    execution_input: Mapping[str, Any],
    *,
    target_chars: int,
    min_chars: int | None = None,
    max_chars: int | None = None,
    reason: str = "external_length_override",
    note: str = "",
    source_chapter_target_chars: int = 0,
) -> dict[str, Any]:
    """Return a copy of a Writer execution input with an externally supplied length budget."""
    updated = deepcopy(dict(execution_input))
    chapter_brief = dict(updated.get("chapter_brief") or {})
    chapter_id = (
        _normalize_text(chapter_brief.get("chapter_id"))
        or _normalize_text(updated.get("chapter_id"))
        or "chapter"
    )
    budget = build_external_length_budget(
        chapter_id=chapter_id,
        target_chars=target_chars,
        min_chars=min_chars,
        max_chars=max_chars,
        reason=reason,
        note=note,
        source_chapter_target_chars=source_chapter_target_chars,
    )
    chapter_brief["target_word_count"] = budget["target_chars"]
    updated["chapter_brief"] = chapter_brief
    updated["length_budget"] = budget
    writer_rules = _normalize_string_list(updated.get("writer_rules"))
    writer_rules.append(
        (
            f"正文长度必须遵守外部长度预算：目标 {budget['target_chars']} 字，"
            f"允许区间 {budget['min_chars']}-{budget['max_chars']} 字；不要用前情回放或后续设定解释凑字。"
        )
    )
    updated["writer_rules"] = [item for item in dict.fromkeys(writer_rules) if item]
    return updated


def _positive_int(value: object, *, fallback: int = 0) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return parsed if parsed > 0 else int(fallback or 0)


def _normalized_length_bounds(
    *,
    target_chars: int,
    min_chars: int | None = None,
    max_chars: int | None = None,
) -> tuple[int, int, int]:
    target = int(target_chars or 0)
    if target <= 0:
        raise ValueError("target_chars must be a positive integer")
    normalized_min = int(min_chars or max(1, target * 85 // 100))
    normalized_max = int(max_chars or max(target, target * 115 // 100))
    if min(normalized_min, normalized_max) <= 0:
        raise ValueError("min_chars and max_chars must be positive integers")
    if not normalized_min <= target <= normalized_max:
        raise ValueError("min_chars must be <= target_chars <= max_chars")
    return target, normalized_min, normalized_max


def _continuity_requirements_from_plot_beats(plot_beats: list[str]) -> list[str]:
    requirements: list[str] = []
    for beat in plot_beats:
        cleaned = re.sub(r"^\s*(起点|触发|行动/冲突|转折/结果|后续铺垫|结果|铺垫)\s*[：:]\s*", "", beat).strip()
        first_sentence = re.split(r"(?<=[。！？!?])\s*", cleaned)[0] if cleaned else ""
        clauses = re.split(r"[；;，,]", first_sentence)
        for clause in clauses:
            anchor = _continuity_requirement_anchor(clause)
            if not anchor:
                continue
            requirements.append(anchor)
            break
    return [item for item in dict.fromkeys(requirements) if item]


def _continuity_requirement_anchor(clause: str) -> str:
    anchor = _normalize_text(clause)
    if not anchor:
        return ""
    anchor = re.sub(r"^(并|且|同时|随后|然后|但|而|从而|因此)", "", anchor).strip()
    if re.search(r"在.+中$", anchor) or re.search(r"(之前|之后|以后|过后|接通后|开始时|结束时)$", anchor):
        return ""
    subject_probe = re.sub(
        r"^(最终|正式|亲自|口头|突然|突如其来|这份|这场|这个|那个|一份|一种|一场)\s*",
        "",
        anchor,
    ).strip()
    if re.match(
        r"^(选择|接受|确认|完成|进入|抵达|发现|看到|遭遇|观察|离开|到达|收到|拿到|触发|开启|关闭|接走|出现|留下|转为|成为)",
        subject_probe,
    ):
        return ""
    normalized = re.sub(
        r"(最终|正式|亲自|口头|突然|突如其来|这份|这场|这个|那个|一份|一种|一场)",
        " ",
        anchor,
    )
    tokens = [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.·-]*|[\u4e00-\u9fff]{2,6}", normalized)
        if token not in {"然后", "随后", "同时", "开始", "继续", "进行", "完成"}
    ]
    if not tokens:
        return _safe_excerpt(anchor, limit=28) if len(anchor) >= 4 else ""
    return " ".join(tokens[:4])


def _authorized_planned_character_constraints(
    *,
    authorized_synopsis: Mapping[str, Any],
    story_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    prefix_character_docs = [
        item for item in story_context.get("character_docs", [])
        if isinstance(item, Mapping)
    ]
    reference_character_docs = [
        {"canonical_name": name}
        for name in _normalize_string_list(authorized_synopsis.get("characters_used"))
    ]
    reference_text = " ".join(
        _normalize_text(value)
        for value in (
            authorized_synopsis.get("combined_synopsis"),
            " ".join(_normalize_string_list(authorized_synopsis.get("plot_beats"))),
            " ".join(_normalize_string_list(authorized_synopsis.get("must_preserve"))),
        )
        if _normalize_text(value)
    )
    for source_name, source_items in (
        ("prefix_context", prefix_character_docs),
        ("authorized_synopsis", reference_character_docs),
    ):
        for item in source_items:
            name = _normalize_text(item.get("canonical_name") or item.get("name"))
            if not name:
                continue
            if source_name == "authorized_synopsis" and reference_text and name not in reference_text:
                continue
            constraints.append(
                {
                    "canonical_name": name,
                    "status": "authorized",
                    "narrative_role": "authorized synopsis or prefix context character",
                    "introduction_required_in_chapter": False,
                    "source": f"writer_{source_name}",
                }
            )
    deduped: dict[str, dict[str, Any]] = {}
    for item in constraints:
        name = _normalize_text(item.get("canonical_name") or item.get("name"))
        if name and name not in deduped:
            deduped[name] = item
    return list(deduped.values())


@dataclass(slots=True)
class StyleReferenceItem:
    fragment_id: str
    source_path: str
    narrative_function: list[str] = field(default_factory=list)
    relationship_state: list[str] = field(default_factory=list)
    style_profile_text: str = ""
    pov_mode: str = ""
    excerpt: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StyleReferenceBundle:
    scene_brief: dict[str, Any]
    selected_fragment_ids: list[str] = field(default_factory=list)
    references: list[StyleReferenceItem] = field(default_factory=list)
    selection_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_brief": dict(self.scene_brief),
            "selected_fragment_ids": list(self.selected_fragment_ids),
            "references": [item.to_dict() for item in self.references],
            "selection_notes": self.selection_notes,
        }


@dataclass(slots=True)
class PlannedCharacterConstraint:
    canonical_name: str
    status: str
    narrative_role: str = ""
    introduction_required_in_chapter: bool = False
    must_not_reveal_early: list[str] = field(default_factory=list)
    relationship_entry_points: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FrozenChapterExecutionInput:
    run_id: str
    book_id: str
    chapter_id: str
    document_title_index: int
    chapter_title: str
    chapter_brief: dict[str, Any]
    length_budget: dict[str, Any]
    fact_inputs: dict[str, Any]
    style_reference_bundle: dict[str, Any]
    forbidden_inputs: list[str] = field(default_factory=list)
    relation_state_gate: dict[str, Any] = field(default_factory=dict)
    planned_character_constraints: list[dict[str, Any]] = field(default_factory=list)
    writer_rules: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "book_id": self.book_id,
            "chapter_id": self.chapter_id,
            "document_title_index": self.document_title_index,
            "chapter_title": self.chapter_title,
            "chapter_brief": dict(self.chapter_brief),
            "length_budget": dict(self.length_budget),
            "fact_inputs": dict(self.fact_inputs),
            "style_reference_bundle": dict(self.style_reference_bundle),
            "forbidden_inputs": list(self.forbidden_inputs),
            "relation_state_gate": dict(self.relation_state_gate),
            "planned_character_constraints": [dict(item) for item in self.planned_character_constraints],
            "writer_rules": list(self.writer_rules),
            "sources": [dict(item) for item in self.sources],
        }


@dataclass(slots=True)
class MemoryWritebackRecord:
    chapter_id: str
    document_title_index: int
    doc_id: int
    chapter_db_id: int
    character_updates: list[dict[str, Any]] = field(default_factory=list)
    world_update: dict[str, Any] = field(default_factory=dict)
    outline_update: dict[str, Any] = field(default_factory=dict)
    activated_planned_characters: list[str] = field(default_factory=list)
    canon_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RollbackEvent:
    event_id: str
    target_freeze_stage: str
    reason: str
    invalidated_freeze_stages: list[str] = field(default_factory=list)
    trigger: str = ""
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WriterRollbackManager:
    def __init__(self, *, run_writer: RunWriter) -> None:
        self.run_writer = run_writer

    def rollback_to_stage(
        self,
        *,
        run_id: str,
        target_freeze_stage: str,
        reason: str,
        trigger: str = "manual",
    ) -> RollbackEvent:
        order = ["freeze_a", "freeze_b", "freeze_c", "freeze_d", "freeze_e"]
        if target_freeze_stage not in order:
            raise ValueError("unsupported rollback target")
        target_index = order.index(target_freeze_stage)
        to_invalidate = [
            stage
            for stage in order[target_index + 1 :]
            if self.run_writer.get_freeze_record(run_id, stage) is not None
        ]
        self.run_writer.invalidate_freezes(run_id, freeze_stages=to_invalidate, reason=reason)
        return self._record_rollback(
            run_id=run_id,
            target_freeze_stage=target_freeze_stage,
            invalidated_freeze_stages=to_invalidate,
            reason=reason,
            trigger=trigger,
        )

    def rollback_after_failure(self, *, run_id: str, failure_count: int, reason: str) -> RollbackEvent:
        if failure_count <= 1:
            return self.rollback_to_stage(
                run_id=run_id,
                target_freeze_stage="freeze_d",
                reason=reason,
                trigger="execution_failure",
            )
        if failure_count == 2:
            return self.rollback_to_stage(
                run_id=run_id,
                target_freeze_stage="freeze_c",
                reason=reason,
                trigger="execution_failure",
            )
        return self.rollback_to_stage(
            run_id=run_id,
            target_freeze_stage="freeze_b",
            reason=reason,
            trigger="execution_failure",
        )

    def cascade_for_character_cast_change(self, *, run_id: str, reason: str) -> RollbackEvent:
        return self.rollback_to_stage(
            run_id=run_id,
            target_freeze_stage="freeze_a",
            reason=reason,
            trigger="character_cast_change",
        )

    def _record_rollback(
        self,
        *,
        run_id: str,
        target_freeze_stage: str,
        invalidated_freeze_stages: list[str],
        reason: str,
        trigger: str,
    ) -> RollbackEvent:
        existing = self._load_events(run_id)
        event = RollbackEvent(
            event_id=f"rollback-{len(existing) + 1:02d}",
            target_freeze_stage=target_freeze_stage,
            invalidated_freeze_stages=invalidated_freeze_stages,
            reason=reason,
            trigger=trigger,
        )
        existing.append(event)
        self.run_writer.write_json(run_id, "rollback_events.json", {"events": [item.to_dict() for item in existing]})
        return event

    def _load_events(self, run_id: str) -> list[RollbackEvent]:
        path = self.run_writer.layout.run_dir(run_id) / "rollback_events.json"
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        events: list[RollbackEvent] = []
        if isinstance(payload, dict):
            for item in payload.get("events") or []:
                if isinstance(item, dict):
                    events.append(
                        RollbackEvent(
                            event_id=str(item.get("event_id") or ""),
                            target_freeze_stage=str(item.get("target_freeze_stage") or ""),
                            invalidated_freeze_stages=[str(x) for x in (item.get("invalidated_freeze_stages") or [])],
                            reason=str(item.get("reason") or ""),
                            trigger=str(item.get("trigger") or ""),
                            created_at=str(item.get("created_at") or _utc_now()),
                        )
                    )
        return events


class RestrictedWriterExecutor:
    def __init__(
        self,
        *,
        repo_root: Path,
        run_writer: RunWriter,
        model_client: Any | None = None,
        mention_service: CharacterMentionService | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.run_writer = run_writer
        self.model_client = model_client
        self.mention_service = mention_service or CharacterMentionService()
        self.assets_repo = AssetsRepo()
        self.documents_repo = DocumentsRepo()
        self.chapters_repo = ChaptersRepo()
        self.character_profiles_repo = CharacterProfilesRepo()
        self.character_profile_service = CharacterProfileService(profiles_repo=self.character_profiles_repo)
        self.world_state_service = WorldStateService(repo_root=repo_root)
        self.outline_service = OutlineService(repo_root=repo_root)
        self.fragment_cards_repo = FragmentCardsRepo()
        self.fragment_clusters_repo = FragmentClustersRepo()
        self.semantic_aliases_repo = SemanticAliasesRepo()
        self._runtime_requirement_aliases: dict[str, tuple[str, ...]] = {}
        self.coarse_retrieval_service = CoarseRetrievalService()
        self.rerank_service = RerankService()

    def prepare_execution_input(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        chapter_id: str,
        auto_confirm: bool = False,
    ) -> dict[str, Any]:
        self._require_frozen(run_id, "freeze_c")
        chapter_package = self._load_frozen_payload(run_id, "freeze_c", "chapter_package.json")
        batch_plan = self._load_optional_frozen_payload(run_id, "freeze_b", "batch_plan.json")
        book_plan = self._load_optional_frozen_payload(run_id, "freeze_a", "book_continuation_plan.json")
        world_pack = self._load_optional_frozen_payload(run_id, "freeze_a", "world_expansion_pack.json")
        cast_plan = self._load_optional_frozen_payload(run_id, "freeze_a", "character_cast_plan.json")
        planned_profiles = self._load_list_payload(run_id, "freeze_a", "planned_character_profiles.json")
        introduction_plan = self._load_optional_frozen_payload(run_id, "freeze_a", "character_introduction_plan.json")

        chapter_brief = self._find_chapter_brief(chapter_package, chapter_id=chapter_id)
        length_plan = self._load_optional_run_payload(run_id, "chapter_length_plan.json")
        length_budget = self._resolve_chapter_length_budget(
            chapter_id=chapter_id,
            chapter_brief=chapter_brief,
            length_plan=length_plan,
        )
        style_bundle = self._build_style_reference_bundle(conn, chapter_brief)
        planned_constraints = self._build_planned_character_constraints(
            chapter_id=chapter_id,
            planned_profiles=planned_profiles,
            introduction_plan=introduction_plan,
        )
        relation_gate = self._build_relation_state_gate(chapter_brief)
        title_index = self._resolve_document_title_index(conn, book_id=book_id, run_id=run_id, chapter_id=chapter_id)
        execution_input = FrozenChapterExecutionInput(
            run_id=run_id,
            book_id=book_id,
            chapter_id=chapter_id,
            document_title_index=title_index,
            chapter_title=str(chapter_brief.get("title") or chapter_id),
            chapter_brief=dict(chapter_brief),
            length_budget=length_budget,
            fact_inputs={
                "book_continuation_plan": dict(book_plan or {}),
                "world_expansion_pack": dict(world_pack or {}),
                "batch_plan": dict(batch_plan or {}),
                "chapter_package_id": str(chapter_package.get("package_id") or ""),
            },
            style_reference_bundle=style_bundle.to_dict(),
            forbidden_inputs=self._collect_forbidden_inputs(chapter_brief, batch_plan, world_pack),
            relation_state_gate=relation_gate,
            planned_character_constraints=[item.to_dict() for item in planned_constraints],
            writer_rules=[
                "只允许承接冻结的 ChapterBrief 与上游 Freeze 事实。",
                "事实输入优先于风格输入，风格只能影响表达不能覆盖事实。",
                "不得越过当前批次边界，不得跳过关系桥接。",
                "不得自由创建未被上游批准的关键新角色。",
                "不得补大型新设定，只能在冻结事实范围内展开。",
                *NARRATION_CONSISTENCY_RULES,
                (
                    f"正文长度必须遵循已确认 ChapterLengthBudget：目标 {length_budget['target_chars']} 字，"
                    f"允许区间 {length_budget['min_chars']}-{length_budget['max_chars']} 字。"
                ),
            ],
            sources=[
                {"type": "freeze_c", "path": "freezes/freeze_c/chapter_package.json"},
                {"type": "chapter_length_plan", "path": "chapter_length_plan.json"},
                {"type": "freeze_b", "path": "freezes/freeze_b/batch_plan.json"},
                {"type": "freeze_a", "path": "freezes/freeze_a/book_continuation_plan.json"},
            ],
        )
        self.run_writer.write_json(run_id, "chapter_brief.json", chapter_brief)
        self.run_writer.write_json(run_id, "chapter_length_budget.json", length_budget)
        self.run_writer.write_json(run_id, "style_reference_bundle.json", style_bundle)
        self.run_writer.write_json(run_id, "chapter_execution_input.json", execution_input)
        checkpoint = {
            "status": "ready_for_freeze_d",
            "chapter_id": chapter_id,
            "artifact_path": str(self.run_writer.layout.run_dir(run_id) / "chapter_execution_input.json"),
            "created_at": _utc_now(),
        }
        self.run_writer.write_json(run_id, "execution_checkpoint.json", checkpoint)
        if auto_confirm:
            self.confirm_freeze_d(run_id=run_id)
        return {
            "chapter_execution_input": execution_input.to_dict(),
            "style_reference_bundle": style_bundle.to_dict(),
            "execution_checkpoint": checkpoint,
            "cast_plan": cast_plan,
        }

    def confirm_freeze_d(self, *, run_id: str) -> dict[str, str]:
        self._require_file(run_id, "chapter_execution_input.json")
        artifact_payloads: dict[str, Any] = {
            "chapter_brief.json": self._load_run_json(run_id, "chapter_brief.json"),
            "chapter_length_budget.json": self._load_run_json(run_id, "chapter_length_budget.json"),
            "style_reference_bundle.json": self._load_run_json(run_id, "style_reference_bundle.json"),
            "chapter_execution_input.json": self._load_run_json(run_id, "chapter_execution_input.json"),
        }
        length_plan = self._load_optional_run_payload(run_id, "chapter_length_plan.json")
        if isinstance(length_plan, dict):
            artifact_payloads["chapter_length_plan.json"] = length_plan
        return self.run_writer.write_freeze_record(
            run_id,
            FreezeRecord(
                freeze_stage="freeze_d",
                summary="受限执行输入已冻结。",
                depends_on=["freeze_c"],
            ),
            artifact_payloads=artifact_payloads,
        )

    def execute_frozen_chapter(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        commit_writeback: bool = False,
        auto_freeze_e: bool = True,
    ) -> dict[str, Any]:
        self._require_frozen(run_id, "freeze_d")
        execution_input = self._load_frozen_payload(run_id, "freeze_d", "chapter_execution_input.json")
        draft_md = self._generate_draft(execution_input)
        base_report = self._check_continuity_extended(
            conn,
            book_id=book_id,
            execution_input=execution_input,
            draft_md=draft_md,
        )
        review_status, accepted_for_writeback, blocked_reason = self._resolve_writeback_gate(
            run_id=run_id,
            chapter_id=str(execution_input.get("chapter_id") or ""),
            canon_ready=base_report.canon_ready,
        )
        continuity_report = ContinuityReport(
            issues=base_report.issues,
            blocked=base_report.blocked,
            summary=base_report.summary,
            relation_state_gate=base_report.relation_state_gate,
            planned_character_gate=base_report.planned_character_gate,
            state_delta=base_report.state_delta,
            canon_ready=base_report.canon_ready,
            review_decision_status=review_status,
            accepted_for_writeback=accepted_for_writeback,
            writeback_blocked_reason=blocked_reason,
            review_scope=base_report.review_scope,
            evidence_sources=base_report.evidence_sources,
        )
        self.run_writer.write_text(run_id, "draft.md", draft_md)
        self.run_writer.write_json(run_id, "continuity_report.json", continuity_report)
        self.run_writer.write_json(run_id, "state_delta.json", continuity_report.state_delta)
        mentioned_profiles = self._write_mentioned_character_profiles(
            conn,
            run_id=run_id,
            book_id=book_id,
            execution_input=execution_input,
            state_delta=continuity_report.state_delta,
        )

        memory_writeback: dict[str, Any] = {}
        final_md = draft_md
        writeback_committed = False
        if continuity_report.accepted_for_writeback and commit_writeback:
            memory_writeback = self.apply_memory_writeback(
                conn,
                run_id=run_id,
                book_id=book_id,
                execution_input=execution_input,
                draft_md=draft_md,
                continuity_report=continuity_report,
            ).to_dict()
            self.run_writer.write_json(run_id, "memory_writeback.json", memory_writeback)
            writeback_committed = True
        self.run_writer.write_text(run_id, "final.md", final_md)

        if continuity_report.accepted_for_writeback and auto_freeze_e:
            artifact_payloads: dict[str, Any] = {
                "chapter_execution_input.json": execution_input,
                "continuity_report.json": continuity_report.to_dict(),
                "state_delta.json": continuity_report.state_delta,
            }
            if memory_writeback:
                artifact_payloads["memory_writeback.json"] = memory_writeback
            if mentioned_profiles:
                artifact_payloads["mentioned_character_profiles.json"] = mentioned_profiles
            self.run_writer.write_freeze_record(
                run_id,
                FreezeRecord(
                    freeze_stage="freeze_e",
                    summary="正文执行与校验通过，可作为 canon 消费。",
                    depends_on=["freeze_d"],
                ),
                artifact_payloads=artifact_payloads,
            )
        return {
            "draft_md": draft_md,
            "draft_path": str(self.run_writer.layout.run_dir(run_id) / "draft.md"),
            "continuity_report_path": str(self.run_writer.layout.run_dir(run_id) / "continuity_report.json"),
            "mentioned_character_profiles_path": str(
                self.run_writer.layout.run_dir(run_id) / "mentioned_character_profiles.json"
            ),
            "continuity_report": continuity_report.to_dict(),
            "memory_writeback": memory_writeback,
            "canon_ready": continuity_report.canon_ready,
            "accepted_for_writeback": continuity_report.accepted_for_writeback,
            "review_decision_status": continuity_report.review_decision_status,
            "writeback_committed": writeback_committed,
        }

    def build_draft_prompt(self, execution_input: Mapping[str, Any]) -> dict[str, str]:
        """Return the exact prompt used by the restricted draft generator."""
        return self._build_execution_prompt(execution_input)

    def generate_draft_from_execution_input(self, execution_input: Mapping[str, Any]) -> str:
        """Generate a draft from a prepared execution input without requiring freeze records."""
        return self._generate_draft(execution_input)

    def build_execution_input_from_authorized_synopsis(
        self,
        *,
        base_execution_data: Mapping[str, Any],
        authorized_synopsis: Mapping[str, Any],
        story_outline: Mapping[str, Any] | None = None,
        story_context: Mapping[str, Any] | None = None,
        target_chars: int | None = None,
        synopsis_source: str = "authorized_story_synopsis",
    ) -> dict[str, Any]:
        """Build a reusable execution input for expanding an authorized synopsis."""
        return build_authorized_synopsis_execution_input(
            base_execution_data=base_execution_data,
            authorized_synopsis=authorized_synopsis,
            story_outline=story_outline,
            story_context=story_context,
            target_chars=target_chars,
            synopsis_source=synopsis_source,
        )

    def apply_external_length_budget(
        self,
        execution_input: Mapping[str, Any],
        *,
        target_chars: int,
        min_chars: int | None = None,
        max_chars: int | None = None,
        reason: str = "external_length_override",
        note: str = "",
        source_chapter_target_chars: int = 0,
    ) -> dict[str, Any]:
        """Apply an externally supplied character budget to a prepared execution input."""
        return apply_external_length_budget(
            execution_input,
            target_chars=target_chars,
            min_chars=min_chars,
            max_chars=max_chars,
            reason=reason,
            note=note,
            source_chapter_target_chars=source_chapter_target_chars,
        )

    def apply_memory_writeback(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        execution_input: Mapping[str, Any],
        draft_md: str,
        continuity_report: ContinuityReport,
    ) -> MemoryWritebackRecord:
        if not continuity_report.canon_ready:
            raise ValueError("continuity report is not canon ready")
        if not continuity_report.accepted_for_writeback:
            raise ValueError("writeback requires accepted review decision")
        chapter_brief = dict(execution_input.get("chapter_brief") or {})
        chapter_title = str(execution_input.get("chapter_title") or chapter_brief.get("title") or "新章节")
        document_title_index = int(execution_input.get("document_title_index") or 1)
        assets = self.assets_repo.get(conn, book_id=book_id)
        source_root = str(assets["source_root"]) if assets is not None else str(self.repo_root)
        generated_path = (
            Path(source_root) / "generated" / f"chapter-{document_title_index:04d}.md"
        ).as_posix()
        doc_id = self.documents_repo.insert_document(
            conn,
            {
                "book_id": book_id,
                "path": generated_path,
                "scope": "generated",
                "title": chapter_title,
                "document_title": chapter_title,
                "document_title_index": document_title_index,
                "inferred_chapter_no": document_title_index,
                "content": draft_md,
                "content_chars": len(draft_md),
                "character_keywords": continuity_report.state_delta.get("mentioned_characters", []),
                "content_tags": ["writer_generated", "canon_ready"],
                "source_path": generated_path,
                "source_file_name": Path(generated_path).name,
                "source_start_offset": 0,
                "source_end_offset": len(draft_md),
                "ingestion_run_id": run_id,
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            },
        )
        state_delta_payload = dict(continuity_report.state_delta)
        chapter_db_id = self.chapters_repo.upsert(
            conn,
            {
                "book_id": book_id,
                "document_title_index": document_title_index,
                "chapter_title": chapter_title,
                "source_doc_start_id": doc_id,
                "source_doc_end_id": doc_id,
                "source_doc_count": 1,
                "source_total_chars": len(draft_md),
                "summary_intermediate": [],
                "summary_md": draft_md,
                "summary_short": _safe_excerpt(draft_md, limit=120),
                "summary_status": "provisional",
                "summary_evidence_window": f"{document_title_index}-{document_title_index}",
                "summary_target_range": f"{document_title_index}-{document_title_index}",
                "importance_score": 80,
                "importance_reason": str(chapter_brief.get("goal") or ""),
                "related_chapters": [],
                "mentioned_characters": state_delta_payload.get("mentioned_characters", []),
                "world_update": state_delta_payload.get("world_update", {}),
                "outline_update": state_delta_payload.get("outline_update", {}),
                "outline_status": "provisional",
                "outline_evidence_window": f"{document_title_index}-{document_title_index}",
                "outline_target_range": f"{document_title_index}-{document_title_index}",
                "close_read_run_id": run_id,
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            },
        )
        character_updates, activated_characters = self._build_character_updates(
            conn,
            book_id=book_id,
            execution_input=execution_input,
            state_delta=state_delta_payload,
        )
        self.character_profile_service.merge_updates(
            conn,
            book_id=book_id,
            chapter_index=document_title_index,
            doc_ids=[doc_id],
            updates=character_updates,
        )
        world_update = dict(state_delta_payload.get("world_update") or {})
        outline_update = dict(state_delta_payload.get("outline_update") or {})
        self.world_state_service.apply_update(book_id=book_id, world_update=world_update)
        self.outline_service.apply_update(
            book_id=book_id,
            chapter_line=str(outline_update.get("chapter_line") or ""),
            timeline_events=[item for item in (outline_update.get("timeline_events") or []) if isinstance(item, dict)],
            importance_score=80,
        )
        registry = self._load_planned_character_registry(run_id)
        for name in activated_characters:
            registry[name] = {
                "status": "canon_active",
                "activated_at": _utc_now(),
                "chapter_id": str(execution_input.get("chapter_id") or ""),
                "document_title_index": document_title_index,
            }
        self.run_writer.write_json(run_id, "planned_character_registry.json", registry)
        return MemoryWritebackRecord(
            chapter_id=str(execution_input.get("chapter_id") or ""),
            document_title_index=document_title_index,
            doc_id=doc_id,
            chapter_db_id=chapter_db_id,
            character_updates=character_updates,
            world_update=world_update,
            outline_update=outline_update,
            activated_planned_characters=activated_characters,
            canon_ready=True,
        )

    def _generate_draft(self, execution_input: Mapping[str, Any]) -> str:
        chapter_brief = dict(execution_input.get("chapter_brief") or {})
        style_bundle = dict(execution_input.get("style_reference_bundle") or {})
        length_budget = dict(execution_input.get("length_budget") or {})
        prompt = self._build_execution_prompt(execution_input)
        if self.model_client is None:
            return self._fallback_draft(
                chapter_brief=chapter_brief,
                style_bundle=style_bundle,
                length_budget=length_budget,
            )
        text = self.model_client.generate_text(
            system_prompt=prompt["system_prompt"],
            user_prompt=prompt["user_prompt"],
            fallback_text=self._fallback_draft(
                chapter_brief=chapter_brief,
                style_bundle=style_bundle,
                length_budget=length_budget,
            ),
        )
        return str(text).strip() + "\n"

    def _build_execution_prompt(self, execution_input: Mapping[str, Any]) -> dict[str, str]:
        chapter_brief = dict(execution_input.get("chapter_brief") or {})
        length_budget = dict(execution_input.get("length_budget") or {})
        reference_document_synopses = chapter_brief.get("reference_document_synopses")
        if not isinstance(reference_document_synopses, list):
            structure_hint = chapter_brief.get("structure_hint")
            reference_document_synopses = (
                structure_hint.get("document_synopses")
                if isinstance(structure_hint, dict) and isinstance(structure_hint.get("document_synopses"), list)
                else []
            )
        coverage_plot_beats = _normalize_string_list(chapter_brief.get("coverage_plot_beats"))
        if not coverage_plot_beats:
            structure_hint = chapter_brief.get("structure_hint")
            coverage_plot_beats = _normalize_string_list(
                structure_hint.get("coverage_plot_beats") if isinstance(structure_hint, dict) else []
            ) or _normalize_string_list(
                structure_hint.get("beats") if isinstance(structure_hint, dict) else []
            )
        expansion_guidance = {
            "target_chars": int(length_budget.get("target_chars") or self._chapter_target_chars(chapter_brief)),
            "min_chars": int(length_budget.get("min_chars") or 0),
            "max_chars": int(length_budget.get("max_chars") or 0),
            "combined_synopsis": chapter_brief.get("combined_synopsis"),
            "coverage_plot_beats": coverage_plot_beats,
            "reference_document_synopses": reference_document_synopses,
            "rule": (
                "必须覆盖 combined_synopsis 与 coverage_plot_beats 的核心事件。"
                "如果 reference_document_synopses 非空，必须按 order 顺序把这些连续 document 梗概合并成"
                "一个连贯长段/章节来扩写；目标是覆盖整组梗概，而不是只写第一条或摘要式带过。"
            ),
            "length_rule": (
                "正文必须接近 target_chars，并落在 min_chars/max_chars 区间内。"
                "如果核心事件已经写完但字数未达目标，只做场景内动作、对白和感官细节的适度展开；"
                "不得用前情回放、未授权旁支、后续设定讲解或下一章节事件凑字。"
            ),
            "history_rule": (
                "fact_inputs.story_outline.current_position、timeline scope=past、recent_story_synopses "
                "只用于理解上一章已经发生了什么。正文不得从这些历史文本的开头重新写起，"
                "不得复述上一章正文；第一段应直接进入 combined_synopsis/coverage_plot_beats 指定的当前目标事件。"
            ),
        }
        return {
            "system_prompt": (
                "你是受限正文执行器。你只能消费冻结的 ChapterBrief 与已冻结事实输入。"
                "事实优先于风格输入。不得自由创建关键新角色，不得新增大型设定，不得跳过关系桥接，"
                "不得越过当前批次边界。必须遵守原作叙事契约，不得擅自更换叙述者或视角机制。"
                "Creative KB、风格参考和结构知识只能辅助表达，不得替换 ChapterBrief 的剧情目标。"
                "若输入包含连续多个 document 梗概，必须按顺序合并为同一段连续正文并写到长度预算附近。"
                "历史上下文和上一章正文只用于承接，不得作为本章正文开头重写或复述。"
                "长度预算是硬约束：不要超过 max_chars，不要为了凑字补写前情回放、原创支线、旅程过场或设定讲解。"
                "chapter_brief.must_include 主要是连续性校验锚点，coverage_plot_beats 才是完整剧情覆盖目标。"
                "只输出正文，不要解释。"
            ),
            "user_prompt": json.dumps(
                {
                    "chapter_title": execution_input.get("chapter_title"),
                    "chapter_brief": chapter_brief,
                    "length_budget": length_budget,
                    "expansion_guidance": expansion_guidance,
                    "narration_consistency_rules": list(NARRATION_CONSISTENCY_RULES),
                    "fact_inputs": execution_input.get("fact_inputs"),
                    "style_reference_bundle": execution_input.get("style_reference_bundle"),
                    "planned_character_constraints": execution_input.get("planned_character_constraints"),
                    "forbidden_inputs": execution_input.get("forbidden_inputs"),
                    "writer_rules": execution_input.get("writer_rules"),
                },
                ensure_ascii=False,
                indent=2,
            ),
        }

    def _fallback_draft(
        self,
        *,
        chapter_brief: Mapping[str, Any],
        style_bundle: Mapping[str, Any],
        length_budget: Mapping[str, Any] | None = None,
    ) -> str:
        title = str(chapter_brief.get("title") or "新章")
        goal = str(chapter_brief.get("goal") or "")
        must_include = _normalize_string_list(chapter_brief.get("must_include"))
        ending_hook = str(chapter_brief.get("ending_hook") or "")
        target_chars = int((length_budget or {}).get("target_chars") or self._chapter_target_chars(chapter_brief))
        reference_excerpt = ""
        references = style_bundle.get("references")
        if isinstance(references, list) and references:
            first = references[0]
            if isinstance(first, dict):
                reference_excerpt = str(first.get("excerpt") or "")
        lines = [
            f"# {title}",
            "",
            f"这章围绕{goal}展开。",
            "人物在压力下没有越过既有关系边界，只能靠实际行动一点点交换信任。",
        ]
        for item in must_include[:3]:
            lines.append(f"场景里必须落到“{item}”，于是叙事会把它放进具体动作和对话里。")
        if reference_excerpt:
            lines.append(f"行文保持克制，参考片段的气口接近：{_safe_excerpt(reference_excerpt, limit=40)}")
        if ending_hook:
            lines.append(f"章末留下新的牵引：{ending_hook}")
        while len("\n".join(lines)) < min(target_chars, 1200):
            lines.append("叙事继续补足行动、观察和对白之间的因果，让长度预算服务于已确认的章节目标。")
        return "\n".join(lines).strip() + "\n"

    def _check_continuity_extended(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        execution_input: Mapping[str, Any],
        draft_md: str,
    ) -> ContinuityReport:
        chapter_brief = dict(execution_input.get("chapter_brief") or {})
        issues: list[ContinuityIssue] = []
        draft_text = str(draft_md or "")
        self._runtime_requirement_aliases = self._load_requirement_aliases(conn, book_id=book_id)
        for term in _normalize_string_list(chapter_brief.get("must_include")):
            if term and not self._requirement_covered(draft_text=draft_text, requirement=term):
                issues.append(
                    ContinuityIssue(
                        type="missing_must_include",
                        severity="high",
                        message=f"必写点未出现：{term}",
                        suggested_fix=f"补写“{term}”的具体动作、对白或结果。",
                    )
                )
        for term in _normalize_string_list(chapter_brief.get("forbidden")):
            if term and term in draft_text:
                issues.append(
                    ContinuityIssue(
                        type="forbidden_present",
                        severity="high",
                        message=f"出现禁写点：{term}",
                        suggested_fix=f"删除或改写与“{term}”有关的句子。",
                    )
                )
        relation_gate = self._evaluate_relation_state_gate(
            draft_text=draft_text,
            relation_state_gate=dict(execution_input.get("relation_state_gate") or {}),
        )
        if relation_gate["blocked"]:
            issues.extend(relation_gate["issues"])
        planned_gate = self._evaluate_planned_character_gate(
            conn,
            book_id=book_id,
            draft_text=draft_text,
            planned_character_constraints=[
                dict(item) for item in (execution_input.get("planned_character_constraints") or []) if isinstance(item, dict)
            ],
        )
        if planned_gate["blocked"]:
            issues.extend(planned_gate["issues"])
        issues.extend(
            self._evaluate_external_length_budget(
                draft_text=draft_text,
                length_budget=dict(execution_input.get("length_budget") or {}),
            )
        )
        issues.extend(
            self._evaluate_history_replay(
                draft_text=draft_text,
                execution_input=execution_input,
            )
        )
        blocked = any(issue.severity == "high" for issue in issues)
        state_delta = self._extract_state_delta(
            execution_input=execution_input,
            draft_text=draft_text,
            blocked=blocked,
        )
        return ContinuityReport(
            issues=issues,
            blocked=blocked,
            summary="continuity_blocked" if blocked else "continuity_ok",
            relation_state_gate=relation_gate["gate"],
            planned_character_gate=planned_gate["gate"],
            state_delta=state_delta,
            canon_ready=not blocked,
            review_scope="chapter_execution",
            evidence_sources=[dict(item) for item in (execution_input.get("sources") or []) if isinstance(item, dict)],
        )

    def _evaluate_external_length_budget(
        self,
        *,
        draft_text: str,
        length_budget: Mapping[str, Any],
    ) -> list[ContinuityIssue]:
        if str(length_budget.get("length_source") or "").strip() != "external":
            return []
        target_chars = _positive_int(length_budget.get("target_chars"))
        min_chars = _positive_int(length_budget.get("min_chars"))
        max_chars = _positive_int(length_budget.get("max_chars"))
        if not target_chars or not min_chars or not max_chars:
            return []
        actual_chars = len(str(draft_text or "").strip())
        if min_chars <= actual_chars <= max_chars:
            return []
        if actual_chars < min_chars:
            message = (
                f"正文长度低于外部长度预算：实际 {actual_chars} 字，"
                f"要求 {min_chars}-{max_chars} 字（目标 {target_chars} 字）。"
            )
            fix = "补足当前授权梗概内的动作、对白和场景细节，不得改写前情或提前推进后续事件。"
        else:
            message = (
                f"正文长度超过外部长度预算：实际 {actual_chars} 字，"
                f"要求 {min_chars}-{max_chars} 字（目标 {target_chars} 字）。"
            )
            fix = "压缩前情回放、设定解释、旅程过场和未授权支线，只保留当前授权梗概的核心事件。"
        return [
            ContinuityIssue(
                type="external_length_budget_violation",
                severity="high",
                message=message,
                suggested_fix=fix,
            )
        ]

    def _evaluate_history_replay(
        self,
        *,
        draft_text: str,
        execution_input: Mapping[str, Any],
    ) -> list[ContinuityIssue]:
        chapter_brief = dict(execution_input.get("chapter_brief") or {})
        length_budget = dict(execution_input.get("length_budget") or {})
        if (
            str(length_budget.get("length_source") or "").strip() != "external"
            and str(chapter_brief.get("chapter_role") or "").strip() != "expansion from authorized synopsis"
        ):
            return []
        fact_inputs = dict(execution_input.get("fact_inputs") or {})
        story_outline = dict(fact_inputs.get("story_outline") or {})
        snippets: list[str] = [_normalize_text(story_outline.get("current_position"))]
        for item in story_outline.get("timeline") or []:
            if isinstance(item, Mapping) and str(item.get("scope") or "") == "past":
                snippets.append(_normalize_text(item.get("summary")))
        for item in fact_inputs.get("recent_story_synopses") or []:
            if isinstance(item, Mapping):
                snippets.append(_normalize_text(item.get("summary_short")))
                snippets.append(_normalize_text(item.get("summary_md")))

        draft_prefix = self._compact_for_replay_check(draft_text)[:360]
        for snippet in snippets:
            anchor = self._history_replay_anchor(snippet)
            if not anchor:
                continue
            if anchor in draft_prefix:
                return [
                    ContinuityIssue(
                        type="history_replay",
                        severity="high",
                        message="正文开头复述了历史上下文，而不是直接进入当前授权梗概。",
                        quote=anchor,
                        suggested_fix=(
                            "删除上一章/current_position/recent_story_synopses 的复述，"
                            "从当前 coverage_plot_beats 的第一个目标事件开始写。"
                        ),
                    )
                ]
        return []

    def _history_replay_anchor(self, text: str) -> str:
        compact = self._compact_for_replay_check(text)
        if len(compact) < 24:
            return ""
        return compact[: min(96, len(compact))]

    def _compact_for_replay_check(self, text: str) -> str:
        return re.sub(r"\s+", "", str(text or ""))

    def _extract_state_delta(
        self,
        *,
        execution_input: Mapping[str, Any],
        draft_text: str,
        blocked: bool,
    ) -> dict[str, Any]:
        chapter_brief = dict(execution_input.get("chapter_brief") or {})
        chapter_id = str(execution_input.get("chapter_id") or "")
        planned_names = [
            str(item.get("canonical_name") or "")
            for item in execution_input.get("planned_character_constraints", [])
            if isinstance(item, dict) and str(item.get("canonical_name") or "")
        ]
        mentioned_characters = self.mention_service.clean_names(
            [
                *_normalize_string_list(chapter_brief.get("must_include")),
                *planned_names,
            ]
        )
        relationship_changes: list[StateChange] = []
        for item in chapter_brief.get("relationship_targets") or []:
            if not isinstance(item, dict):
                continue
            current_state = str(item.get("current_state") or "")
            target_state = str(item.get("target_state") or "")
            if current_state and target_state and current_state != target_state:
                relationship_changes.append(
                    StateChange(
                        subject=str(item.get("relation_type") or "关系线"),
                        from_state=current_state,
                        to_state=target_state,
                        reason=str(chapter_brief.get("goal") or ""),
                    )
                )
        character_changes: list[StateChange] = []
        timeline_label = str(execution_input.get("chapter_title") or chapter_brief.get("title") or chapter_id)
        state_delta = StateDelta(
            chapter_id=chapter_id,
            character_state_changes=character_changes,
            relationship_state_changes=relationship_changes,
            timeline_events=[f"{timeline_label}：{_safe_excerpt(str(chapter_brief.get('goal') or ''), limit=80)}"],
            world_state_changes=[],
            outline_progress=[str(chapter_brief.get("goal") or "")],
            canon_ready=not blocked,
            sources=[],
        )
        return {
            **state_delta.to_dict(),
            "mentioned_characters": mentioned_characters,
            "world_update": {
                "should_update": False,
                "changes": [],
            },
            "outline_update": {
                "chapter_line": f"[{execution_input.get('document_title_index')}] {timeline_label}: {_safe_excerpt(str(chapter_brief.get('goal') or ''), limit=72)}",
                "timeline_events": [
                    {
                        "label": timeline_label,
                        "participants": mentioned_characters[:4],
                        "summary": _safe_excerpt(str(chapter_brief.get("goal") or ""), limit=80),
                    }
                ],
            },
        }

    def _write_mentioned_character_profiles(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        execution_input: Mapping[str, Any],
        state_delta: Mapping[str, Any],
    ) -> dict[str, Any]:
        mentioned_names = _normalize_string_list(state_delta.get("mentioned_characters"))
        mentioned_set = set(mentioned_names)
        matched_profiles = [
            profile
            for profile in self._original_character_profile_payloads(conn, book_id=book_id)
            if self._profile_matches_mentions(profile, mentioned_set)
        ]
        matched_names = {str(profile.get("canonical_name") or "") for profile in matched_profiles}
        payload = {
            "book_id": book_id,
            "chapter_id": str(execution_input.get("chapter_id") or ""),
            "source": "sqlite:character_profiles",
            "mentioned_characters": mentioned_names,
            "matched_profiles": matched_profiles,
            "missing_profile_names": [name for name in mentioned_names if name not in matched_names],
        }
        self.run_writer.write_json(run_id, "mentioned_character_profiles.json", payload)
        self.run_writer.write_text(
            run_id,
            "mentioned_character_profiles.md",
            self._format_mentioned_character_profiles_markdown(payload),
        )
        return payload

    def _original_character_profile_payloads(self, conn: sqlite3.Connection, *, book_id: str) -> list[dict[str, Any]]:
        rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        return [self._character_profile_row_to_dict(row) for row in rows]

    def _character_profile_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        json_fields = {
            "aliases_json": "aliases",
            "personality_json": "personality",
            "occupations_json": "occupations",
            "age_timeline_json": "age_timeline",
            "abilities_json": "abilities",
            "recent_activity_json": "recent_activity",
            "relationships_json": "relationships",
            "story_events_json": "story_events",
            "chapter_indexes_json": "chapter_indexes",
        }
        payload: dict[str, Any] = {}
        for key in row.keys():
            if key in json_fields:
                payload[json_fields[key]] = self._parse_profile_json_field(row[key])
            else:
                payload[key] = row[key]
        return payload

    def _parse_profile_json_field(self, value: object) -> Any:
        if not isinstance(value, str) or not value.strip():
            return []
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _profile_matches_mentions(self, profile: Mapping[str, Any], mentioned_names: set[str]) -> bool:
        canonical_name = str(profile.get("canonical_name") or "")
        aliases = _normalize_string_list(profile.get("aliases"))
        return canonical_name in mentioned_names or any(alias in mentioned_names for alias in aliases)

    def _format_mentioned_character_profiles_markdown(self, payload: Mapping[str, Any]) -> str:
        lines = [
            "# Mentioned Character Profiles",
            "",
            f"book_id: {payload.get('book_id', '')}",
            f"chapter_id: {payload.get('chapter_id', '')}",
            "source: sqlite:character_profiles",
            "",
        ]
        profiles = [dict(item) for item in (payload.get("matched_profiles") or []) if isinstance(item, Mapping)]
        if not profiles:
            lines.append("未匹配到原文人物档案。")
            return "\n".join(lines).rstrip() + "\n"
        for profile in profiles:
            lines.extend(
                [
                    f"## {profile.get('canonical_name', '')}",
                    "",
                    str(profile.get("profile_summary_md") or "").strip(),
                    "",
                    f"- aliases: {', '.join(_normalize_string_list(profile.get('aliases'))) or '[]'}",
                    f"- occupations: {json.dumps(profile.get('occupations') or [], ensure_ascii=False)}",
                    f"- relationships: {json.dumps(profile.get('relationships') or [], ensure_ascii=False)}",
                    f"- recent_activity: {json.dumps(profile.get('recent_activity') or [], ensure_ascii=False)}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def _build_character_updates(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        execution_input: Mapping[str, Any],
        state_delta: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        mentioned_characters = _normalize_string_list(state_delta.get("mentioned_characters"))
        known_names = {
            str(row["canonical_name"])
            for row in self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        }
        planned_constraints = [
            dict(item)
            for item in (execution_input.get("planned_character_constraints") or [])
            if isinstance(item, dict)
        ]
        planned_by_name = {str(item.get("canonical_name") or ""): item for item in planned_constraints}
        updates: list[dict[str, Any]] = []
        activated: list[str] = []
        for name in mentioned_characters:
            planned = planned_by_name.get(name)
            if planned is not None:
                updates.append(
                    {
                        "canonical_name": name,
                        "aliases": [],
                        "personality": [str(x) for x in planned.get("core_personality", [])] if isinstance(planned.get("core_personality"), list) else [],
                        "occupations": [str(planned.get("narrative_role") or "")] if planned.get("narrative_role") else [],
                        "recent_activity": str(execution_input.get("chapter_title") or ""),
                        "relationships": [
                            {
                                "target_character": str(item.get("target_character") or ""),
                                "relation_type": "planned_entry",
                                "status": str(item.get("initial_state") or ""),
                            }
                            for item in (planned.get("relationship_entry_points") or [])
                            if isinstance(item, dict)
                        ],
                    }
                )
                if name not in known_names:
                    activated.append(name)
                continue
            if name in known_names:
                updates.append(
                    {
                        "canonical_name": name,
                        "aliases": [],
                        "personality": [],
                        "occupations": [],
                        "recent_activity": str(execution_input.get("chapter_title") or ""),
                        "relationships": [],
                    }
                )
        return updates, activated

    def _build_style_reference_bundle(self, conn: sqlite3.Connection, chapter_brief: Mapping[str, Any]) -> StyleReferenceBundle:
        scene_brief = SceneBrief(
            scene_objective=str(chapter_brief.get("goal") or ""),
            emotional_goal=str(chapter_brief.get("emotional_goal") or ""),
            conflict_goal=str(chapter_brief.get("conflict_goal") or ""),
            narrative_function=_normalize_string_list(
                [chapter_brief.get("plot_function") or chapter_brief.get("chapter_role") or "承接推进"]
            ),
            emotion_mode=_normalize_string_list(
                [chapter_brief.get("emotional_goal") or "克制表达"]
            ),
            character_temperament=[],
            relationship_state=[
                str(item.get("current_state") or "")
                for item in (chapter_brief.get("relationship_targets") or [])
                if isinstance(item, dict)
            ],
            style_need=_normalize_string_list(
                (chapter_brief.get("structure_hint") or {}).get("beats") if isinstance(chapter_brief.get("structure_hint"), dict) else []
            ),
            must_avoid=_normalize_string_list(chapter_brief.get("forbidden")) or ["避免设定冲突"],
            preferred_tags=_normalize_string_list(chapter_brief.get("must_include")),
        )
        query_terms = [
            scene_brief.scene_objective,
            scene_brief.emotional_goal,
            scene_brief.conflict_goal,
            *scene_brief.narrative_function,
            *scene_brief.preferred_tags,
        ]
        query_text = " ".join(item for item in query_terms if item).strip()
        fts_hits = self.fragment_cards_repo.search_fts(conn, query_text=query_text, limit=12)
        fragment_ids = [item.fragment_id for item in fts_hits]
        cards = self.fragment_cards_repo.list_by_fragment_ids(conn, fragment_ids=fragment_ids)
        if not cards:
            cards = self.fragment_cards_repo.list_representatives(conn)[:8]
        cluster_ids = [card.cluster_id for card in cards if card.cluster_id]
        clusters = self.fragment_clusters_repo.list_by_cluster_ids(conn, cluster_ids=list(dict.fromkeys(cluster_ids)))
        coarse = self.coarse_retrieval_service.retrieve(
            scene_brief=scene_brief,
            fragment_cards=cards,
            fragment_clusters=clusters,
            fts_fragment_ids=fragment_ids,
        )
        coarse_cards = self.fragment_cards_repo.list_by_fragment_ids(conn, fragment_ids=coarse.candidate_fragment_ids)
        rerank = self.rerank_service.rerank(
            scene_brief=scene_brief,
            candidates=coarse_cards,
            anchor_context=str(chapter_brief.get("goal") or ""),
            recent_window_summary=str(chapter_brief.get("conflict_goal") or ""),
        )
        selected_map = {item.fragment_id: item for item in coarse_cards}
        score_map = {item.candidate_id: item.final_score for item in rerank.scores}
        references = [
            StyleReferenceItem(
                fragment_id=fragment_id,
                source_path=selected_map[fragment_id].source_path,
                narrative_function=list(selected_map[fragment_id].narrative_function),
                relationship_state=list(selected_map[fragment_id].relationship_state),
                style_profile_text=selected_map[fragment_id].style_profile_text,
                pov_mode=selected_map[fragment_id].pov_mode,
                excerpt=selected_map[fragment_id].source_excerpt,
                score=float(score_map.get(fragment_id, 0.0)),
            )
            for fragment_id in rerank.selected_fragment_ids
            if fragment_id in selected_map
        ]
        return StyleReferenceBundle(
            scene_brief=scene_brief.to_dict(),
            selected_fragment_ids=list(rerank.selected_fragment_ids),
            references=references,
            selection_notes=rerank.selection_notes,
        )

    def _build_planned_character_constraints(
        self,
        *,
        chapter_id: str,
        planned_profiles: list[dict[str, Any]],
        introduction_plan: dict[str, Any] | None,
    ) -> list[PlannedCharacterConstraint]:
        intro_by_name: dict[str, dict[str, Any]] = {}
        if isinstance(introduction_plan, dict):
            for item in introduction_plan.get("introduction_items") or []:
                if not isinstance(item, dict):
                    continue
                intro_by_name[str(item.get("planned_character_id") or "")] = item
        constraints: list[PlannedCharacterConstraint] = []
        for item in planned_profiles:
            if not isinstance(item, dict):
                continue
            planned_character_id = str(item.get("planned_character_id") or "")
            intro_item = intro_by_name.get(planned_character_id, {})
            constraints.append(
                PlannedCharacterConstraint(
                    canonical_name=str(item.get("canonical_name") or ""),
                    status=str(item.get("status") or "planned"),
                    narrative_role=str(item.get("narrative_role") or ""),
                    introduction_required_in_chapter=str(intro_item.get("chapter_id") or "") == chapter_id,
                    must_not_reveal_early=[str(x) for x in (item.get("must_not_reveal_early") or [])],
                    relationship_entry_points=[
                        dict(entry)
                        for entry in (item.get("relationship_entry_points") or [])
                        if isinstance(entry, dict)
                    ],
                )
            )
        return constraints

    def _build_relation_state_gate(self, chapter_brief: Mapping[str, Any]) -> dict[str, Any]:
        targets: list[dict[str, Any]] = []
        blocked = False
        for item in chapter_brief.get("relationship_targets") or []:
            if not isinstance(item, dict):
                continue
            required_bridge = _normalize_string_list(item.get("required_bridge"))
            current_state = str(item.get("current_state") or "")
            target_state = str(item.get("target_state") or "")
            allowed = bool(item.get("allowed", True))
            if not allowed or (current_state != target_state and not required_bridge):
                blocked = True
            targets.append(
                {
                    "relation_type": str(item.get("relation_type") or ""),
                    "current_state": current_state,
                    "target_state": target_state,
                    "allowed": allowed,
                    "required_bridge": required_bridge,
                }
            )
        return {"blocked": blocked, "targets": targets}

    def _evaluate_relation_state_gate(self, *, draft_text: str, relation_state_gate: dict[str, Any]) -> dict[str, Any]:
        issues: list[ContinuityIssue] = []
        blocked = False
        for item in relation_state_gate.get("targets") or []:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("allowed", True)):
                blocked = True
                issues.append(
                    ContinuityIssue(
                        type="illegal_relationship_target",
                        severity="high",
                        message=f"关系目标不允许推进：{item.get('relation_type', '')}",
                        suggested_fix="先回到规划层补桥接事件或下调目标状态。",
                    )
                )
                continue
            current_state = str(item.get("current_state") or "")
            target_state = str(item.get("target_state") or "")
            required_bridge = _normalize_string_list(item.get("required_bridge"))
            if current_state != target_state and required_bridge:
                if not any(self._requirement_covered(draft_text=draft_text, requirement=term) for term in required_bridge):
                    blocked = True
                    issues.append(
                        ContinuityIssue(
                            type="missing_relationship_bridge",
                            severity="high",
                            message=f"关系推进缺少桥接事件：{', '.join(required_bridge)}",
                            suggested_fix="在正文里补足共同危机、公开站队等明确桥接动作。",
                        )
                    )
        return {"blocked": blocked, "issues": issues, "gate": relation_state_gate}

    def _evaluate_planned_character_gate(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        draft_text: str,
        planned_character_constraints: list[dict[str, Any]],
    ) -> dict[str, Any]:
        _ = draft_text
        issues: list[ContinuityIssue] = []
        known_names = {
            str(row["canonical_name"])
            for row in self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        }
        planned_names = {
            str(item.get("canonical_name") or "")
            for item in planned_character_constraints
            if str(item.get("canonical_name") or "")
        }
        mentioned: list[str] = []
        unknown_mentions: list[str] = []
        blocked = bool(unknown_mentions)
        if unknown_mentions:
            issues.append(
                ContinuityIssue(
                    type="unapproved_key_character",
                    severity="medium",
                    message=f"正文出现未被上游批准的关键新角色：{', '.join(unknown_mentions)}",
                    suggested_fix="删除该角色，或先在人物补充链路中加入 CharacterCastPlan。",
                )
            )
        return {
            "blocked": blocked,
            "issues": issues,
            "gate": {
                "mentioned_characters": mentioned,
                "allowed_existing_characters": sorted(known_names),
                "allowed_planned_characters": sorted(planned_names),
                "unknown_mentions": unknown_mentions,
            },
        }

    def _requirement_covered(self, *, draft_text: str, requirement: str) -> bool:
        if not requirement:
            return True
        if requirement in draft_text:
            return True
        keywords = self._requirement_keywords(requirement)
        if not keywords:
            return False
        hits = [keyword for keyword in keywords if self._requirement_keyword_present(draft_text, keyword)]
        if len(keywords) <= 2:
            return bool(hits)
        return len(hits) >= 2

    def _requirement_keyword_present(self, draft_text: str, keyword: str) -> bool:
        if keyword in draft_text:
            return True
        aliases = self._runtime_requirement_aliases.get(keyword, ())
        return any(alias and alias in draft_text for alias in aliases)

    def _load_requirement_aliases(self, conn: sqlite3.Connection, *, book_id: str) -> dict[str, tuple[str, ...]]:
        try:
            aliases = self.semantic_aliases_repo.list_by_book(
                conn,
                book_id=book_id,
                category="requirement_coverage",
            )
        except sqlite3.OperationalError:
            return {}
        return {
            alias.canonical_key: tuple(alias.aliases)
            for alias in aliases
            if alias.canonical_key and alias.aliases
        }

    def _requirement_keywords(self, requirement: str) -> list[str]:
        keywords: list[str] = []
        for canonical_key in sorted(self._runtime_requirement_aliases, key=len, reverse=True):
            if canonical_key in requirement and canonical_key not in keywords:
                keywords.append(canonical_key)
        normalized = re.sub(r"[，。！？；：、“”《》（）()\[\]{}]", " ", requirement)
        normalized = re.sub(r"[和与及或并且通过符合的地得在把被将为对向里中上下一起]+", " ", normalized)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_·-]*|[\u4e00-\u9fff]{2,6}", normalized):
            if token not in keywords:
                keywords.append(token)
        return keywords[:8]

    def _find_chapter_brief(self, chapter_package: Mapping[str, Any], *, chapter_id: str) -> dict[str, Any]:
        for item in chapter_package.get("chapters") or []:
            if isinstance(item, dict) and str(item.get("chapter_id") or "") == chapter_id:
                return dict(item)
        raise ValueError(f"chapter_id not found in frozen package: {chapter_id}")

    def _resolve_chapter_length_budget(
        self,
        *,
        chapter_id: str,
        chapter_brief: Mapping[str, Any],
        length_plan: Any | None,
    ) -> dict[str, Any]:
        if isinstance(length_plan, Mapping):
            for item in length_plan.get("budgets") or []:
                if isinstance(item, Mapping) and str(item.get("chapter_id") or "") == chapter_id:
                    return self._normalize_length_budget(item, chapter_brief=chapter_brief)
        return self._fallback_length_budget(chapter_id=chapter_id, chapter_brief=chapter_brief)

    def _normalize_length_budget(
        self,
        budget: Mapping[str, Any],
        *,
        chapter_brief: Mapping[str, Any],
    ) -> dict[str, Any]:
        target = int(budget.get("target_chars") or self._chapter_target_chars(chapter_brief))
        min_chars = int(budget.get("min_chars") or int(target * 0.85))
        max_chars = int(budget.get("max_chars") or int(target * 1.2))
        if min(target, min_chars, max_chars) <= 0:
            raise ValueError("chapter length budget values must be positive")
        if not min_chars <= target <= max_chars:
            raise ValueError("chapter length budget must satisfy min <= target <= max")
        return {
            "chapter_id": str(budget.get("chapter_id") or chapter_brief.get("chapter_id") or ""),
            "target_chars": target,
            "min_chars": min_chars,
            "max_chars": max_chars,
            "is_focus_chapter": bool(budget.get("is_focus_chapter", False)),
            "focus_reason": str(budget.get("focus_reason") or ""),
            "expansion_notes": _normalize_string_list(budget.get("expansion_notes")),
            "source_chapter_target_word_count": int(
                budget.get("source_chapter_target_word_count") or chapter_brief.get("target_word_count") or 0
            ),
        }

    def _fallback_length_budget(self, *, chapter_id: str, chapter_brief: Mapping[str, Any]) -> dict[str, Any]:
        target = self._chapter_target_chars(chapter_brief)
        return {
            "chapter_id": chapter_id,
            "target_chars": target,
            "min_chars": max(1, int(target * 0.85)),
            "max_chars": max(target, int(target * 1.2)),
            "is_focus_chapter": False,
            "focus_reason": "",
            "expansion_notes": ["未找到 chapter_length_plan.json 时，从 ChapterBrief.target_word_count 兼容生成。"],
            "source_chapter_target_word_count": int(chapter_brief.get("target_word_count") or 0),
        }

    def _chapter_target_chars(self, chapter_brief: Mapping[str, Any]) -> int:
        return max(1, int(chapter_brief.get("target_word_count") or 1200) * 2)

    def _collect_forbidden_inputs(
        self,
        chapter_brief: Mapping[str, Any],
        batch_plan: Mapping[str, Any] | None,
        world_pack: Mapping[str, Any] | None,
    ) -> list[str]:
        forbidden = _normalize_string_list(chapter_brief.get("forbidden"))
        if isinstance(batch_plan, Mapping):
            forbidden.extend(_normalize_string_list(batch_plan.get("must_not_consume")))
        if isinstance(world_pack, Mapping):
            forbidden.extend(_normalize_string_list(world_pack.get("open_items")))
        deduped: list[str] = []
        seen: set[str] = set()
        for item in forbidden:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _resolve_document_title_index(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        run_id: str,
        chapter_id: str,
    ) -> int:
        existing_path = self.run_writer.layout.run_dir(run_id) / "chapter_execution_input.json"
        if existing_path.exists():
            try:
                existing = self._load_run_json(run_id, "chapter_execution_input.json")
                if str(existing.get("chapter_id") or "") == chapter_id:
                    return int(existing.get("document_title_index") or 1)
            except Exception:
                pass
        title_indexes = self.documents_repo.list_title_indexes(conn, book_id=book_id)
        return (max(title_indexes) + 1) if title_indexes else 1

    def _load_planned_character_registry(self, run_id: str) -> dict[str, Any]:
        path = self.run_writer.layout.run_dir(run_id) / "planned_character_registry.json"
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else {}

    def _resolve_writeback_gate(
        self,
        *,
        run_id: str,
        chapter_id: str,
        canon_ready: bool,
    ) -> tuple[str, bool, str]:
        decision = self._load_optional_run_payload(run_id, "generation_review_decision.json")
        status = ""
        if isinstance(decision, dict):
            status = str(decision.get("status") or "").strip().lower()
            decision_chapter_id = str(decision.get("chapter_id") or "").strip()
            if decision_chapter_id and chapter_id and decision_chapter_id != chapter_id:
                return status, False, "review_decision_chapter_mismatch"
        if not canon_ready:
            return status, False, "continuity_blocked"
        if status != "accepted":
            return status, False, "review_not_accepted"
        return status, True, ""

    def refresh_writeback_gate(
        self,
        *,
        run_id: str,
        chapter_id: str,
        continuity_report: ContinuityReport,
    ) -> ContinuityReport:
        review_status, accepted_for_writeback, blocked_reason = self._resolve_writeback_gate(
            run_id=run_id,
            chapter_id=chapter_id,
            canon_ready=continuity_report.canon_ready,
        )
        return ContinuityReport(
            issues=list(continuity_report.issues),
            blocked=continuity_report.blocked,
            summary=continuity_report.summary,
            relation_state_gate=dict(continuity_report.relation_state_gate),
            planned_character_gate=dict(continuity_report.planned_character_gate),
            state_delta=dict(continuity_report.state_delta),
            canon_ready=continuity_report.canon_ready,
            review_decision_status=review_status,
            accepted_for_writeback=accepted_for_writeback,
            writeback_blocked_reason=blocked_reason,
            review_scope=continuity_report.review_scope,
            evidence_sources=[dict(item) for item in continuity_report.evidence_sources],
        )

    def _load_run_json(self, run_id: str, name: str) -> Any:
        path = self.run_writer.layout.run_dir(run_id) / name
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "data" in raw:
            return raw["data"]
        return raw

    def _load_optional_run_payload(self, run_id: str, name: str) -> Any | None:
        path = self.run_writer.layout.run_dir(run_id) / name
        if not path.exists():
            return None
        return self._load_run_json(run_id, name)

    def _load_frozen_payload(self, run_id: str, freeze_stage: str, artifact_name: str) -> dict[str, Any]:
        record = self.run_writer.get_freeze_record(run_id, freeze_stage)
        if record is None or record.status != "frozen":
            raise FileNotFoundError(f"freeze artifact unavailable: {freeze_stage}/{artifact_name}")
        for artifact in record.artifacts:
            if artifact.name != artifact_name:
                continue
            raw = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
            payload = raw.get("data") if isinstance(raw, dict) else raw
            if not isinstance(payload, dict):
                raise ValueError(f"frozen payload is not an object: {artifact_name}")
            return payload
        raise FileNotFoundError(f"artifact not found: {artifact_name}")

    def _load_optional_frozen_payload(self, run_id: str, freeze_stage: str, artifact_name: str) -> dict[str, Any] | None:
        try:
            return self._load_frozen_payload(run_id, freeze_stage, artifact_name)
        except FileNotFoundError:
            return None

    def _load_list_payload(self, run_id: str, freeze_stage: str, artifact_name: str) -> list[dict[str, Any]]:
        record = self.run_writer.get_freeze_record(run_id, freeze_stage)
        if record is None:
            return []
        for artifact in record.artifacts:
            if artifact.name != artifact_name:
                continue
            raw = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
            payload = raw.get("data") if isinstance(raw, dict) else raw
            if not isinstance(payload, list):
                return []
            return [dict(item) for item in payload if isinstance(item, dict)]
        return []

    def _require_frozen(self, run_id: str, freeze_stage: str) -> None:
        record = self.run_writer.get_freeze_record(run_id, freeze_stage)
        if record is None or record.status != "frozen":
            raise ValueError(f"缺少已冻结的 {freeze_stage}")

    def _require_file(self, run_id: str, name: str) -> None:
        path = self.run_writer.layout.run_dir(run_id) / name
        if not path.exists():
            raise FileNotFoundError(f"required run artifact missing: {name}")
