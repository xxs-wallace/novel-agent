from __future__ import annotations

from .model_only import ModelOnlyReviewer


class SourceChapterLiteraryDiagnosticReviewer(ModelOnlyReviewer):
    reviewer_id = "source_chapter_literary_diagnostic"
    reviewer_version = "0.1.0"
    display_name_zh = "原文章节文学与人物诊断"
    supported_target_types = {"source_chapter"}
    allowed_tools = ["memory_query"]
    dimensions = ["文学执行", "人物契合", "人物特点体现", "连续性与因果", "证据置信度"]
    default_budget = {
        "max_model_calls": 6,
        "max_tool_calls": 10,
        "max_memory_query_rounds": 4,
        "max_kb_query_rounds": 0,
        "max_target_chars": 65536,
        "max_context_chars": 65536,
        "max_findings": 14,
        "json_repair_attempts": 1,
    }
    focus_zh = (
        "完整阅读用户选择的已入库原文章节，评价原作者该段在文学性、章节功能、节奏、冲突、"
        "情绪曲线、主题表达、人物塑造和人物特点体现上的优缺点；结合 Memory 中人物档案、"
        "人物状态卡、章节摘要和必要的历史原文摘录判断是否与前文人物塑造冲突。"
    )
    boundary_zh = (
        "不做 close-read 建模，不写回 Memory、人物档案或 Writer artifact；不把人物张力直接等同于写崩，"
        "必须区分明确矛盾、可解释张力、人物特点表达不足和证据不足。"
    )
    context_guidance_zh = (
        "先从目标章节中抽取人物、关系、事件、情绪转折和待核查问题；Memory 证据只能通过 memory_query 请求。"
        "tool_requests 可以在 budget 中声明 request_type，例如 character_profile、character_state_card_search、"
        "story_detail、chapter_summary、theme_signal_card_search、source_arc 或 raw_excerpt。"
        "只有摘要层不足以判断人物语气、关系张力、关键行动、伏笔措辞或前文铺垫时，才请求 raw_excerpt；"
        "raw_excerpt 必须携带 read_reason、expected_confirmation、affects_analysis，并尽量提供 document_ids、"
        "source_doc_ids 或 chapter_refs。目标原文不得超过 64KB，目标原文与历史原文摘录合计不得超过 128KB；"
        "若证据超预算，应把低优先级历史原文压缩为带来源的结论摘要，并在报告中降低置信度。"
    )
