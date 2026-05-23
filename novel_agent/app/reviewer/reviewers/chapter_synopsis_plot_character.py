from __future__ import annotations

from .model_only import ModelOnlyReviewer


class ChapterSynopsisPlotCharacterReviewer(ModelOnlyReviewer):
    reviewer_id = "chapter_synopsis_plot_character"
    display_name_zh = "章节梗概剧情与人物评审"
    supported_target_types = {"chapter_brief", "synopsis"}
    allowed_tools = ["memory_query"]
    dimensions = ["剧情目标", "事件推进", "人物动机", "关系状态", "正文指导性"]
    default_budget = {
        "max_model_calls": 6,
        "max_tool_calls": 6,
        "max_memory_query_rounds": 4,
        "max_kb_query_rounds": 0,
        "max_target_chars": 10000,
        "max_context_chars": 16000,
        "max_findings": 12,
        "json_repair_attempts": 1,
    }
    focus_zh = "从章节梗概或 chapter_brief 中抽取人物、行动、关系、状态变化和关键事件，评估剧情合理性与人物一致性。"
    boundary_zh = "不评价正文文笔，不做全文大纲方向裁决，不臆造人物档案。"
    context_guidance_zh = "人物档案、关系状态和历史行动只能通过 memory_query 请求 ReviewerMemoryTool；证据不足必须明说。"
