from __future__ import annotations

from .model_only import ModelOnlyReviewer


class KBDraftStyleAtmosphereReviewer(ModelOnlyReviewer):
    reviewer_id = "kb_draft_style_atmosphere"
    display_name_zh = "文笔与氛围评审"
    supported_target_types = {"draft", "raw_text"}
    allowed_tools = ["kb_retrieval"]
    dimensions = ["文笔细节", "氛围", "节奏", "叙述视角", "风格一致性"]
    default_budget = {
        "max_model_calls": 6,
        "max_tool_calls": 4,
        "max_memory_query_rounds": 0,
        "max_kb_query_rounds": 3,
        "max_target_chars": 12000,
        "max_context_chars": 16000,
        "max_findings": 10,
        "json_repair_attempts": 1,
    }
    focus_zh = "先总结目标草稿的剧情、场景、叙事功能和情绪基调，再用 KB 相似段落比较文笔细节、文风和氛围。"
    boundary_zh = "不把 KB 相似段落当作剧情正确性标准，不查询 Memory，不做人物历史一致性裁决。"
    context_guidance_zh = "相似桥段或风格参考只能通过 kb_retrieval 请求 ReviewerKBTool；比较范围限于文笔、文风、氛围和细节执行。"
