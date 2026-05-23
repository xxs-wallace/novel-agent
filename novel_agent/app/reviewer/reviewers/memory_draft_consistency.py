from __future__ import annotations

from .model_only import ModelOnlyReviewer


class MemoryDraftConsistencyReviewer(ModelOnlyReviewer):
    reviewer_id = "memory_draft_consistency"
    display_name_zh = "正文与记忆一致性评审"
    supported_target_types = {"draft"}
    allowed_tools = ["memory_query"]
    dimensions = ["历史事件一致性", "人物状态", "关系状态", "设定约束", "时间线"]
    default_budget = {
        "max_model_calls": 6,
        "max_tool_calls": 8,
        "max_memory_query_rounds": 4,
        "max_kb_query_rounds": 0,
        "max_target_chars": 12000,
        "max_context_chars": 18000,
        "max_findings": 12,
        "json_repair_attempts": 1,
    }
    focus_zh = "先抽取草稿中的事件、人物、地点、关系、设定和状态 claims，再用 Memory 证据核查历史一致性。"
    boundary_zh = "不评价整体文笔，不评价全文大纲方向，不把缺少证据的推测写成确认矛盾。"
    context_guidance_zh = "所有历史证据只能通过 memory_query 请求 ReviewerMemoryTool；必须区分确认矛盾和证据不足。"
