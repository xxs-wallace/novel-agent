from __future__ import annotations

import difflib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ...runs.writer import RunWriter


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _clean_tuple(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(_clean_text(value) for value in values if _clean_text(value))


class ScopedArtifactRevisionError(ValueError):
    """Base error for scoped artifact revision contract violations."""


class ScopeGuardError(ScopedArtifactRevisionError):
    """Raised when a request escapes the current review artifact scope."""


class RevisionResultError(ScopedArtifactRevisionError):
    """Raised when a candidate revision result violates the contract."""


@dataclass(frozen=True, slots=True)
class ScopedArtifactRevisionLLMInput:
    request: dict[str, Any]
    policy: dict[str, Any]
    target_artifact: dict[str, Any]
    allowed_context: dict[str, Any]
    user_feedback: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScopedArtifactRevisionAdapter(Protocol):
    def generate_candidate(self, llm_input: ScopedArtifactRevisionLLMInput) -> Mapping[str, Any] | ScopedArtifactRevisionResult:
        """Return a structured candidate result without writing files."""


class ModelScopedArtifactRevisionAdapter:
    def __init__(self, *, model_client: Any | None) -> None:
        self.model_client = model_client

    def generate_candidate(self, llm_input: ScopedArtifactRevisionLLMInput) -> Mapping[str, Any]:
        if self.model_client is None:
            raise RevisionResultError("Scoped Artifact Revision requires a revision adapter or model client")
        payload, _ = self.model_client.generate_json(
            system_prompt=(
                "You revise exactly one writer workflow artifact. Return JSON only. "
                "Do not write files. Do not modify Memory, KB, workflow state, prompts, or other artifacts."
            ),
            user_prompt=json.dumps(llm_input.to_dict(), ensure_ascii=False, indent=2),
            fallback_factory=lambda: {
                "revision_id": f"revision-{llm_input.request['request_id']}",
                "request_id": llm_input.request["request_id"],
                "status": "candidate",
                "target_artifact_type": llm_input.request["target_artifact_type"],
                "target_artifact_path": llm_input.request["target_artifact_path"],
                "change_summary": "dry-run candidate kept the artifact unchanged",
                "validation": {"adapter": "dry_run"},
                "created_at": _utc_now(),
                "revised_artifact": llm_input.target_artifact,
            },
            use_fallback_on_error=False,
        )
        if not isinstance(payload, Mapping):
            raise RevisionResultError("revision adapter must return a JSON object")
        return payload


@dataclass(frozen=True, slots=True)
class ScopedArtifactReviewContext:
    run_id: str
    current_stage: str
    current_artifact_type: str
    current_artifact_path: str
    run_dir: str | None = None
    current_batch_id: str = ""
    current_chapter_id: str = ""
    allowed_chapter_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _clean_text(self.run_id))
        object.__setattr__(self, "current_stage", _clean_text(self.current_stage))
        object.__setattr__(self, "current_artifact_type", _clean_text(self.current_artifact_type))
        object.__setattr__(self, "current_artifact_path", _clean_text(self.current_artifact_path))
        object.__setattr__(self, "run_dir", _clean_text(self.run_dir) or None)
        object.__setattr__(self, "current_batch_id", _clean_text(self.current_batch_id))
        object.__setattr__(self, "current_chapter_id", _clean_text(self.current_chapter_id))
        object.__setattr__(self, "allowed_chapter_ids", _clean_tuple(self.allowed_chapter_ids))
        if not self.run_id:
            raise ScopeGuardError("run_id is required for scoped artifact revision context")
        if not self.current_stage:
            raise ScopeGuardError("current_stage is required for scoped artifact revision context")
        if not self.current_artifact_type:
            raise ScopeGuardError("current_artifact_type is required for scoped artifact revision context")
        if not self.current_artifact_path:
            raise ScopeGuardError("current_artifact_path is required for scoped artifact revision context")


@dataclass(frozen=True, slots=True)
class RevisionStagePolicy:
    review_stage: str
    artifact_types: tuple[str, ...]
    artifact_filenames: Mapping[str, tuple[str, ...]]
    schema_required_fields: Mapping[str, tuple[str, ...]]
    allowed_fields: Mapping[str, tuple[str, ...]]
    forbidden_targets: tuple[str, ...]

    def allows_artifact(self, artifact_type: str) -> bool:
        return _clean_text(artifact_type) in self.artifact_types

    def required_fields_for(self, artifact_type: str) -> tuple[str, ...]:
        return self.schema_required_fields.get(_clean_text(artifact_type), ())

    def allowed_fields_for(self, artifact_type: str) -> tuple[str, ...]:
        return self.allowed_fields.get(_clean_text(artifact_type), ())

    def allowed_filenames_for(self, artifact_type: str) -> tuple[str, ...]:
        return self.artifact_filenames.get(_clean_text(artifact_type), ())


