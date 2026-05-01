from __future__ import annotations

import json
from typing import Any


def build_global_memory_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Global Memory Agent，只负责把章节摘要和世界观候选归纳为长期世界观更新候选。\n"
        "你默认不读取全文原文；输入里不应包含 documents 原文。\n"
        "要求：\n"
        "1. 只输出 world_update；不要输出 character_updates，不要归纳人物档案。\n"
        "2. world_update 只写稳定设定增量，分区限定为：世界类型、时代背景、能力体系、超自然要素、阵营势力、核心禁忌与规则。\n"
        "3. 按 source_doc_ids/source_title_indexes 的阅读顺序合并候选，避免重复、冲突和弱证据写入。\n"
        "4. 如果候选不足或只是普通剧情/人物动作，请返回 should_update=false。\n"
        "5. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "world_update": {"should_update": false, "changes": [{"section": "能力体系", "summary": "新增/修正内容", "evidence": "证据"}]}\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
