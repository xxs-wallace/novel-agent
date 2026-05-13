from __future__ import annotations

import getpass
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, cast

from ..runs.layout import RunLayout
from ..runs.writer import RunWriter
from .bootstrap import resolve_db_path, resolve_repo_root
from .cli import ArtifactPresenter, DecisionPanel, TuiApp, TuiSessionConfig, WriterStatusPresenter
from .constants import DEFAULT_CLOSE_READ_DOC_BUDGET, DEFAULT_CLOSE_READING_STAGE, DEFAULT_SEGMENTATION_STAGE
from .llm import JsonModelClient, ModelSettings
from .orchestrators import (
    RestrictedWriterExecutor,
    WriterInteractiveWorkflow,
    WriterLayeredGenerationOrchestrator,
    WriterRollbackManager,
)
from .repos.creative_kb_storage import init_creative_kb_schema
from .repos.db import NovelAgentDB
from .repos.documents_repo import DocumentsRepo
from .repos.fragment_cards_repo import FragmentCardsRepo
from .runner.close_read_runner import CloseReadRunner
from .runner.segmentation_runner import SegmentationRunner
from .schemas.config_schema import CloseReadAgentConfig, SegmentationAgentConfig
from .schemas.creative_kb_schema import CreativeKBBuildResult
from .services.creative_kb_facade import CreativeKnowledgeBaseFacade
from .services.fragment_card_builder_service import FragmentCardBuilderService
from .services.source_arc_mapping_service import SourceArcMappingService
from .services.writer_memory_workspace_service import WriterMemoryWorkspaceService


DEFAULT_PIPELINE_SEGMENT_STEP_KB = 32
DEFAULT_PIPELINE_CLOSE_STEP_BATCHES = 1
DEFAULT_PIPELINE_SEGMENT_MODEL_NAME = "deepseek-v4-flash"
DEFAULT_PIPELINE_CLOSE_READ_MODEL_NAME = "deepseek-v4-pro"
DEFAULT_PIPELINE_CREATIVE_KB_MODEL_NAME = "deepseek-v4-flash"
DEFAULT_WRITER_MODEL_NAME = "deepseek-v4-pro"
DEFAULT_PIPELINE_CREATIVE_KB_COMMIT_BATCH_SIZE = 8
STATUS_PRESENTER = WriterStatusPresenter()
ARTIFACT_PRESENTER = ArtifactPresenter()


