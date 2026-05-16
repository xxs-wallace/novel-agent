from __future__ import annotations

import json
from typing import Any


def build_character_evidence_coverage_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Evidence Coverage Agent，只负责复核第一轮人物证据是否漏掉真实人物。\n"
        "你必须同时阅读 chapter_summary、documents 原文、existing_character_evidence 和 existing_character_roster。\n"
        "任务边界：\n"
        "1. 只输出第一轮 evidence 漏掉的真实人物；已经存在于 existing_character_evidence 的人物不要重复输出。\n"
        "2. 不要总结章节，不要更新人物档案，不要输出世界观。\n"
        "3. 如果章节摘要提到某人物，但原文 documents 不能支撑其真实出场/发言/行动/关系变化，不要输出。\n"
        "4. 如果原文中有反复出现、正式行动、明确发言、被称呼或与他人发生关系的人物，而 existing_character_evidence 漏掉了，必须输出。\n"
        "5. existing_character_roster 只用于判断别名/既有人物归并，不是候选名单；roster 外的新人物也应输出。\n"
        "6. 能确认指向既有人物时 canonical_name 使用 roster 中 canonical_name，原文称呼放入 aliases；确认是新人物时 canonical_name 使用原文中最稳定的人物称呼。\n"
        "7. 每个输出人物必须包含 source_doc_ids 和 source_title_indexes；跨多个 document 出现时可以列多个 doc_id。\n"
        "8. candidate_type 使用 character / ambiguous / non_person / object / scene 等短标签；低置信或弱共现候选请标 ambiguous 或不输出。\n"
        "9. 严禁把动词、物品、抽象名词、场景词当人物名。\n"
        "10. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "coverage_gap_found": false,\n'
        '  "coverage_notes": "一句话说明是否发现漏召回，可为空",\n'
        '  "characters": [\n'
        "    {\n"
        '      "canonical_name": "漏掉的人物",\n'
        '      "aliases": [],\n'
        '      "is_speaking_character": true,\n'
        '      "speaking_evidence": "有明确说话归因。",\n'
        '      "personhood_evidence": "被称呼并执行人物行动。",\n'
        '      "activity_or_state_evidence": "参与本章关键行动。",\n'
        '      "relationship_evidence": "与其他人物发生直接互动。",\n'
        '      "source_doc_ids": [1],\n'
        '      "source_title_indexes": [12],\n'
        '      "candidate_type": "character",\n'
        '      "confidence": 0.9,\n'
        '      "uncertainty_reason": ""\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(_coverage_prompt_input(prompt_input), ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def _coverage_prompt_input(prompt_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": prompt_input.get("book_id"),
        "chapter_summary": prompt_input.get("chapter_summary", {}),
        "character_evidence_batch": prompt_input.get("character_evidence_batch", {}),
        "existing_character_evidence": prompt_input.get("existing_character_evidence", {}),
        "existing_character_roster": prompt_input.get("existing_character_roster", []),
    }
