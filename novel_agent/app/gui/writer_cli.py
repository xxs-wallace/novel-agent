from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_agent.app.cli import WriterStatusPresenter
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.run_interactive import (
    _slugify_task_name,
    build_writer_workflow,
    resolve_writer_memory_db_path,
    run_writer_guided_flow,
    run_writer_workflow_action,
)


STATUS_PRESENTER = WriterStatusPresenter()


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    repo_root = Path(str(payload["repo_root"])).expanduser().resolve()
    task_name = str(payload["task_name"]).strip()
    book_id = _slugify_task_name(task_name)
    run_id = str(payload.get("run_id") or uuid.uuid4().hex).strip()
    product_mode = str(payload.get("product_mode") or "assist")
    action = str(payload.get("action") or "guided")
    dry_run = bool(payload.get("dry_run", True))
    api_key = str(payload.get("api_key") or "").strip() or None
    db_path = resolve_writer_memory_db_path(
        repo_root=repo_root,
        book_id=book_id,
        reset=bool(payload.get("reset_writer_memory", False)),
    )
    print(f"Writer memory sqlite: {db_path}")
    runs_dir = repo_root / "runs" / "writer"
    chapter_id = str(payload.get("chapter_id") or "").strip()
    mapped_chapter_id = _map_chapter_id_alias(
        runs_dir=runs_dir,
        run_id=run_id,
        chapter_id=chapter_id,
        chapter_count=int(payload.get("chapter_count") or 3),
    )
    if action == "prepare_execution" and not mapped_chapter_id:
        mapped_chapter_id = _first_available_chapter_id(runs_dir=runs_dir, run_id=run_id)
    if mapped_chapter_id != chapter_id:
        print(f"chapter_id 已映射：{chapter_id or '<留空>'} -> {mapped_chapter_id or '<自动选择第一章>'}")

    try:
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
                result = run_writer_guided_flow(
                    workflow=workflow,
                    conn=conn,
                    run_id=run_id,
                    book_id=book_id,
                    product_mode=product_mode,
                    intent_payload=_dict_payload(payload.get("intent_payload")),
                    user_world_notes=str(payload.get("user_world_notes") or ""),
                    target_chapter_count=int(payload.get("target_chapter_count") or 3),
                    chapter_count=int(payload.get("chapter_count") or 3),
                    chapter_id=mapped_chapter_id,
                    allow_incomplete_modeling=bool(payload.get("allow_incomplete_modeling", True)),
                    execute_chapter=bool(payload.get("execute_chapter", False)),
                )
            elif action in {"accept_chapter", "revise_chapter_length", "replan_chapter", "discard_chapter"}:
                status_by_action = {
                    "accept_chapter": "accepted",
                    "revise_chapter_length": "revise_length",
                    "replan_chapter": "replan_chapter",
                    "discard_chapter": "discarded",
                }
                _write_review_decision(
                    workflow=workflow,
                    run_id=run_id,
                    status=status_by_action[action],
                )
                result = workflow.continue_after_chapter_acceptance(run_id=run_id)
            else:
                result = run_writer_workflow_action(
                    workflow=workflow,
                    conn=conn,
                    action=action,
                    run_id=run_id,
                    book_id=book_id,
                    product_mode=product_mode,
                    payload=_action_payload(payload, action, chapter_id=mapped_chapter_id),
                )
            conn.commit()
    except ValueError as exc:
        if "chapter_id not found in frozen package" not in str(exc):
            raise
        print("Writer 参数错误：chapter_id 必须来自已冻结的 ChapterPackage。")
        print(f"你填写的是：{chapter_id}")
        available_ids = _available_chapter_ids(runs_dir=runs_dir, run_id=run_id)
        if available_ids:
            print("当前可用 chapter_id：")
            for available_id in available_ids:
                print(f"- {available_id}")
        else:
            print("当前还没有可读取的章节包；guided 模式请把 chapter_id 留空，让系统自动使用第一章。")
        return 2

    _print_public_result(result=result, run_id=run_id, book_id=book_id)
    return 0


