from __future__ import annotations

import json
from typing import Any


def build_character_canonical_name_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Canonical Name Agent，只负责为同一个人物档案选择稳定的叙事主称呼。\n"
        "输入中的 candidate_names 都已经被上游判断为同一人物的称谓或别名；你不能判断它们是不是同一个人，也不能发明新名字。\n"
        "选择原则：\n"
        "1. 只能从 candidate_names 中选择 preferred_canonical_name。\n"
        "2. 如果 current_canonical_name 已经是既有人物档案标题，默认保留它；它代表叙事视角中已稳定使用的主称呼，不因后文出现全名、昵称、职业称谓或关系称呼而自动改名。\n"
        "3. 只有新证据明确说明旧标题是误认对象、写错、伪装名或假名时，才可改 preferred_canonical_name，并在 reason 中写明修正依据。\n"
        "4. 关系内称呼（例如老公、老板、某哥、Don 等）应进入 aliases_to_keep 或关系称呼，不应覆盖既有人物标题。\n"
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
