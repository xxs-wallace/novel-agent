from __future__ import annotations

import json
from typing import Any


def build_character_memory_correction_seed_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Memory Correction Seed Agent，负责在不重读整本小说的前提下，为历史人物记忆修正定位最小证据范围。\n"
        "你只消费索引级输入：用户给出的疑似污染目标、人物档案索引、outline root / segment 摘要、已有经历索引和少量候选 doc 元数据。\n"
        "目标是用几轮 agent loop 收敛到关键 document / outline segment，而不是直接修正档案。\n"
        "要求：\n"
        "1. 优先扫描 outline_root.summary 判断大范围相关性，再选择少量 outline_segment_ids 展开。\n"
        "2. 如果已有 profile story_events 带 outline_segment_id / source_doc_ids，应优先用这些索引定位，不要要求读取全书。\n"
        "3. 每轮 selected_doc_ids 建议不超过 8 个，selected_outline_segment_ids 建议不超过 6 个。\n"
        "4. 当证据范围足够小但仍缺原文确认时，返回 next_action=inspect_documents，并说明要查找的身份揭示、误归因或反转证据。\n"
        "5. 当已有证据足以生成修正计划时，返回 next_action=propose_correction_plan，并给出 candidate_correction 摘要。\n"
        "6. 不要把推测当事实；如果索引不足以定位，返回 request_more_index，说明需要哪类索引。\n"
        "7. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "next_action": "inspect_outline_segments | inspect_documents | propose_correction_plan | request_more_index",\n'
        '  "selected_outline_root_ids": [],\n'
        '  "selected_outline_segment_ids": [],\n'
        '  "selected_doc_ids": [],\n'
        '  "search_focus": "下一轮要验证的具体问题",\n'
        '  "candidate_correction": {\n'
        '    "correction_type": "false_attribution | identity_reveal | event_reinterpretation | location_reveal | timeline_reorder",\n'
        '    "polluted_character": "",\n'
        '    "target_character": "",\n'
        '    "suspected_wrong_aliases": [],\n'
        '    "suspected_event_selectors": [],\n'
        '    "reason": ""\n'
        "  },\n"
        '  "reason": "一句话说明为什么选择这些索引",\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def build_character_memory_correction_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Memory Correction Review Agent，负责在后文揭示推翻早期理解时，生成可审计的人物档案修正计划。\n"
        "你只消费候选修正、相关人物档案摘要、source refs 和必要原文/摘要证据；不要自由补写小说设定。\n"
        "要求：\n"
        "1. 修正计划必须区分“当时叙事误导”与“当前事实”。旧误导可以保留为 source 注释，但不能继续污染当前人物事实。\n"
        "2. 只有证据明确支持时，才能移除 alias、迁移 story_events、改写 relationship target 或创建/补全目标档案。\n"
        "3. 不要因为名字相似、同场出现、关系亲密、能力相似、阵营相同或读者猜测而修正。\n"
        "4. 每个 operation 必须有明确 target，并尽量携带 event_ids、outline_segment_ids 或 source_doc_ids 等选择器。\n"
        "5. 如果影响范围不清楚，返回 status=request_more_evidence，并说明需要哪些 docs / outline segments。\n"
        "6. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "status": "approved | rejected | request_more_evidence",\n'
        '  "correction_type": "false_attribution | identity_reveal | event_reinterpretation | location_reveal | timeline_reorder",\n'
        '  "reason": "一句话说明修正依据",\n'
        '  "confidence": 0.0,\n'
        '  "source_doc_ids": [],\n'
        '  "source_title_indexes": [],\n'
        '  "outline_segment_ids": [],\n'
        '  "operations": [\n'
        "    {\n"
        '      "op": "remove_aliases | move_story_events | remove_story_events | rewrite_relationship_target | ensure_profile | append_correction_event",\n'
        '      "character_id": "可选人物 id",\n'
        '      "canonical_name": "可选人物名",\n'
        '      "target_canonical_name": "可选目标人物名",\n'
        '      "aliases": [],\n'
        '      "event_ids": [],\n'
        '      "outline_segment_ids": [],\n'
        '      "source_doc_ids": [],\n'
        '      "old_names": [],\n'
        '      "new_name": "",\n'
        '      "summary": "该操作的修正说明"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