def _dict_payload(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _action_payload(payload: dict[str, Any], action: str, *, chapter_id: str) -> dict[str, object]:
    if action == "prepare_planning":
        return {
            "intent_payload": _dict_payload(payload.get("intent_payload")),
            "user_world_notes": str(payload.get("user_world_notes") or ""),
        }
    if action == "prepare_batch_plan":
        return {"target_chapter_count": int(payload.get("target_chapter_count") or 3)}
    if action == "prepare_chapter_package":
        return {"chapter_count": int(payload.get("chapter_count") or 3)}
    if action == "prepare_execution":
        return {"chapter_id": chapter_id}
    if action == "continue_after_length_review":
        return {
            "default_target_chars": payload.get("default_target_chars"),
            "chapter_overrides": payload.get("chapter_overrides") or {},
        }
    return {}


def _write_review_decision(*, workflow: object, run_id: str, status: str) -> None:
    run_writer = workflow.run_writer
    state = workflow.load_workflow_state(run_id=run_id) or {}
    existing = _load_run_json(run_writer.layout.run_dir(run_id) / "generation_review_decision.json")
    chapter_id = str(existing.get("chapter_id") or state.get("current_chapter_id") or "").strip()
    draft_id = str(existing.get("draft_id") or state.get("current_draft_id") or "draft-001").strip()
    decision_id = str(existing.get("decision_id") or f"review-{chapter_id or 'chapter'}-{draft_id}").strip()
    next_action_by_status = {
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
    length_plan_update = existing.get("length_plan_update")
    if status == "revise_length" and not isinstance(length_plan_update, dict):
        length_plan_update = {
            "schema_version": "1.0",
            "update_id": f"length-update-{decision_id}",
            "decision_id": decision_id,
            "chapter_id": chapter_id,
            "target_chars": 1,
            "min_chars": 1,
            "max_chars": 1,
            "reason_code": reason_by_status[status],
            "feedback_text": "用户要求调整字数或节奏后重写。",
        }
    chapter_replan_request = existing.get("chapter_replan_request")
    if status == "replan_chapter" and not isinstance(chapter_replan_request, dict):
        chapter_replan_request = {
            "schema_version": "1.0",
            "request_id": f"chapter-replan-{decision_id}",
            "decision_id": decision_id,
            "chapter_id": chapter_id,
            "reason_code": reason_by_status[status],
            "feedback_text": "用户要求修改章节梗概后重写。",
            "must_preserve": [],
            "must_change": [],
            "forbidden_carryover": [],
        }
    payload = {
        **existing,
        "schema_version": "1.0",
        "decision_id": decision_id,
        "run_id": run_id,
        "chapter_id": chapter_id,
        "draft_id": draft_id,
        "status": status,
        "reason_code": reason_by_status[status],
        "feedback_text": str(existing.get("feedback_text") or ""),
        "next_action_checkpoint": next_action_by_status[status],
        "length_plan_update": length_plan_update if status == "revise_length" else None,
        "chapter_replan_request": chapter_replan_request if status == "replan_chapter" else None,
        "reviewer_type": "user",
        "created_at": str(existing.get("created_at") or datetime.now(timezone.utc).isoformat()),
    }
    run_writer.write_generation_review_decision(run_id, payload)


def _print_public_result(*, result: dict[str, Any], run_id: str, book_id: str) -> None:
    checkpoint = result.get("checkpoint") if isinstance(result, dict) else None
    if isinstance(checkpoint, dict):
        view = STATUS_PRESENTER.present_checkpoint(checkpoint)
    else:
        view = STATUS_PRESENTER.present(str(result.get("stage") or result.get("status") or result.get("current_stage") or ""))
    payload = {
        "当前流程": view.flow,
        "当前步骤": view.step,
        "说明": view.message,
        "下一步": view.next_action,
        "run_id": run_id,
        "book_id": book_id,
    }
    artifact_path = ""
    if isinstance(checkpoint, dict):
        artifact_path = str(checkpoint.get("artifact_path") or "")
    elif isinstance(result, dict):
        artifact_path = str(result.get("artifact_path") or "")
    if artifact_path:
        payload["artifact_path"] = artifact_path
    print("Writer 工作台状态：")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_run_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = raw.get("data") if isinstance(raw, dict) else raw
    return dict(payload) if isinstance(payload, dict) else {}


def _map_chapter_id_alias(*, runs_dir: Path, run_id: str, chapter_id: str, chapter_count: int) -> str:
    if not chapter_id:
        return ""
    ordinal = _parse_chapter_ordinal(chapter_id)
    if ordinal is None:
        return chapter_id

    existing_ids = _available_chapter_ids(runs_dir=runs_dir, run_id=run_id)
    if 1 <= ordinal <= len(existing_ids):
        return existing_ids[ordinal - 1]
    if ordinal == 1:
        return ""
    return chapter_id


def _parse_chapter_ordinal(value: str) -> int | None:
    normalized = value.strip().lower().replace("chapter", "").replace("第", "").replace("章", "")
    normalized = normalized.strip()
    if normalized.isdecimal():
        return int(normalized)
    chinese_digits = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if normalized in chinese_digits:
        return chinese_digits[normalized]
    match = re.fullmatch(r"ch0*([1-9]\d*)", normalized)
    if match:
        return int(match.group(1))
    return None


def _available_chapter_ids(*, runs_dir: Path, run_id: str) -> list[str]:
    candidates = [
        runs_dir / run_id / "freezes" / "freeze_c" / "chapter_package.json",
        runs_dir / run_id / "chapter_package.json",
        runs_dir / run_id / "chapter_length_plan.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data = payload.get("data") if isinstance(payload, dict) else payload
        ids = _chapter_ids_from_payload(data)
        if ids:
            return ids
    return []


def _first_available_chapter_id(*, runs_dir: Path, run_id: str) -> str:
    available_ids = _available_chapter_ids(runs_dir=runs_dir, run_id=run_id)
    return available_ids[0] if available_ids else ""


def _chapter_ids_from_payload(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("chapters") or payload.get("budgets") or []
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict) and str(item.get("chapter_id") or "").strip():
            ids.append(str(item["chapter_id"]))
    return ids


if __name__ == "__main__":
    raise SystemExit(main())