COMMON_FORBIDDEN_TARGETS = (
    "memory",
    "memory_writeback",
    "kb",
    "creative_kb",
    "workflow_state",
    "workflow_checkpoints",
    "system_prompt",
    "prompt",
    "other_batch",
    "other_batches",
    "other_chapter",
    "other_chapters",
)

FORBIDDEN_FEEDBACK_TERMS = (
    "memory",
    "记忆",
    "kb",
    "知识库",
    "creative kb",
    "workflow state",
    "workflow_state",
    "工作流状态",
    "系统 prompt",
    "system prompt",
    "prompt",
    "其他批次",
    "别的批次",
    "other batch",
    "其他章节",
    "别的章节",
    "other chapter",
)

FORBIDDEN_FILE_NAMES = {
    "workflow_state.json",
    "workflow_checkpoints.json",
    "memory_writeback.json",
    "accepted_chapters.md",
    "novel.db",
    "prompt.txt",
    "system_prompt.txt",
    "authorized_inputs.json",
}

FORBIDDEN_PATH_PARTS = {
    "memory",
    "kb",
    "creative_kb",
    "prompts",
    "system_prompts",
}

REVISION_STAGE_POLICIES: dict[str, RevisionStagePolicy] = {
    "freeze_a_review": RevisionStagePolicy(
        review_stage="freeze_a_review",
        artifact_types=("BookContinuationPlan", "WorldExpansionPack", "CharacterCastPlan"),
        artifact_filenames={
            "BookContinuationPlan": ("book_continuation_plan.json",),
            "WorldExpansionPack": ("world_expansion_pack.json",),
            "CharacterCastPlan": ("character_cast_plan.json",),
        },
        schema_required_fields={
            "BookContinuationPlan": ("plan_id", "book_id", "continuation_goal"),
            "WorldExpansionPack": ("pack_id", "book_id"),
            "CharacterCastPlan": ("cast_plan_id", "book_id"),
        },
        allowed_fields={
            "BookContinuationPlan": (
                "plan_id",
                "book_id",
                "continuation_goal",
                "ending_direction",
                "target_chapter_count",
                "target_total_chars",
                "default_chapter_target_chars",
                "pacing_profile",
                "length_distribution_notes",
                "climax_plan",
                "chapter_outline_slots",
                "stage_highlights",
                "character_arcs",
                "relationship_guardrails",
                "must_preserve",
                "open_questions",
                "evidence",
                "sources",
            ),
            "WorldExpansionPack": (
                "pack_id",
                "book_id",
                "required_for_plot",
                "constraint_rules",
                "open_items",
                "evidence",
                "sources",
            ),
            "CharacterCastPlan": (
                "cast_plan_id",
                "book_id",
                "depends_on",
                "planned_characters",
                "open_questions",
                "must_not_consume",
            ),
        },
        forbidden_targets=COMMON_FORBIDDEN_TARGETS + ("downstream_batch", "draft"),
    ),
    "batch_review": RevisionStagePolicy(
        review_stage="batch_review",
        artifact_types=("BatchPlan",),
        artifact_filenames={"BatchPlan": ("batch_plan.json",)},
        schema_required_fields={"BatchPlan": ("batch_id", "book_id", "scope_start", "scope_end", "batch_goal")},
        allowed_fields={
            "BatchPlan": (
                "batch_id",
                "book_id",
                "scope_start",
                "scope_end",
                "batch_goal",
                "emotional_arc",
                "conflict_arc",
                "must_resolve",
                "must_not_consume",
                "planned_character_beats",
                "exit_hook",
                "evidence",
                "sources",
            )
        },
        forbidden_targets=COMMON_FORBIDDEN_TARGETS + ("draft", "final", "chapter_package"),
    ),
    "chapter_review": RevisionStagePolicy(
        review_stage="chapter_review",
        artifact_types=("ChapterPackage", "ChapterBrief"),
        artifact_filenames={
            "ChapterPackage": ("chapter_package.json",),
            "ChapterBrief": ("chapter_package.json", "chapter_brief.json"),
        },
        schema_required_fields={
            "ChapterPackage": ("package_id", "batch_id", "chapters"),
            "ChapterBrief": ("chapter_id", "title", "goal"),
        },
        allowed_fields={
            "ChapterPackage": ("package_id", "batch_id", "package_goal", "chapters", "review_notes", "sources"),
            "ChapterBrief": (
                "chapter_id",
                "title",
                "goal",
                "chapter_role",
                "plot_function",
                "emotional_goal",
                "conflict_goal",
                "relationship_targets",
                "must_include",
                "forbidden",
                "structure_hint",
                "ending_hook",
                "target_word_count",
                "sources",
            ),
        },
        forbidden_targets=COMMON_FORBIDDEN_TARGETS + ("batch_goal", "length_plan", "draft"),
    ),
    "wait_chapter_review": RevisionStagePolicy(
        review_stage="wait_chapter_review",
        artifact_types=("ChapterPackage", "ChapterBrief"),
        artifact_filenames={
            "ChapterPackage": ("chapter_package.json",),
            "ChapterBrief": ("chapter_package.json", "chapter_brief.json"),
        },
        schema_required_fields={
            "ChapterPackage": ("package_id", "batch_id", "chapters"),
            "ChapterBrief": ("chapter_id", "title", "goal"),
        },
        allowed_fields={
            "ChapterPackage": ("package_id", "batch_id", "package_goal", "chapters", "review_notes", "sources"),
            "ChapterBrief": (
                "chapter_id",
                "title",
                "goal",
                "chapter_role",
                "plot_function",
                "emotional_goal",
                "conflict_goal",
                "relationship_targets",
                "must_include",
                "forbidden",
                "structure_hint",
                "ending_hook",
                "target_word_count",
                "sources",
            ),
        },
        forbidden_targets=COMMON_FORBIDDEN_TARGETS + ("batch_goal", "length_plan", "draft"),
    ),
    "wait_length_review": RevisionStagePolicy(
        review_stage="wait_length_review",
        artifact_types=("ChapterLengthPlan",),
        artifact_filenames={"ChapterLengthPlan": ("chapter_length_plan.json",)},
        schema_required_fields={
            "ChapterLengthPlan": (
                "plan_id",
                "batch_id",
                "default_target_chars",
                "default_min_chars",
                "default_max_chars",
                "budgets",
            )
        },
        allowed_fields={
            "ChapterLengthPlan": (
                "plan_id",
                "batch_id",
                "default_target_chars",
                "default_min_chars",
                "default_max_chars",
                "budgets",
                "focus_chapter_ids",
                "climax_chapter_ids",
                "review_notes",
                "sources",
            )
        },
        forbidden_targets=COMMON_FORBIDDEN_TARGETS
        + ("chapter_goal", "relationship_targets", "world_expansion_pack", "chapter_package", "draft"),
    ),
    "freeze_d_review": RevisionStagePolicy(
        review_stage="freeze_d_review",
        artifact_types=("ChapterExecutionInput",),
        artifact_filenames={"ChapterExecutionInput": ("chapter_execution_input.json",)},
        schema_required_fields={"ChapterExecutionInput": ("run_id", "book_id", "chapter_id", "chapter_brief", "length_budget")},
        allowed_fields={
            "ChapterExecutionInput": (
                "run_id",
                "book_id",
                "chapter_id",
                "document_title_index",
                "chapter_title",
                "chapter_brief",
                "length_budget",
                "fact_inputs",
                "style_reference_bundle",
                "forbidden_inputs",
                "relation_state_gate",
                "planned_character_constraints",
                "writer_rules",
                "sources",
            )
        },
        forbidden_targets=COMMON_FORBIDDEN_TARGETS + ("unfrozen_plot", "draft", "final"),
    ),
}


