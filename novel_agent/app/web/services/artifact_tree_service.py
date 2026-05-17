from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ...cli.facade import WorkflowFacade
from ...repos.db import NovelAgentDB
from ...run_interactive import resolve_writer_memory_db_path
from ..schemas import ArtifactTreeNode
from .artifact_ids import encode_artifact_id
from .web_session_service import WebSessionService


class ArtifactTreeService:
    """Builds user-facing artifact trees from DB rows, memory files and writer runs."""

    _PERSON_SECTIONS = (
        ("基本信息", "basic"),
        ("当前目标", "goals"),
        ("关系网络", "relationships"),
        ("性格与说话方式", "voice"),
        ("已知秘密", "secrets"),
        ("禁止误写点", "forbidden"),
        ("最近变化", "recent"),
    )

    _WRITER_ITEMS = (
        ("续写概览", "writer_run", "run_overview", "workflow_state.json"),
        ("写作目标", "writer_artifact", "continuation_intent", "continuation_intent.json"),
        ("大纲研究结果", "writer_stage", "outline_research", "sufficiency_decision.json"),
        ("问题集", "writer_artifact", "outline_questions", "outline_research_question_set.json"),
        ("大纲研究笔记", "writer_artifact", "planning_notebook", "planning_notebook.json"),
        ("检索轨迹", "writer_artifact", "research_trace", "outline_research_trace.json"),
        ("全书续写规划", "writer_artifact", "book_plan", "book_continuation_plan.json"),
        ("本批剧情大纲", "writer_artifact", "batch_plan", "batch_plan.json"),
        ("章节标题与梗概", "writer_artifact", "chapter_package", "chapter_package.json"),
        ("章节写作指导", "writer_artifact", "writing_guidance", "chapter_writing_guidance.json"),
        ("正文草稿", "draft", "draft", "draft.md"),
        ("验收决策", "writer_artifact", "generation_review", "generation_review_decision.json"),
        ("写回摘要", "writeback", "writeback", "memory_writeback.json"),
    )

    _WRITER_STAGE_ORDER = {
        "initialized": 0,
        "outline_research_user_input": 1,
        "outline_research_blocked": 1,
        "freeze_a_review": 2,
        "freeze_a": 3,
        "batch_review": 4,
        "freeze_b": 5,
        "chapter_review": 6,
        "wait_chapter_review": 6,
        "freeze_c": 7,
        "freeze_d": 8,
        "wait_chapter_acceptance": 9,
        "writeback_review": 10,
        "completed": 11,
    }

    def __init__(self, *, repo_root: Path, facade: WorkflowFacade | None = None) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.facade = facade or WorkflowFacade(repo_root=self.repo_root)

    def tree(self, *, task_id: str, surface: str) -> list[ArtifactTreeNode]:
        if surface == "close-read":
            return self.close_read_tree(task_id=task_id)
        if surface == "writer":
            return self.writer_tree(task_id=task_id)
        raise ValueError("surface must be close-read or writer")

    def close_read_tree(self, *, task_id: str) -> list[ArtifactTreeNode]:
        return [
            self._node(task_id=task_id, surface="close-read", label="总览", kind="overview", view_kind="overview"),
            self._chapters_node(task_id),
            self._people_node(task_id),
            self._node(task_id=task_id, surface="close-read", label="世界观", kind="world_item", view_kind="world"),
            self._node(task_id=task_id, surface="close-read", label="故事大纲", kind="outline", view_kind="outline"),
            self._node(task_id=task_id, surface="close-read", label="源作品篇章地图", kind="source_arc", view_kind="source_arc"),
        ]

    def writer_tree(self, *, task_id: str) -> list[ArtifactTreeNode]:
        runs = self._writer_runs(task_id)
        if not runs:
            return []
        nodes: list[ArtifactTreeNode] = []
        for index, (run_dir, state) in enumerate(runs, start=1):
            if not self._writer_run_has_user_artifacts(run_dir):
                continue
            children = self._writer_run_children(task_id=task_id, run_dir=run_dir, state=state)
            if not children:
                continue
            nodes.append(
                self._node(
                    task_id=task_id,
                    surface="writer",
                    label=self._writer_run_label(run_dir=run_dir, state=state, index=index),
                    kind="writer_run_group",
                    view_kind="run_overview",
                    path=run_dir / "workflow_state.json",
                    extra={"run_id": run_dir.name},
                    badge=self._writer_run_badge(state),
                    children=children,
                )
            )
        return nodes

    def _writer_run_children(self, *, task_id: str, run_dir: Path, state: Mapping[str, Any]) -> list[ArtifactTreeNode]:
        active_stage = self._active_writer_stage(state)
        nodes: list[ArtifactTreeNode] = []
        for label, node_kind, view_kind, filename in self._WRITER_ITEMS:
            path = run_dir / filename
            if not self._should_show_writer_item(view_kind=view_kind, path=path, active_stage=active_stage):
                continue
            badge = "已生成"
            nodes.append(
                self._node(
                    task_id=task_id,
                    surface="writer",
                    label=label,
                    kind=node_kind,
                    view_kind=view_kind,
                    path=path,
                    extra={"run_id": run_dir.name},
                    badge=badge,
                )
            )
        generated_chapters = self._writer_generated_chapter_nodes(task_id=task_id, run_id=run_dir.name)
        if generated_chapters:
            nodes.append(
                self._node(
                    task_id=task_id,
                    surface="writer",
                    label="已写回章节",
                    kind="writer_stage",
                    view_kind="generated_chapters",
                    extra={"run_id": run_dir.name},
                    badge=f"{len(generated_chapters)} 章",
                    children=generated_chapters,
                )
            )
        return nodes

    def _chapters_node(self, task_id: str) -> ArtifactTreeNode:
        children = [
            self._node(
                task_id=task_id,
                surface="close-read",
                label=f"{row.get('document_title_index')}. {row.get('chapter_title') or '未命名章节'}",
                kind="chapter",
                view_kind="chapter",
                extra={"document_title_index": row.get("document_title_index")},
            )
            for row in self._chapter_rows(task_id)
        ]
        return self._node(
            task_id=task_id,
            surface="close-read",
            label="章节摘要",
            kind="chapter",
            view_kind="chapters",
            children=children,
        )

    def _people_node(self, task_id: str) -> ArtifactTreeNode:
        grouped: dict[str, list[ArtifactTreeNode]] = {"主角": [], "配角": [], "反派": [], "未归类": []}
        for row in self._person_rows(task_id):
            name = str(row.get("canonical_name") or "未命名人物")
            group = self._person_group(row)
            person_node = self._node(
                task_id=task_id,
                surface="close-read",
                label=name,
                kind="person",
                view_kind="person",
                extra={"name": name},
                children=[
                    self._node(
                        task_id=task_id,
                        surface="close-read",
                        label=label,
                        kind="person_section",
                        view_kind="person_section",
                        extra={"name": name, "section": section},
                    )
                    for label, section in self._PERSON_SECTIONS
                ],
            )
            grouped[group].append(person_node)
        children = [
            self._node(
                task_id=task_id,
                surface="close-read",
                label=group,
                kind="person",
                view_kind="person_group",
                extra={"group": group},
                children=items,
            )
            for group, items in grouped.items()
            if items or group == "未归类"
        ]
        return self._node(
            task_id=task_id,
            surface="close-read",
            label="人物百科",
            kind="person",
            view_kind="people",
            children=children,
        )

    def _node(
        self,
        *,
        task_id: str,
        surface: str,
        label: str,
        kind: str,
        view_kind: str,
        children: Iterable[ArtifactTreeNode] = (),
        path: Path | None = None,
        extra: dict[str, Any] | None = None,
        badge: str = "",
    ) -> ArtifactTreeNode:
        descriptor: dict[str, Any] = {
            "task_id": task_id,
            "surface": surface,
            "kind": view_kind,
        }
        if path is not None:
            descriptor["path"] = str(path)
        descriptor.update(extra or {})
        return ArtifactTreeNode(
            id=encode_artifact_id(descriptor),
            label=label,
            kind=kind,
            surface=surface,  # type: ignore[arg-type]
            badge=badge,
            children=list(children),
        )

    def _chapter_rows(self, task_id: str) -> list[dict[str, Any]]:
        db_path = self.facade.db_path_for_book(task_id)
        if not db_path.exists():
            return []
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            rows = conn.execute(
                """
                SELECT document_title_index, chapter_title, summary_md, summary_short, mentioned_characters_json,
                       world_update_json, outline_update_json, importance_score
                FROM chapters
                WHERE book_id = ?
                ORDER BY document_title_index
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _writer_generated_chapter_nodes(self, *, task_id: str, run_id: str) -> list[ArtifactTreeNode]:
        rows = self._writer_generated_chapter_rows(task_id=task_id, run_id=run_id)
        return [
            self._node(
                task_id=task_id,
                surface="writer",
                label=f"{row.get('document_title_index')}. {row.get('chapter_title') or '未命名章节'}",
                kind="chapter",
                view_kind="generated_chapter",
                extra={
                    "run_id": run_id,
                    "document_title_index": row.get("document_title_index"),
                },
                badge="已写回",
            )
            for row in rows
        ]

    def _writer_generated_chapter_rows(self, *, task_id: str, run_id: str) -> list[dict[str, Any]]:
        db_path = resolve_writer_memory_db_path(repo_root=self.repo_root, book_id=task_id, reset=False)
        if not db_path.exists():
            return []
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            rows = conn.execute(
                """
                SELECT chapter_id, document_title_index, chapter_title, source_doc_start_id,
                       source_doc_end_id, source_total_chars, summary_short, updated_at
                FROM chapters
                WHERE book_id = ? AND close_read_run_id = ?
                ORDER BY document_title_index
                """,
                (task_id, run_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _person_rows(self, task_id: str) -> list[dict[str, Any]]:
        db_path = self.facade.db_path_for_book(task_id)
        if not db_path.exists():
            return []
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            rows = conn.execute(
                """
                SELECT canonical_name, aliases_json, profile_summary_md, speaking_character_status,
                       personhood_evidence_summary, personality_json, occupations_json, abilities_json,
                       recent_activity_json, relationships_json, importance_score
                FROM character_profiles
                WHERE book_id = ?
                ORDER BY importance_score DESC, canonical_name
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _person_group(row: dict[str, Any]) -> str:
        importance = int(row.get("importance_score") or 0)
        profile = str(row.get("profile_summary_md") or "")
        if "反派" in profile:
            return "反派"
        if importance >= 80:
            return "主角"
        if importance >= 40:
            return "配角"
        return "未归类"

    def _latest_writer_run(self, task_id: str) -> tuple[Path | None, dict[str, Any]]:
        state = WebSessionService(repo_root=self.repo_root, facade=self.facade).latest_writer_state(task_id)
        run_dir_text = str(state.get("run_dir") or "")
        if not run_dir_text:
            return None, {}
        run_dir = Path(run_dir_text)
        if not run_dir.exists():
            return None, {}
        return run_dir, state

    def _writer_runs(self, task_id: str) -> list[tuple[Path, dict[str, Any]]]:
        states = WebSessionService(repo_root=self.repo_root, facade=self.facade).writer_states(task_id)
        runs: list[tuple[Path, dict[str, Any]]] = []
        for state in states:
            run_dir_text = str(state.get("run_dir") or "")
            if not run_dir_text:
                continue
            run_dir = Path(run_dir_text)
            if run_dir.exists():
                runs.append((run_dir, state))
        return runs

    def _writer_run_label(self, *, run_dir: Path, state: Mapping[str, Any], index: int) -> str:
        chapter_title = self._writer_chapter_title(run_dir)
        if chapter_title:
            return chapter_title
        if (run_dir / "draft.md").exists():
            return f"续写草稿 {index}"
        if (run_dir / "chapter_package.json").exists():
            return f"章节规划 {index}"
        return f"续写记录 {index}"

    def _writer_chapter_title(self, run_dir: Path) -> str:
        for name in ("chapter_brief.json", "chapter_execution_input.json"):
            payload = self._load_json_data(run_dir / name)
            title = str(payload.get("chapter_title") or payload.get("title") or "").strip()
            if title:
                return title
            chapter_brief = payload.get("chapter_brief") if isinstance(payload.get("chapter_brief"), Mapping) else {}
            title = str((chapter_brief or {}).get("title") or "").strip()
            if title:
                return title
        package = self._load_json_data(run_dir / "chapter_package.json")
        chapters = package.get("chapters") if isinstance(package.get("chapters"), list) else []
        for chapter in chapters:
            if not isinstance(chapter, Mapping):
                continue
            title = str(chapter.get("chapter_title") or chapter.get("title") or "").strip()
            if title:
                return title
        return ""

    def _writer_run_badge(self, state: Mapping[str, Any]) -> str:
        active_stage = self._active_writer_stage(state)
        if active_stage == "wait_chapter_acceptance":
            return "待验收"
        if active_stage in {"freeze_a_review", "batch_review", "chapter_review", "wait_chapter_review", "writeback_review"}:
            return "待审阅"
        if active_stage in {"completed", "writeback_committed"}:
            return "已完成"
        return "已生成"

    @staticmethod
    def _writer_run_has_user_artifacts(run_dir: Path) -> bool:
        for name in (
            "continuation_intent.json",
            "sufficiency_decision.json",
            "book_continuation_plan.json",
            "batch_plan.json",
            "chapter_package.json",
            "chapter_writing_guidance.json",
            "draft.md",
            "generation_review_decision.json",
            "memory_writeback.json",
        ):
            if (run_dir / name).exists():
                return True
        return False

    @classmethod
    def _active_writer_stage(cls, state: dict[str, Any]) -> str:
        pending = state.get("pending_checkpoint") if isinstance(state.get("pending_checkpoint"), dict) else {}
        return str((pending or {}).get("stage") or state.get("current_stage") or "")

    @classmethod
    def _stage_rank(cls, stage: str) -> int:
        return cls._WRITER_STAGE_ORDER.get(stage, -1)

    @classmethod
    def _should_show_writer_item(cls, *, view_kind: str, path: Path, active_stage: str) -> bool:
        if not path.exists():
            return False
        rank = cls._stage_rank(active_stage)
        if view_kind == "batch_plan":
            return rank >= cls._stage_rank("batch_review")
        if view_kind == "chapter_package":
            return rank >= cls._stage_rank("chapter_review")
        if view_kind in {"writing_guidance", "draft", "generation_review", "writeback"}:
            return rank >= cls._stage_rank("chapter_review")
        return True

    @staticmethod
    def _load_json_data(path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else {}
