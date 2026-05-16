from __future__ import annotations

import json
from typing import Any


def build_character_canonical_name_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Canonical Name Agent，只负责为同一个人物档案选择最适合作为百科标题的名字。\n"
        "输入中的 candidate_names 都已经被上游判断为同一人物的称谓或别名；你不能判断它们是不是同一个人，也不能发明新名字。\n"
        "选择原则：\n"
        "1. 只能从 candidate_names 中选择 preferred_canonical_name。\n"
        "2. 优先选择最像正式姓名/全名/稳定称呼的名字；如果有全名，通常优先于关系称谓、职业称谓、代词、叙事标签、昵称和临时称呼。\n"
        "3. 每次新剧情带来新称谓或别名时，都要重新评估；如果新证据显示旧标题是假名、误认对象、伪装名或临时称呼，可以选择新出现的更正式姓名替换旧标题。\n"
        "4. 如果没有足够信息证明哪个更正式，保留 current_canonical_name。\n"
        "5. aliases_to_keep 应包含其余仍可作为检索别名的称谓；不要加入 candidate_names 之外的内容。\n"
        "6. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "preferred_canonical_name": "必须来自 candidate_names",\n'
        '  "aliases_to_keep": [],\n'
        '  "reason": "一句话说明为什么这个名字更适合作为标题",\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
