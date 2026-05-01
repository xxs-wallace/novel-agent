from __future__ import annotations

import json

from ..schemas.creative_kb_schema import FragmentCard, SceneBrief


def build_rerank_prompt(
    *,
    scene_brief: SceneBrief,
    candidates: list[FragmentCard],
    anchor_context: str,
    recent_window_summary: str,
    top_n: int,
) -> tuple[str, str]:
    system_prompt = (
        "你是创作知识库在线检索层的高精度 rerank 助手。\n"
        "你必须使用固定 rubric 对候选 fragment_cards 打分，并且只输出严格 JSON。\n"
        "禁止输出解释、散文、Markdown 代码块或额外字段。\n"
        "Rubric 维度必须包含：continuity_fit, scene_function_fit, character_temperament_fit, "
        "relationship_state_fit, emotion_expression_fit, style_fit, transferability, "
        "context_dependency_penalty, final_score, reason。\n"
        "重要约束：\n"
        "1. continuity_fit 等 7 个 fit/transferability 分值必须是 0-10 的整数。\n"
        "2. context_dependency_penalty 必须是 0-10 的整数，数值越高表示惩罚越强。\n"
        "3. final_score 必须是 0-10 的数值。\n"
        "4. selected_fragment_ids 长度必须在 1-4。\n"
        "5. 默认不允许同一 cluster_id 重复入选；如候选同簇，优先代表片段。\n"
        "6. preferred_tags 只是弱辅助信号，不可作为主排序依据；主排序依据应来自 scene function、情绪机制、关系状态、风格与可迁移性。\n"
    )
    user_prompt = (
        "请基于以下检索意图和候选列表输出 rerank JSON。\n\n"
        f"scene_brief:\n{json.dumps(scene_brief.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"anchor_context:\n{anchor_context.strip()}\n\n"
        f"recent_window_summary:\n{recent_window_summary.strip()}\n\n"
        f"top_n: {top_n}\n\n"
        "candidate_fragment_cards:\n"
        f"{json.dumps([_candidate_payload(item) for item in candidates], ensure_ascii=False, indent=2)}\n\n"
        "只输出 JSON：\n"
        f"{json.dumps(_rerank_example(), ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def _candidate_payload(candidate: FragmentCard) -> dict[str, object]:
    return {
        "fragment_id": candidate.fragment_id,
        "cluster_id": candidate.cluster_id,
        "is_cluster_representative": candidate.is_cluster_representative,
        "content_summary": candidate.content_summary,
        "narrative_function": candidate.narrative_function,
        "narrative_function_text": candidate.narrative_function_text,
        "emotion_tags": candidate.emotion_tags,
        "emotion_mechanism_text": candidate.emotion_mechanism_text,
        "character_temperament": candidate.character_temperament,
        "relationship_state": candidate.relationship_state,
        "preferred_tags": candidate.preferred_tags,
        "style_profile_text": candidate.style_profile_text,
        "source_excerpt": candidate.source_excerpt,
        "transferability_score": candidate.transferability_score,
        "context_dependency_level": candidate.context_dependency_level,
    }


def _rerank_example() -> dict[str, object]:
    return {
        "scores": [
            {
                "candidate_id": "fragment-1",
                "cluster_id": "cluster-a",
                "continuity_fit": 8,
                "scene_function_fit": 9,
                "character_temperament_fit": 8,
                "relationship_state_fit": 8,
                "emotion_expression_fit": 9,
                "style_fit": 8,
                "transferability": 9,
                "context_dependency_penalty": 2,
                "final_score": 8.46,
                "reason": "叙事功能、情绪机制、关系状态都高度贴合，且上下文依赖较低。",
            }
        ],
        "selected_fragment_ids": ["fragment-1"],
        "selection_notes": "固定 rubric rerank，默认按 cluster 去重并优先代表片段。",
    }
