from __future__ import annotations

from .model_only import ModelOnlyReviewer


class OutlinePlotDevelopmentReviewer(ModelOnlyReviewer):
    reviewer_id = "outline_plot_development"
    display_name_zh = "大纲剧情发展评审"
    supported_target_types = {"outline"}
    allowed_tools = ["artifact_read", "memory_query"]
    dimensions = ["剧情承接", "阶段推进", "因果链", "长期结构", "主支线落点"]
    default_budget = {
        "max_model_calls": 6,
        "max_tool_calls": 4,
        "max_memory_query_rounds": 2,
        "max_kb_query_rounds": 0,
        "max_target_chars": 12000,
        "max_context_chars": 14000,
        "max_findings": 10,
        "json_repair_attempts": 1,
    }
    focus_zh = "结合已授权的前序大纲、篇章地图或 Memory 事件线索，评估目标大纲的剧情发展合理性、阶段推进和长期结构。"
    boundary_zh = "不评价正文文笔，不把参考评分当作 Writer 或 benchmark 的质量裁决。"
    context_guidance_zh = "优先读取授权的前序 outline artifact；如需要历史事件证据，只能请求 memory_query。"
