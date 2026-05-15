from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ...cli.facade import WorkflowFacade
from ...repos.db import NovelAgentDB
from ..schemas import ArtifactTreeNode
from .artifact_ids import encode_artifact_id


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
        ("Run 总览", "writer_run", "run_overview", "workflow_state.json"),
        ("全书续写规划", "writer_artifact", "book_plan", "book_continuation_plan.json"),
        ("本批剧情大纲", "writer_artifact", "batch_plan", "batch_plan.json"),
        ("章节标题与梗概", "writer_artifact", "chapter_package", "chapter_package.json"),
        ("章节长度计划", "writer_artifact", "length_plan", "chapter_length_plan.json"),
        ("本章写作材料", "writer_artifact", "execution_input", "chapter_execution_input.json"),
        ("正文草稿", "draft", "draft", "draft.md"),
        ("写回确认", "writeback", "writeback", "memory_writeback.json"),
    )

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
        run_dir, _state = self._latest_writer_run(task_id)
        nodes: list[ArtifactTreeNode] = []
        for label, node_kind, view_kind, filename in self._WRITER_ITEMS:
            path = run_dir / filename if run_dir else None
            badge = "已生成" if path and path.exists() else ""
            nodes.append(
                self._node(
                    task_id=task_id,
                    surface="writer",
                    label=label,
                    kind=node_kind,
                    view_kind=view_kind,
                    path=path,
                    extra={"run_id": run_dir.name if run_dir else ""},
                    badge=badge,
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
        writer_root = self.repo_root / "runs" / "writer"
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        if not writer_root.exists():
            return None, {}
        for state_path in writer_root.glob("*/workflow_state.json"):
            payload = self._load_json_data(state_path)
            if str(payload.get("book_id") or "") == task_id:
                candidates.append((state_path.stat().st_mtime, state_path.parent, payload))
        if not candidates:
            return None, {}
        _, run_dir, state = sorted(candidates, key=lambda item: item[0])[-1]
        return run_dir, state

    @staticmethod
    def _load_json_data(path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else {}