def _prompt_text(prompt: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        print("输入不能为空，请重试。")


def _prompt_secret(prompt: str) -> str:
    while True:
        value = getpass.getpass(f"{prompt}: ").strip()
        if value:
            return value
        print("输入不能为空，请重试。")


def _prompt_choice(prompt: str, *, choices: dict[str, str], default: str) -> str:
    labels = "/".join([f"{key}={label}" for key, label in choices.items()])
    while True:
        value = input(f"{prompt} ({labels}) [{default}]: ").strip().lower()
        if not value:
            return default
        if value in choices:
            return value
        print(f"无效选项：{value}，请重试。")


def _prompt_optional_int(prompt: str, *, default: int | None = None, min_value: int = 1) -> int | None:
    suffix = f" [{default}]" if default is not None else " [留空表示不限制]"
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("请输入整数，或直接回车。")
            continue
        if value < min_value:
            print(f"请输入不小于 {min_value} 的整数。")
            continue
        return value


def _prompt_yes_no(prompt: str, *, default: bool) -> bool:
    default_label = "y" if default else "n"
    while True:
        value = input(f"{prompt} [y/n, default={default_label}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def _prompt_list(prompt: str, *, default: str = "") -> list[str]:
    raw = _prompt_text(prompt, default=default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _slugify_task_name(task_name: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", task_name.strip()).strip("-").lower()
    return normalized or "novel-task"


def _kb_to_chars(value_kb: int | None) -> int | None:
    if value_kb is None:
        return None
    return int(value_kb) * 1024


def _min_positive(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _chars_to_kb(value_chars: int) -> float:
    return round(value_chars / 1024, 2)


def _query_scalar(conn: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> int:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)


def _load_progress_snapshot(*, db_path: Path, book_id: str) -> dict[str, object]:
    if not db_path.exists():
        return {
            "segmentation_chars": 0,
            "segmentation_kb": 0.0,
            "close_read_chars": 0,
            "close_read_kb": 0.0,
            "last_completed_doc_id": None,
        }
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        segmentation_chars = _query_scalar(
            conn,
            "SELECT COALESCE(SUM(content_chars), 0) FROM documents WHERE book_id = ?",
            (book_id,),
        )
        close_progress = conn.execute(
            """
            SELECT last_completed_doc_id
            FROM reading_progress
            WHERE book_id = ? AND agent_stage = ?
            """,
            (book_id, DEFAULT_CLOSE_READING_STAGE),
        ).fetchone()
        last_completed_doc_id = (
            int(close_progress["last_completed_doc_id"])
            if close_progress and close_progress["last_completed_doc_id"] is not None
            else None
        )
        if last_completed_doc_id is None:
            close_read_chars = 0
        else:
            close_read_chars = _query_scalar(
                conn,
                "SELECT COALESCE(SUM(content_chars), 0) FROM documents WHERE book_id = ? AND doc_id <= ?",
                (book_id, last_completed_doc_id),
            )
        segmentation_progress = conn.execute(
            """
            SELECT current_source_offset
            FROM reading_progress
            WHERE book_id = ? AND agent_stage = ?
            """,
            (book_id, DEFAULT_SEGMENTATION_STAGE),
        ).fetchone()
    return {
        "segmentation_chars": segmentation_chars,
        "segmentation_kb": _chars_to_kb(segmentation_chars),
        "close_read_chars": close_read_chars,
        "close_read_kb": _chars_to_kb(close_read_chars),
        "last_completed_doc_id": last_completed_doc_id,
        "segmentation_source_offset": (
            int(segmentation_progress["current_source_offset"])
            if segmentation_progress and segmentation_progress["current_source_offset"] is not None
            else None
        ),
    }


def _resolve_api_key() -> str:
    env_value = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env_value:
        return env_value
    return _prompt_secret("未检测到 DEEPSEEK_API_KEY，请输入 DeepSeek API Key")


def build_writer_workflow(
    *,
    repo_root: Path,
    db_path: Path,
    runs_dir: Path,
    dry_run: bool,
    api_key: str | None = None,
    thinking: str | None = "enabled",
    reasoning_effort: str | None = "high",
    include_reasoning_content: bool = True,
    revision_adapter: object | None = None,
) -> tuple[NovelAgentDB, WriterInteractiveWorkflow]:
    model_client = None
    if not dry_run:
        model_client = JsonModelClient(
            ModelSettings(
                model_type="OpenAIModel",
                model_name=DEFAULT_WRITER_MODEL_NAME,
                provider="openai_compatible",
                base_url="https://api.deepseek.com",
                api_key=api_key,
                api_key_env="DEEPSEEK_API_KEY",
                retry_without_thinking_on_failure=True,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                include_reasoning_content=include_reasoning_content,
                dry_run=False,
            )
        )
    db = NovelAgentDB(db_path)
    run_writer = RunWriter(layout=RunLayout(base_dir=runs_dir))
    planner = WriterLayeredGenerationOrchestrator(
        repo_root=repo_root,
        run_writer=run_writer,
        model_client=model_client,
    )
    executor = RestrictedWriterExecutor(
        repo_root=repo_root,
        run_writer=run_writer,
        model_client=model_client,
    )
    rollback_manager = WriterRollbackManager(run_writer=run_writer)
    workflow = WriterInteractiveWorkflow(
        planner=planner,
        executor=executor,
        rollback_manager=rollback_manager,
        run_writer=run_writer,
        revision_adapter=revision_adapter,
    )
    return db, workflow


def resolve_writer_memory_db_path(*, repo_root: Path, book_id: str, reset: bool = False) -> Path:
    source_db_path = resolve_db_path(repo_root, str(repo_root / ".indexes" / f"{book_id}.db"))
    workspace = WriterMemoryWorkspaceService(repo_root=repo_root).ensure_workspace(
        book_id=book_id,
        source_db_path=source_db_path,
        reset=reset,
    )
    return workspace.writer_db_path


def run_writer_workflow_action(
    *,
    workflow: WriterInteractiveWorkflow,
    conn: sqlite3.Connection,
    action: str,
    run_id: str,
    book_id: str,
    product_mode: str,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    if action == "initialize":
        return workflow.initialize_workflow(run_id=run_id, book_id=book_id, product_mode=product_mode)
    if action == "prepare_planning":
        intent_payload = payload.get("intent_payload")
        return workflow.prepare_planning(
            conn,
            run_id=run_id,
            book_id=book_id,
            product_mode=product_mode,
            intent_payload=dict(intent_payload) if isinstance(intent_payload, dict) else {},
            user_world_notes=str(payload.get("user_world_notes") or ""),
            character_seed_payloads=cast(list[Mapping[str, Any]], payload.get("character_seed_payloads") or []),
            roster_hint_payloads=cast(list[Mapping[str, Any]], payload.get("roster_hint_payloads") or []),
        )
    if action == "continue_after_planning_review":
        return workflow.continue_after_planning_review(run_id=run_id)
    if action == "continue_after_outline_research_input":
        return workflow.continue_after_outline_research_input(
            conn,
            run_id=run_id,
            book_id=book_id,
            product_mode=product_mode,
            user_answers={
                str(key): str(value)
                for key, value in (payload.get("user_answers") or {}).items()
            }
            if isinstance(payload.get("user_answers"), dict)
            else {},
            user_world_notes=str(payload.get("user_world_notes") or ""),
            character_seed_payloads=cast(list[Mapping[str, Any]], payload.get("character_seed_payloads") or []),
            roster_hint_payloads=cast(list[Mapping[str, Any]], payload.get("roster_hint_payloads") or []),
        )
    if action == "prepare_batch_plan":
        return workflow.prepare_batch_plan(
            conn,
            run_id=run_id,
            book_id=book_id,
            product_mode=product_mode,
            target_chapter_count=int(cast(Any, payload.get("target_chapter_count") or 3)),
        )
    if action == "continue_after_batch_review":
        return workflow.continue_after_batch_review(
            run_id=run_id,
            artifact_path=str(payload.get("artifact_path") or "") or None,
        )
    if action == "prepare_chapter_package":
        return workflow.prepare_chapter_package(
            run_id=run_id,
            book_id=book_id,
            product_mode=product_mode,
            chapter_count=int(cast(Any, payload.get("chapter_count") or 3)),
        )
    if action == "continue_after_chapter_review":
        return workflow.continue_after_chapter_review(
            run_id=run_id,
            artifact_path=str(payload.get("artifact_path") or "") or None,
        )
    if action == "prepare_chapter_length_plan":
        return workflow.prepare_chapter_length_plan(
            run_id=run_id,
            product_mode=product_mode,
        )
    if action == "continue_after_length_review":
        return workflow.continue_after_length_review(
            run_id=run_id,
            artifact_path=str(payload.get("artifact_path") or "") or None,
            default_target_chars=(
                int(cast(Any, payload["default_target_chars"]))
                if payload.get("default_target_chars") not in (None, "")
                else None
            ),
            chapter_overrides=cast(Mapping[str, Mapping[str, Any]], payload.get("chapter_overrides") or {}),
        )
    if action == "prepare_execution":
        return workflow.prepare_execution(
            conn,
            run_id=run_id,
            book_id=book_id,
            chapter_id=str(payload.get("chapter_id") or ""),
            product_mode=product_mode,
        )
    if action == "continue_after_execution_review":
        return workflow.continue_after_execution_review(run_id=run_id)
    if action == "execute_current_chapter":
        return workflow.execute_current_chapter(
            conn,
            run_id=run_id,
            book_id=book_id,
            product_mode=product_mode,
        )
    if action in {
        "continue_after_chapter_acceptance",
        "accept_chapter",
        "revise_length",
        "replan_chapter",
        "discard_chapter",
    }:
        status_by_action = {
            "accept_chapter": "accepted",
            "revise_length": "revise_length",
            "replan_chapter": "replan_chapter",
            "discard_chapter": "discarded",
        }
        normalized_payload = dict(payload)
        if action in status_by_action:
            normalized_payload["status"] = status_by_action[action]
        if normalized_payload.get("status"):
            _write_writer_review_decision_payload(
                workflow=workflow,
                run_id=run_id,
                payload=normalized_payload,
            )
        return workflow.continue_after_chapter_acceptance(run_id=run_id)
    if action == "approve_writeback":
        return workflow.approve_writeback(conn, run_id=run_id, book_id=book_id)
    if action == "request_scoped_artifact_revision":
        return workflow.request_scoped_artifact_revision(
            run_id=run_id,
            user_feedback=str(payload.get("user_feedback") or ""),
            request_id=str(payload.get("request_id") or "") or None,
            target_stage=str(payload.get("target_stage") or "") or None,
            target_artifact_type=str(payload.get("target_artifact_type") or "") or None,
            target_artifact_path=str(payload.get("target_artifact_path") or "") or None,
        )
    if action == "apply_scoped_artifact_revision":
        return workflow.apply_scoped_artifact_revision(
            run_id=run_id,
            request_id=str(payload.get("request_id") or ""),
        )
    if action == "resume":
        return workflow.resume_from_latest_checkpoint(run_id=run_id) or {}
    if action == "character_cast_change":
        return workflow.register_character_cast_change(
            run_id=run_id,
            reason=str(payload.get("reason") or "人物补充方案已修改，需要级联回滚。"),
        )
    raise ValueError(f"Unsupported writer workflow action: {action}")


def _modeling_missing_guidance(missing_steps: list[str]) -> list[str]:
    guidance_by_step = {
        "documents.not_indexed": "先运行粗读/分段 pipeline，把原文切入 documents 表。",
        "memory.character_profiles": "先运行精读/记忆流程，生成角色档案。",
        "memory.story_outline": "补齐 story outline 资产，可通过精读摘要或手工大纲生成。",
        "memory.world_summary": "补齐 world summary 资产，可通过精读摘要或手工世界观整理生成。",
        "creative_kb.fragment_cards": "运行 Creative KB 构建，生成 fragment_cards / fragment_clusters。",
        "memory.source_arc_map": "运行 post-close-read Source Arc Mapping，生成 .memory/arcs/<book_id>.source_arc_map.json。",
        "creative_kb.narrative_structure_patterns": "运行 KB 结构模式沉淀，生成 NarrativeStructurePattern / ArcPatternCard。",
    }
    return [guidance_by_step.get(step, f"补齐建模缺失项：{step}") for step in missing_steps]


def _modeling_advisory_steps(modeling_status: Any) -> list[str]:
    checks = getattr(modeling_status, "checks", [])
    missing: list[str] = []
    for item in checks:
        name = str(getattr(item, "name", "")).strip()
        ready = bool(getattr(item, "ready", False))
        if ready:
            continue
        if name == "source_arc_map":
            missing.append("memory.source_arc_map")
        elif name == "narrative_structure_patterns":
            missing.append("creative_kb.narrative_structure_patterns")
    return missing


def _run_data_path(workflow: WriterInteractiveWorkflow, run_id: str, artifact_name: str) -> Path:
    return workflow.run_writer.layout.run_dir(run_id) / artifact_name


def _load_run_data(workflow: WriterInteractiveWorkflow, run_id: str, artifact_name: str) -> dict[str, Any]:
    path = _run_data_path(workflow, run_id, artifact_name)
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = raw.get("data") if isinstance(raw, dict) else raw
    return dict(payload) if isinstance(payload, dict) else {}


def load_writer_artifact_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    if path.suffix.lower() == ".json":
        try:
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            return {"path": str(path), "exists": True, "error": f"invalid json: {exc}"}
        payload = raw["data"] if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
        return {
            "path": str(path),
            "exists": True,
            "content": payload,
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path),
        "exists": True,
        "chars": len(text),
        "preview": text[:2048],
    }


def build_writer_artifact_review_payload(stage: str, artifact_path: str) -> dict[str, Any]:
    path = Path(artifact_path)
    payload = load_writer_artifact_payload(path)
    payload["stage"] = stage
    payload["display_policy"] = (
        "full_planning_artifact"
        if stage in {"batch_review", "chapter_review", "wait_length_review"}
        else "path_and_summary"
    )
    if stage == "wait_length_review":
        payload["prompt"] = "是否需要调整默认章节长度、重点章节或单章长度 override？"
    return payload


def build_writer_draft_review_payload(*, run_dir: Path, artifact_path: str, preview_chars: int = 1200) -> dict[str, Any]:
    draft_path = run_dir / "draft.md"
    draft_text = draft_path.read_text(encoding="utf-8", errors="replace") if draft_path.exists() else ""
    decision_path = Path(artifact_path)
    decision_payload = load_writer_artifact_payload(decision_path)
    return {
        "stage": "wait_chapter_acceptance",
        "draft_path": str(draft_path),
        "draft_exists": draft_path.exists(),
        "draft_chars": len(draft_text),
        "draft_preview": draft_text[:preview_chars],
        "generation_review_decision_path": str(decision_path),
        "generation_review_decision": decision_payload.get("content", {}),
        "display_policy": "path_metadata_and_short_preview",
    }


def _first_chapter_id_from_length_plan(workflow: WriterInteractiveWorkflow, run_id: str) -> str:
    plan = _load_run_data(workflow, run_id, "chapter_length_plan.json")
    for item in plan.get("budgets") or []:
        if isinstance(item, dict) and str(item.get("chapter_id") or "").strip():
            return str(item["chapter_id"])
    raise ValueError("chapter_length_plan.json 中没有可用的章节预算")


def _maybe_confirm_pending_review(
    *,
    workflow: WriterInteractiveWorkflow,
    run_id: str,
    stage: str,
    confirm_review: Callable[[str, str], bool],
    on_confirm: Callable[[], dict[str, Any] | dict[str, str]],
) -> dict[str, Any] | None:
    checkpoint = workflow.resume_from_latest_checkpoint(run_id=run_id)
    if not checkpoint or checkpoint.get("stage") != stage:
        return None
    artifact_path = str(checkpoint.get("artifact_path") or workflow.run_writer.layout.run_dir(run_id))
    if not confirm_review(stage, artifact_path):
        return {"status": "waiting_for_review", "checkpoint": checkpoint}
    return dict(on_confirm())


def run_writer_guided_flow(
    *,
    workflow: WriterInteractiveWorkflow,
    conn: sqlite3.Connection,
    run_id: str,
    book_id: str,
    product_mode: str,
    intent_payload: Mapping[str, Any],
    user_world_notes: str = "",
    target_chapter_count: int = 3,
    chapter_count: int = 3,
    chapter_id: str = "",
    default_target_chars: int | None = None,
    chapter_length_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    allow_incomplete_modeling: bool = False,
    confirm_review: Callable[[str, str], bool] | None = None,
    accept_chapter_review: Callable[[str], str] | None = None,
    execute_chapter: bool = False,
) -> dict[str, Any]:
    init_creative_kb_schema(conn)
    mode = product_mode.strip().lower()
    confirm_review = confirm_review or (lambda _stage, _artifact_path: True)
    state = workflow.load_workflow_state(run_id=run_id) or workflow.initialize_workflow(
        run_id=run_id,
        book_id=book_id,
        product_mode=mode,
    )
    modeling_status = workflow.planner.check_modeling_status(conn, book_id=book_id)
    modeling_advisories = _modeling_advisory_steps(modeling_status)
    missing_guidance = _modeling_missing_guidance([*modeling_status.missing_modeling_steps, *modeling_advisories])
    result: dict[str, Any] = {
        "run_id": run_id,
        "book_id": book_id,
        "product_mode": mode,
        "workflow_state": state,
        "modeling_status": modeling_status.to_dict(),
        "modeling_advisories": modeling_advisories,
        "missing_guidance": missing_guidance,
        "artifacts": {},
    }
    if not modeling_status.ready_for_continuation and not allow_incomplete_modeling:
        result["status"] = "blocked_by_modeling"
        return result

    result["planning"] = workflow.prepare_planning(
        conn,
        run_id=run_id,
        book_id=book_id,
        product_mode=mode,
        intent_payload=intent_payload,
        user_world_notes=user_world_notes,
    )
    if result["planning"].get("stage") in {"outline_research_user_input", "outline_research_blocked"}:
        return {
            **result,
            "status": result["planning"].get("status"),
            "checkpoint": result["planning"].get("checkpoint"),
            "stage": result["planning"].get("stage"),
        }
    pending = _maybe_confirm_pending_review(
        workflow=workflow,
        run_id=run_id,
        stage="freeze_a_review",
        confirm_review=confirm_review,
        on_confirm=lambda: workflow.continue_after_planning_review(run_id=run_id),
    )
    if pending and pending.get("status") == "waiting_for_review":
        return {**result, **pending}
    result["freeze_a"] = pending or {}

    result["batch_plan"] = workflow.prepare_batch_plan(
        conn,
        run_id=run_id,
        book_id=book_id,
        product_mode=mode,
        target_chapter_count=target_chapter_count,
    )
    pending = _maybe_confirm_pending_review(
        workflow=workflow,
        run_id=run_id,
        stage="batch_review",
        confirm_review=confirm_review,
        on_confirm=lambda: workflow.continue_after_batch_review(run_id=run_id),
    )
    if pending and pending.get("status") == "waiting_for_review":
        return {**result, **pending}
    result["freeze_b"] = pending or {}

    result["chapter_package"] = workflow.prepare_chapter_package(
        run_id=run_id,
        book_id=book_id,
        product_mode=mode,
        chapter_count=chapter_count,
    )
    pending = _maybe_confirm_pending_review(
        workflow=workflow,
        run_id=run_id,
        stage="chapter_review",
        confirm_review=confirm_review,
        on_confirm=lambda: workflow.continue_after_chapter_review(run_id=run_id),
    )
    if pending and pending.get("status") == "waiting_for_review":
        return {**result, **pending}
    result["freeze_c"] = pending or {}

    if default_target_chars is not None or chapter_length_overrides:
        result["length_review_override"] = workflow.continue_after_length_review(
            run_id=run_id,
            default_target_chars=default_target_chars,
            chapter_overrides=chapter_length_overrides or {},
        )

    pending = _maybe_confirm_pending_review(
        workflow=workflow,
        run_id=run_id,
        stage="wait_length_review",
        confirm_review=confirm_review,
        on_confirm=lambda: workflow.continue_after_length_review(
            run_id=run_id,
            default_target_chars=default_target_chars,
            chapter_overrides=chapter_length_overrides or {},
        ),
    )
    if pending and pending.get("status") == "waiting_for_review":
        return {**result, **pending}
    result["length_review"] = pending or {}

    current_chapter_id = chapter_id.strip() or _first_chapter_id_from_length_plan(workflow, run_id)
    result["current_chapter_id"] = current_chapter_id
    result["execution_input"] = workflow.prepare_execution(
        conn,
        run_id=run_id,
        book_id=book_id,
        chapter_id=current_chapter_id,
        product_mode=mode,
    )
    pending = _maybe_confirm_pending_review(
        workflow=workflow,
        run_id=run_id,
        stage="freeze_d_review",
        confirm_review=confirm_review,
        on_confirm=lambda: workflow.continue_after_execution_review(run_id=run_id),
    )
    if pending and pending.get("status") == "waiting_for_review":
        return {**result, **pending}
    if workflow.run_writer.get_freeze_record(run_id, "freeze_d") is None:
        result["freeze_d"] = workflow.continue_after_execution_review(run_id=run_id)
    else:
        result["freeze_d"] = pending or {}

    if execute_chapter:
        result["execution_result"] = workflow.execute_current_chapter(
            conn,
            run_id=run_id,
            book_id=book_id,
            product_mode=mode,
        )
        acceptance_checkpoint = workflow.resume_from_latest_checkpoint(run_id=run_id)
        if acceptance_checkpoint and acceptance_checkpoint.get("stage") == "wait_chapter_acceptance":
            artifact_path = str(acceptance_checkpoint.get("artifact_path") or _run_data_path(workflow, run_id, "generation_review_decision.json"))
            review_status = accept_chapter_review(artifact_path).strip().lower() if accept_chapter_review else ""
            if review_status not in {"accepted", "revise_length", "replan_chapter", "discarded"}:
                return {
                    **result,
                    "status": "waiting_for_review",
                    "checkpoint": acceptance_checkpoint,
                    "workflow_state": workflow.load_workflow_state(run_id=run_id) or {},
                }
            _write_writer_review_decision_status(
                workflow=workflow,
                run_id=run_id,
                status=review_status,
            )
            acceptance_outcome = workflow.continue_after_chapter_acceptance(run_id=run_id)
            result["chapter_acceptance"] = acceptance_outcome
            if acceptance_outcome.get("stage") in {"wait_chapter_acceptance", "wait_length_review", "wait_chapter_review"}:
                return {
                    **result,
                    "status": "waiting_for_review",
                    "checkpoint": acceptance_outcome,
                    "workflow_state": workflow.load_workflow_state(run_id=run_id) or {},
                }
        writeback_checkpoint = workflow.resume_from_latest_checkpoint(run_id=run_id)
        if writeback_checkpoint and writeback_checkpoint.get("stage") == "writeback_review":
            artifact_path = str(writeback_checkpoint.get("artifact_path") or _run_data_path(workflow, run_id, "continuity_report.json"))
            if not confirm_review("writeback_review", artifact_path):
                return {
                    **result,
                    "status": "waiting_for_review",
                    "checkpoint": writeback_checkpoint,
                    "workflow_state": workflow.load_workflow_state(run_id=run_id) or {},
                }
            result["writeback"] = workflow.approve_writeback(conn, run_id=run_id, book_id=book_id)
    result["status"] = "ready_for_execution" if not execute_chapter else "chapter_executed"
    result["workflow_state"] = workflow.load_workflow_state(run_id=run_id) or {}
    result["artifacts"] = {
        "run_dir": str(workflow.run_writer.layout.run_dir(run_id)),
        "chapter_length_plan": str(_run_data_path(workflow, run_id, "chapter_length_plan.json")),
        "chapter_execution_input": str(_run_data_path(workflow, run_id, "chapter_execution_input.json")),
    }
    return result


def redact_writer_result_for_terminal(payload: object) -> object:
    return _redact_writer_payload(payload)


def _redact_writer_payload(payload: object) -> object:
    large_text_keys = {"draft_md", "draft_text", "final_md", "content", "summary_md"}
    if isinstance(payload, Mapping):
        redacted: dict[str, object] = {}
        for key, value in payload.items():
            key_text = str(key)
            if key_text in large_text_keys and isinstance(value, str):
                redacted[key_text] = {
                    "omitted_from_terminal": True,
                    "chars": len(value),
                    "reason": "正文已写入 runs 目录，避免占满 terminal 缓存。",
                }
                continue
            redacted[key_text] = _redact_writer_payload(value)
        return redacted
    if isinstance(payload, list):
        return [_redact_writer_payload(item) for item in payload]
    return payload


def _write_writer_review_decision_status(
    *,
    workflow: WriterInteractiveWorkflow,
    run_id: str,
    status: str,
) -> None:
    _write_writer_review_decision_payload(
        workflow=workflow,
        run_id=run_id,
        payload={"status": status},
    )


def _write_writer_review_decision_payload(
    *,
    workflow: WriterInteractiveWorkflow,
    run_id: str,
    payload: Mapping[str, Any],
) -> None:
    state = workflow.load_workflow_state(run_id=run_id) or {}
    existing = _load_run_data_if_exists(workflow, run_id, "generation_review_decision.json")
    status = str(payload.get("status") or existing.get("status") or "").strip().lower()
    chapter_id = str(existing.get("chapter_id") or state.get("current_chapter_id") or "").strip()
    draft_id = str(existing.get("draft_id") or state.get("current_draft_id") or "draft-001").strip()
    decision_id = str(existing.get("decision_id") or f"review-{chapter_id or 'chapter'}-{draft_id}").strip()
    next_checkpoint_by_status = {
        "accepted": "freeze_e",
        "revise_length": "wait_length_review",
        "replan_chapter": "wait_chapter_review",
        "discarded": "halted",
    }
    reason_by_status = {
        "accepted": "approved",
        "revise_length": "length_or_pacing_revision_requested",
        "replan_chapter": "chapter_plan_revision_requested",
        "discarded": "discarded_by_user",
    }
    reason_code = str(payload.get("reason_code") or reason_by_status.get(status, status))
    feedback_text = str(payload.get("feedback_text") or existing.get("feedback_text") or "")
    length_plan_update = payload.get("length_plan_update") or existing.get("length_plan_update")
    if status == "revise_length" and not isinstance(length_plan_update, Mapping):
        length_plan_update = {
            "schema_version": "1.0",
            "update_id": f"length-update-{decision_id}",
            "decision_id": decision_id,
            "chapter_id": chapter_id,
            "target_chars": 1,
            "min_chars": 1,
            "max_chars": 1,
            "reason_code": reason_code,
            "feedback_text": feedback_text or "用户要求调整字数或节奏后重写。",
        }
    if status == "revise_length" and isinstance(length_plan_update, Mapping):
        length_plan_update = {
            "schema_version": "1.0",
            "update_id": f"length-update-{decision_id}",
            "decision_id": decision_id,
            "chapter_id": chapter_id,
            "reason_code": reason_code,
            "feedback_text": feedback_text,
            "preserve_story_direction": True,
            **dict(length_plan_update),
        }
    chapter_replan_request = payload.get("chapter_replan_request") or existing.get("chapter_replan_request")
    if status == "replan_chapter" and not isinstance(chapter_replan_request, Mapping):
        chapter_replan_request = {
            "schema_version": "1.0",
            "request_id": f"chapter-replan-{decision_id}",
            "decision_id": decision_id,
            "chapter_id": chapter_id,
            "reason_code": reason_code,
            "feedback_text": feedback_text or "用户要求修改章节梗概后重写。",
            "must_preserve": [],
            "must_change": [feedback_text or "调整章节目标、事件安排或展开方式"],
            "forbidden_carryover": [],
        }
    if status == "replan_chapter" and isinstance(chapter_replan_request, Mapping):
        must_change = chapter_replan_request.get("must_change")
        chapter_replan_request = {
            "schema_version": "1.0",
            "request_id": f"chapter-replan-{decision_id}",
            "decision_id": decision_id,
            "chapter_id": chapter_id,
            "reason_code": reason_code,
            "feedback_text": feedback_text,
            "replan_scope": "current_chapter",
            "must_preserve": [],
            "must_change": [feedback_text or "调整章节目标、事件安排或展开方式"]
            if not isinstance(must_change, list) or not must_change
            else must_change,
            "forbidden_carryover": [],
            **dict(chapter_replan_request),
        }
    workflow.run_writer.write_generation_review_decision(
        run_id,
        {
            **existing,
            "schema_version": "1.0",
            "decision_id": decision_id,
            "run_id": run_id,
            "chapter_id": chapter_id,
            "draft_id": draft_id,
            "status": status,
            "reason_code": reason_code,
            "feedback_text": feedback_text,
            "next_action_checkpoint": next_checkpoint_by_status.get(status, ""),
            "length_plan_update": length_plan_update if status == "revise_length" else None,
            "chapter_replan_request": chapter_replan_request if status == "replan_chapter" else None,
            "reviewer_type": "user",
        },
    )


def _load_run_data_if_exists(workflow: WriterInteractiveWorkflow, run_id: str, artifact_name: str) -> dict[str, Any]:
    path = _run_data_path(workflow, run_id, artifact_name)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = raw.get("data") if isinstance(raw, dict) else raw
    return dict(payload) if isinstance(payload, dict) else {}


def _print_writer_panel(title: str, payload: Mapping[str, Any]) -> None:
    print("")
    print(title)
    print(json.dumps(dict(payload), ensure_ascii=False, indent=2))


def _print_optional_modeling_panels(*, repo_root: Path, book_id: str) -> None:
    source_arc_path = repo_root / ".memory" / "arcs" / f"{book_id}.source_arc_map.json"
    _print_writer_panel("源作品篇章地图面板：", _source_arc_panel_payload(source_arc_path))
    pattern_paths = [
        repo_root / ".memory" / "structure_patterns" / f"{book_id}.narrative_structure_patterns.json",
        repo_root / ".memory" / "structure_patterns" / f"{book_id}.arc_pattern_cards.json",
        repo_root / ".memory" / "arcs" / f"{book_id}.narrative_structure_patterns.json",
        repo_root / ".memory" / "arcs" / f"{book_id}.arc_pattern_cards.json",
    ]
    _print_writer_panel("全局结构模式面板：", _structure_pattern_panel_payload(pattern_paths))


def _source_arc_panel_payload(path: Path) -> dict[str, Any]:
    payload = load_writer_artifact_payload(path)
    content = payload.get("content")
    if not isinstance(content, Mapping):
        return {"path": str(path), "ready": False, "message": "SourceArcMap 尚未生成。"}
    arcs = [item for item in content.get("arcs", []) if isinstance(item, Mapping)]
    return {
        "path": str(path),
        "ready": True,
        "source_summary_count": content.get("source_summary_count", 0),
        "used_compression": bool(content.get("used_compression")),
        "arc_count": len(arcs),
        "arcs": [
            {
                "source_arc_id": arc.get("source_arc_id", ""),
                "source_arc_title": arc.get("source_arc_title", ""),
                "range": f"{arc.get('start_document_title_index', '')}-{arc.get('end_document_title_index', '')}",
                "source_arc_role": arc.get("source_arc_role", ""),
                "pacing_notes": arc.get("pacing_notes", ""),
            }
            for arc in arcs[:12]
        ],
    }


def _structure_pattern_panel_payload(paths: list[Path]) -> dict[str, Any]:
    ready_paths = [path for path in paths if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip()]
    if not ready_paths:
        return {
            "ready": False,
            "expected_paths": [str(path) for path in paths],
            "message": "NarrativeStructurePattern / ArcPatternCard 尚未生成。",
        }
    previews = []
    for path in ready_paths:
        payload = load_writer_artifact_payload(path)
        previews.append(
            {
                "path": str(path),
                "content": payload.get("content", payload.get("preview", "")),
            }
        )
    return {"ready": True, "patterns": previews}


def _prompt_writer_review(stage: str, artifact_path: str) -> bool:
    status = STATUS_PRESENTER.present(stage, technical_details={"artifact_path": artifact_path})
    summary = ARTIFACT_PRESENTER.summarize(artifact_path, stage=stage)
    print("")
    print(f"当前步骤：{status.step}")
    if status.message:
        print(f"说明：{status.message}")
    print(f"请审阅/修改后保存：{artifact_path}")
    print("提示：保存只是保留修改，保存不等于确认；确认后才会进入下一步。")
    print(summary.render())
    if stage == "wait_length_review":
        _maybe_prompt_length_plan_adjustment(Path(artifact_path))
    print(f"确认后：{status.next_action}")
    return _prompt_yes_no("是否确认并继续", default=True)


def _prompt_writer_acceptance_review(workflow: WriterInteractiveWorkflow, run_id: str, artifact_path: str) -> str:
    run_dir = workflow.run_writer.layout.run_dir(run_id)
    draft_path = run_dir / "draft.md"
    draft_text = draft_path.read_text(encoding="utf-8", errors="replace") if draft_path.exists() else ""
    panel = DecisionPanel.chapter_acceptance(
        draft_path=str(draft_path),
        draft_chars=len(draft_text),
        target_chars=0,
    )
    print("")
    print(panel.render())
    _print_writer_panel(
        "草稿预览：",
        build_writer_draft_review_payload(run_dir=run_dir, artifact_path=artifact_path),
    )
    choice = _prompt_choice(
        "请审核本章草稿",
        choices={
            "accept": "接受并进入写回确认",
            "revise": "调整字数后重写",
            "replan": "修改章节梗概后重写",
            "discard": "作废草稿",
            "wait": "暂不决定",
        },
        default="wait",
    )
    if choice == "accept":
        return "accepted"
    if choice == "revise":
        return "revise_length"
    if choice == "replan":
        return "replan_chapter"
    if choice == "discard":
        return "discarded"
    return ""


def _print_public_writer_result(result: Mapping[str, Any]) -> None:
    checkpoint = result.get("checkpoint")
    workflow_state = result.get("workflow_state")
    internal_status = str(result.get("status") or "")
    if isinstance(checkpoint, Mapping):
        status = STATUS_PRESENTER.present_checkpoint(checkpoint)
    elif isinstance(workflow_state, Mapping):
        status = STATUS_PRESENTER.present(str(workflow_state.get("current_stage") or internal_status))
    else:
        status = STATUS_PRESENTER.present(internal_status)
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), Mapping) else {}
    print("")
    print("Writer 工作台状态：")
    print(
        json.dumps(
            {
                "当前流程": status.flow,
                "当前步骤": status.step,
                "说明": status.message,
                "下一步": status.next_action,
                "run_id": result.get("run_id", ""),
                "book_id": result.get("book_id", ""),
                "artifacts": artifacts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _maybe_prompt_length_plan_adjustment(path: Path) -> None:
    if not path.exists():
        return
    if not _prompt_yes_no("是否需要调整章节长度计划", default=False):
        return
    default_target = _prompt_optional_int("请输入新的默认目标字数（回车跳过）", default=None, min_value=1)
    chapter_overrides: dict[str, dict[str, int]] = {}
    while _prompt_yes_no("是否添加/修改单章长度 override", default=False):
        chapter_id = _prompt_text("请输入 chapter_id")
        target = _prompt_optional_int("请输入本章 target_chars", default=None, min_value=1)
        if target is None:
            print("未输入 target_chars，本章 override 已跳过。")
            continue
        min_chars = _prompt_optional_int("请输入本章 min_chars", default=max(1, int(target * 0.85)), min_value=1)
        max_chars = _prompt_optional_int("请输入本章 max_chars", default=max(target, int(target * 1.15)), min_value=1)
        chapter_overrides[chapter_id] = {
            "target_chars": target,
            "min_chars": int(min_chars or target),
            "max_chars": int(max_chars or target),
        }
    if default_target is None and not chapter_overrides:
        print("未输入调整项，保持原长度计划。")
        return
    apply_length_plan_overrides_to_file(
        path,
        default_target_chars=default_target,
        chapter_overrides=chapter_overrides,
    )
    print(f"已更新长度计划：{path}")


def apply_length_plan_overrides_to_file(
    path: Path,
    *,
    default_target_chars: int | None = None,
    chapter_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    wrapped = isinstance(raw, dict) and isinstance(raw.get("data"), dict)
    plan = dict(raw["data"] if wrapped else raw)
    normalized_overrides = {
        str(chapter_id).strip(): dict(value)
        for chapter_id, value in (chapter_overrides or {}).items()
        if str(chapter_id).strip() and isinstance(value, Mapping)
    }
    default_bounds: tuple[int, int, int] | None = None
    if default_target_chars is not None:
        default_bounds = _length_bounds_from_target(default_target_chars)
        plan["default_target_chars"], plan["default_min_chars"], plan["default_max_chars"] = default_bounds
    budgets: list[dict[str, Any]] = []
    seen_chapters: set[str] = set()
    for item in plan.get("budgets") or []:
        if not isinstance(item, Mapping):
            continue
        budget = dict(item)
        chapter_id = str(budget.get("chapter_id") or "").strip()
        if not chapter_id:
            continue
        seen_chapters.add(chapter_id)
        override = normalized_overrides.get(chapter_id)
        if override is not None:
            target, min_chars, max_chars = _length_bounds_from_mapping(override)
            budget["target_chars"] = target
            budget["min_chars"] = min_chars
            budget["max_chars"] = max_chars
            budget["is_focus_chapter"] = True
            budget["focus_reason"] = str(override.get("reason") or budget.get("focus_reason") or "interactive_override")
        elif default_bounds is not None:
            budget["target_chars"], budget["min_chars"], budget["max_chars"] = default_bounds
        budgets.append(budget)
    for chapter_id, override in normalized_overrides.items():
        if chapter_id in seen_chapters:
            continue
        target, min_chars, max_chars = _length_bounds_from_mapping(override)
        budgets.append(
            {
                "chapter_id": chapter_id,
                "target_chars": target,
                "min_chars": min_chars,
                "max_chars": max_chars,
                "is_focus_chapter": True,
                "focus_reason": str(override.get("reason") or "interactive_override"),
                "expansion_notes": [str(override.get("note") or "用户在 wait_length_review 直接新增本章长度 override。")],
                "source_chapter_target_word_count": 0,
            }
        )
    plan["budgets"] = budgets
    notes = [str(item) for item in (plan.get("review_notes") or []) if str(item).strip()]
    note = "已在 wait_length_review 通过交互输入更新章节长度计划。"
    if note not in notes:
        notes.append(note)
    plan["review_notes"] = notes
    if wrapped:
        raw["data"] = plan
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def _length_bounds_from_mapping(value: Mapping[str, Any]) -> tuple[int, int, int]:
    target = int(value.get("target_chars") or value.get("target") or 0)
    if target <= 0:
        raise ValueError("target_chars must be positive")
    min_chars = int(value.get("min_chars") or value.get("min") or max(1, target * 85 // 100))
    max_chars = int(value.get("max_chars") or value.get("max") or max(target, target * 115 // 100))
    if not min_chars <= target <= max_chars:
        raise ValueError("min_chars must be <= target_chars <= max_chars")
    return target, min_chars, max_chars


def _length_bounds_from_target(target: int) -> tuple[int, int, int]:
    target_chars = int(target)
    if target_chars <= 0:
        raise ValueError("target_chars must be positive")
    return target_chars, max(1, target_chars * 85 // 100), max(target_chars, target_chars * 115 // 100)


def _collect_writer_intent_payload() -> tuple[dict[str, object], str]:
    intent_payload: dict[str, object] = {
        "major_characters": _prompt_list("请输入主要角色（逗号分隔）", default=""),
        "desired_actions": _prompt_list("请输入续写动作目标（逗号分隔）", default=""),
        "avoidances": _prompt_list("请输入避免项（逗号分隔）", default=""),
        "preferred_outcome": _prompt_text("请输入期望结果", default=""),
        "notes": _prompt_text("请输入补充说明", default=""),
    }
    user_world_notes = _prompt_text("请输入世界观补充（可留空）", default="")
    return intent_payload, user_world_notes


def _run_writer_workflow_interactive(*, repo_root: Path) -> int:
    dry_run = _prompt_yes_no("是否以 dry-run 运行 Writer 工作流", default=True)
    api_key = None if dry_run else _resolve_api_key()
    task_name = _prompt_text("请输入 Writer 工作流任务名称")
    book_id = _slugify_task_name(task_name)
    db_path = resolve_db_path(repo_root, str(repo_root / ".indexes" / f"{book_id}.db"))
    runs_dir = repo_root / "runs" / "writer"
    product_mode = _prompt_choice(
        "请选择产品模式",
        choices={"assist": "Assist Mode", "batch": "Batch Mode", "auto_novel": "Auto Novel Mode"},
        default="assist",
    )
    action = _prompt_choice(
        "请选择 Writer 工作流动作",
        choices={
            "guided": "连续向导",
            "initialize": "初始化",
            "prepare_planning": "生成全书续写规划",
            "resume": "恢复最近检查点",
            "prepare_chapter_length_plan": "准备章节长度计划",
            "continue_after_length_review": "确认章节长度计划",
            "prepare_execution": "整理本章写作材料",
        },
        default="guided",
    )
    run_id = _prompt_text("请输入 run_id（留空则自动生成）", default=uuid.uuid4().hex)
    reset_writer_memory = _prompt_yes_no("是否重置 Writer 独立 memory 副本（会丢弃 Writer 已回写内容）", default=False)
    db_path = resolve_writer_memory_db_path(
        repo_root=repo_root,
        book_id=book_id,
        reset=reset_writer_memory,
    )
    print(f"Writer memory sqlite: {db_path}")
    db, workflow = build_writer_workflow(
        repo_root=repo_root,
        db_path=db_path,
        runs_dir=runs_dir,
        dry_run=dry_run,
        api_key=api_key,
    )
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        if action == "guided":
            workflow.initialize_workflow(run_id=run_id, book_id=book_id, product_mode=product_mode)
            modeling_status = workflow.planner.check_modeling_status(conn, book_id=book_id)
            _print_writer_panel("建模状态面板：", modeling_status.to_dict())
            _print_optional_modeling_panels(repo_root=repo_root, book_id=book_id)
            modeling_advisories = _modeling_advisory_steps(modeling_status)
            if modeling_advisories:
                _print_writer_panel(
                    "可选建模建议：",
                    {
                        "missing_optional_steps": modeling_advisories,
                        "guidance": _modeling_missing_guidance(modeling_advisories),
                    },
                )
            if not modeling_status.ready_for_continuation:
                _print_writer_panel(
                    "缺失引导：",
                    {
                        "missing_steps": modeling_status.missing_modeling_steps,
                        "guidance": _modeling_missing_guidance(modeling_status.missing_modeling_steps),
                    },
                )
                if not _prompt_yes_no("建模未完成，是否仍要继续生成规划草案", default=False):
                    conn.commit()
                    return 0
            intent_payload, user_world_notes = _collect_writer_intent_payload()
            target_chapter_count = _prompt_optional_int("请输入当前批次计划章节数", default=3, min_value=1) or 3
            chapter_count = _prompt_optional_int("请输入本次生成章节梗概数", default=target_chapter_count, min_value=1) or target_chapter_count
            chapter_id = _prompt_text("请输入要写作的 chapter_id（留空则使用长度计划第一章）", default="")
            execute_chapter = _prompt_yes_no("本章写作材料确认后是否立即执行当前章正文", default=False)
            result = run_writer_guided_flow(
                workflow=workflow,
                conn=conn,
                run_id=run_id,
                book_id=book_id,
                product_mode=product_mode,
                intent_payload=intent_payload,
                user_world_notes=user_world_notes,
                target_chapter_count=target_chapter_count,
                chapter_count=chapter_count,
                chapter_id=chapter_id,
                allow_incomplete_modeling=True,
                confirm_review=_prompt_writer_review,
                accept_chapter_review=lambda artifact_path: _prompt_writer_acceptance_review(
                    workflow,
                    run_id,
                    artifact_path,
                ),
                execute_chapter=execute_chapter,
            )
            conn.commit()
            _print_public_writer_result(result)
            return 0
        payload: dict[str, object] = {}
        if action == "prepare_planning":
            payload = {
                "intent_payload": {
                    "major_characters": _prompt_text("请输入主要角色（逗号分隔）", default="").split(","),
                    "desired_actions": _prompt_text("请输入续写动作目标（逗号分隔）", default="").split(","),
                    "avoidances": _prompt_text("请输入避免项（逗号分隔）", default="").split(","),
                    "preferred_outcome": _prompt_text("请输入期望结果", default=""),
                    "notes": _prompt_text("请输入补充说明", default=""),
                },
                "user_world_notes": _prompt_text("请输入世界观补充（可留空）", default=""),
            }
        if action == "prepare_execution":
            payload = {
                "chapter_id": _prompt_text("请输入 chapter_id"),
            }
        result = run_writer_workflow_action(
            workflow=workflow,
            conn=conn,
            action=action,
            run_id=run_id,
            book_id=book_id,
            product_mode=product_mode,
            payload=payload,
        )
        conn.commit()
    _print_public_writer_result(
        {
            "run_id": run_id,
            "book_id": book_id,
            "status": result.get("status", ""),
            "workflow_state": result if isinstance(result, Mapping) else {},
            "artifacts": {},
        }
    )
    return 0


def _build_segmentation_config(
    *,
    book_id: str,
    source_path: Path,
    db_path: Path,
    api_key: str,
    max_total_chars: int | None,
    resume_from_checkpoint: bool,
    thinking: str | None = "enabled",
    reasoning_effort: str | None = "high",
    include_reasoning_content: bool = True,
) -> SegmentationAgentConfig:
    model_config: dict[str, object] = {
        "model_type": "OpenAIModel",
        "model_name": DEFAULT_PIPELINE_SEGMENT_MODEL_NAME,
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "api_key": api_key,
        "api_key_env": "DEEPSEEK_API_KEY",
        "thinking": thinking,
        "include_reasoning_content": include_reasoning_content,
        "max_output_tokens": 12288,
    }
    if reasoning_effort is not None:
        model_config["reasoning_effort"] = reasoning_effort
    return SegmentationAgentConfig.from_mapping(
        {
            "book": {
                "book_id": book_id,
                "source_root": source_path.as_posix(),
            },
            "model": model_config,
            "read_strategy": {"max_total_chars": max_total_chars},
            "storage": {"sqlite_path": db_path.as_posix()},
            "runtime": {"dry_run": False, "resume_from_checkpoint": resume_from_checkpoint},
        }
    )


def _build_close_read_config(
    *,
    book_id: str,
    db_path: Path,
    api_key: str,
    debug_path: Path,
    max_chapters: int | None,
    document_chars_budget: int = DEFAULT_CLOSE_READ_DOC_BUDGET,
    thinking: str | None = "enabled",
    reasoning_effort: str | None = "high",
    include_reasoning_content: bool = True,
) -> CloseReadAgentConfig:
    close_config = CloseReadAgentConfig(book_id=book_id, sqlite_path=db_path.as_posix())
    close_config.model.model_type = "OpenAIModel"
    close_config.model.model_name = DEFAULT_PIPELINE_CLOSE_READ_MODEL_NAME
    close_config.model.provider = "openai_compatible"
    close_config.model.base_url = "https://api.deepseek.com"
    close_config.model.api_key = api_key
    close_config.model.api_key_env = "DEEPSEEK_API_KEY"
    close_config.model.thinking = thinking
    close_config.model.reasoning_effort = reasoning_effort
    close_config.model.include_reasoning_content = include_reasoning_content
    close_config.runtime.debug_markdown_path = debug_path.as_posix()
    close_config.runtime.max_chapters = max_chapters
    close_config.runtime.document_chars_budget = int(document_chars_budget)
    return close_config


def _build_creative_kb_facade(
    *,
    api_key: str,
    model_name: str = DEFAULT_PIPELINE_CREATIVE_KB_MODEL_NAME,
    thinking: str | None = "enabled",
    reasoning_effort: str | None = "high",
    include_reasoning_content: bool = True,
) -> CreativeKnowledgeBaseFacade:
    fragment_cards_repo = FragmentCardsRepo()
    builder = FragmentCardBuilderService(
        model_client=JsonModelClient(
            ModelSettings(
                model_type="OpenAIModel",
                model_name=model_name,
                provider="openai_compatible",
                base_url="https://api.deepseek.com",
                api_key=api_key,
                api_key_env="DEEPSEEK_API_KEY",
                max_output_tokens=8192,
                retry_without_thinking_on_failure=True,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                include_reasoning_content=include_reasoning_content,
            )
        ),
        fragment_cards_repo=fragment_cards_repo,
    )
    return CreativeKnowledgeBaseFacade(
        fragment_card_builder_service=builder,
        fragment_cards_repo=fragment_cards_repo,
    )


def _build_creative_kb(
    *,
    db_path: Path,
    book_id: str,
    api_key: str,
    creative_kb_facade: CreativeKnowledgeBaseFacade | None = None,
    max_doc_id: int | None = None,
    thinking: str | None = "enabled",
    reasoning_effort: str | None = "high",
    include_reasoning_content: bool = True,
) -> CreativeKBBuildResult:
    db = NovelAgentDB(db_path)
    facade = creative_kb_facade or _build_creative_kb_facade(
        api_key=api_key,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        include_reasoning_content=include_reasoning_content,
    )

    def print_progress(event: dict[str, Any]) -> None:
        print(json.dumps({"creative_kb_progress": event}, ensure_ascii=False))

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        documents = DocumentsRepo().fetch_after_doc_id(conn, book_id=book_id)
        if max_doc_id is not None:
            documents = [document for document in documents if document.doc_id <= int(max_doc_id)]
        try:
            result = facade.build_creative_kb(
                conn,
                documents=documents,
                commit_batch_size=DEFAULT_PIPELINE_CREATIVE_KB_COMMIT_BATCH_SIZE,
                progress_callback=print_progress,
            )
        except TypeError:
            result = facade.build_creative_kb(conn, documents=documents)
        conn.commit()
    return result


def _build_source_arc_map(
    *,
    repo_root: Path,
    db_path: Path,
    book_id: str,
    api_key: str | None = None,
) -> dict[str, object]:
    db = NovelAgentDB(db_path)
    normalized_api_key = str(api_key or "").strip()
    should_use_model = bool(normalized_api_key) and normalized_api_key not in {"unused", "test-key"}
    model_client = (
        JsonModelClient(
            ModelSettings(
                model_type="OpenAIModel",
                model_name=DEFAULT_PIPELINE_CLOSE_READ_MODEL_NAME,
                provider="openai_compatible",
                base_url="https://api.deepseek.com",
                api_key=normalized_api_key,
                api_key_env="DEEPSEEK_API_KEY",
                thinking="enabled",
                reasoning_effort="high",
                include_reasoning_content=True,
                max_output_tokens=12288,
            )
        )
        if should_use_model
        else None
    )
    service = SourceArcMappingService(repo_root=repo_root, model_client=model_client)
    with db.connect() as conn:
        db.init_schema(conn)
        summaries = service.load_chapter_plot_summaries(conn, book_id=book_id)
        if not summaries:
            return {
                "status": "skipped",
                "reason": "no_chapter_summaries",
                "book_id": book_id,
            }
        source_arc_map = service.build_from_chapters(conn, book_id=book_id)
        json_path, markdown_path = service.ensure_paths(book_id)
    return {
        "status": "built",
        "book_id": book_id,
        "source_summary_count": source_arc_map.source_summary_count,
        "used_compression": source_arc_map.used_compression,
        "arc_count": len(source_arc_map.arcs),
        "json_path": json_path.as_posix(),
        "markdown_path": markdown_path.as_posix(),
    }


def _run_pipeline(
    *,
    repo_root: Path,
    book_id: str,
    source_path: Path,
    db_path: Path,
    debug_path: Path,
    api_key: str,
    run_mode: str,
    max_read_kb: int | None,
    max_close_batches: int | None,
    segment_step_kb: int,
    close_step_batches: int,
    build_creative_kb: bool,
    close_document_chars_budget: int = DEFAULT_CLOSE_READ_DOC_BUDGET,
    should_stop: Callable[[], bool] | None = None,
    thinking: str | None = "enabled",
    reasoning_effort: str | None = "high",
    include_reasoning_content: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, object]:
    should_stop = should_stop or (lambda: False)
    remaining_read_chars = _kb_to_chars(max_read_kb)
    remaining_close_batches = max_close_batches
    total_inserted_documents = 0
    total_segmentation_batches = 0
    total_close_read_batches = 0
    creative_kb_runs: list[dict[str, object]] = []
    iteration = 0
    segmentation_resume = run_mode == "resume"
    progress_snapshot = _load_progress_snapshot(db_path=db_path, book_id=book_id)

    def print_prompt_progress(event: dict[str, Any]) -> None:
        if progress_callback is not None:
            progress_callback(event)
        print(json.dumps({"prompt_timing": event}, ensure_ascii=False))

    while True:
        if should_stop():
            break
        if remaining_read_chars is not None and remaining_read_chars <= 0 and (
            remaining_close_batches is None or remaining_close_batches <= 0
        ):
            break
        if remaining_read_chars is None and remaining_close_batches is not None and remaining_close_batches <= 0:
            break

        iteration += 1
        iteration_made_progress = False
        seg_result = None
        close_result = None
        segmentation_delta_chars = 0

        if remaining_read_chars is None or remaining_read_chars > 0:
            segmentation_chars_before = int(progress_snapshot["segmentation_chars"])
            seg_round_chars = _min_positive(remaining_read_chars, segment_step_kb * 1024)
            seg_config = _build_segmentation_config(
                book_id=book_id,
                source_path=source_path,
                db_path=db_path,
                api_key=api_key,
                max_total_chars=seg_round_chars,
                resume_from_checkpoint=segmentation_resume,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                include_reasoning_content=include_reasoning_content,
            )
            seg_result = SegmentationRunner(
                repo_root=repo_root,
                db_path=db_path,
                config=seg_config,
                progress_callback=print_prompt_progress,
            ).run()
            total_inserted_documents += seg_result.inserted_documents
            total_segmentation_batches += seg_result.batch_count
            segmentation_resume = True
            segmentation_after = _load_progress_snapshot(db_path=db_path, book_id=book_id)
            segmentation_delta_chars = max(
                0,
                int(segmentation_after["segmentation_chars"]) - segmentation_chars_before,
            )
            if remaining_read_chars is not None and seg_round_chars is not None:
                remaining_read_chars = max(0, remaining_read_chars - segmentation_delta_chars)
            iteration_made_progress = (
                iteration_made_progress
                or segmentation_delta_chars > 0
                or seg_result.inserted_documents > 0
            )

        if remaining_close_batches is None or remaining_close_batches > 0:
            if should_stop():
                break
            close_round_batches = _min_positive(remaining_close_batches, close_step_batches)
            close_config = _build_close_read_config(
                book_id=book_id,
                db_path=db_path,
                api_key=api_key,
                debug_path=debug_path,
                max_chapters=close_round_batches,
                document_chars_budget=close_document_chars_budget,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                include_reasoning_content=include_reasoning_content,
            )
            close_result = CloseReadRunner(
                repo_root=repo_root,
                db_path=db_path,
                config=close_config,
                progress_callback=print_prompt_progress,
                should_stop=should_stop,
            ).run()
            total_close_read_batches += close_result.processed_batches
            if remaining_close_batches is not None:
                remaining_close_batches = max(0, remaining_close_batches - close_result.processed_batches)
            iteration_made_progress = iteration_made_progress or close_result.processed_batches > 0

            if build_creative_kb and close_result.processed_batches > 0 and not should_stop():
                close_progress = _load_progress_snapshot(db_path=db_path, book_id=book_id)
                max_doc_id = close_progress.get("last_completed_doc_id")
                if isinstance(max_doc_id, int) and max_doc_id > 0:
                    result = _build_creative_kb(
                        db_path=db_path,
                        book_id=book_id,
                        api_key=api_key,
                        max_doc_id=max_doc_id,
                        thinking=thinking,
                        reasoning_effort=reasoning_effort,
                        include_reasoning_content=include_reasoning_content,
                    )
                    creative_kb_payload = result.to_dict()
                    creative_kb_payload["max_doc_id"] = max_doc_id
                    creative_kb_runs.append(creative_kb_payload)
                    print(
                        json.dumps(
                            {
                                "creative_kb": creative_kb_payload,
                            },
                            ensure_ascii=False,
                        )
                    )

        progress_snapshot = _load_progress_snapshot(db_path=db_path, book_id=book_id)
        close_read_lag_chars = max(
            0,
            int(progress_snapshot["segmentation_chars"]) - int(progress_snapshot["close_read_chars"]),
        )
        seg_batches = seg_result.batch_count if seg_result is not None else 0
        close_batches = close_result.processed_batches if close_result is not None else 0
        print(
            json.dumps(
                {
                    "iteration": iteration,
                    "segmentation_batches": seg_batches,
                    "close_read_batches": close_batches,
                    "segment_step_kb": segment_step_kb,
                    "close_step_batches": close_step_batches,
                    "remaining_read_kb": None if remaining_read_chars is None else round(remaining_read_chars / 1024, 2),
                    "remaining_close_batches": remaining_close_batches,
                    "segmentation_delta_kb": _chars_to_kb(segmentation_delta_chars),
                    "segmentation_delta_chars": segmentation_delta_chars,
                    "segmentation_progress_kb": progress_snapshot["segmentation_kb"],
                    "close_read_progress_kb": progress_snapshot["close_read_kb"],
                    "segmentation_progress_chars": progress_snapshot["segmentation_chars"],
                    "close_read_progress_chars": progress_snapshot["close_read_chars"],
                    "close_read_lag_kb": _chars_to_kb(close_read_lag_chars),
                    "close_read_lag_chars": close_read_lag_chars,
                    "close_read_batch_metrics": close_result.batch_metrics if close_result is not None else [],
                },
                ensure_ascii=False,
            )
        )

        if not iteration_made_progress:
            break
        if remaining_read_chars is not None and remaining_read_chars <= 0 and (
            remaining_close_batches is None or remaining_close_batches <= 0
        ):
            break
        if remaining_read_chars is None and remaining_close_batches is not None and remaining_close_batches <= 0:
            break

    source_arc_map_result = (
        {"status": "skipped", "reason": "cancelled"}
        if should_stop()
        else _build_source_arc_map(
            repo_root=repo_root,
            db_path=db_path,
            book_id=book_id,
            api_key=api_key,
        )
    )
    print(
        json.dumps(
            {
                "source_arc_map": source_arc_map_result,
            },
            ensure_ascii=False,
        )
    )

    creative_kb_result: dict[str, object] | None = creative_kb_runs[-1] if creative_kb_runs else None
    if build_creative_kb and not creative_kb_runs and not should_stop():
        max_doc_id = progress_snapshot.get("last_completed_doc_id")
        result = _build_creative_kb(
            db_path=db_path,
            book_id=book_id,
            api_key=api_key,
            max_doc_id=max_doc_id if isinstance(max_doc_id, int) else None,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            include_reasoning_content=include_reasoning_content,
        )
        creative_kb_result = result.to_dict()
        if isinstance(max_doc_id, int):
            creative_kb_result["max_doc_id"] = max_doc_id
        creative_kb_runs.append(creative_kb_result)
        print(
            json.dumps(
                {
                    "creative_kb": creative_kb_result,
                },
                ensure_ascii=False,
            )
        )

    return {
        "inserted_documents": total_inserted_documents,
        "segmentation_batches": total_segmentation_batches,
        "close_read_batches": total_close_read_batches,
        "source_arc_map": source_arc_map_result,
        "creative_kb": creative_kb_result,
        "creative_kb_runs": creative_kb_runs,
        "segmentation_progress_kb": progress_snapshot["segmentation_kb"],
        "close_read_progress_kb": progress_snapshot["close_read_kb"],
        "segmentation_progress_chars": progress_snapshot["segmentation_chars"],
        "close_read_progress_chars": progress_snapshot["close_read_chars"],
        "close_read_lag_kb": _chars_to_kb(
            max(0, int(progress_snapshot["segmentation_chars"]) - int(progress_snapshot["close_read_chars"]))
        ),
        "close_read_lag_chars": max(
            0,
            int(progress_snapshot["segmentation_chars"]) - int(progress_snapshot["close_read_chars"]),
        ),
        "debug_markdown": debug_path.as_posix(),
    }


def main() -> int:
    repo_root = resolve_repo_root()
    print("小说续写工作台")
    print("统一入口可承载粗读、精读、Creative KB、Writer 与恢复流程。")
    entry_mode = _prompt_choice(
        "请选择下一步动作",
        choices={
            "resume": "继续上次会话",
            "read": "导入/粗读原文",
            "close-read": "运行精读建模",
            "status": "查看建模状态",
            "kb": "构建 Creative KB",
            "writer": "开始或恢复 Writer",
            "pipeline": "兼容 smoke：旧粗读/精读 pipeline",
        },
        default="read",
    )
    if entry_mode in {"writer", "resume"}:
        return _run_writer_workflow_interactive(repo_root=repo_root)
    if entry_mode == "status":
        task_name = _prompt_text("请输入当前项目/任务名称")
        book_id = _slugify_task_name(task_name)
        app = TuiApp(repo_root=repo_root, config=TuiSessionConfig(project=task_name, book_id=book_id))
        snapshot = app.facade.modeling_status(book_id=book_id)
        print("")
        print("建模状态：")
        print(
            STATUS_PRESENTER.present_sidebar(
                project=task_name,
                internal_status="memory ready" if snapshot.close_read_ready else "documents indexed",
                modeling_ready=snapshot.ready_map(),
            )
        )
        return 0

    api_key = _resolve_api_key()
    task_name = _prompt_text("请输入当前执行的任务名称（用于区分不同小说任务）")
    book_id = _slugify_task_name(task_name)
    db_path = resolve_db_path(repo_root, str(repo_root / ".indexes" / f"{book_id}.db"))
    if entry_mode == "kb":
        if not db_path.exists():
            raise SystemExit(f"构建 Creative KB 需要已有粗读数据库，但当前不存在：{db_path}")
        kb_result = _build_creative_kb(db_path=db_path, book_id=book_id, api_key=api_key)
        print("Creative KB 已可用：")
        print(json.dumps(kb_result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    source_root = _prompt_text("请输入需要阅读的小说路径（文件或目录）")
    source_path = Path(source_root).expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(f"小说路径不存在: {source_path}")

    debug_path = (repo_root / ".memory" / "debug" / f"{book_id}.sqlite.md").resolve()
    run_mode = _prompt_choice(
        "请选择本轮运行模式",
        choices={"fresh": "从头开始", "resume": "从 checkpoint 继续"},
        default="fresh",
    )
    max_read_kb = _prompt_optional_int(
        "请输入本轮粗读最多额外读取多少 KB（resume 模式下表示在 checkpoint 之后再读多少 KB）",
        default=50,
        min_value=1,
    )
    max_close_batches = _prompt_optional_int(
        "请输入本轮精读最多处理多少轮（按章节 batch 计）",
        default=12,
        min_value=1,
    )
    segment_step_kb = _prompt_optional_int(
        "请输入每轮粗读步长 KB（建议 16-32，默认 32）",
        default=DEFAULT_PIPELINE_SEGMENT_STEP_KB,
        min_value=1,
    )
    close_step_batches = _prompt_optional_int(
        "请输入每轮精读步长 batch（建议 1，默认 1）",
        default=DEFAULT_PIPELINE_CLOSE_STEP_BATCHES,
        min_value=1,
    )
    build_creative_kb = _prompt_yes_no("是否在粗读/精读后构建 Creative KB 桥段知识库", default=True)

    if run_mode == "fresh" and db_path.exists():
        db_path.unlink()
    if run_mode == "resume" and not db_path.exists():
        raise SystemExit(f"resume 模式需要已有数据库，但当前不存在：{db_path}")

    initial_progress = _load_progress_snapshot(db_path=db_path, book_id=book_id)

    print("")
    print("即将开始执行：")
    print(json.dumps(
        {
            "task_name": task_name,
            "book_id": book_id,
            "source_root": source_path.as_posix(),
            "execution_mode": "pipeline",
            "run_mode": run_mode,
            "max_read_kb": max_read_kb,
            "max_close_batches": max_close_batches,
            "segment_step_kb": segment_step_kb,
            "close_step_batches": close_step_batches,
            "build_creative_kb": build_creative_kb,
            "db_path": db_path.as_posix(),
            "debug_markdown": debug_path.as_posix(),
            "current_progress": {
                "segmentation_kb": initial_progress["segmentation_kb"],
                "close_read_kb": initial_progress["close_read_kb"],
                "segmentation_chars": initial_progress["segmentation_chars"],
                "close_read_chars": initial_progress["close_read_chars"],
            },
        },
        ensure_ascii=False,
        indent=2,
    ))
    print("")

    result = _run_pipeline(
        repo_root=repo_root,
        book_id=book_id,
        source_path=source_path,
        db_path=db_path,
        debug_path=debug_path,
        api_key=api_key,
        run_mode=run_mode,
        max_read_kb=max_read_kb,
        max_close_batches=max_close_batches,
        segment_step_kb=segment_step_kb or DEFAULT_PIPELINE_SEGMENT_STEP_KB,
        close_step_batches=close_step_batches or DEFAULT_PIPELINE_CLOSE_STEP_BATCHES,
        build_creative_kb=build_creative_kb,
    )

    print("")
    print("执行完成：")
    print(
        json.dumps(
            {
                "book_id": book_id,
                "db_path": db_path.as_posix(),
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if entry_mode != "pipeline":
        follow_up = _prompt_choice(
            "本轮建模完成后，你想继续做什么",
            choices={
                "status": "查看建模状态",
                "kb": "构建 Creative KB",
                "writer": "开始续写",
                "finish": "稍后继续",
            },
            default="finish",
        )
        if follow_up == "status":
            app = TuiApp(repo_root=repo_root, config=TuiSessionConfig(project=task_name, book_id=book_id))
            snapshot = app.facade.modeling_status(book_id=book_id, db_path=db_path)
            print(
                STATUS_PRESENTER.present_sidebar(
                    project=task_name,
                    internal_status="memory ready" if snapshot.close_read_ready else "documents indexed",
                    modeling_ready=snapshot.ready_map(),
                )
            )
        elif follow_up == "kb" and not build_creative_kb:
            kb_result = _build_creative_kb(db_path=db_path, book_id=book_id, api_key=api_key)
            print("Creative KB 已可用：")
            print(json.dumps(kb_result.to_dict(), ensure_ascii=False, indent=2))
        elif follow_up == "writer":
            print("精读记忆已可用，接下来进入 Writer。")
            return _run_writer_workflow_interactive(repo_root=repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
