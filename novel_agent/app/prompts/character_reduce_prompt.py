from __future__ import annotations

import json
from typing import Any


def build_character_reduce_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Character Reduce Agent，只负责归纳一个真实人物的长期人物档案更新候选。\n"
        "你不会读取全文原文，也不会读取完整 chapter_summary_md；只消费按 doc_id 顺序排列的人物 evidence、"
        "chapter_context_text/current_outline_segment、来源索引和持久化 profile_brief。\n"
        "要求：\n"
        "1. 只输出当前 canonical_name 对应人物的 character_update；不要处理其他人物、世界观或大纲。\n"
        "2. 如果输入有 character_id，character_update 必须原样带回该 character_id；它是优先身份索引。\n"
        "3. 同一人物跨多个 documents 的状态、行动和关系必须按 source_doc_ids 的故事顺序归纳。\n"
        "4. existing_profile.profile_brief 是该人物持久化常驻简档；不要把已有同义事实重新输出为新事实，也不要制造重复的人物性证据。\n"
        "5. relationships 在人物内直接归并，避免同义重复和与 existing_profile 冲突；证据不足时返回空数组。\n"
        "6. 如果证据中出现关系内称呼，将其写入 relationship.address_terms，推荐保留方向，如“妻子称他为老公”“同事称他为 Don”。\n"
        "7. 关系明细只输出到 relationships 字段，不要复制进 personhood_evidence_summary、recent_activity 或 profile_summary_md。\n"
        "8. relationships.status_summary 只写短关系状态，不要写完整剧情因果；关系变化过程写入人物经历。\n"
        "9. chapter_context_text 优先使用 current_outline_segment；只有缺少可用 outline_segment 时才用章节短摘要兜底；不要要求完整 chapter_summary_md。\n"
        "10. 如果 current_outline_segment 存在，必须只为当前目标人物输出 recent_key_experiences 或 key_experiences；保留 outline_segment_id 和 source_doc_range。\n"
        "11. 经历 summary 必须按该人物在本段中的作用压缩：主推动者/主要受影响者/口述来源保留较完整剧情；背景出场只保留极简相关事实。\n"
        "12. 不要把同一段 outline_segment 的完整剧情无差别复制给所有出现人物。\n"
        "13. reduce_policy.detail_level 控制写入粒度：detailed 可保留较完整 profile/event；compact 只写简单 profile、短关系状态和压缩经历；"
        "index_only 只写当前 segment/source 索引、极短当前相关事实和必要关系称呼，不展开完整剧情。\n"
        "14. 只有角色在大部分当前 documents 中高频出现、直接推动剧情、承受主要影响或有关键口述/对话时，才输出 detailed 级经历。\n"
        "15. 非核心角色即使出现在本段，也不得复制完整 outline_segment；只输出 compression_level=index_only 或 brief 的人物相关索引摘要。\n"
        "16. 不要补全没有证据的性格、年龄、职业、能力、关系或经历。\n"
        "17. 如果当前剧情可能需要更新 profile_brief，只输出 compact 触发信号或简短原因；不要在本轮自行重写完整人物简档。\n"
        "18. 如果证据不足以写入长期档案，返回 should_update=false 且 character_update=null。\n"
        "19. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "should_update": true,\n'
        '  "character_id": "123",\n'
        '  "canonical_name": "角色甲",\n'
        '  "character_update": {\n'
        '    "character_id": "123", "canonical_name": "角色甲", "aliases": [],\n'
        '    "personality": [], "occupations": [], "age_update": null, "abilities": [],\n'
        '    "recent_activity": "",\n'
        '    "relationships": [{"target_name": "角色乙", "relation_type": "同事", "sentiment_state": "", "status_summary": "", "address_terms": ["角色乙称他为 Don"]}],\n'
        '    "recent_key_experiences": [{"experience_id": "char-exp:123:outline-segment:chapter-4:docs-7-8", "outline_segment_id": "outline-segment:chapter-4:docs-7-8", "role_in_segment": "main_driver", "compression_level": "full", "label": "角色甲推动关键冲突", "summary": "只针对角色甲的近期剧情压缩。", "source_chapter_indexes": [4], "source_doc_ids": [7, 8], "source_doc_range": "7-8", "participants": ["角色甲", "角色乙"]}],\n'
        '    "older_experience": [],\n'
        '    "profile_brief_compact": {"needed": false, "reason": "", "change_types": [], "history_needed": false},\n'
        '    "evidence_level": "inferred", "is_speaking_character": false,\n'
        '    "speaking_character_status": "personhood_supported", "speaking_evidence": "",\n'
        '    "personhood_evidence_summary": "", "activity_or_state_evidence": "", "relationship_evidence": ""\n'
        "  }\n"
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
