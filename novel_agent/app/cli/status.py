from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class StatusView:
    flow: str
    step: str
    next_action: str = ""
    message: str = ""
    technical_details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WriterStageAction:
    label: str
    workflow_action: str
    description: str = ""


class StatusPresenter:
    """Translates internal runner/workflow states into user-facing Chinese copy."""

    FORBIDDEN_PUBLIC_TOKENS = (
        "artifact saved",
        "checkpoint confirmed",
        "Freeze B pending",
        "freeze_d_review",
        "wait_chapter_acceptance",
        "freeze_a_review",
        "batch_review",
        "wait_length_review",
        "wait_chapter_review",
        "writeback_review",
    )

    _READ_STATUS: dict[str, tuple[str, str, str]] = {
        "source selected": ("导入原文", "已选择原文", "开始导入原文并切分"),
        "segmentation": ("导入原文", "正在导入原文并切分", "完成后可进入阅读"),
        "segmentation running": ("导入原文", "正在导入原文并切分", "完成后可进入阅读"),
        "documents indexed": ("导入原文", "原文已入库", "可以开始阅读建模"),
        "segmentation paused": ("导入原文", "原文导入已暂停，可稍后继续", "从 checkpoint 继续导入原文"),
        "segmentation failed": ("导入原文", "导入原文遇到问题", "查看错误并从 checkpoint 重试"),
        "close_reading": ("阅读", "正在阅读章节", "整理人物、世界观与大纲"),
        "memory extraction": ("阅读", "正在整理人物、世界观与大纲", "完成后可查看建模状态"),
        "summary review ready": ("阅读", "阅读摘要需要检查", "审阅摘要后继续"),
        "memory ready": ("阅读", "阅读记忆已可用", "可以构建知识库或开始续写"),
        "close_read paused": ("阅读", "阅读已暂停，可稍后继续", "从最近 checkpoint 继续阅读"),
    }

    _WRITER_STATUS: dict[str, tuple[str, str, str]] = {
        "artifact saved": ("Writer 分层生成", "已保存你的修改", "保存后仍需确认当前审阅步骤"),
        "checkpoint confirmed": ("Writer 分层生成", "已确认，继续下一步", "系统会进入后续生成阶段"),
        "pending": ("Writer 分层生成", "等待你确认", "确认后继续下一步"),
        "confirmed": ("Writer 分层生成", "已确认，继续下一步", "系统会进入后续生成阶段"),
        "needs_review": ("Writer 分层生成", "需要审阅", "审阅并确认后继续"),
        "blocked_by_modeling": ("Writer 分层生成", "前置建模未完成", "返回导入原文、阅读或知识库流程补齐材料"),
        "initialized": ("Writer 分层生成", "写作流程已初始化", "下一步生成全书续写规划"),
        "agent_running": ("Writer 分层生成", "Writer 正在推进", "等待下一次可审阅产物或正文草稿"),
        "reviewing_artifact": ("Writer 分层生成", "请审阅当前产物", "通过时可补充要求，不通过时请给出调整反馈"),
        "needs_user_input": ("Writer 分层生成", "需要你补充几个关键问题", "回答后继续大纲研究"),
        "generating_draft": ("Writer 分层生成", "正在生成正文草稿", "完成后请验收当前章节"),
        "reviewing_draft": ("Writer 分层生成", "请验收当前章节", "接受后进入写回确认"),
        "outline_research_user_input": ("Writer 分层生成", "需要你补充几个关键问题", "回答后继续大纲研究"),
        "outline_research_blocked": ("Writer 分层生成", "前置建模不足", "先补齐建模材料再继续"),
        "freeze_a_review": ("Writer 分层生成", "请审阅全书续写规划", "确认后生成本批剧情大纲"),
        "freeze_a": ("Writer 分层生成", "全书续写规划已确认", "下一步生成本批剧情大纲"),
        "batch_review": ("Writer 分层生成", "请审阅本批剧情大纲", "确认后生成章节标题与梗概"),
        "Freeze B pending": ("Writer 分层生成", "请审阅本批剧情大纲", "确认后生成章节标题与梗概"),
        "freeze_b": ("Writer 分层生成", "本批剧情大纲已确认", "下一步生成章节标题与梗概"),
        "chapter_review": ("Writer 分层生成", "请审阅章节标题与梗概", "通过后直接整理写作输入并生成正文草稿"),
        "freeze_c": ("Writer 分层生成", "章节梗概已确认", "下一步整理写作输入并生成正文草稿"),
        "wait_length_review": ("Writer 分层生成", "旧长度确认待迁移", "回到章节梗概审阅或正文准备"),
        "length_confirmed": ("Writer 分层生成", "旧长度计划已确认", "下一步整理写作输入并生成正文草稿"),
        "freeze_d_review": ("Writer 分层生成", "旧写作材料确认待迁移", "直接进入正文生成准备"),
        "ready_for_freeze_d": ("Writer 分层生成", "写作输入已准备好", "下一步生成正文草稿"),
        "freeze_d": ("Writer 分层生成", "本章写作输入已准备好", "下一步生成正文草稿"),
        "canon_ready": ("Writer 分层生成", "连续性检查通过", "请验收当前章节"),
        "wait_chapter_acceptance": ("Writer 分层生成", "请验收当前章节", "接受后进入写回确认"),
        "wait_chapter_review": ("Writer 分层生成", "请调整章节规划后重写", "通过后直接重新生成正文草稿"),
        "accepted": ("Writer 分层生成", "已接受本章", "下一步确认写回续写记忆"),
        "rewrite_requested": ("Writer 分层生成", "按反馈重写正文", "基于当前章节梗概重新生成正文"),
        "replan_requested": ("Writer 分层生成", "重做章节规划", "返回章节标题与梗概审阅"),
        "discarded": ("Writer 分层生成", "已作废当前草稿", "流程暂停，稍后可选择恢复点"),
        "writeback_review": ("Writer 分层生成", "请确认写回续写记忆", "确认后更新续写记忆"),
        "writeback_committed": ("Writer 分层生成", "已更新续写记忆", "进入完成状态"),
        "freeze_e": ("Writer 分层生成", "本章已验收", "可以进入下一章或下一批"),
        "completed": ("Writer 分层生成", "本章已完成", "可以进入下一章或下一批"),
        "halted": ("Writer 分层生成", "流程已暂停", "选择恢复点后继续"),
        "ready_for_execution": ("Writer 分层生成", "写作材料已准备好", "可以生成正文草稿"),
        "chapter_executed": ("Writer 分层生成", "正文草稿已生成", "请验收当前章节"),
        "waiting_for_review": ("Writer 分层生成", "需要你审阅后继续", "保存不等于确认，请选择确认动作"),
    }

    _WRITER_STAGE_DESCRIPTIONS: dict[str, str] = {
        "artifact saved": "已保存文件内容；保存只是保留修改，不会自动确认当前审阅节点。",
        "reviewing_artifact": "请审阅当前产物；通过时可补充字数、风格、节奏、重点段落或禁止项，不通过时请说明标题、因果、人物动机、场景顺序或伏笔需要怎样调整。",
        "reviewing_draft": "当前章节草稿已经生成，请决定接受、基于反馈重写、修改章节梗概后重写、作废或稍后继续。",
        "generating_draft": "Writer 正在基于已通过的章节梗概、用户补充和装配上下文生成正文草稿。",
        "outline_research_user_input": "大纲研究发现少量阻塞问题；你的回答会作为用户授权证据进入 planning notebook，不会直接写入正式记忆。",
        "outline_research_blocked": "大纲研究判断前置建模不足；系统不会生成正式全书规划。",
        "freeze_a_review": "系统已生成全书续写方向、世界观补全与人物补充材料。",
        "batch_review": "系统已生成本批剧情大纲；确认后才会据此生成章节标题与梗概。",
        "Freeze B pending": "系统已生成本批剧情大纲；确认后才会据此生成章节标题与梗概。",
        "chapter_review": "系统已生成章节标题、目标、冲突与梗概；通过时可补充字数、风格、节奏、重点描写和禁止项。",
        "wait_length_review": "这是旧 run 的迁移状态；新流程不再要求单独确认长度计划。",
        "freeze_d_review": "这是旧 run 的迁移状态；新流程不再要求单独确认写作材料。",
        "wait_chapter_acceptance": "当前章节草稿已经生成，请决定接受、基于反馈重写、修改章节梗概后重写、作废或稍后继续。",
        "wait_chapter_review": "请修改章节标题与梗概；通过后会直接重新整理写作输入并生成正文。",
        "writeback_review": "请确认本章造成的事实、人物状态与伏笔变化是否写回续写记忆。",
    }

    _WRITER_ACTIONS: dict[str, tuple[WriterStageAction, ...]] = {
        "not_initialized": (
            WriterStageAction("初始化工作流", "initialize"),
            WriterStageAction("生成全书续写规划", "prepare_planning"),
        ),
        "initialized": (WriterStageAction("生成全书续写规划", "prepare_planning"),),
        "outline_research_user_input": (
            WriterStageAction("提交补充回答并继续大纲研究", "continue_after_outline_research_input"),
        ),
        "freeze_a_review": (WriterStageAction("确认全书续写规划", "continue_after_planning_review"),),
        "freeze_a": (WriterStageAction("生成本批剧情大纲", "prepare_batch_plan"),),
        "batch_review": (WriterStageAction("确认本批剧情大纲", "continue_after_batch_review"),),
        "freeze_b": (WriterStageAction("生成章节标题与梗概", "prepare_chapter_package"),),
        "chapter_review": (WriterStageAction("通过章节梗概并继续", "approve_writer_artifact"),),
        "wait_chapter_review": (
            WriterStageAction(
                "通过修改后的章节梗概并继续",
                "approve_writer_artifact",
                "用于“修改章节梗概后重写”的继续路径。",
            ),
        ),
        "wait_length_review": (WriterStageAction("迁移回章节梗概审阅", "approve_writer_artifact"),),
        "length_confirmed": (WriterStageAction("整理本章写作材料", "prepare_execution"),),
        "freeze_d_review": (
            WriterStageAction(
                "迁移到正文生成准备",
                "continue_after_execution_review",
                "旧 run 兼容动作；新流程不会出现独立写作材料确认点。",
            ),
        ),
        "freeze_d": (WriterStageAction("生成当前章草稿", "execute_current_chapter"),),
        "wait_chapter_acceptance": (
            WriterStageAction("接受本章", "accept_chapter", "后续进入写回确认或完成路径。"),
            WriterStageAction("基于反馈重写本章", "rewrite_chapter", "后续基于当前章节梗概重写。"),
            WriterStageAction("修改章节梗概后重写", "replan_chapter", "后续回到章节梗概调整。"),
            WriterStageAction("作废本次草稿", "discard_chapter", "后续暂停流程。"),
        ),
        "writeback_review": (WriterStageAction("确认写回续写记忆", "approve_writeback"),),
    }

    _KB_STATUS: dict[str, tuple[str, str, str]] = {
        "kb_building": ("知识库", "正在构建 Creative KB", "完成后可开始续写"),
        "kb_ready": ("知识库", "Creative KB 已可用", "可以开始续写"),
        "kb_failed": ("知识库", "知识库构建遇到问题", "查看错误并重试失败文档"),
    }

    def present(self, internal_status: str, *, technical_details: Mapping[str, Any] | None = None) -> StatusView:
        normalized = str(internal_status or "").strip()
        flow, step, next_action = self._lookup(normalized)
        details = dict(technical_details or {})
        if normalized:
            details.setdefault("internal_stage", normalized)
        view = StatusView(
            flow=flow,
            step=self._sanitize(step),
            next_action=self._sanitize(next_action),
            message=self._sanitize(self.writer_stage_description(normalized)),
            technical_details=details,
        )
        self.assert_public_text(view.step)
        self.assert_public_text(view.next_action)
        self.assert_public_text(view.message)
        return view

    def present_checkpoint(self, checkpoint: Mapping[str, Any] | None) -> StatusView:
        if not checkpoint:
            return self.present("initialized")
        stage = str(checkpoint.get("stage") or "")
        return self.present(
            stage,
            technical_details={
                "checkpoint_id": checkpoint.get("checkpoint_id", ""),
                "checkpoint_status": checkpoint.get("status", ""),
                "artifact_path": checkpoint.get("artifact_path", ""),
                "source": checkpoint.get("source", ""),
            },
        )

    def present_sidebar(
        self,
        *,
        project: str,
        internal_status: str,
        modeling_ready: Mapping[str, bool] | None = None,
        artifact_path: str = "",
        saved: bool = True,
        run_id: str = "",
        checkpoint_id: str = "",
    ) -> str:
        view = self.present(
            internal_status,
            technical_details={
                "run_id": run_id,
                "checkpoint_id": checkpoint_id,
                "artifact_path": artifact_path,
            },
        )
        lines = [
            f"当前项目  {project or '未选择'}",
            f"当前流程  {view.flow}",
            f"当前步骤  {view.step}",
        ]
        if view.next_action:
            lines.append(f"下一步    {view.next_action}")
        if artifact_path:
            lines.append(f"文件      {Path(artifact_path).name}")
            lines.append(f"状态      {'已保存' if saved else '有未保存修改'}")
        if modeling_ready:
            ready_items = [name for name, ready in modeling_ready.items() if ready]
            missing_items = [name for name, ready in modeling_ready.items() if not ready]
            lines.append(f"建模准备  已完成 {len(ready_items)} 项，待补齐 {len(missing_items)} 项")
        if run_id or checkpoint_id or artifact_path:
            details = ", ".join(
                item
                for item in [
                    f"run id={run_id}" if run_id else "",
                    f"checkpoint={checkpoint_id}" if checkpoint_id else "",
                    f"artifact={artifact_path}" if artifact_path else "",
                ]
                if item
            )
            lines.append(f"技术详情  {details}")
        rendered = "\n".join(lines)
        self.assert_public_text(rendered, allow_technical_details=True)
        return rendered

    def event_message(self, event_name: str, payload: Mapping[str, Any] | None = None) -> str:
        if event_name == "artifact_saved":
            return "已保存你的修改；保存不等于确认，当前审阅步骤仍在等待你确认。"
        if event_name == "confirm_checkpoint":
            next_status = str((payload or {}).get("next_status") or "")
            view = self.present(next_status) if next_status else None
            return f"已确认，下一步：{view.step if view else '继续下一步'}"
        if event_name == "runner_progress":
            return self._runner_progress_message(payload or {})
        return self.present(event_name).step

    def writer_stage_description(self, stage: str) -> str:
        return self._WRITER_STAGE_DESCRIPTIONS.get(str(stage or "").strip(), "")

    def writer_actions_for_stage(self, *, stage: str, pending_stage: str = "") -> tuple[WriterStageAction, ...]:
        active_stage = str(pending_stage or stage or "not_initialized").strip()
        return self._WRITER_ACTIONS.get(active_stage, ())

    def assert_public_text(self, text: str, *, allow_technical_details: bool = False) -> None:
        if allow_technical_details:
            main_text = "\n".join(line for line in text.splitlines() if not line.startswith("技术详情"))
        else:
            main_text = text
        for token in self.FORBIDDEN_PUBLIC_TOKENS:
            if token in main_text:
                raise AssertionError(f"internal token leaked to public UI: {token}")

    def _lookup(self, status: str) -> tuple[str, str, str]:
        if status in self._WRITER_STATUS:
            return self._WRITER_STATUS[status]
        if status in self._READ_STATUS:
            return self._READ_STATUS[status]
        if status in self._KB_STATUS:
            return self._KB_STATUS[status]
        if not status:
            return ("工作台", "等待你选择下一步", "可以查看状态、导入原文、阅读、构建知识库或开始续写")
        return ("工作台", "正在处理当前步骤", "查看技术详情或稍后重试")

    def _sanitize(self, text: str) -> str:
        replacements = {
            "artifact saved": "已保存你的修改",
            "Freeze B pending": "请审阅本批剧情大纲",
            "freeze_d_review": "旧写作材料确认待迁移",
            "wait_chapter_acceptance": "请验收当前章节",
            "checkpoint confirmed": "已确认，继续下一步",
        }
        sanitized = text
        for token, replacement in replacements.items():
            sanitized = sanitized.replace(token, replacement)
        return sanitized

    def _runner_progress_message(self, payload: Mapping[str, Any]) -> str:
        stage = str(payload.get("stage") or payload.get("agent") or "").strip()
        if stage == "segmentation":
            return "正在导入原文并切分"
        if stage == "close_reading":
            indexes = payload.get("document_title_indexes")
            if isinstance(indexes, list) and indexes:
                return f"正在阅读章节 {indexes[0]}-{indexes[-1]}"
            return "正在阅读章节"
        if stage == "creative_kb":
            return "正在构建 Creative KB"
        return "正在处理当前步骤"


class WriterStatusPresenter(StatusPresenter):
    """Writer-specific public presenter shared by CLI and GUI surfaces."""
