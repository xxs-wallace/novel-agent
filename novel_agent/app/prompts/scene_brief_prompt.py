from __future__ import annotations

import json

from ..schemas.orchestration_schema import CreativeKBRetrievalInput


def build_scene_brief_prompt(
    *,
    retrieval_input: CreativeKBRetrievalInput,
    fallback_scene_brief: dict[str, object],
) -> tuple[str, str]:
    system_prompt = (
        "你是创作知识库在线检索层的 SceneBrief 生成器。\n"
        "你必须把输入上下文压缩为可检索的结构化 SceneBrief，并且只输出严格 JSON。\n"
        "禁止输出解释、分析散文、Markdown 代码块或额外字段。\n"
        "硬性要求：\n"
        "1. 输出字段仅允许 scene_objective, emotional_goal, conflict_goal, narrative_function, emotion_mode, "
        "character_temperament, relationship_state, style_need, must_avoid, preferred_tags。\n"
        "2. scene_objective、narrative_function、emotion_mode、must_avoid 必须非空。\n"
        "3. preferred_tags 仅作为辅助定位，不可替代 narrative_function / emotion_mode / style_need。\n"
        "4. 若证据不足，保守输出，避免编造人物关系或世界设定。\n"
    )
    user_prompt = (
        "请基于输入生成 SceneBrief JSON。\n\n"
        f"anchor_context:\n{retrieval_input.anchor_context.strip()}\n\n"
        f"recent_window_summary:\n{retrieval_input.recent_window_summary.strip()}\n\n"
        f"goal:\n{retrieval_input.goal.strip()}\n\n"
        f"previous_generated_segment:\n{(retrieval_input.previous_generated_segment or '').strip()}\n\n"
        f"retrieval_context:\n{json.dumps(retrieval_input.retrieval_context.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"legacy_scene_plan:\n{json.dumps(retrieval_input.scene_plan, ensure_ascii=False, indent=2)}\n\n"
        "若信息不足，请保守复用 fallback 建议并仅做必要修正。\n"
        f"fallback_scene_brief:\n{json.dumps(fallback_scene_brief, ensure_ascii=False, indent=2)}\n\n"
        "只输出 JSON：\n"
        f"{json.dumps(_scene_brief_example(), ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def _scene_brief_example() -> dict[str, object]:
    return {
        "scene_objective": "续写一段未和解关系中的雨夜停顿与告别前压抑",
        "emotional_goal": "维持克制悲伤，不让情绪直接爆发",
        "conflict_goal": "保持表面平静但不化解核心误解",
        "narrative_function": ["收束", "情绪沉浸"],
        "emotion_mode": ["克制", "悲伤"],
        "character_temperament": ["敏感", "克制"],
        "relationship_state": ["未和解"],
        "style_need": ["短句", "低对白", "高内心密度"],
        "must_avoid": ["突然表白", "设定冲突"],
        "preferred_tags": ["雨天", "告别"],
    }
