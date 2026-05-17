from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ...cli.artifacts import ArtifactPresenter
from ...cli.facade import WorkflowFacade
from ...cli.status import WriterStatusPresenter
from ...repos.db import NovelAgentDB
from ...run_interactive import resolve_writer_memory_db_path
from ..schemas import ArtifactCard, ArtifactSection, ArtifactTable, ArtifactView
from .artifact_ids import decode_artifact_id


class ArtifactViewService:
    """Transforms internal artifacts into user-readable Web view models."""

    def __init__(
        self,
        *,
        repo_root: Path,
        facade: WorkflowFacade | None = None,
        artifact_presenter: ArtifactPresenter | None = None,
        status_presenter: WriterStatusPresenter | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.facade = facade or WorkflowFacade(repo_root=self.repo_root)
        self.artifact_presenter = artifact_presenter or ArtifactPresenter()
        self.status_presenter = status_presenter or WriterStatusPresenter()

    def view(self, artifact_id: str) -> ArtifactView:
        descriptor = decode_artifact_id(artifact_id)
        surface = str(descriptor.get("surface") or "")
        kind = str(descriptor.get("kind") or "")
        task_id = str(descriptor.get("task_id") or "")
        if surface == "close-read":
            return self._close_read_view(artifact_id=artifact_id, task_id=task_id, descriptor=descriptor)
        if surface == "writer":
            return self._writer_view(artifact_id=artifact_id, task_id=task_id, descriptor=descriptor)
        raise ValueError("unknown artifact surface")

    def technical(self, artifact_id: str) -> dict[str, Any]:
        descriptor = decode_artifact_id(artifact_id)
        payload: dict[str, Any] = {"artifact_id": artifact_id, "descriptor": descriptor}
        path = self._safe_path(str(descriptor.get("path") or ""))
        if path and path.exists():
            payload["path"] = str(path)
            if path.suffix.lower() == ".json":
                payload["raw_json"] = self._load_json(path, unwrap_data=False)
            else:
                payload["raw_text"] = path.read_text(encoding="utf-8", errors="replace")
        else:
            payload["source"] = self._technical_source(descriptor)
        return payload

    def save_text(self, artifact_id: str, text: str) -> dict[str, Any]:
        descriptor = decode_artifact_id(artifact_id)
        path = self._safe_path(str(descriptor.get("path") or ""))
        if not path:
            return {"saved": False, "message": "这个产物不是可直接保存的文件。"}
        result = self.artifact_presenter.save_text(path, text)
        return {
            "saved": result.saved,
            "message": result.message,
            "validation_error": result.validation_error,
            "path": str(result.path),
        }

    def _close_read_view(self, *, artifact_id: str, task_id: str, descriptor: Mapping[str, Any]) -> ArtifactView:
        kind = str(descriptor.get("kind") or "")
        if kind == "overview":
            status = self.facade.modeling_status(book_id=task_id)
            ready = status.ready_map()
            return ArtifactView(
                artifact_id=artifact_id,
                title="阅读总览",
                kind="close_read_overview",
                sections=[
                    ArtifactSection(title="建模准备度", body=self._join_pairs(ready)),
                    ArtifactSection(title="已处理章节范围", body=self._counts_line(status.counts)),
                    ArtifactSection(title="下一步", body="可以查看章节摘要、人物百科、世界观、故事大纲或源作品篇章地图。"),
                ],
                technical_available=True,
            )
        if kind == "chapter":
            return self._chapter_view(artifact_id=artifact_id, task_id=task_id, descriptor=descriptor)
        if kind == "chapters":
            return self._chapters_view(artifact_id=artifact_id, task_id=task_id)
        if kind in {"people", "person_group"}:
            title = {"people": "人物百科", "person_group": str(descriptor.get("group") or "人物分组")}[kind]
            return ArtifactView(
                artifact_id=artifact_id,
                title=title,
                kind=kind,
                sections=[ArtifactSection(title="浏览提示", body="请在目录树中选择具体条目查看详细内容。")],
            )
        if kind in {"person", "person_section"}:
            return self._person_view(artifact_id=artifact_id, task_id=task_id, descriptor=descriptor)
        if kind == "world":
            return self._markdown_asset_view(
                artifact_id=artifact_id,
                title="世界观",
                kind="world",
                candidates=[
                    self.repo_root / ".memory" / "world" / f"{task_id}.summary.md",
                    self.repo_root / ".memory" / "world" / f"{task_id}.md",
                    self.repo_root / ".memory" / "worlds" / f"{task_id}.world_summary.md",
                    self.repo_root / ".memory" / "worlds" / f"{task_id}.world.md",
                ],
            )
        if kind == "outline":
            return self._outline_view(artifact_id=artifact_id, task_id=task_id)
        if kind == "source_arc":
            return self._source_arc_view(artifact_id=artifact_id, task_id=task_id)
        return self._missing_view(artifact_id, "阅读产物", kind)

    def _writer_view(self, *, artifact_id: str, task_id: str, descriptor: Mapping[str, Any]) -> ArtifactView:
        kind = str(descriptor.get("kind") or "")
        path = self._safe_path(str(descriptor.get("path") or ""))
        if kind == "run_overview":
            state = self._load_json(path) if path else {}
            pending = state.get("pending_checkpoint") if isinstance(state.get("pending_checkpoint"), Mapping) else {}
            visible_stage = str((pending or {}).get("stage") or state.get("current_stage") or "")
            status = self.status_presenter.present(visible_stage)
            return ArtifactView(
                artifact_id=artifact_id,
                title="续写概览",
                kind="writer_run",
                sections=[
                    ArtifactSection(title="当前状态", body=status.step),
                    ArtifactSection(title="待确认步骤", body=status.next_action),
                    ArtifactSection(title="产物浏览", body="请在 Writer 目录树中查看规划、草稿、验收与写回摘要。"),
                    ArtifactSection(title="下一步", body=status.next_action or "等待你选择下一步"),
                ],
                technical_available=bool(path and path.exists()),
            )
        if kind == "generated_chapters":
            return self._writer_generated_chapters_view(
                artifact_id=artifact_id,
                task_id=task_id,
                run_id=str(descriptor.get("run_id") or ""),
            )
        if kind == "generated_chapter":
            return self._writer_generated_chapter_view(
                artifact_id=artifact_id,
                task_id=task_id,
                run_id=str(descriptor.get("run_id") or ""),
                document_title_index=int(descriptor.get("document_title_index") or 0),
            )
        if not path or not path.exists():
            return self._missing_view(artifact_id, self._writer_title(kind), kind)
        if kind == "continuation_intent":
            return self._continuation_intent_view(artifact_id, path)
        if kind == "outline_research":
            return self._outline_research_view(artifact_id, path)
        if kind == "outline_questions":
            return self._outline_questions_view(artifact_id, path)
        if kind == "planning_notebook":
            return self._planning_notebook_view(artifact_id, path)
        if kind == "research_trace":
            return self._research_trace_view(artifact_id, path)
        if kind == "book_plan":
            return self._book_plan_view(artifact_id, path)
        if kind == "batch_plan":
            return self._batch_plan_view(artifact_id, path)
        if kind == "chapter_package":
            return self._chapter_package_view(artifact_id, path)
        if kind == "length_plan":
            return self._length_plan_view(artifact_id, path)
        if kind == "execution_input":
            return self._execution_input_view(artifact_id, path)
        if kind == "writing_guidance":
            return self._writing_guidance_view(artifact_id, path)
        if kind == "draft":
            return self._draft_view(artifact_id, path)
        if kind == "generation_review":
            return self._generation_review_view(artifact_id, path)
        if kind == "writeback":
            return self._writeback_view(artifact_id, path)
        summary = self.artifact_presenter.summarize(path)
        return ArtifactView(
            artifact_id=artifact_id,
            title=summary.title,
            kind=kind,
            sections=[ArtifactSection(title=label, body=value) for label, value in summary.sections if value],
            markdown=summary.preview,
            technical_available=True,
        )

    def _chapter_view(self, *, artifact_id: str, task_id: str, descriptor: Mapping[str, Any]) -> ArtifactView:
        index = int(descriptor.get("document_title_index") or 0)
        row = self._chapter_row(task_id, index)
        if not row:
            return self._missing_view(artifact_id, "章节摘要", "chapter")
        mentioned = self._json_value(row.get("mentioned_characters_json"), [])
        world_update = self._json_value(row.get("world_update_json"), {})
        outline_update = self._json_value(row.get("outline_update_json"), {})
        summary_markdown = self._chapter_summary_markdown(row)
        summary_short = str(row.get("summary_short") or "").strip()
        range_text = self._chapter_range_text(row)
        return ArtifactView(
            artifact_id=artifact_id,
            title=str(row.get("chapter_title") or f"第 {index} 章"),
            kind="chapter_summary",
            sections=[
                ArtifactSection(title="处理范围", body=range_text),
                ArtifactSection(title="短剧情概括", body=summary_short or self._plain_preview(summary_markdown)),
                ArtifactSection(title="角色状态变化", body=self._list_or_mapping_text(mentioned)),
                ArtifactSection(title="伏笔和信息增量", body=self._list_or_mapping_text(outline_update)),
                ArtifactSection(title="世界观增量", body=self._list_or_mapping_text(world_update)),
            ],
            markdown=summary_markdown,
            technical_available=True,
        )

    def _chapters_view(self, *, artifact_id: str, task_id: str) -> ArtifactView:
        rows = self._chapter_rows(task_id)
        if not rows:
            return self._missing_view(artifact_id, "章节摘要", "chapters")
        latest = rows[-1]
        table_rows = [
            {
                "章节": f"{row.get('document_title_index')}. {row.get('chapter_title') or '未命名章节'}",
                "处理范围": self._chapter_range_text(row),
                "短剧情概括": str(row.get("summary_short") or "").strip() or self._plain_preview(self._chapter_summary_markdown(row)),
                "更新时间": str(row.get("updated_at") or ""),
            }
            for row in rows
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="章节摘要",
            kind="chapters",
            sections=[
                ArtifactSection(title="章节数", body=f"已生成 {len(rows)} 个章节摘要。"),
                ArtifactSection(
                    title="最新更新",
                    body=(
                        f"{latest.get('document_title_index')}. {latest.get('chapter_title') or '未命名章节'} "
                        f"{self._chapter_range_text(latest)}"
                    ),
                ),
            ],
            tables=[
                ArtifactTable(
                    title="章节摘要索引",
                    columns=["章节", "处理范围", "短剧情概括", "更新时间"],
                    rows=table_rows,
                )
            ],
            technical_available=True,
        )

    def _writer_generated_chapters_view(self, *, artifact_id: str, task_id: str, run_id: str) -> ArtifactView:
        rows = self._writer_generated_chapter_rows(task_id=task_id, run_id=run_id)
        if not rows:
            return self._missing_view(artifact_id, "已写回章节", "generated_chapters")
        table_rows = [
            {
                "章节": f"{row.get('document_title_index')}. {row.get('chapter_title') or '未命名章节'}",
                "字数": str(row.get("source_total_chars") or ""),
                "短剧情概括": str(row.get("summary_short") or "").strip(),
                "更新时间": str(row.get("updated_at") or ""),
            }
            for row in rows
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="已写回章节",
            kind="writer_generated_chapters",
            sections=[
                ArtifactSection(title="章节数", body=f"本次 Writer 运行已写回 {len(rows)} 章。"),
                ArtifactSection(title="查看方式", body="请选择左侧子章节查看正文和摘要。"),
            ],
            tables=[
                ArtifactTable(
                    title="章节目录",
                    columns=["章节", "字数", "短剧情概括", "更新时间"],
                    rows=table_rows,
                )
            ],
            technical_available=True,
        )

    def _writer_generated_chapter_view(
        self,
        *,
        artifact_id: str,
        task_id: str,
        run_id: str,
        document_title_index: int,
    ) -> ArtifactView:
        row = self._writer_generated_chapter_row(
            task_id=task_id,
            run_id=run_id,
            document_title_index=document_title_index,
        )
        if not row:
            return self._missing_view(artifact_id, "已写回章节", "generated_chapter")
        mentioned = self._json_value(row.get("mentioned_characters_json"), [])
        world_update = self._json_value(row.get("world_update_json"), {})
        outline_update = self._json_value(row.get("outline_update_json"), {})
        summary_markdown = self._chapter_summary_markdown(row)
        summary_short = str(row.get("summary_short") or "").strip()
        return ArtifactView(
            artifact_id=artifact_id,
            title=str(row.get("chapter_title") or f"第 {document_title_index} 章"),
            kind="writer_generated_chapter",
            sections=[
                ArtifactSection(title="处理范围", body=self._chapter_range_text(row)),
                ArtifactSection(title="短剧情概括", body=summary_short or self._plain_preview(summary_markdown)),
                ArtifactSection(title="角色状态变化", body=self._list_or_mapping_text(mentioned)),
                ArtifactSection(title="伏笔和信息增量", body=self._list_or_mapping_text(outline_update)),
                ArtifactSection(title="世界观增量", body=self._list_or_mapping_text(world_update)),
            ],
            markdown=summary_markdown,
            technical_available=True,
        )

    def _person_view(self, *, artifact_id: str, task_id: str, descriptor: Mapping[str, Any]) -> ArtifactView:
        name = str(descriptor.get("name") or "")
        row = self._person_row(task_id, name)
        if not row:
            return self._missing_view(artifact_id, name or "人物百科", "person")
        aliases = self._json_value(row.get("aliases_json"), [])
        occupations = self._json_value(row.get("occupations_json"), [])
        abilities = self._json_value(row.get("abilities_json"), [])
        personality = self._json_value(row.get("personality_json"), [])
        relationships = self._json_value(row.get("relationships_json"), [])
        recent = self._json_value(row.get("recent_activity_json"), [])
        basic = "\n".join(
            item
            for item in [
                str(row.get("profile_summary_md") or ""),
                f"别名：{self._list_or_mapping_text(aliases)}" if aliases else "",
                f"身份/职业：{self._list_or_mapping_text(occupations)}" if occupations else "",
                f"能力：{self._list_or_mapping_text(abilities)}" if abilities else "",
            ]
            if item
        )
        sections = [
            ArtifactSection(title="基本信息", body=basic or "暂无明确记录。"),
            ArtifactSection(title="当前目标", body=self._list_or_mapping_text(recent) or "暂无明确记录。"),
            ArtifactSection(title="关系网络", body=self._relationship_text(relationships) or "暂无明确记录。"),
            ArtifactSection(title="性格与说话方式", body=self._list_or_mapping_text(personality) or "暂无明确记录。"),
            ArtifactSection(title="已知秘密", body="暂无明确记录。"),
            ArtifactSection(title="禁止误写点", body="暂无明确记录。"),
            ArtifactSection(title="最近变化", body=self._list_or_mapping_text(recent) or "暂无明确记录。"),
        ]
        requested_section = str(descriptor.get("section") or "")
        if requested_section:
            section_title = {
                "basic": "基本信息",
                "goals": "当前目标",
                "relationships": "关系网络",
                "voice": "性格与说话方式",
                "secrets": "已知秘密",
                "forbidden": "禁止误写点",
                "recent": "最近变化",
            }.get(requested_section, "")
            sections = [section for section in sections if section.title == section_title] or sections
        return ArtifactView(
            artifact_id=artifact_id,
            title=name,
            kind="person_encyclopedia",
            sections=sections,
            technical_available=True,
        )

    def _source_arc_view(self, *, artifact_id: str, task_id: str) -> ArtifactView:
        path = self.repo_root / ".memory" / "arcs" / f"{task_id}.source_arc_map.json"
        if not path.exists():
            md_path = self.repo_root / ".memory" / "arcs" / f"{task_id}.source_arc_map.md"
            return self._markdown_asset_view(
                artifact_id=artifact_id,
                title="源作品篇章地图",
                kind="source_arc",
                candidates=[md_path],
            )
        payload = self._load_json(path)
        arcs = [arc for arc in payload.get("arcs", []) if isinstance(arc, Mapping)]
        cards = [
            ArtifactCard(
                title=str(arc.get("source_arc_title") or arc.get("source_arc_id") or "未命名篇章"),
                subtitle=str(arc.get("source_arc_role") or ""),
                body=self._list_or_mapping_text(arc.get("core_events") or []),
                fields={
                    "范围": f"{arc.get('start_document_title_index', '')}-{arc.get('end_document_title_index', '')}",
                    "节奏": str(arc.get("pacing_notes") or ""),
                },
            )
            for arc in arcs
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="源作品篇章地图",
            kind="source_arc",
            sections=[ArtifactSection(title="篇章结构", body=f"共 {len(cards)} 个篇章。")],
            cards=cards,
            technical_available=True,
        )

    def _outline_view(self, *, artifact_id: str, task_id: str) -> ArtifactView:
        rows = self._chapter_rows(task_id)
        markdown = self._outline_markdown_from_chapter_rows(task_id=task_id, rows=rows)
        if markdown:
            return ArtifactView(
                artifact_id=artifact_id,
                title="故事大纲",
                kind="outline",
                markdown=markdown,
                technical_available=True,
            )
        return self._markdown_asset_view(
            artifact_id=artifact_id,
            title="故事大纲",
            kind="outline",
            candidates=[
                self.repo_root / ".memory" / "outlines" / f"{task_id}.md",
                self.repo_root / ".memory" / "outlines" / f"{task_id}.outline.md",
            ],
        )

    def _continuation_intent_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        sections = [
            ArtifactSection(title="剧情提示", body=self._intent_goal_text(payload)),
            ArtifactSection(title="目标规模", body=self._intent_scale_text(payload)),
            ArtifactSection(title="高潮设想", body=self._intent_climax_text(payload)),
            ArtifactSection(title="额外约束", body=self._intent_constraints_text(payload)),
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="写作目标",
            kind="writer_continuation_intent",
            sections=self._nonempty_sections(
                sections,
                fallback_title="保存状态",
                fallback_body="本次 Writer 提交未保存可展示的写作目标；后续新提交会在这里显示。",
            ),
            technical_available=True,
        )

    def _outline_research_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        sections = [
            ArtifactSection(title="研究结论", body=self._outline_research_status_text(self._first_text(payload, "status", "decision", "summary"))),
            ArtifactSection(title="已确认信息", body=self._fact_list_text(payload.get("known_enough") or payload.get("confirmed_facts"))),
            ArtifactSection(title="仍缺口", body=self._fact_list_text(payload.get("blocking_gaps") or payload.get("optional_gaps"))),
            ArtifactSection(title="可用假设", body=self._fact_list_text(payload.get("assumptions"))),
            ArtifactSection(title="风险提示", body=self._fact_list_text(payload.get("remaining_risks"))),
            ArtifactSection(title="待用户回答", body=self._fact_list_text(payload.get("user_questions"))),
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="大纲研究结果",
            kind="writer_outline_research",
            sections=self._nonempty_sections(
                sections,
                fallback_title="研究结论",
                fallback_body="本轮没有提出需要你补充的问题，已继续进入规划。",
            ),
            technical_available=True,
        )

    def _outline_questions_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        questions = [item for item in payload.get("questions", []) if isinstance(item, Mapping)]
        rows = [
            {
                "问题": str(item.get("prompt") or ""),
                "是否必答": "是" if item.get("required", True) else "否",
                "提示": str(item.get("hint") or ""),
                "风险": str(item.get("risk_level") or ""),
            }
            for item in questions
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="大纲研究问题集",
            kind="writer_outline_questions",
            sections=[
                ArtifactSection(title="状态", body="待回答" if str(payload.get("status") or "") == "pending" else str(payload.get("status") or "")),
                ArtifactSection(title="使用方式", body="请在中间会话的问题卡中回答，并通过结构化按钮继续研究。"),
            ],
            tables=[ArtifactTable(title="问题", columns=["问题", "是否必答", "提示", "风险"], rows=rows)],
            technical_available=True,
        )

    def _planning_notebook_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        evidence = payload.get("evidence") or payload.get("facts") or payload.get("entries") or []
        confirmed = payload.get("confirmed_facts") or payload.get("known_facts") or []
        candidates = payload.get("candidate_facts") or payload.get("candidate_plot_moves") or []
        blocked = payload.get("blocked_plot_moves") or payload.get("blocked_facts") or []
        sections = [
            ArtifactSection(title="研究摘要", body=self._first_text(payload, "summary", "planning_summary")),
            ArtifactSection(title="已确认材料", body=self._fact_list_text(confirmed) or self._filter_notebook_text(evidence, "user_authorized")),
            ArtifactSection(title="候选推进", body=self._fact_list_text(candidates)),
            ArtifactSection(title="暂不采用", body=self._fact_list_text(blocked)),
            ArtifactSection(title="未决问题", body=self._fact_list_text(payload.get("open_questions") or payload.get("questions"))),
            ArtifactSection(title="剩余风险", body=self._fact_list_text(payload.get("risks") or payload.get("remaining_risks"))),
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="大纲研究笔记",
            kind="writer_planning_notebook",
            sections=self._nonempty_sections(sections, fallback_title="研究笔记", fallback_body=self._fact_list_text(evidence)[:2000]),
            technical_available=True,
        )

    def _research_trace_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        requests = payload.get("requests") or payload.get("turns") or payload.get("trace") or []
        rounds = payload.get("rounds") if isinstance(payload.get("rounds"), list) else []
        sections = [
            ArtifactSection(title="查询轮次", body=self._research_trace_text(rounds or requests)),
            ArtifactSection(title="来源摘要", body=self._fact_list_text(payload.get("sources") or payload.get("evidence_sources"))),
            ArtifactSection(title="下一步建议", body=self._fact_list_text(payload.get("next_steps") or payload.get("recommendations"))),
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="检索轨迹",
            kind="writer_research_trace",
            sections=self._nonempty_sections(sections, fallback_title="查询轮次", fallback_body="本轮没有记录可展示的检索轨迹。"),
            technical_available=True,
        )

    def _book_plan_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        climax = payload.get("climax_plan") if isinstance(payload.get("climax_plan"), Mapping) else {}
        return ArtifactView(
            artifact_id=artifact_id,
            title="全书续写规划",
            kind="writer_book_plan",
            sections=[
                ArtifactSection(title="续写目标", body=self._first_text(payload, "continuation_goal", "goal")),
                ArtifactSection(title="故事规模", body=self._book_scale_text(payload)),
                ArtifactSection(title="世界观补充", body=self._list_or_mapping_text(payload.get("world_additions") or payload.get("world_notes"))),
                ArtifactSection(title="人物补充", body=self._list_or_mapping_text(payload.get("character_additions") or payload.get("character_notes"))),
                ArtifactSection(title="高潮与回收", body=self._list_or_mapping_text(climax or payload.get("recovery_plan"))),
                ArtifactSection(title="角色弧", body=self._list_or_mapping_text(payload.get("character_arcs") or payload.get("arc_roadmap"))),
                ArtifactSection(title="假设和未决问题", body=self._list_or_mapping_text(payload.get("assumptions") or payload.get("open_questions"))),
                ArtifactSection(title="必须保持", body=self._list_or_mapping_text(payload.get("must_preserve"))),
            ],
            technical_available=True,
        )

    def _batch_plan_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        return ArtifactView(
            artifact_id=artifact_id,
            title="本批剧情大纲",
            kind="writer_batch_plan",
            sections=[
                ArtifactSection(title="起点状态", body=self._first_text(payload, "start_state", "entry_state")),
                ArtifactSection(title="阶段目标", body=self._first_text(payload, "stage_goal", "goal", "batch_goal")),
                ArtifactSection(title="主要冲突", body=self._first_text(payload, "main_conflict", "central_conflict", "conflict")),
                ArtifactSection(title="情绪节奏", body=self._first_text(payload, "emotional_pacing", "pacing_notes", "mood")),
                ArtifactSection(title="出口钩子", body=self._first_text(payload, "exit_hook", "expected_closure", "exit_state", "ending_state")),
                ArtifactSection(title="禁止提前消费项", body=self._list_or_mapping_text(payload.get("forbidden_early_consumption") or payload.get("forbidden_items"))),
            ],
            technical_available=True,
        )

    def _chapter_package_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        chapters = [item for item in payload.get("chapters", []) if isinstance(item, Mapping)]
        rows = [
            {
                "章节": str(item.get("chapter_title") or item.get("title") or item.get("chapter_id") or ""),
                "目标": str(item.get("chapter_goal") or item.get("goal") or ""),
                "场景节拍": self._list_or_mapping_text(item.get("scene_beats")),
                "人物行动": self._list_or_mapping_text(item.get("character_actions") or item.get("characters")),
                "关系推进": self._list_or_mapping_text(item.get("relationship_goal") or item.get("relationship_progression") or item.get("relationship_targets")),
                "必须出现/禁止项": self._list_or_mapping_text(item.get("must_include") or item.get("required_items")) + "\n" + self._list_or_mapping_text(item.get("forbidden_items") or item.get("forbidden")),
            }
            for item in chapters
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="章节标题与梗概",
            kind="writer_chapter_package",
            tables=[ArtifactTable(title="章节梗概", columns=["章节", "目标", "场景节拍", "人物行动", "关系推进", "必须出现/禁止项"], rows=rows)],
            sections=[
                ArtifactSection(title="待确认问题", body=self._list_or_mapping_text(payload.get("open_questions") or payload.get("review_notes"))),
            ],
            technical_available=True,
        )

    def _length_plan_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        budgets = [item for item in payload.get("budgets", []) if isinstance(item, Mapping)]
        rows = [
            {
                "章节": str(item.get("chapter_id") or item.get("chapter_title") or ""),
                "目标字数": str(item.get("target_chars") or item.get("chars") or ""),
                "重点": self._list_or_mapping_text(item.get("focus") or item.get("focus_notes")),
            }
            for item in budgets
        ]
        return ArtifactView(
            artifact_id=artifact_id,
            title="章节长度计划",
            kind="writer_length_plan",
            sections=[
                ArtifactSection(title="默认字数", body=str(payload.get("default_target_chars") or "")),
                ArtifactSection(title="重点章节与高潮章节", body=self._list_or_mapping_text(payload.get("focus_chapter_ids") or payload.get("climax_chapter_ids"))),
            ],
            tables=[ArtifactTable(title="单章预算", columns=["章节", "目标字数", "重点"], rows=rows)],
            technical_available=True,
        )

    def _execution_input_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        return ArtifactView(
            artifact_id=artifact_id,
            title="本章写作材料",
            kind="writer_execution_input",
            sections=[
                ArtifactSection(title="事实型上下文", body=self._list_or_mapping_text(payload.get("fact_constraints") or payload.get("memory_constraints"))),
                ArtifactSection(title="风格与桥段参考", body=self._list_or_mapping_text(payload.get("style_references") or payload.get("creative_references"))),
                ArtifactSection(title="禁止项", body=self._list_or_mapping_text(payload.get("forbidden_items") or payload.get("forbidden_carryover"))),
            ],
            cards=[
                ArtifactCard(
                    title=str(payload.get("chapter_title") or payload.get("chapter_id") or "当前章节"),
                    body=self._list_or_mapping_text(payload.get("length_budget")),
                )
            ],
            technical_available=True,
        )

    def _writing_guidance_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        supplement = payload.get("user_supplement") if isinstance(payload.get("user_supplement"), Mapping) else {}
        return ArtifactView(
            artifact_id=artifact_id,
            title="章节写作指导",
            kind="writer_writing_guidance",
            sections=[
                ArtifactSection(title="章节", body=str(payload.get("chapter_title") or payload.get("chapter_id") or "")),
                ArtifactSection(title="用户补充原文", body=str((supplement or {}).get("supplement_text") or "")),
                ArtifactSection(title="派生长度预算", body=self._list_or_mapping_text(payload.get("length_budget"))),
                ArtifactSection(title="风格与节奏", body=self._list_or_mapping_text(payload.get("style") or payload.get("pacing_notes") or payload.get("writer_rules"))),
                ArtifactSection(title="重点展开要求", body=self._list_or_mapping_text(payload.get("focus") or payload.get("chapter_brief_summary"))),
            ],
            technical_available=True,
        )

    def _draft_view(self, artifact_id: str, path: Path) -> ArtifactView:
        text = path.read_text(encoding="utf-8", errors="replace")
        return ArtifactView(
            artifact_id=artifact_id,
            title="正文草稿",
            kind="writer_draft",
            sections=[
                ArtifactSection(title="字数", body=str(len(text))),
                ArtifactSection(title="开头预览", body=text[:300]),
                ArtifactSection(title="连续性检查", body="请查看同一 run 的连续性报告或写回确认。"),
            ],
            markdown=text,
            technical_available=True,
        )

    def _generation_review_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        status_label = {
            "accepted": "接受本章",
            "rewrite_requested": "基于反馈重写",
            "replan_requested": "修改章节梗概后重写",
            "discarded": "作废本次草稿",
        }.get(str(payload.get("status") or ""), str(payload.get("status") or "待决定"))
        return ArtifactView(
            artifact_id=artifact_id,
            title="验收决策",
            kind="writer_generation_review",
            sections=[
                ArtifactSection(title="当前决定", body=status_label),
                ArtifactSection(title="反馈原文", body=str(payload.get("feedback_text") or "")),
                ArtifactSection(title="下一步", body=self._generation_next_action_text(str(payload.get("next_action") or ""))),
                ArtifactSection(title="写回边界", body="只有接受本章才会进入写回摘要审阅；其它分支不会写入 Memory 或 Creative KB。"),
            ],
            technical_available=True,
        )


    def _writeback_view(self, artifact_id: str, path: Path) -> ArtifactView:
        payload = self._load_json(path)
        return ArtifactView(
            artifact_id=artifact_id,
            title="写回确认",
            kind="writer_writeback",
            sections=[
                ArtifactSection(title="人物状态变化", body=self._list_or_mapping_text(payload.get("character_state_changes") or payload.get("activated_planned_characters"))),
                ArtifactSection(title="世界状态变化", body=self._list_or_mapping_text(payload.get("world_state_changes") or payload.get("world_updates"))),
                ArtifactSection(title="新伏笔", body=self._list_or_mapping_text(payload.get("new_hooks") or payload.get("foreshadowing"))),
                ArtifactSection(title="已回收信息", body=self._list_or_mapping_text(payload.get("resolved_hooks") or payload.get("recovered_information"))),
            ],
            technical_available=True,
        )

    def _markdown_asset_view(self, *, artifact_id: str, title: str, kind: str, candidates: list[Path]) -> ArtifactView:
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            return self._missing_view(artifact_id, title, kind)
        return ArtifactView(
            artifact_id=artifact_id,
            title=title,
            kind=kind,
            sections=[ArtifactSection(title="内容", body=path.read_text(encoding="utf-8", errors="replace"))],
            technical_available=True,
        )

    def _outline_markdown_from_chapter_rows(self, *, task_id: str, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        outline_path = next(
            (
                candidate
                for candidate in [
                    self.repo_root / ".memory" / "outlines" / f"{task_id}.md",
                    self.repo_root / ".memory" / "outlines" / f"{task_id}.outline.md",
                ]
                if candidate.exists()
            ),
            None,
        )
        file_sections = self._outline_file_sections(outline_path)
        lines = ["# 故事大纲", "", "## 主线概览"]
        lines.extend(file_sections.get("主线概览") or ["- 待补充"])
        lines.append("")
        lines.append("## 分章节进度")
        lines.extend(self._outline_chapter_lines(rows) or ["- 暂无更新"])
        lines.append("")
        lines.append("## 关键时间节点")
        lines.extend(self._outline_timeline_lines(rows) or ["- 暂无更新"])
        lines.append("")
        lines.append("## 当前未解问题")
        lines.extend(file_sections.get("当前未解问题") or ["- 待补充"])
        return "\n".join(lines).strip() + "\n"

    def _outline_chapter_lines(self, rows: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        seen: set[str] = set()
        for row in rows:
            outline_update = self._json_value(row.get("outline_update_json"), {})
            chapter_line = (
                str(outline_update.get("chapter_line") or "").strip()
                if isinstance(outline_update, Mapping)
                else ""
            )
            if not chapter_line:
                index = row.get("document_title_index")
                title = str(row.get("chapter_title") or "未命名章节").strip()
                summary = str(row.get("summary_short") or "").strip()
                chapter_line = f"[{index}] {title}: {summary}".strip()
            chapter_line = self._compact_text(chapter_line)
            key = self._normalized_match_text(chapter_line)
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(f"- {chapter_line}")
        return lines

    def _outline_timeline_lines(self, rows: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        seen: set[str] = set()
        for row in rows:
            outline_update = self._json_value(row.get("outline_update_json"), {})
            if not isinstance(outline_update, Mapping):
                continue
            raw_events = outline_update.get("timeline_events")
            events = raw_events if isinstance(raw_events, list) else []
            if not events and str(outline_update.get("event_summary") or "").strip():
                events = [
                    {
                        "label": f"{row.get('chapter_title') or '章节'}剧情进展",
                        "summary": outline_update.get("event_summary"),
                        "source_doc_ids": outline_update.get("source_doc_ids"),
                        "source_doc_range": outline_update.get("source_doc_range"),
                    }
                ]
            for event in events:
                if not isinstance(event, Mapping):
                    continue
                line = self._render_outline_timeline_event(row=row, event=event)
                key = self._normalized_match_text(line)
                if not key or key in seen:
                    continue
                seen.add(key)
                lines.append(line)
        return lines

    def _render_outline_timeline_event(self, *, row: Mapping[str, Any], event: Mapping[str, Any]) -> str:
        summary = self._compact_text(event.get("summary") or event.get("label") or "")
        label = self._compact_text(event.get("label") or "") or self._compact_text(row.get("chapter_title") or "未命名事件")
        participants = event.get("participants")
        participant_text = ",".join(
            self._compact_text(item)
            for item in (participants if isinstance(participants, list) else [])
            if self._compact_text(item)
        )
        source_doc_ids = self._safe_int_list(event.get("source_doc_ids"))
        source_doc_range = self._compact_text(event.get("source_doc_range") or "") or self._doc_range_text(source_doc_ids)
        source_parts = []
        event_id = self._compact_text(event.get("event_id") or "")
        if event_id:
            source_parts.append(f"事件：{event_id}")
        if source_doc_range:
            source_parts.append(f"documents：{source_doc_range}")
        source_text = f" | {' | '.join(source_parts)}" if source_parts else ""
        return f"- {label} | 人物：{participant_text} | {summary}{source_text}".rstrip()

    def _outline_file_sections(self, path: Path | None) -> dict[str, list[str]]:
        sections = {"主线概览": [], "当前未解问题": []}
        if path is None:
            return sections
        current: str | None = None
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.rstrip()
            if line.startswith("## "):
                heading = line[3:].strip()
                current = heading if heading in sections else None
                continue
            if current is None:
                continue
            text = self._compact_text(line)
            if not text or text in {"- 暂无更新", "- 待补充"}:
                continue
            sections[current].append(text if text.startswith("- ") else f"- {text}")
        return sections

    def _chapter_rows(self, task_id: str) -> list[dict[str, Any]]:
        db_path = self.facade.db_path_for_book(task_id)
        if not db_path.exists():
            return []
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            rows = conn.execute(
                """
                SELECT document_title_index, chapter_title, source_doc_start_id, source_doc_end_id,
                       source_doc_count, source_total_chars, summary_intermediate_json, summary_md,
                       summary_short, mentioned_characters_json, world_update_json, outline_update_json,
                       importance_score, updated_at
                FROM chapters
                WHERE book_id = ?
                ORDER BY document_title_index
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _writer_generated_chapter_rows(self, *, task_id: str, run_id: str) -> list[dict[str, Any]]:
        db_path = resolve_writer_memory_db_path(repo_root=self.repo_root, book_id=task_id, reset=False)
        if not db_path.exists():
            return []
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            rows = conn.execute(
                """
                SELECT document_title_index, chapter_title, source_doc_start_id, source_doc_end_id,
                       source_doc_count, source_total_chars, summary_intermediate_json, summary_md,
                       summary_short, mentioned_characters_json, world_update_json, outline_update_json,
                       importance_score, updated_at
                FROM chapters
                WHERE book_id = ? AND close_read_run_id = ?
                ORDER BY document_title_index
                """,
                (task_id, run_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _writer_generated_chapter_row(
        self,
        *,
        task_id: str,
        run_id: str,
        document_title_index: int,
    ) -> dict[str, Any]:
        db_path = resolve_writer_memory_db_path(repo_root=self.repo_root, book_id=task_id, reset=False)
        if not db_path.exists():
            return {}
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            row = conn.execute(
                """
                SELECT document_title_index, chapter_title, source_doc_start_id, source_doc_end_id,
                       source_doc_count, source_total_chars, summary_intermediate_json, summary_md,
                       summary_short, mentioned_characters_json, world_update_json, outline_update_json,
                       importance_score, updated_at
                FROM chapters
                WHERE book_id = ? AND close_read_run_id = ? AND document_title_index = ?
                """,
                (task_id, run_id, document_title_index),
            ).fetchone()
        return dict(row) if row else {}

    def _chapter_row(self, task_id: str, document_title_index: int) -> dict[str, Any]:
        db_path = self.facade.db_path_for_book(task_id)
        if not db_path.exists():
            return {}
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            row = conn.execute(
                """
                SELECT document_title_index, chapter_title, source_doc_start_id, source_doc_end_id,
                       source_doc_count, source_total_chars, summary_intermediate_json, summary_md,
                       summary_short, mentioned_characters_json, world_update_json, outline_update_json,
                       importance_score, updated_at
                FROM chapters
                WHERE book_id = ? AND document_title_index = ?
                """,
                (task_id, document_title_index),
            ).fetchone()
        return dict(row) if row else {}

    def _chapter_summary_markdown(self, row: Mapping[str, Any]) -> str:
        summary_md = str(row.get("summary_md") or "").strip()
        if summary_md:
            return summary_md
        intermediate = self._json_value(row.get("summary_intermediate_json"), [])
        if isinstance(intermediate, list):
            parts = [str(item).strip() for item in intermediate if str(item).strip()]
            if parts:
                return "\n\n---\n\n".join(parts)
        return str(row.get("summary_short") or "").strip()

    def _chapter_range_text(self, row: Mapping[str, Any]) -> str:
        start = row.get("source_doc_start_id")
        end = row.get("source_doc_end_id")
        count = row.get("source_doc_count")
        total_chars = row.get("source_total_chars")
        parts = []
        if start is not None and end is not None:
            parts.append(f"doc {start}-{end}")
        if count is not None:
            parts.append(f"{count} 个片段")
        if total_chars is not None:
            parts.append(f"{total_chars} 字")
        return "；".join(parts)

    def _safe_int_list(self, value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        cleaned: set[int] = set()
        for item in value:
            try:
                cleaned.add(int(item))
            except (TypeError, ValueError):
                continue
        return sorted(cleaned)

    def _doc_range_text(self, doc_ids: list[int]) -> str:
        if not doc_ids:
            return ""
        return str(doc_ids[0]) if len(doc_ids) == 1 else f"{doc_ids[0]}-{doc_ids[-1]}"

    def _compact_text(self, value: object) -> str:
        return " ".join(str(value or "").split())

    def _normalized_match_text(self, value: object) -> str:
        return "".join(ch for ch in self._compact_text(value).lower() if ch.isalnum())

    def _plain_preview(self, text: str, limit: int = 180) -> str:
        compact = " ".join(str(text or "").replace("#", "").split())
        if len(compact) <= limit:
            return compact
        return f"{compact[:limit].rstrip()}..."

    def _person_row(self, task_id: str, name: str) -> dict[str, Any]:
        db_path = self.facade.db_path_for_book(task_id)
        if not db_path.exists():
            return {}
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            row = conn.execute(
                """
                SELECT canonical_name, aliases_json, profile_summary_md, speaking_character_status,
                       personhood_evidence_summary, personality_json, occupations_json, abilities_json,
                       recent_activity_json, relationships_json, importance_score
                FROM character_profiles
                WHERE book_id = ? AND canonical_name = ?
                """,
                (task_id, name),
            ).fetchone()
        return dict(row) if row else {}

    def _technical_source(self, descriptor: Mapping[str, Any]) -> dict[str, Any]:
        surface = str(descriptor.get("surface") or "")
        kind = str(descriptor.get("kind") or "")
        if surface == "close-read" and kind == "person":
            return self._person_row(str(descriptor.get("task_id") or ""), str(descriptor.get("name") or ""))
        if surface == "close-read" and kind == "chapter":
            return self._chapter_row(str(descriptor.get("task_id") or ""), int(descriptor.get("document_title_index") or 0))
        return {}

    def _safe_path(self, raw_path: str) -> Path | None:
        if not raw_path:
            return None
        path = Path(raw_path).expanduser().resolve()
        try:
            path.relative_to(self.repo_root)
        except ValueError:
            return None
        return path

    def _load_json(self, path: Path | None, *, unwrap_data: bool = True) -> dict[str, Any]:
        if path is None or not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if unwrap_data and isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            raw = raw["data"]
        return dict(raw) if isinstance(raw, dict) else {"items": raw}

    @staticmethod
    def _json_value(raw: Any, default: Any) -> Any:
        if raw in (None, ""):
            return default
        if isinstance(raw, (list, dict)):
            return raw
        try:
            return json.loads(str(raw))
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _filter_notebook_text(self, value: Any, evidence_level: str) -> str:
        items = value if isinstance(value, list) else []
        matched = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            item_level = str(item.get("evidence_level") or item.get("source_type") or item.get("level") or "")
            if item_level == evidence_level:
                matched.append(item)
        return self._list_or_mapping_text(matched)

    def _intent_goal_text(self, payload: Mapping[str, Any]) -> str:
        goals = payload.get("desired_actions")
        if isinstance(goals, list):
            lines = [self._compact_text(item) for item in goals if self._compact_text(item)]
            if lines:
                return "\n".join(f"{index}. {line}" for index, line in enumerate(lines, start=1))
        for key in ("continuation_goal", "preferred_outcome", "notes"):
            text = self._compact_text(payload.get(key))
            if text:
                return text
        return "本次提交没有保存明确剧情提示；后续新提交会在这里显示。"

    def _intent_scale_text(self, payload: Mapping[str, Any]) -> str:
        scale = payload.get("story_scale") if isinstance(payload.get("story_scale"), Mapping) else payload
        labels = {
            "目标章节数": ("target_chapter_count", "target_chapters"),
            "目标总字数": ("target_total_chars", "target_total_words"),
            "默认单章字数": ("default_chapter_target_chars", "default_chapter_chars", "default_target_chars"),
            "节奏偏好": ("pacing_profile", "pacing_preference", "pacing"),
            "长度分配备注": ("length_distribution_notes",),
        }
        lines = []
        for label, keys in labels.items():
            for key in keys:
                value = scale.get(key) if isinstance(scale, Mapping) else None
                if value not in (None, "", []):
                    lines.append(f"{label}：{self._compact_text(value)}")
                    break
        return "\n".join(lines)

    def _intent_climax_text(self, payload: Mapping[str, Any]) -> str:
        climax = payload.get("climax_plan") if isinstance(payload.get("climax_plan"), Mapping) else {}
        labels = {
            "剧情高潮": "conflict_climax",
            "情感高潮": "emotional_climax",
            "目标章节位置": "target_chapter_index",
            "必须铺垫": "must_foreshadow",
            "禁止提前解决": "must_not_resolve_before",
            "回收期待": "payoff_expectation",
        }
        lines = []
        for label, key in labels.items():
            value = climax.get(key) if isinstance(climax, Mapping) else None
            text = self._list_or_mapping_text(value)
            if text:
                lines.append(f"{label}：{text}")
        return "\n".join(lines)

    def _intent_constraints_text(self, payload: Mapping[str, Any]) -> str:
        lines = []
        for label, key in {
            "必须避免": "avoidances",
            "备注": "notes",
            "期望结果": "preferred_outcome",
        }.items():
            text = self._list_or_mapping_text(payload.get(key))
            if text:
                lines.append(f"{label}：{text}")
        return "\n".join(lines)

    @staticmethod
    def _nonempty_sections(
        sections: list[ArtifactSection],
        *,
        fallback_title: str,
        fallback_body: str,
    ) -> list[ArtifactSection]:
        visible = [section for section in sections if str(section.body or "").strip()]
        if visible:
            return visible
        return [ArtifactSection(title=fallback_title, body=fallback_body)]

    def _fact_list_text(self, value: Any, *, limit: int = 8) -> str:
        if value in (None, "", []):
            return ""
        items = value if isinstance(value, list) else [value]
        lines = []
        for item in items[:limit]:
            if isinstance(item, Mapping):
                text = self._first_text(
                    item,
                    "claim",
                    "summary",
                    "text",
                    "description",
                    "question",
                    "prompt",
                    "reason",
                    "title",
                )
                if self._looks_like_serialized_payload(text):
                    text = self._first_text(item, "note") or self._source_snippets_text(item.get("sources"))
                if not text:
                    text = self._list_or_mapping_text(item)
            else:
                text = self._list_or_mapping_text(item)
            text = self._compact_text(text)
            if text:
                lines.append(f"- {text[:500]}")
        return "\n".join(lines)

    @staticmethod
    def _looks_like_serialized_payload(text: str) -> bool:
        compact = text.strip()
        if not compact:
            return False
        return compact.startswith(("[{", "{'")) or compact.count("{") >= 3 or compact.count("\\\"") >= 4

    def _source_snippets_text(self, sources: Any) -> str:
        if not isinstance(sources, list):
            return ""
        snippets = []
        for source in sources[:4]:
            if not isinstance(source, Mapping):
                continue
            label = self._compact_text(source.get("type") or "")
            snippet = self._compact_text(source.get("snippet") or source.get("note") or "")
            if snippet:
                snippets.append(f"{label}：{snippet}" if label else snippet)
        return "；".join(snippets)

    def _research_trace_text(self, value: Any) -> str:
        if not isinstance(value, list):
            return self._fact_list_text(value)
        lines = []
        for index, item in enumerate(value[:8], start=1):
            if not isinstance(item, Mapping):
                text = self._compact_text(item)
                if text:
                    lines.append(f"- 第 {index} 条：{text[:500]}")
                continue
            requests = item.get("requests") if isinstance(item.get("requests"), list) else []
            if requests:
                request_text = "；".join(
                    self._compact_text(req.get("query") or req.get("type") or req)
                    for req in requests
                    if isinstance(req, Mapping) and self._compact_text(req.get("query") or req.get("type") or req)
                )
                if request_text:
                    lines.append(f"- 第 {index} 轮：{request_text[:500]}")
                continue
            text = self._fact_list_text(item, limit=1)
            if text:
                lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _outline_research_status_text(status: str) -> str:
        return {
            "enough": "信息足够，可以进入规划。",
            "needs_user_input": "需要用户补充关键问题。",
            "proceed_with_assumptions": "可带着明确假设继续。",
            "blocked": "前置建模不足，需要先补材料。",
        }.get(status, status)

    def _book_scale_text(self, payload: Mapping[str, Any]) -> str:
        parts = []
        for label, keys in {
            "目标章节数": ("target_chapter_count", "target_chapters", "chapter_count"),
            "目标总字数": ("target_total_chars", "target_total_words", "total_words"),
            "默认单章字数": ("default_chapter_chars", "default_chapter_words", "default_target_chars"),
            "节奏": ("pacing", "pacing_profile", "pacing_preference"),
        }.items():
            value = ""
            for key in keys:
                if payload.get(key) not in (None, ""):
                    value = str(payload.get(key))
                    break
            if value:
                parts.append(f"{label}：{value}")
        return "\n".join(parts)

    @staticmethod
    def _generation_next_action_text(next_action: str) -> str:
        return {
            "writeback_review": "进入写回摘要审阅",
            "agent_loop_rewrite_draft": "基于当前已通过章节梗概重写正文",
            "agent_loop_replan_chapter": "回到章节标题与梗概审阅",
            "halted": "暂停在当前草稿",
        }.get(next_action, "等待你选择下一步")

    @classmethod
    def _list_or_mapping_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return cls._public_writer_text(value.strip())
        if isinstance(value, list):
            return "\n".join(cls._list_or_mapping_text(item) for item in value if cls._list_or_mapping_text(item))
        if isinstance(value, Mapping):
            parts = []
            for key, item in value.items():
                item_text = cls._list_or_mapping_text(item)
                label = cls._public_writer_text(str(key))
                parts.append(f"{label}：{item_text}" if item_text else label)
            return "\n".join(parts)
        return cls._public_writer_text(str(value))

    @staticmethod
    def _public_writer_text(value: str) -> str:
        replacements = {
            "ChapterBrief": "章节梗概",
            "BatchPlan": "本批剧情大纲",
            "BookContinuationPlan": "全书续写规划",
            "must_resolve": "必须推进的剧情",
            "must_not_consume": "禁止提前消耗的内容",
            "stage_goal": "阶段目标",
        }
        text = value
        for raw, public in replacements.items():
            text = text.replace(raw, public)
        return text

    @classmethod
    def _relationship_text(cls, relationships: Any) -> str:
        if not isinstance(relationships, list):
            return cls._list_or_mapping_text(relationships)
        lines = []
        for item in relationships:
            if isinstance(item, Mapping):
                target = item.get("target_name") or item.get("name") or "相关人物"
                relation = item.get("relation_type") or item.get("relationship") or ""
                status = item.get("status_summary") or item.get("summary") or item.get("sentiment_state") or ""
                lines.append("：".join(str(part) for part in [target, relation, status] if part))
            else:
                lines.append(str(item))
        return "\n".join(lines)

    @staticmethod
    def _join_pairs(value: Mapping[str, bool]) -> str:
        return "；".join(f"{name}={'已完成' if ready else '待补齐'}" for name, ready in value.items())

    @staticmethod
    def _counts_line(counts: Mapping[str, int]) -> str:
        return "；".join(f"{key}={value}" for key, value in counts.items())

    @staticmethod
    def _writer_title(kind: str) -> str:
        return {
            "continuation_intent": "写作目标",
            "book_plan": "全书续写规划",
            "outline_research": "大纲研究结果",
            "outline_questions": "问题集",
            "planning_notebook": "大纲研究笔记",
            "research_trace": "检索轨迹",
            "batch_plan": "本批剧情大纲",
            "chapter_package": "章节标题与梗概",
            "length_plan": "章节长度计划",
            "execution_input": "本章写作材料",
            "writing_guidance": "章节写作指导",
            "draft": "正文草稿",
            "generation_review": "验收决策",
            "writeback": "写回摘要",
        }.get(kind, "Writer 产物")

    @staticmethod
    def _missing_view(artifact_id: str, title: str, kind: str) -> ArtifactView:
        return ArtifactView(
            artifact_id=artifact_id,
            title=title,
            kind=kind,
            sections=[ArtifactSection(title="状态", body="产物尚未生成。请先运行对应流程，或稍后刷新。")],
            technical_available=False,
        )
