from __future__ import annotations

import json
from typing import Any


def build_memory_candidate_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Memory Update Candidate Agent。\n"
        "你不读取全文原文，只基于章节摘要、人物证据、世界观概要、故事大纲和已有人物档案，"
        "输出长期 Memory 的更新候选。\n"
        "要求：\n"
        "1. character_updates 只写真实角色的事实、状态、关系变化；不要写桥段写法偏好。\n"
        "2. 人物更新主要依据 character_evidence_batches 中的发言判断、人物性证据、行动状态证据和关系证据。\n"
        "3. 低置信、candidate_type 为 non_person/object/scene/abstract/weak_cooccurrence 的候选必须降权或丢弃。\n"
        "4. world_update 只写稳定设定增量，分区限定为：世界类型、时代背景、能力体系、超自然要素、阵营势力、核心禁忌与规则。\n"
        "5. outline_update.chapter_line 优先概括主线推进、关键转折和不可逆事件。\n"
        "6. Memory Update Agent 后续只消费你输出的候选事实；不要要求它理解 Character Evidence prompt、offset 或原文连续证据。\n"
        "7. 如果证据不足，请返回空数组或 should_update=false，不要补全。\n"
        "8. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "world_update": {"should_update": false, "changes": [{"section": "能力体系", "summary": "新增/修正内容", "evidence": "证据"}]},\n'
        '  "character_updates": [{"canonical_name": "角色甲", "aliases": [], "personality": [], "occupations": [], "age_update": null, "abilities": [], "recent_activity": "", "relationships": []}],\n'
        '  "outline_update": {"chapter_line": "[12] 章节名: 本章发生了什么", "timeline_events": [{"label": "事件名", "participants": ["角色甲"], "summary": "事件概括"}]}\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
