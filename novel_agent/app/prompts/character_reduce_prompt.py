from __future__ import annotations

import json
from typing import Any


def build_character_reduce_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Reduce Agent，只负责归纳一个真实人物的长期人物档案更新候选。\n"
        "你不会读取全文原文，只消费按 doc_id 顺序排列的人物 evidence、章节摘要和已有 profile。\n"
        "要求：\n"
        "1. 只输出当前 canonical_name 对应人物的 character_update；不要处理其他人物、世界观或大纲。\n"
        "2. 同一人物跨多个 documents 的状态、行动和关系必须按 source_doc_ids 的故事顺序归纳。\n"
        "3. relationships 在人物内直接归并，避免同义重复；证据不足时返回空数组。\n"
        "4. 不要补全没有证据的性格、年龄、职业、能力或关系。\n"
        "5. 如果证据不足以写入长期档案，返回 should_update=false 且 character_update=null。\n"
        "6. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "should_update": true,\n'
        '  "canonical_name": "角色甲",\n'
        '  "character_update": {"canonical_name": "角色甲", "aliases": [], "personality": [], "occupations": [], "age_update": null, "abilities": [], "recent_activity": "", "relationships": [], "evidence_level": "inferred", "is_speaking_character": false, "speaking_character_status": "personhood_supported", "speaking_evidence": "", "personhood_evidence_summary": "", "activity_or_state_evidence": "", "relationship_evidence": ""}\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
