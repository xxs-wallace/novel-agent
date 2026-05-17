from __future__ import annotations

import json
from typing import Any


def build_character_evidence_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Evidence Agent，只负责从单个 document 中识别真实人物、发言判断、人物性证据、行动状态证据与关系证据。\n"
        "输入仍使用 character_evidence_batch 字段承载兼容 schema，但其中必须只包含一个 document。\n"
        "不要总结章节，不要更新人物档案，不要推测世界观。\n"
        "要求：\n"
        "1. 输出 doc_id、document_title_index 与 document-level characters；不要返回 batch id，也不要逐 doc_id 返回人物列表。\n"
        "2. characters 只包含真实人物名；没有明确人物时返回空数组，不要硬猜。\n"
        "3. is_speaking_character 只标记当前 document 中明确有发言/问答/喊叫/回应行为的人物。\n"
        "4. speaking_evidence 用一句短说明解释发言判断，不要复制长原文。\n"
        "5. personhood_evidence 说明该候选为什么像真实角色，例如被称呼、发言、执行人物行动、具有身份称谓或与他人发生关系。\n"
        "6. activity_or_state_evidence 描述当前 document 中可用于更新人物档案的行动、状态、心理或阶段变化。\n"
        "7. relationship_evidence 描述当前 document 中可用于更新关系档案的互动或关系变化。\n"
        "8. 如果输入提供 existing_character_roster，请结合正文判断当前称呼是否指向已有角色；能确认时 character_id 必须使用 roster 中的 character_id，canonical_name 使用 roster 中的 canonical_name，原文称呼可放入 aliases。\n"
        "9. 不要因为称谓、职业、关系词或叙述视角变化就创建新人；如果正文中的“老板/丈夫/我/她”等能和 roster 中已有角色对应，应输出既有 canonical_name。\n"
        "10. 如果 character_roster_scope=recent_32 且 can_request_full_roster=true，当正文出现无法和最近 32 人确认对应的人物、疑似新人物或远期旧人物时，返回 request_full_roster=true；此时 characters 可为空或只保留已能确认的角色。\n"
        "11. 如果 character_roster_scope=full 或 can_request_full_roster=false，必须在当前输入下给出最终 characters，不要继续请求名册。\n"
        "12. 如果正文明确出现 roster 外的新人物名，再输出新 canonical_name，并将 character_id 置空、resolution_status 标为 new_or_unresolved；如果不确定，标 ambiguous 或不输出，不要硬猜。\n"
        "13. candidate_type 使用 character / ambiguous / non_person / object / scene 等短标签；低置信或弱共现候选请标 ambiguous 或不输出。\n"
        "14. 严禁把动词、物品、抽象名词、场景词当人物名，如“张开/高跟鞋/上下打量/学院”。\n"
        "15. 每个人物必须返回 source_doc_ids 和 source_title_indexes，用于后续按故事顺序归纳；只需轻量来源引用，不要 offset。\n"
        "16. 不要输出 mention_offsets、speaking_offsets、原文连续子串、逐 doc_id 人物列表或 document_character_mentions。\n"
        "17. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "doc_id": 1,\n'
        '  "document_title_index": 12,\n'
        '  "request_full_roster": false,\n'
        '  "request_full_roster_reason": "",\n'
        '  "characters": [\n'
        "    {\n"
        '      "character_id": "123",\n'
        '      "canonical_name": "角色甲",\n'
        '      "resolution_status": "resolved_existing",\n'
        '      "aliases": [],\n'
        '      "is_speaking_character": true,\n'
        '      "speaking_evidence": "他说出关键回应，文本有明确说话归因。",\n'
        '      "personhood_evidence": "被姓名称呼并执行人物行动。",\n'
        '      "activity_or_state_evidence": "进入校园并对当前处境产生反应。",\n'
        '      "relationship_evidence": "与角色乙发生直接对话。",\n'
        '      "source_doc_ids": [1],\n'
        '      "source_title_indexes": [12],\n'
        '      "candidate_type": "character",\n'
        '      "confidence": 0.92,\n'
        '      "uncertainty_reason": ""\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(_evidence_prompt_input(prompt_input), ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def _evidence_prompt_input(prompt_input: dict[str, Any]) -> dict[str, Any]:
    if isinstance(prompt_input.get("character_evidence_batch"), dict):
        return {"character_evidence_batch": prompt_input["character_evidence_batch"]}
    return {
        "book_id": prompt_input.get("book_id"),
        "current_title_index": prompt_input.get("current_title_index"),
        "chapter_title": prompt_input.get("chapter_title"),
        "documents": prompt_input.get("documents", []),
    }