@dataclass(frozen=True, slots=True)
class ScopedArtifactRevisionRequest:
    request_id: str
    run_id: str
    target_stage: str
    target_artifact_type: str
    target_artifact_path: str
    user_feedback: str
    scope: dict[str, Any]
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _clean_text(self.request_id))
        object.__setattr__(self, "run_id", _clean_text(self.run_id))
        object.__setattr__(self, "target_stage", _clean_text(self.target_stage))
        object.__setattr__(self, "target_artifact_type", _clean_text(self.target_artifact_type))
        object.__setattr__(self, "target_artifact_path", _clean_text(self.target_artifact_path))
        object.__setattr__(self, "user_feedback", _clean_text(self.user_feedback))
        object.__setattr__(self, "created_at", _clean_text(self.created_at) or _utc_now())
        object.__setattr__(self, "scope", dict(self.scope or {}))
        missing = [
            name
            for name in (
                "request_id",
                "run_id",
                "target_stage",
                "target_artifact_type",
                "target_artifact_path",
                "user_feedback",
                "created_at",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise ScopeGuardError(f"ScopedArtifactRevisionRequest missing required fields: {', '.join(missing)}")
        if not isinstance(self.scope, dict):
            raise ScopeGuardError("scope must be a dict")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScopedArtifactRevisionRequest":
        required = {
            "request_id",
            "run_id",
            "target_stage",
            "target_artifact_type",
            "target_artifact_path",
            "user_feedback",
            "scope",
            "created_at",
        }
        missing = sorted(name for name in required if name not in payload)
        if missing:
            raise ScopeGuardError(f"ScopedArtifactRevisionRequest missing required fields: {', '.join(missing)}")
        return cls(
            request_id=str(payload["request_id"]),
            run_id=str(payload["run_id"]),
            target_stage=str(payload["target_stage"]),
            target_artifact_type=str(payload["target_artifact_type"]),
            target_artifact_path=str(payload["target_artifact_path"]),
            user_feedback=str(payload["user_feedback"]),
            scope=dict(payload["scope"] if isinstance(payload["scope"], Mapping) else {}),
            created_at=str(payload["created_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScopedArtifactRevisionResult:
    revision_id: str
    request_id: str
    status: str
    target_artifact_type: str
    target_artifact_path: str
    change_summary: str
    validation: dict[str, Any]
    created_at: str
    revised_artifact: dict[str, Any] | None = None
    patch: list[dict[str, Any]] | None = None
    diff_path: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "revision_id", _clean_text(self.revision_id))
        object.__setattr__(self, "request_id", _clean_text(self.request_id))
        object.__setattr__(self, "status", _clean_text(self.status))
        object.__setattr__(self, "target_artifact_type", _clean_text(self.target_artifact_type))
        object.__setattr__(self, "target_artifact_path", _clean_text(self.target_artifact_path))
        object.__setattr__(self, "change_summary", _clean_text(self.change_summary))
        object.__setattr__(self, "created_at", _clean_text(self.created_at) or _utc_now())
        object.__setattr__(self, "validation", dict(self.validation or {}))
        object.__setattr__(self, "diff_path", _clean_text(self.diff_path))
        if self.revised_artifact is not None:
            object.__setattr__(self, "revised_artifact", dict(self.revised_artifact))
        if self.patch is not None:
            object.__setattr__(self, "patch", [dict(item) for item in self.patch])
        missing = [
            name
            for name in (
                "revision_id",
                "request_id",
                "status",
                "target_artifact_type",
                "target_artifact_path",
                "change_summary",
                "created_at",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise RevisionResultError(f"ScopedArtifactRevisionResult missing required fields: {', '.join(missing)}")
        if self.revised_artifact is None and self.patch is None:
            raise RevisionResultError("ScopedArtifactRevisionResult must include revised_artifact or patch")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScopedArtifactRevisionResult":
        required = {
            "revision_id",
            "request_id",
            "status",
            "target_artifact_type",
            "target_artifact_path",
            "change_summary",
            "validation",
            "created_at",
        }
        missing = sorted(name for name in required if name not in payload)
        if missing:
            raise RevisionResultError(f"ScopedArtifactRevisionResult missing required fields: {', '.join(missing)}")
        revised = payload.get("revised_artifact")
        patch = payload.get("patch")
        return cls(
            revision_id=str(payload["revision_id"]),
            request_id=str(payload["request_id"]),
            status=str(payload["status"]),
            target_artifact_type=str(payload["target_artifact_type"]),
            target_artifact_path=str(payload["target_artifact_path"]),
            change_summary=str(payload["change_summary"]),
            validation=dict(payload["validation"] if isinstance(payload["validation"], Mapping) else {}),
            created_at=str(payload["created_at"]),
            revised_artifact=dict(revised) if isinstance(revised, Mapping) else None,
            patch=[dict(item) for item in patch] if isinstance(patch, list) else None,
            diff_path=str(payload.get("diff_path") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.revised_artifact is None:
            payload.pop("revised_artifact", None)
        if self.patch is None:
            payload.pop("patch", None)
        if not self.diff_path:
            payload.pop("diff_path", None)
        return payload


def get_revision_stage_policy(stage: str) -> RevisionStagePolicy:
    normalized = _clean_text(stage)
    policy = REVISION_STAGE_POLICIES.get(normalized)
    if policy is None:
        raise ScopeGuardError(f"Scoped Artifact Revision is not allowed for stage: {normalized}")
    return policy


def validate_scoped_revision_request(
    request: ScopedArtifactRevisionRequest,
    context: ScopedArtifactReviewContext,
) -> RevisionStagePolicy:
    policy = get_revision_stage_policy(request.target_stage)
    if request.run_id != context.run_id:
        raise ScopeGuardError("request run_id must match the current review context")
    if request.target_stage != context.current_stage:
        raise ScopeGuardError("request target_stage must match the current review stage")
    if not policy.allows_artifact(request.target_artifact_type):
        raise ScopeGuardError(
            f"{request.target_artifact_type} is not an allowed artifact type for {request.target_stage}"
        )
    if context.current_artifact_type != request.target_artifact_type:
        raise ScopeGuardError("request target_artifact_type must match the current review artifact")

    target_path = _normalize_artifact_path(request.target_artifact_path, context.run_dir)
    current_path = _normalize_artifact_path(context.current_artifact_path, context.run_dir)
    if target_path != current_path:
        raise ScopeGuardError("request target_artifact_path must be the current review artifact")
    _guard_path_is_in_run_dir(target_path, context.run_dir)
    _guard_path_is_not_forbidden(target_path)
    _guard_allowed_filename(request.target_artifact_type, target_path, policy)
    _guard_feedback_is_not_forbidden(request.user_feedback)
    _guard_single_artifact_scope(request, target_path, context)
    _guard_scope_identifiers(request, context)
    return policy


def _guard_feedback_is_not_forbidden(user_feedback: str) -> None:
    normalized = _clean_text(user_feedback).lower()
    mutation_terms = (
        "修改",
        "改",
        "写入",
        "更新",
        "删除",
        "调整",
        "modify",
        "change",
        "update",
        "write",
        "edit",
        "alter",
        "set",
    )
    negation_terms = ("不要", "不得", "不能", "别", "禁止", "do not", "don't", "without", "avoid")
    forbidden: list[str] = []
    for term in FORBIDDEN_FEEDBACK_TERMS:
        term = term.lower()
        start = normalized.find(term)
        while start >= 0:
            before = normalized[max(0, start - 16) : start]
            after = normalized[start + len(term) : start + len(term) + 16]
            if any(negation in before for negation in negation_terms):
                start = normalized.find(term, start + len(term))
                continue
            if any(mutation in before or mutation in after for mutation in mutation_terms):
                forbidden.append(term)
                break
            start = normalized.find(term, start + len(term))
    if forbidden:
        raise ScopeGuardError(
            "user feedback asks to modify targets outside the current artifact scope: "
            + ", ".join(sorted(set(forbidden)))
        )


def validate_scoped_revision_result(
    request: ScopedArtifactRevisionRequest,
    result: ScopedArtifactRevisionResult,
    context: ScopedArtifactReviewContext,
) -> RevisionStagePolicy:
    policy = validate_scoped_revision_request(request, context)
    if result.request_id != request.request_id:
        raise RevisionResultError("result request_id must match the request")
    if result.target_artifact_type != request.target_artifact_type:
        raise RevisionResultError("result target_artifact_type must match the request")
    if _normalize_artifact_path(result.target_artifact_path, context.run_dir) != _normalize_artifact_path(
        request.target_artifact_path,
        context.run_dir,
    ):
        raise RevisionResultError("result target_artifact_path must match the request")
    if result.revised_artifact is not None:
        _validate_revised_artifact_schema(result.revised_artifact, request.target_artifact_type, policy)
        _guard_forbidden_payload_targets(result.revised_artifact, policy)
        _guard_revised_artifact_identifiers(result.revised_artifact, context)
    if result.patch is not None:
        _validate_patch_scope(result.patch, policy)
    return policy


def _normalize_artifact_path(path: str, run_dir: str | None) -> Path:
    candidate = Path(_clean_text(path)).expanduser()
    if not candidate.is_absolute() and run_dir:
        candidate = Path(run_dir).expanduser() / candidate
    return candidate.resolve(strict=False)


def _guard_path_is_in_run_dir(path: Path, run_dir: str | None) -> None:
    if not run_dir:
        return
    root = Path(run_dir).expanduser().resolve(strict=False)
    if path != root and root not in path.parents:
        raise ScopeGuardError("target_artifact_path must stay inside the current run directory")


def _guard_path_is_not_forbidden(path: Path) -> None:
    if path.name.lower() in FORBIDDEN_FILE_NAMES:
        raise ScopeGuardError(f"target artifact is forbidden: {path.name}")
    parts = {part.lower() for part in path.parts}
    forbidden = sorted(parts & FORBIDDEN_PATH_PARTS)
    if forbidden:
        raise ScopeGuardError(f"target artifact path crosses forbidden area: {', '.join(forbidden)}")


def _guard_allowed_filename(artifact_type: str, path: Path, policy: RevisionStagePolicy) -> None:
    allowed = policy.allowed_filenames_for(artifact_type)
    if allowed and path.name not in allowed:
        raise ScopeGuardError(f"{path.name} is not an allowed file for {artifact_type} at {policy.review_stage}")


def _guard_single_artifact_scope(
    request: ScopedArtifactRevisionRequest,
    target_path: Path,
    context: ScopedArtifactReviewContext,
) -> None:
    scope = request.scope
    multi_target_keys = ("target_artifact_paths", "target_artifacts", "write_paths", "artifact_paths")
    for key in multi_target_keys:
        value = scope.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) > 1:
            raise ScopeGuardError("scope may bind only one target artifact")
    scoped_path = scope.get("target_artifact_path") or scope.get("current_artifact_path") or scope.get("artifact_path")
    if scoped_path and _normalize_artifact_path(str(scoped_path), context.run_dir) != target_path:
        raise ScopeGuardError("scope artifact path must match the request target artifact")
    scoped_type = _clean_text(scope.get("target_artifact_type") or scope.get("current_artifact_type"))
    if scoped_type and scoped_type != request.target_artifact_type:
        raise ScopeGuardError("scope artifact type must match the request target artifact")


def _guard_scope_identifiers(request: ScopedArtifactRevisionRequest, context: ScopedArtifactReviewContext) -> None:
    scope = request.scope
    expected_batch_id = context.current_batch_id or _clean_text(scope.get("current_batch_id"))
    target_batch_id = _clean_text(scope.get("target_batch_id") or scope.get("batch_id"))
    if expected_batch_id and target_batch_id and target_batch_id != expected_batch_id:
        raise ScopeGuardError("request cannot target another batch")

    expected_chapter_id = context.current_chapter_id or _clean_text(scope.get("current_chapter_id"))
    target_chapter_id = _clean_text(scope.get("target_chapter_id") or scope.get("chapter_id"))
    if expected_chapter_id and target_chapter_id and target_chapter_id != expected_chapter_id:
        raise ScopeGuardError("request cannot target another chapter")

    allowed_chapter_ids = context.allowed_chapter_ids or tuple(
        _clean_text(item)
        for item in scope.get("allowed_chapter_ids", ())
        if _clean_text(item)
    )
    if allowed_chapter_ids and target_chapter_id and target_chapter_id not in allowed_chapter_ids:
        raise ScopeGuardError("request chapter_id is outside the current artifact scope")


def _validate_revised_artifact_schema(
    artifact: Mapping[str, Any],
    artifact_type: str,
    policy: RevisionStagePolicy,
) -> None:
    required = set(policy.required_fields_for(artifact_type))
    missing = sorted(field_name for field_name in required if field_name not in artifact)
    if missing:
        raise RevisionResultError(f"revised_artifact missing required fields: {', '.join(missing)}")
    allowed = set(policy.allowed_fields_for(artifact_type))
    unknown = sorted(str(field_name) for field_name in artifact if allowed and str(field_name) not in allowed)
    if unknown:
        raise RevisionResultError(f"revised_artifact contains fields outside the whitelist: {', '.join(unknown)}")


def _guard_forbidden_payload_targets(payload: Mapping[str, Any], policy: RevisionStagePolicy) -> None:
    forbidden = {_clean_text(item).lower() for item in policy.forbidden_targets}

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key).strip().lower()
                if key_text in forbidden:
                    raise RevisionResultError(f"revised_artifact attempts to modify forbidden target: {path}{key_text}")
                walk(child, f"{path}{key_text}.")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}{index}.")

    walk(payload)


def _guard_revised_artifact_identifiers(
    artifact: Mapping[str, Any],
    context: ScopedArtifactReviewContext,
) -> None:
    batch_id = _clean_text(artifact.get("batch_id"))
    if context.current_batch_id and batch_id and batch_id != context.current_batch_id:
        raise RevisionResultError("revised_artifact cannot switch to another batch")
    chapter_id = _clean_text(artifact.get("chapter_id"))
    if context.current_chapter_id and chapter_id and chapter_id != context.current_chapter_id:
        raise RevisionResultError("revised_artifact cannot switch to another chapter")
    allowed_chapter_ids = set(context.allowed_chapter_ids)
    if allowed_chapter_ids:
        chapter_ids = _extract_chapter_ids(artifact)
        outside = sorted(chapter_ids - allowed_chapter_ids)
        if outside:
            raise RevisionResultError(f"revised_artifact contains chapters outside the current scope: {', '.join(outside)}")


def _extract_chapter_ids(value: Any) -> set[str]:
    chapter_ids: set[str] = set()
    if isinstance(value, Mapping):
        chapter_id = _clean_text(value.get("chapter_id"))
        if chapter_id:
            chapter_ids.add(chapter_id)
        for child in value.values():
            chapter_ids.update(_extract_chapter_ids(child))
    elif isinstance(value, list):
        for child in value:
            chapter_ids.update(_extract_chapter_ids(child))
    return chapter_ids


def _validate_patch_scope(patch: Sequence[Mapping[str, Any]], policy: RevisionStagePolicy) -> None:
    forbidden = {_clean_text(item).lower() for item in policy.forbidden_targets}
    for item in patch:
        path = _clean_text(item.get("path")).lower().strip("/")
        first_segment = path.split("/", 1)[0] if path else ""
        if first_segment in forbidden:
            raise RevisionResultError(f"patch attempts to modify forbidden target: {first_segment}")


def build_readable_artifact_diff(
    *,
    original_artifact: Mapping[str, Any],
    revised_artifact: Mapping[str, Any],
    from_label: str = "current",
    to_label: str = "candidate",
) -> str:
    original_lines = json.dumps(dict(original_artifact), ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    revised_lines = json.dumps(dict(revised_artifact), ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    return "\n".join(
        difflib.unified_diff(
            original_lines,
            revised_lines,
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
        )
    )


def validate_scoped_revision_references(
    *,
    revised_artifact: Mapping[str, Any],
    allowed_context: Mapping[str, Any],
) -> None:
    allowed_paths = _collect_allowed_source_paths(allowed_context)
    if not allowed_paths:
        return
    referenced_paths = _collect_payload_source_paths(revised_artifact)
    unknown = sorted(path for path in referenced_paths if path not in allowed_paths)
    if unknown:
        raise RevisionResultError(f"revised_artifact references sources outside the whitelist: {', '.join(unknown)}")


def validate_upstream_freeze_constraints(
    *,
    request: ScopedArtifactRevisionRequest,
    revised_artifact: Mapping[str, Any],
    allowed_context: Mapping[str, Any],
) -> None:
    upstream = allowed_context.get("upstream_freezes")
    upstream_freezes = dict(upstream) if isinstance(upstream, Mapping) else {}
    artifact_type = request.target_artifact_type
    if artifact_type == "BatchPlan":
        freeze_a = dict(upstream_freezes.get("freeze_a") or {})
        book_id = _clean_text(freeze_a.get("book_id"))
        if book_id and _clean_text(revised_artifact.get("book_id")) != book_id:
            raise RevisionResultError("BatchPlan cannot switch book_id away from frozen Freeze A context")
    if artifact_type in {"ChapterPackage", "ChapterBrief"}:
        batch_plan = dict(upstream_freezes.get("freeze_b") or {})
        batch_id = _clean_text(batch_plan.get("batch_id"))
        if batch_id and _clean_text(revised_artifact.get("batch_id")) != batch_id:
            raise RevisionResultError("ChapterPackage cannot switch batch_id away from frozen BatchPlan")
    if artifact_type == "ChapterLengthPlan":
        chapter_package = dict(upstream_freezes.get("freeze_c") or {})
        batch_id = _clean_text(chapter_package.get("batch_id"))
        if batch_id and _clean_text(revised_artifact.get("batch_id")) != batch_id:
            raise RevisionResultError("ChapterLengthPlan cannot switch batch_id away from frozen ChapterPackage")
        allowed_chapters = _extract_chapter_ids(chapter_package)
        budget_chapters = _extract_chapter_ids(revised_artifact.get("budgets") or [])
        outside = sorted(budget_chapters - allowed_chapters)
        if outside:
            raise RevisionResultError(f"ChapterLengthPlan budgets reference chapters outside frozen package: {', '.join(outside)}")
    if artifact_type == "ChapterExecutionInput":
        chapter_id = _clean_text(revised_artifact.get("chapter_id"))
        chapter_brief = revised_artifact.get("chapter_brief")
        length_budget = revised_artifact.get("length_budget")
        if isinstance(chapter_brief, Mapping) and _clean_text(chapter_brief.get("chapter_id")) not in {"", chapter_id}:
            raise RevisionResultError("ChapterExecutionInput chapter_brief must keep the target chapter_id")
        if isinstance(length_budget, Mapping) and _clean_text(length_budget.get("chapter_id")) not in {"", chapter_id}:
            raise RevisionResultError("ChapterExecutionInput length_budget must keep the target chapter_id")


def _collect_allowed_source_paths(value: Any) -> set[str]:
    paths = _collect_payload_source_paths(value)
    explicit = value.get("source_paths") if isinstance(value, Mapping) else None
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        paths.update(_clean_text(item) for item in explicit if _clean_text(item))
    return paths


def _collect_payload_source_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in {"path", "source_path", "artifact_path"}:
                text = _clean_text(child)
                if text:
                    paths.add(text)
            paths.update(_collect_payload_source_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.update(_collect_payload_source_paths(child))
    return paths


@dataclass(frozen=True, slots=True)
class ScopedArtifactRevisionStore:
    run_writer: RunWriter

    def write_request(self, request: ScopedArtifactRevisionRequest) -> Path:
        name = f"scoped_artifact_revisions/{request.request_id}/request.json"
        path = self.run_writer.write_json(request.run_id, name, request)
        self._upsert_index(request.run_id, request_id=request.request_id, request_path=path, request=request)
        return path

    def write_result(
        self,
        result: ScopedArtifactRevisionResult,
        *,
        request: ScopedArtifactRevisionRequest,
    ) -> Path:
        if result.request_id != request.request_id:
            raise RevisionResultError("result request_id must match the persisted request")
        name = f"scoped_artifact_revisions/{request.request_id}/result.json"
        path = self.run_writer.write_json(request.run_id, name, result)
        self._upsert_index(request.run_id, request_id=request.request_id, result_path=path, request=request, result=result)
        return path

    def write_diff(self, request: ScopedArtifactRevisionRequest, diff_text: str) -> Path:
        name = f"scoped_artifact_revisions/{request.request_id}/diff.md"
        return self.run_writer.write_text(request.run_id, name, diff_text)

    def read_request(self, run_id: str, request_id: str) -> ScopedArtifactRevisionRequest:
        path = self.run_writer.layout.run_dir(run_id) / "scoped_artifact_revisions" / request_id / "request.json"
        payload = self._load_document_data(path)
        return ScopedArtifactRevisionRequest.from_dict(payload)

    def read_result(self, run_id: str, request_id: str) -> ScopedArtifactRevisionResult:
        path = self.run_writer.layout.run_dir(run_id) / "scoped_artifact_revisions" / request_id / "result.json"
        payload = self._load_document_data(path)
        return ScopedArtifactRevisionResult.from_dict(payload)

    def _upsert_index(
        self,
        run_id: str,
        *,
        request_id: str,
        request_path: Path | None = None,
        result_path: Path | None = None,
        request: ScopedArtifactRevisionRequest | None = None,
        result: ScopedArtifactRevisionResult | None = None,
    ) -> None:
        index_path = self.run_writer.layout.run_dir(run_id) / "scoped_artifact_revisions" / "index.json"
        current = self._load_index(index_path)
        revisions = {
            str(item.get("request_id")): dict(item)
            for item in current.get("revisions", [])
            if isinstance(item, Mapping) and item.get("request_id")
        }
        record = revisions.get(request_id, {"request_id": request_id})
        if request_path is not None:
            record["request_path"] = str(request_path)
        if result_path is not None:
            record["result_path"] = str(result_path)
        if request is not None:
            record.update(
                {
                    "run_id": request.run_id,
                    "target_stage": request.target_stage,
                    "target_artifact_type": request.target_artifact_type,
                    "target_artifact_path": request.target_artifact_path,
                    "user_feedback": request.user_feedback,
                    "created_at": request.created_at,
                }
            )
        if result is not None:
            record.update(
                {
                    "revision_id": result.revision_id,
                    "result_status": result.status,
                    "change_summary": result.change_summary,
                    "diff_path": result.diff_path,
                }
            )
        revisions[request_id] = record
        payload = {"revisions": list(revisions.values())}
        self.run_writer.write_json(run_id, "scoped_artifact_revisions/index.json", payload)

    def _load_index(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"revisions": []}
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, Mapping) else raw
        return dict(payload) if isinstance(payload, Mapping) else {"revisions": []}

    def _load_document_data(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"scoped artifact revision document not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, Mapping) else raw
        if not isinstance(payload, Mapping):
            raise RevisionResultError(f"scoped artifact revision document is not an object: {path}")
        return dict(payload)
