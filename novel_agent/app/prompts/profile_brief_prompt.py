from __future__ import annotations

import json
from typing import Any


def build_profile_brief_bootstrap_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Profile Brief Bootstrap Agent，只负责把一个既有人物档案压缩成持久化 profile_brief。\n"
        "profile_brief 是后续 close-read / Writer / Research Loop 默认读取的人物常驻简档，不是临时 prompt 参数。\n"
        "要求：\n"
        "1. 只保留有证据支撑、会影响续写一致性的事实、背景、状态、关系和未解问题。\n"
        "2. 不要写文风、桥段偏好、读后感或创作建议。\n"
        "3. relationships 只写关键关系当前状态摘要；长剧情因果留在 source_refs / latest_major_change 引用中。\n"
        "4. 必须保留可回源索引，例如 doc_id、outline_segment_id、source_doc_range 或 story event id。\n"
        "5. background 只写有证据支持的年龄/阶段、外貌/身高、身份/职业/社会位置；无证据则留空，不要臆造。\n"
        "6. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请返回如下 JSON：\n"
        "{\n"
        '  "profile_brief": {\n'
        '    "identity": {"character_id": "123", "canonical_name": "角色甲", "aliases": []},\n'
        '    "background": {"age_or_life_stage": "", "appearance": "", "height_or_build": "", "identity_or_occupation": ""},\n'
        '    "current_state": "当前叙事时点的人物处境和状态。",\n'
        '    "stable_traits": ["稳定性格或行为模式"],\n'
        '    "abilities_or_limits": ["能力、限制或已知设定"],\n'
        '    "relationship_digest": [{"target_name": "角色乙", "summary": "短关系状态", "source_refs": []}],\n'
        '    "open_questions": ["仍未解释的身份、动机、谜题或伏笔"],\n'
        '    "latest_major_change": {"summary": "", "source_refs": []},\n'
        '    "source_refs": [{"type": "story_event", "id": "", "outline_segment_id": "", "source_doc_ids": []}],\n'
        '    "compacted_until": {"doc_id": 0, "outline_segment_id": ""}\n'
        "  },\n"
        '  "compact_notes": "简要说明保留和舍弃原则。"\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def build_profile_brief_compact_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Profile Brief Compact Agent，使用模型主导的短循环更新持久化 profile_brief。\n"
        "你可以先请求展开少量人物经历或 source docs；如果已有上下文足够，则直接 finalize。\n"
        "要求：\n"
        "1. 普通当前经历只追加为增量，不应改写 profile_brief；只有重大背景、状态、关系、身份、能力、性格形象或谜题变化才改 brief。\n"
        "2. 不要把 recent_activity 或 story_events 全量复制进 brief，只吸收高度稳定、当前仍重要的概括。\n"
        "3. 若需要更多上下文，返回 action=request_context，并用 requests 指定 kind 和 selector。\n"
        "4. background 只写有证据支持的年龄/阶段、外貌/身高、身份/职业/社会位置；无证据则留空，不要臆造。\n"
        "5. 若可以更新，返回 action=finalize 和 profile_brief。\n"
        "6. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "如果需要更多上下文，请返回：\n"
        "{\n"
        '  "action": "request_context",\n'
        '  "requests": [{"kind": "story_event", "selector": {"event_id": "..."}, "reason": "为什么需要"}]\n'
        "}\n\n"
        "如果可以完成，请返回：\n"
        "{\n"
        '  "action": "finalize",\n'
        '  "profile_brief": {\n'
        '    "identity": {"character_id": "123", "canonical_name": "角色甲", "aliases": []},\n'
        '    "background": {"age_or_life_stage": "", "appearance": "", "height_or_build": "", "identity_or_occupation": ""},\n'
        '    "current_state": "",\n'
        '    "stable_traits": [],\n'
        '    "abilities_or_limits": [],\n'
        '    "relationship_digest": [],\n'
        '    "open_questions": [],\n'
        '    "latest_major_change": {"summary": "", "source_refs": []},\n'
        '    "source_refs": [],\n'
        '    "compacted_until": {"doc_id": 0, "outline_segment_id": ""}\n'
        "  },\n"
        '  "consumed_recent_activity_refs": [],\n'
        '  "compact_notes": "本轮为什么需要或不需要更新 brief。"\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
