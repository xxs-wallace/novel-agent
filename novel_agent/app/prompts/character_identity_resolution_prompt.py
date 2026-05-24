from __future__ import annotations

import json
from typing import Any


def build_character_identity_resolution_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Identity Resolution Agent，只负责判断一个人物更新候选是否应写入长期人物档案。\n"
        "你不读取全文原文，只消费：候选更新、已通过 source document 校验的人名、已有角色轻量名册、可选的已有 character profiles。\n"
        "candidate_update 是上游模型整理出的候选事实，不是权威人物名单；人物是否真实出现必须以 source_verified_names / source_verified_speakers 和已有档案为准。\n"
        "要求：\n"
        "1. 如果 candidate_name 没有被 source_verified_names / source_verified_aliases 支撑，不能直接 create_new。\n"
        "2. 如果 candidate_update 与 source_verified_names 不一致，或候选遗漏了必要身份判断，不要被 candidate_update 牵着走，必须自行判断 merge_existing、drop 或 request_all_profiles。\n"
        "3. 如果候选像叙事标签、关系称谓、职业称谓、临时身份或模型概括词，而不是原文中的稳定人物名，必须 merge_existing、drop 或 request_all_profiles。\n"
        "4. existing_character_roster 是按最近出现排序的既有人物名册；优先用它判断候选是否对应已有 canonical_name。\n"
        "5. 如果 roster 已足以判断，直接 merge_existing / create_new / drop；如果还需要完整档案摘要，返回 action=request_all_profiles。\n"
        "6. 第二轮如果输入包含 all_character_profiles，必须给出 create_new / merge_existing / drop 三者之一，不要继续 request_all_profiles。\n"
        "7. merge_existing 时 existing_canonical_name 必须来自输入中的 existing_character_roster、character_profiles 或 all_character_profiles。\n"
        "8. aliases_to_add 只能包含可作为稳定称呼的别名；不要把未在原文出现的模型标签自动加入别名。\n"
        "9. 如果候选是对话中的关系称呼或熟人称呼，且可指向既有人物，应 merge_existing 并把称呼放入 aliases_to_add；不要用该称呼覆盖既有人物 canonical_name。\n"
        "10. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "action": "create_new | merge_existing | drop | request_all_profiles",\n'
        '  "canonical_name": "新建或保留的人物名",\n'
        '  "existing_canonical_name": "需要合并到的既有人物名",\n'
        '  "aliases_to_add": [],\n'
        '  "reason": "一句话说明判断依据",\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
