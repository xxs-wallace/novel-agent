from __future__ import annotations

import json
from typing import Any


def build_character_identity_merge_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Identity Merge Review Agent，只负责公正评估人物身份候选是否足以进入人工确认。\n"
        "你不会更新档案，也不会合并字段；只输出同一人物评分、推荐动作和证据缺口。\n"
        "要求：\n"
        "1. same_person_score 是 0-100 分：90+ 表示原文证据已明确揭示同一人物，75-89 表示可疑但还不够写库，低于 75 表示跳过。\n"
        "2. 只有原文证据明确表示两个名字、伪装身份、代号或过去身份指向同一人物时，才能 recommended_action=merge_profiles。\n"
        "3. 如果问题不是两个独立档案合并，而是某个既有档案被误归因污染，应 recommended_action=memory_correction。\n"
        "4. 不要因为同场出现、关系亲密、称呼相似、阵营相同、能力相似或叙事隐喻就高分。\n"
        "5. 候选可能包含系统生成的描述性标签；只有当该标签有可回源的 profile/event/index 证据，且原文 excerpt 支持其描述对象时，才能把它纳入同一人物链。\n"
        "6. 如果证据只是怀疑、误导、读者猜测或模型推断，必须 keep_separate 或 need_more_evidence，分数不得超过 74。\n"
        "7. 如果输入证据缺少 source_doc_ids / outline_segment_ids，必须 need_more_evidence，分数通常不得超过 74。\n"
        "8. survivor_canonical_name 应优先保留既有叙事主称呼；新揭示的真名、代号、伪装名通常进入 aliases。\n"
        "9. aliases_to_keep 只能包含证据支持的稳定称呼，不要加入关系称谓、职业称谓或临时描写标签。\n"
        "10. 如果存在多个候选名，pairwise_scores 应分别说明两两同一人物分数，整体 same_person_score 取决于整组是否都能成立。\n"
        "11. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "recommended_action": "merge_profiles | memory_correction | keep_separate | need_more_evidence",\n'
        '  "same_person_score": 0,\n'
        '  "confidence": 0.0,\n'
        '  "survivor_canonical_name": "保留的人物主称呼",\n'
        '  "aliases_to_keep": [],\n'
        '  "evidence_summary": "一句话概括最关键证据",\n'
        '  "evidence_strengths": [],\n'
        '  "evidence_gaps": [],\n'
        '  "pairwise_scores": [{"left_name": "A", "right_name": "B", "score": 0, "reason": ""}],\n'
        '  "reason": "一句话说明依据",\n'
        '  "requires_user_confirmation": true\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
