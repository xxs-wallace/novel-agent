from __future__ import annotations

import json
from typing import Any


def build_character_full_roster_prefilter_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Full Roster Prefilter Gate，只负责在完整人物名册中筛出可能与当前 document 人物称呼相关的候选。\n"
        "你不是最终身份判断 Agent；宁可多保留，也不要错删可能相关人物。\n"
        "要求：\n"
        "1. 只根据 document_context、first_pass_request、roster_filter_hints 和 full_roster_index 选择候选。\n"
        "2. 必须保留与正文候选姓名、别名、称谓有词面匹配或强语义匹配的人物。\n"
        "3. 必须保留最近出现且可能与当前人物关系线索相关的人物。\n"
        "4. 对低频、久未出现、无姓名/别名/关系/职业线索命中的人物可以剔除。\n"
        "5. 如果线索不足、风险过高或无法筛选，返回 fallback_to_full_roster=true。\n"
        "6. selected_character_ids 目标不超过 max_candidates，但明显相关者可以超出。\n"
        "7. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "fallback_to_full_roster": false,\n'
        '  "selected_character_ids": ["123"],\n'
        '  "selected_canonical_names": ["角色甲"],\n'
        '  "reason": "一句话说明筛选依据",\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, separators=(",", ":"))
    )
    return system_prompt, user_prompt
