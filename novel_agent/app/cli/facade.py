from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ...schemas import RunConfig
from ..bootstrap import resolve_db_path
from ..constants import DEFAULT_CLOSE_READING_STAGE, DEFAULT_SEGMENTATION_STAGE
from ..query_close_read import CloseReadQueryService
from ..repos.creative_kb_storage import init_creative_kb_schema
from ..repos.db import NovelAgentDB
from ..services.paragraph_benchmark_service import ParagraphBenchmarkService
from ..services.smoke_benchmark_service import AgenticSmokeBenchmarkService
from ..runner.creative_kb_benchmark_runner import (
    CreativeKBBenchmarkRunConfig,
    CreativeKBBenchmarkRunner,
    CreativeKBBenchmarkSummaryPresenter,
)
from .events import RunEventStream


@dataclass(frozen=True, slots=True)
class ModelingStatusSnapshot:
    book_id: str
    documents_ready: bool
    close_read_ready: bool
    character_profiles_ready: bool
    world_summary_ready: bool
    story_outline_ready: bool
    creative_kb_ready: bool
    source_arc_map_ready: bool
    counts: dict[str, int]

    def ready_map(self) -> dict[str, bool]:
        return {
            "原文": self.documents_ready,
            "阅读记忆": self.close_read_ready,
            "人物档案": self.character_profiles_ready,
            "世界观": self.world_summary_ready,
            "故事大纲": self.story_outline_ready,
            "桥段 KB": self.creative_kb_ready,
            "源作品篇章地图": self.source_arc_map_ready,
        }


@dataclass(frozen=True, slots=True)
class TuiTaskSnapshot:
    book_id: str
    source_path: str = ""
    db_path: Path | None = None
    documents_count: int = 0
    chapters_count: int = 0
    max_doc_id: int = 0
    segmentation_completed_doc_id: int = 0
    close_read_completed_doc_id: int = 0

    @property
    def close_read_done(self) -> bool:
        return self.max_doc_id > 0 and self.close_read_completed_doc_id >= self.max_doc_id

    def render_status_line(self, *, active: bool = False) -> str:
        marker = "* " if active else "  "
        source = f" · source={self.source_path}" if self.source_path else ""
        close_status = "阅读完成" if self.close_read_done else f"阅读至 doc {self.close_read_completed_doc_id or 0}/{self.max_doc_id or 0}"
        return (
            f"{marker}{self.book_id} · documents={self.documents_count} · chapters={self.chapters_count} · "
            f"导入原文至 doc {self.segmentation_completed_doc_id or 0}/{self.max_doc_id or 0} · {close_status}{source}"
        )


