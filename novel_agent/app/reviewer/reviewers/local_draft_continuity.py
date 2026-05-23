from __future__ import annotations

from .model_only import ModelOnlyReviewer


class LocalDraftContinuityReviewer(ModelOnlyReviewer):
    reviewer_id = "local_draft_continuity"
    display_name_zh = "局部正文连续性评审"
    supported_target_types = {"draft"}
    allowed_tools = ["artifact_read"]
    dimensions = ["局部承接", "剧情动作连续性", "场景衔接", "叙事视角", "文风过渡"]
    default_budget = {
        "max_model_calls": 5,
        "max_tool_calls": 3,
        "max_memory_query_rounds": 0,
        "max_kb_query_rounds": 0,
        "max_target_chars": 12000,
        "max_context_chars": 10000,
        "max_findings": 10,
        "json_repair_attempts": 1,
    }
    focus_zh = "结合目标中包含的最近正文窗口、最新草稿和授权 artifact，评估局部剧情承接、场景衔接和文风过渡。"
    boundary_zh = "默认不读取全文大纲，不做全局剧情方向裁决，不评价与局部衔接无关的历史设定。"
    context_guidance_zh = "最近上下文通常由 ReviewTarget 或授权 artifact 提供；如无上下文，只能降低置信度并说明证据不足。"
