from __future__ import annotations

import json
from typing import Any


def build_world_evidence_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 World Evidence Agent，只负责从 documents 中抽取世界观/规则/势力/能力/禁忌证据。\n"
        "不要总结章节，不要更新人物档案，不要写人物关系。\n"
        "要求：\n"
        "1. 只输出 world_evidence_candidates 和 world_signal_score。\n"
        "2. candidates 只记录稳定设定，不记录普通人物行动、情绪或一次性桥段。\n"
        "3. section 只能使用：世界类型、时代背景、能力体系、超自然要素、阵营势力、核心禁忌与规则。\n"
        "4. 每个候选必须带 source_doc_ids、source_title_indexes 和 confidence。\n"
        "5. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "world_signal_score": 0,\n'
        '  "world_evidence_candidates": [{"section": "能力体系", "summary": "稳定设定候选", "evidence_hint": "简短证据说明", "source_doc_ids": [1], "source_title_indexes": [12], "confidence": 0.8}]\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