class WorkflowFacade:
    """Thin boundary between the unified CLI and existing business runners."""

    def __init__(self, *, repo_root: Path, event_stream: RunEventStream | None = None) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.event_stream = event_stream or RunEventStream()

    def db_path_for_book(self, book_id: str) -> Path:
        return resolve_db_path(self.repo_root, str(self.repo_root / ".indexes" / f"{book_id}.db"))

    def ensure_task(self, *, book_id: str, source_path: str = "") -> TuiTaskSnapshot:
        normalized = self._normalize_task_id(book_id)
        tasks = self._load_task_registry()
        existing = dict(tasks.get(normalized, {})) if isinstance(tasks.get(normalized), dict) else {}
        if source_path.strip():
            existing["source_path"] = str(Path(source_path).expanduser())
        existing.setdefault("source_path", "")
        tasks[normalized] = existing
        self._save_task_registry(tasks)
        return self.task_snapshot(book_id=normalized)

    def task_snapshot(self, *, book_id: str) -> TuiTaskSnapshot:
        normalized = self._normalize_task_id(book_id)
        registry = self._load_task_registry()
        db_path = self.db_path_for_book(normalized)
        source_path = str((registry.get(normalized) or {}).get("source_path") or "")
        documents_count = 0
        chapters_count = 0
        max_doc_id = 0
        segmentation_completed_doc_id = 0
        close_read_completed_doc_id = 0
        if db_path.exists():
            db = NovelAgentDB(db_path)
            with db.connect() as conn:
                db.init_schema(conn)
                row = conn.execute(
                    "SELECT COUNT(*) AS count, COALESCE(MAX(doc_id), 0) AS max_doc_id FROM documents WHERE book_id = ?",
                    (normalized,),
                ).fetchone()
                if row:
                    documents_count = int(row["count"] or 0)
                    max_doc_id = int(row["max_doc_id"] or 0)
                row = conn.execute("SELECT COUNT(*) AS count FROM chapters WHERE book_id = ?", (normalized,)).fetchone()
                if row:
                    chapters_count = int(row["count"] or 0)
                source_row = conn.execute(
                    "SELECT source_path FROM documents WHERE book_id = ? AND source_path != '' ORDER BY doc_id LIMIT 1",
                    (normalized,),
                ).fetchone()
                if source_row and not source_path:
                    source_path = str(source_row["source_path"] or "")
                segmentation_completed_doc_id = self._segmentation_progress_doc_id(
                    conn,
                    book_id=normalized,
                    fallback_doc_id=max_doc_id,
                )
                close_read_completed_doc_id = self._last_completed_doc_id(
                    conn,
                    book_id=normalized,
                    agent_stage=DEFAULT_CLOSE_READING_STAGE,
                )
        return TuiTaskSnapshot(
            book_id=normalized,
            source_path=source_path,
            db_path=db_path,
            documents_count=documents_count,
            chapters_count=chapters_count,
            max_doc_id=max_doc_id,
            segmentation_completed_doc_id=segmentation_completed_doc_id,
            close_read_completed_doc_id=close_read_completed_doc_id,
        )

    def list_tasks(self) -> list[TuiTaskSnapshot]:
        task_ids = set(self._load_task_registry())
        indexes_dir = self.repo_root / ".indexes"
        if indexes_dir.exists():
            task_ids.update(path.stem for path in indexes_dir.glob("*.db"))
        return [self.task_snapshot(book_id=book_id) for book_id in sorted(task_ids)]

    def render_task_list(self, *, active_book_id: str = "") -> str:
        tasks = self.list_tasks()
        if not tasks:
            return "当前还没有任务。使用 /new-task <task_id> <source_path> 创建任务。"
        lines = ["当前任务："]
        lines.extend(
            f"{index:>2}. {task.render_status_line(active=task.book_id == active_book_id)}"
            for index, task in enumerate(tasks, start=1)
        )
        lines.append(
            "使用 /task <编号|task_id> 进入任务；使用 /new-task <task_id> <source_path> 创建任务；"
            "使用 /delete-task <编号|task_id> 预览清理。"
        )
        return "\n".join(lines)

    def delete_task(self, *, book_id: str, confirm: bool = False, include_runs: bool = False) -> dict[str, object]:
        normalized = self._normalize_task_id(book_id)
        tasks = self._load_task_registry()
        candidate_paths = self._task_artifact_paths(normalized, include_runs=include_runs)
        existing_paths = [path for path in candidate_paths if path.exists() or path.is_symlink()]
        if not confirm:
            return {
                "book_id": normalized,
                "confirmed": False,
                "registry_entry": normalized in tasks,
                "candidate_paths": [str(path) for path in existing_paths],
            }

        tasks.pop(normalized, None)
        self._save_task_registry(tasks)
        deleted_paths: list[str] = []
        errors: list[str] = []
        for path in existing_paths:
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                deleted_paths.append(str(path))
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        self.event_stream.emit(
            "系统",
            f"已删除任务 {normalized} 的本地建模产物",
            payload={"deleted_paths": deleted_paths, "errors": errors},
        )
        return {
            "book_id": normalized,
            "confirmed": True,
            "deleted_paths": deleted_paths,
            "errors": errors,
        }

    def reset_close_read_task(self, *, book_id: str) -> dict[str, object]:
        normalized = self._normalize_task_id(book_id)
        db_path = self.db_path_for_book(normalized)
        deleted = {
            "chapters": 0,
            "character_profiles": 0,
            "close_read_progress": 0,
            "documents_reset": 0,
            "files": 0,
        }
        if db_path.exists():
            db = NovelAgentDB(db_path)
            with db.connect() as conn:
                db.init_schema(conn)
                deleted["chapters"] = self._delete_count(conn, "chapters", book_id=normalized)
                deleted["character_profiles"] = self._delete_count(conn, "character_profiles", book_id=normalized)
                cursor = conn.execute(
                    "DELETE FROM reading_progress WHERE book_id = ? AND agent_stage = ?",
                    (normalized, DEFAULT_CLOSE_READING_STAGE),
                )
                deleted["close_read_progress"] = int(cursor.rowcount if cursor.rowcount >= 0 else 0)
                cursor = conn.execute(
                    """
                    UPDATE documents
                    SET character_keywords_json = '[]', content_tags_csv = '', updated_at = updated_at
                    WHERE book_id = ?
                    """,
                    (normalized,),
                )
                deleted["documents_reset"] = int(cursor.rowcount if cursor.rowcount >= 0 else 0)
                conn.commit()
        for path in self._close_read_artifact_paths(normalized):
            if path.exists():
                path.unlink()
                deleted["files"] = int(deleted["files"]) + 1
        self.event_stream.emit("系统", f"已清空任务 {normalized} 的阅读进度", payload=deleted)
        return {"book_id": normalized, "deleted": deleted}

    def modeling_status(self, *, book_id: str, db_path: Path | None = None) -> ModelingStatusSnapshot:
        db_path = db_path or self.db_path_for_book(book_id)
        counts = {
            "documents": 0,
            "chapters": 0,
            "character_profiles": 0,
            "fragment_cards": 0,
            "fragment_card_docs": 0,
            "fragment_clusters": 0,
        }
        if db_path.exists():
            db = NovelAgentDB(db_path)
            with db.connect() as conn:
                db.init_schema(conn)
                init_creative_kb_schema(conn)
                counts["documents"] = self._count(conn, "documents", book_id=book_id)
                counts["chapters"] = self._count(conn, "chapters", book_id=book_id)
                counts["character_profiles"] = self._count(conn, "character_profiles", book_id=book_id)
                counts["fragment_cards"] = self._count(conn, "fragment_cards")
                counts["fragment_card_docs"] = self._count_distinct(conn, "fragment_cards", "doc_id")
                counts["fragment_clusters"] = self._count(conn, "fragment_clusters")
        world_summary = self.repo_root / ".memory" / "world" / f"{book_id}.summary.md"
        world_markdown = self.repo_root / ".memory" / "world" / f"{book_id}.md"
        outline = self.repo_root / ".memory" / "outlines" / f"{book_id}.md"
        source_arc = self.repo_root / ".memory" / "arcs" / f"{book_id}.source_arc_map.json"
        return ModelingStatusSnapshot(
            book_id=book_id,
            documents_ready=counts["documents"] > 0,
            close_read_ready=counts["chapters"] > 0,
            character_profiles_ready=counts["character_profiles"] > 0,
            world_summary_ready=world_summary.exists() or world_markdown.exists(),
            story_outline_ready=outline.exists(),
            creative_kb_ready=counts["fragment_cards"] > 0,
            source_arc_map_ready=source_arc.exists(),
            counts=counts,
        )

    def query_close_read(
        self,
        *,
        book_id: str,
        query_type: str,
        character_name: str = "",
        document_title_index: int | None = None,
        doc_id: int | None = None,
        summary_scope: str = "all",
        output_format: str = "markdown",
    ) -> str:
        result = CloseReadQueryService(repo_root=self.repo_root).query(
            task_id=book_id,
            query_type=query_type,
            db_path=self.db_path_for_book(book_id),
            character_name=character_name,
            document_title_index=document_title_index,
            doc_id=doc_id,
            summary_scope=summary_scope,
            output_format=output_format,
        )
        return result.rendered

    def start_read_pipeline(
        self,
        *,
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
        close_document_chars_budget: int = 20000,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        from .. import run_interactive

        self.event_stream.emit("系统", "开始在统一工作台中运行导入原文/阅读")
        with self.event_stream.capture_stdout(ingest_progress=False):
            result = run_interactive._run_pipeline(  # noqa: SLF001 - facade intentionally delegates to legacy runner.
                repo_root=self.repo_root,
                book_id=book_id,
                source_path=source_path,
                db_path=db_path,
                debug_path=debug_path,
                api_key=api_key,
                run_mode=run_mode,
                max_read_kb=max_read_kb,
                max_close_batches=max_close_batches,
                segment_step_kb=segment_step_kb,
                close_step_batches=close_step_batches,
                build_creative_kb=build_creative_kb,
                close_document_chars_budget=close_document_chars_budget,
                should_stop=should_stop,
                progress_callback=self.event_stream.progress_callback,
            )
        self.event_stream.emit("系统", "导入原文/阅读本轮已完成", payload=result)
        return result

    def build_creative_kb(self, *, db_path: Path, book_id: str, api_key: str) -> dict[str, object]:
        from .. import run_interactive

        self.event_stream.emit("系统", "开始构建 Creative KB")
        with self.event_stream.capture_stdout(ingest_progress=False):
            result = run_interactive._build_creative_kb(  # noqa: SLF001
                db_path=db_path,
                book_id=book_id,
                api_key=api_key,
                progress_callback=self.event_stream.progress_callback,
            )
        payload = result.to_dict()
        self.event_stream.emit("系统", "Creative KB 已可用", payload=payload)
        return payload

    def start_writer(
        self,
        *,
        book_id: str,
        run_id: str | None = None,
        product_mode: str = "assist",
        dry_run: bool = True,
        api_key: str | None = None,
        intent_payload: Mapping[str, Any] | None = None,
        user_world_notes: str = "",
        target_chapter_count: int = 3,
        chapter_count: int = 3,
        allow_incomplete_modeling: bool = True,
    ) -> dict[str, Any]:
        from .. import run_interactive

        run_id = run_id or uuid.uuid4().hex
        db_path = run_interactive.resolve_writer_memory_db_path(
            repo_root=self.repo_root,
            book_id=book_id,
            reset=False,
        )
        db, workflow = run_interactive.build_writer_workflow(
            repo_root=self.repo_root,
            db_path=db_path,
            runs_dir=self.repo_root / "runs" / "writer",
            dry_run=dry_run,
            api_key=api_key,
        )
        self.event_stream.emit("系统", "开始 Writer 分层生成", payload={"run_id": run_id})
        with db.connect() as conn:
            db.init_schema(conn)
            init_creative_kb_schema(conn)
            result = run_interactive.run_writer_guided_flow(
                workflow=workflow,
                conn=conn,
                run_id=run_id,
                book_id=book_id,
                product_mode=product_mode,
                intent_payload=dict(intent_payload or {}),
                user_world_notes=user_world_notes,
                target_chapter_count=target_chapter_count,
                chapter_count=chapter_count,
                allow_incomplete_modeling=allow_incomplete_modeling,
                confirm_review=lambda _stage, _artifact_path: False,
            )
            conn.commit()
        self.event_stream.emit("系统", "Writer 已到达可审阅节点", payload={"run_id": run_id, "status": result.get("status")})
        return result

    def writer_action(
        self,
        *,
        book_id: str,
        run_id: str,
        action: str,
        product_mode: str = "assist",
        payload: dict[str, object] | None = None,
        dry_run: bool = True,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        from .. import run_interactive

        db_path = run_interactive.resolve_writer_memory_db_path(
            repo_root=self.repo_root,
            book_id=book_id,
            reset=False,
        )
        db, workflow = run_interactive.build_writer_workflow(
            repo_root=self.repo_root,
            db_path=db_path,
            runs_dir=self.repo_root / "runs" / "writer",
            dry_run=dry_run,
            api_key=api_key,
        )
        with db.connect() as conn:
            db.init_schema(conn)
            init_creative_kb_schema(conn)
            result = run_interactive.run_writer_workflow_action(
                workflow=workflow,
                conn=conn,
                action=action,
                run_id=run_id,
                book_id=book_id,
                product_mode=product_mode,
                payload=payload or {},
            )
            conn.commit()
        self.event_stream.emit("系统", "Writer 状态已更新", payload={"run_id": run_id, "action": action})
        return result

    def request_scoped_artifact_revision(
        self,
        *,
        book_id: str,
        run_id: str,
        user_feedback: str,
        current_review_state: str = "",
        target_artifact_path: str = "",
        product_mode: str = "assist",
        dry_run: bool = True,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, object] = {"user_feedback": user_feedback}
        if current_review_state:
            payload["target_stage"] = current_review_state
        if target_artifact_path:
            payload["target_artifact_path"] = target_artifact_path
        result = self.writer_action(
            book_id=book_id,
            run_id=run_id,
            action="request_scoped_artifact_revision",
            product_mode=product_mode,
            payload=payload,
            dry_run=dry_run,
            api_key=api_key,
        )
        self.event_stream.emit("系统", "已生成受控修订候选", payload={"run_id": run_id, "status": result.get("status")})
        return result

    def apply_scoped_artifact_revision(
        self,
        *,
        book_id: str,
        run_id: str,
        request_id: str,
        product_mode: str = "assist",
        dry_run: bool = True,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        result = self.writer_action(
            book_id=book_id,
            run_id=run_id,
            action="apply_scoped_artifact_revision",
            product_mode=product_mode,
            payload={"request_id": request_id},
            dry_run=dry_run,
            api_key=api_key,
        )
        self.event_stream.emit("系统", "已应用受控修订候选", payload={"run_id": run_id, "request_id": request_id})
        return result

    def run_paragraph_benchmark(
        self,
        *,
        source_path: Path,
        prefix_count: int,
        recent_window_size: int = 3,
        target_length_chars: int = 600,
        outline_path: Path | None = None,
        character_names: list[str] | str | None = None,
        use_real_model: bool = True,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        generation_config = (
            RunConfig(
                prompt=None,
                model_type="InferenceClientModel",
                model_id="Qwen/Qwen3-Next-80B-A3B-Thinking",
                provider=None,
                api_key=api_key,
                action_type="tool_calling",
                tools=[],
                imports=[],
                verbosity_level=1,
                dry_run=False,
            )
            if use_real_model
            else None
        )
        self.event_stream.emit(
            "系统",
            "开始运行最小续写 benchmark",
            payload={
                "source_path": str(source_path),
                "prefix_count": prefix_count,
                "recent_window_size": recent_window_size,
            },
        )
        result = ParagraphBenchmarkService().run(
            source_path=source_path,
            prefix_count=prefix_count,
            recent_window_size=recent_window_size,
            target_length_chars=target_length_chars,
            outline_path=outline_path,
            character_names=character_names,
            runs_dir=self.repo_root / "runs" / "paragraph_benchmark",
            generation_config=generation_config,
        )
        payload = {
            "run_id": result.run_id,
            "run_dir": result.run_dir,
            "source_path": result.sample.source_path,
            "prefix_count": result.sample.prefix_count,
            "target_segment_index": result.sample.target_segment_index,
            "generated_chars": len(result.generated_text),
            "reference_truth_chars": len(result.sample.reference_truth),
            "decision": result.reviewer_report.decision,
            "score": result.reviewer_report.score,
            "summary": result.reviewer_report.summary,
        }
        self.event_stream.emit("系统", "最小续写 benchmark 已完成", payload=payload)
        return payload

    def run_smoke_benchmark(
        self,
        *,
        target: str = "",
        source_path: Path | None = None,
        sample_path: Path | None = None,
        db_path: Path | None = None,
        use_real_model: bool = True,
        api_key: str | None = None,
        enable_outline_research_loop: bool = False,
        outline_research_author_brief: bool = False,
    ) -> dict[str, Any]:
        if not use_real_model:
            raise ValueError("端到端 Agentic benchmark 必须使用真实 LLM。")
        self.event_stream.emit(
            "系统",
            "开始运行端到端 Agentic smoke benchmark",
            payload={
                "target": target,
                "source_path": str(source_path or ""),
                "sample_path": str(sample_path or ""),
                "db_path": str(db_path or ""),
            },
        )
        if sample_path is not None or db_path is not None:
            raise ValueError("端到端 Agentic benchmark 不接受预构造 sample/db；请使用 longzu-32kb 或 --source。")
        agentic_service = AgenticSmokeBenchmarkService(repo_root=self.repo_root)
        if source_path is not None:
            result = agentic_service.run_from_source(
                source_path=source_path,
                api_key=api_key or "",
                runs_dir=self.repo_root / "runs" / "benchmarks",
                enable_outline_research_loop=enable_outline_research_loop,
                outline_research_author_brief=outline_research_author_brief,
                use_real_outline_research_reviewer=outline_research_author_brief,
            )
        elif target in {"", "longzu-32kb"}:
            result = agentic_service.run_longzu_32kb(
                api_key=api_key or "",
                runs_dir=self.repo_root / "runs" / "benchmarks",
                enable_outline_research_loop=enable_outline_research_loop,
                outline_research_author_brief=outline_research_author_brief,
                use_real_outline_research_reviewer=outline_research_author_brief,
            )
        elif target == "longzu-240kb" and outline_research_author_brief:
            result = agentic_service.run_from_source(
                source_path=self.repo_root / "novel_agent" / "tests" / "longzu_240kb.txt",
                api_key=api_key or "",
                runs_dir=self.repo_root / "runs" / "benchmarks",
                prefix_min_chars=120_000,
                reference_min_chars=120_000,
                max_read_kb=240,
                max_close_batches=48,
                enable_outline_research_loop=enable_outline_research_loop,
                outline_research_author_brief=True,
                use_real_outline_research_reviewer=True,
            )
        else:
            raise ValueError(f"未知 benchmark 目标：{target}")
        payload = result.to_dict()
        if outline_research_author_brief:
            payload["summary_text"] = (
                f"OutlineResearchReviewer：{result.reviewer_summary} ({result.reviewer_decision}, {result.reviewer_score:.2f})\n"
                f"flow_status：{result.outline_research_status}\n"
                f"artifact_dir：{result.outline_research_artifact_dir}\n"
                f"leakage_audit：{result.outline_research_leakage_audit_path}\n"
                f"major_failures：{', '.join(result.outline_research_major_failures or []) or 'none'}\n"
                f"next_steps：{'; '.join(result.outline_research_next_steps or [])}"
            )
        else:
            payload["summary_text"] = (
                f"梗概层 Reviewer：{result.synopsis_summary} ({result.synopsis_decision}, {result.synopsis_score:.2f})\n"
                f"扩写层 Reviewer：{result.expansion_summary} ({result.expansion_decision}, {result.expansion_score:.2f})\n"
                f"综合 Reviewer：{result.reviewer_summary} ({result.reviewer_decision}, {result.reviewer_score:.2f})\n"
                f"run_id：{result.run_id}\n"
                f"产物目录：{result.run_dir}\n"
                f"生成梗概：{result.generated_synopsis_path}\n"
                f"原文梗概：{result.reference_synopsis_path}\n"
                f"Writer 草稿：{result.draft_path}\n"
                f"Reference truth：{result.reference_truth_path}\n"
                f"生成字数：{result.generated_chars}\n"
                f"reference truth 字数：{result.reference_truth_chars}"
            )
        self.event_stream.emit("系统", "端到端 Agentic smoke benchmark 已完成", payload=payload)
        return payload

    def run_creative_kb_benchmark(
        self,
        *,
        target: str = "longzu-32kb",
        source_path: Path | None = None,
        run_id: str | None = None,
        artifact_dir: Path | None = None,
        case_count: int = 3,
        enable_writer_ab: bool = False,
        use_real_model: bool = True,
        dry_run_model: bool = False,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        self.event_stream.emit(
            "系统",
            "开始运行 Creative KB Benchmark",
            payload={
                "target": target,
                "source_path": str(source_path or ""),
                "run_id": run_id or "",
                "artifact_dir": str(artifact_dir or ""),
                "case_count": case_count,
                "enable_writer_ab": enable_writer_ab,
                "dry_run_model": dry_run_model,
            },
        )
        fixture = self._creative_kb_fixture_from_target(target)
        if source_path is not None:
            fixture = None
        runner = CreativeKBBenchmarkRunner(
            repo_root=self.repo_root,
            progress_callback=self.event_stream.progress_callback,
        )
        result = runner.run(
            CreativeKBBenchmarkRunConfig(
                source_path=source_path,
                fixture=fixture,
                run_id=run_id,
                artifact_dir=artifact_dir,
                case_count=case_count,
                enable_writer_ab=enable_writer_ab,
                use_real_model=use_real_model,
                dry_run_model=dry_run_model,
                api_key=api_key,
                api_key_env="DEEPSEEK_API_KEY",
            )
        )
        presenter = CreativeKBBenchmarkSummaryPresenter()
        payload = result.to_dict()
        payload["summary_text"] = presenter.to_text(result)
        payload["summary"] = str(result.retrieval_review_summary.get("summary") or "")
        payload["decision"] = str(result.retrieval_review_summary.get("decision") or "pending")
        payload["score"] = float(result.retrieval_review_summary.get("score") or 0.0)
        payload["run_dir"] = result.artifact_dir
        self.event_stream.emit("系统", "Creative KB Benchmark 已完成", payload=payload)
        return payload

    @staticmethod
    def _creative_kb_fixture_from_target(target: str) -> str:
        normalized = str(target or "longzu-32kb").strip()
        return {
            "longzu-32kb": "longzu_32kb",
            "longzu_32kb": "longzu_32kb",
            "longzu-96kb": "longzu_96kb",
            "longzu_96kb": "longzu_96kb",
        }.get(normalized, normalized)

    @staticmethod
    def _count(conn: sqlite3.Connection, table: str, *, book_id: str | None = None) -> int:
        if book_id is None:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        else:
            row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE book_id = ?", (book_id,)).fetchone()
        return int(row[0] or 0) if row is not None else 0

    @staticmethod
    def _count_distinct(conn: sqlite3.Connection, table: str, column: str) -> int:
        row = conn.execute(f"SELECT COUNT(DISTINCT {column}) FROM {table}").fetchone()
        return int(row[0] or 0) if row is not None else 0

    @staticmethod
    def _delete_count(conn: sqlite3.Connection, table: str, *, book_id: str) -> int:
        cursor = conn.execute(f"DELETE FROM {table} WHERE book_id = ?", (book_id,))
        return int(cursor.rowcount if cursor.rowcount >= 0 else 0)

    def _close_read_artifact_paths(self, book_id: str) -> list[Path]:
        return [
            self.repo_root / ".memory" / "world" / f"{book_id}.summary.md",
            self.repo_root / ".memory" / "world" / f"{book_id}.md",
            self.repo_root / ".memory" / "worlds" / f"{book_id}.world_summary.md",
            self.repo_root / ".memory" / "worlds" / f"{book_id}.world.md",
            self.repo_root / ".memory" / "outlines" / f"{book_id}.md",
            self.repo_root / ".memory" / "outlines" / f"{book_id}.outline.md",
            self.repo_root / ".memory" / "arcs" / f"{book_id}.source_arc_map.json",
            self.repo_root / ".memory" / "arcs" / f"{book_id}.source_arc_map.md",
        ]

    def _task_artifact_paths(self, book_id: str, *, include_runs: bool = False) -> list[Path]:
        paths: list[Path] = []
        index_paths = [
            self.repo_root / ".indexes" / f"{book_id}.db",
            self.repo_root / ".indexes" / f"{book_id}-writer.db",
            self.repo_root / ".indexes" / "writer" / f"{book_id}.db",
        ]
        for base_path in index_paths:
            paths.extend([base_path, Path(f"{base_path}-wal"), Path(f"{base_path}-shm")])

        paths.extend(self._close_read_artifact_paths(book_id))
        memory_dirs = [
            self.repo_root / ".memory" / "world",
            self.repo_root / ".memory" / "worlds",
            self.repo_root / ".memory" / "outlines",
            self.repo_root / ".memory" / "arcs",
            self.repo_root / ".memory" / "debug",
            self.repo_root / ".memory" / "review",
            self.repo_root / ".memory" / "structure_patterns",
        ]
        for directory in memory_dirs:
            if directory.exists():
                paths.extend(path for path in directory.glob(f"{book_id}.*") if path.is_file() or path.is_symlink())
        paths.append(self.repo_root / ".memory" / "writer" / book_id)
        if include_runs:
            paths.extend(
                [
                    self.repo_root / "runs" / "writer" / book_id,
                    self.repo_root / "runs" / "benchmarks" / book_id,
                    self.repo_root / "runs" / "creative_kb_benchmarks" / book_id,
                    self.repo_root / "runs" / "paragraph_benchmark" / book_id,
                ]
            )
            writer_root = self.repo_root / "runs" / "writer"
            if writer_root.exists():
                for state_path in writer_root.glob("*/workflow_state.json"):
                    try:
                        raw = json.loads(state_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    payload = raw.get("data") if isinstance(raw, dict) else raw
                    if isinstance(payload, dict) and str(payload.get("book_id") or "") == book_id:
                        paths.append(state_path.parent)
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            resolved = str(path)
            if resolved not in seen:
                seen.add(resolved)
                deduped.append(path)
        return deduped

    def _load_task_registry(self) -> dict[str, dict[str, str]]:
        path = self.repo_root / ".indexes" / "tasks.json"
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            self._normalize_task_id(key): dict(value)
            for key, value in payload.items()
            if isinstance(value, dict)
        }

    def _save_task_registry(self, tasks: Mapping[str, Mapping[str, str]]) -> None:
        path = self.repo_root / ".indexes" / "tasks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _normalize_task_id(book_id: str) -> str:
        normalized = str(book_id or "").strip()
        if not normalized:
            raise ValueError("task id 不能为空")
        return normalized

    @staticmethod
    def _last_completed_doc_id(conn: sqlite3.Connection, *, book_id: str, agent_stage: str) -> int:
        row = conn.execute(
            "SELECT last_completed_doc_id FROM reading_progress WHERE book_id = ? AND agent_stage = ?",
            (book_id, agent_stage),
        ).fetchone()
        return int(row["last_completed_doc_id"] or 0) if row else 0

    @staticmethod
    def _segmentation_progress_doc_id(conn: sqlite3.Connection, *, book_id: str, fallback_doc_id: int) -> int:
        row = conn.execute(
            """
            SELECT current_source_path, current_source_offset, last_completed_doc_id
            FROM reading_progress
            WHERE book_id = ? AND agent_stage = ?
            """,
            (book_id, DEFAULT_SEGMENTATION_STAGE),
        ).fetchone()
        if not row:
            return 0
        if row["last_completed_doc_id"] is not None:
            return int(row["last_completed_doc_id"] or 0)
        if row["current_source_path"] or row["current_source_offset"] is not None:
            return fallback_doc_id
        return 0
