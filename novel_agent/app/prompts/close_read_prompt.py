from __future__ import annotations

import json
from typing import Any


def build_close_read_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    source_total_chars = int(prompt_input.get("source_total_chars", 0) or 0)
    summary_target_chars_min = int(prompt_input.get("summary_target_chars_min", 0) or 0)
    system_prompt = (
        "你是小说阅读助手。\n"
        "请基于当前章节 documents、已有故事大纲、世界观概要和人物档案，输出严格 JSON。\n"
        "你的任务不是摘抄原文，而是提炼章节剧情梗概、剧情作用、人物变化、世界观增量和大纲增量。\n"
        "重要约束：\n"
        "1. chapter_summary_md 必须是压缩后的剧情梗概，不允许把原文大段直接拼接进去，也不允许截取 document 开头/结尾当摘要。\n"
        f"2. 当前章节正文总长度约为 {source_total_chars} 字，chapter_summary_md 至少写到 {summary_target_chars_min} 字，不能只写一两句话。\n"
        "3. chapter_summary_md 重点保留：地点、人物、行动、冲突、结果、关键心理变化。\n"
        "4. 建议使用 Markdown 小标题或短段落组织，至少覆盖“剧情推进”“人物状态/关系变化”“关键信息/设定”三部分。\n"
        "5. 你必须基于每个 document 的正文重新分析涉及人物，不要依赖导入原文阶段的人物字段；上游给出的人物字段可能为空，也可能只是本地提示。\n"
        "6. document_character_mentions 必须逐个 doc_id 返回真实人物名数组；没有明确人物时返回空数组，不要硬猜。\n"
        "   - 你必须同时返回 character_evidence：一个字典，key 是人物名，value 是 1-3 条证据片段。\n"
        "   - 每条证据片段必须是本 doc 原文中的连续子串，且必须包含该人物名（逐字匹配）。\n"
        "   - 对于不确定的人名/疑似动词/物品名，请不要输出。尤其要避免把“张开/张望/高跟鞋”等动作或物品误当人名。\n"
        "   - 对非显然人物名（不在已知角色里），证据片段还必须包含人物线索：如“名叫/叫做/名字是”、或“X说/问/道/喊/叫/答”、或“先生/教授/校长/同学”等称谓。\n"
        "   - 如果无法提供证据片段，则该人物名不得出现在 character_keywords 中。\n"
        "7. character_updates 只能包含真实角色，canonical_name 必须是人物名；严禁写入“不是某人”“上下打量”这类短语。\n"
        "8. 忽略冗长战斗描写、环境描写、重复对白细节。\n"
        "9. 如果没有足够证据，不要编造人物性格、年龄、关系或世界观设定。\n"
        "10. 如果某字段无更新，请返回空数组、空字符串或 should_update=false，而不是胡乱补全；作者信息、扉页、目录、版权/出版信息、广告等非小说正文不要编造成剧情。\n"
        "11. world_update.changes[].section 只能使用这 6 个固定分区：世界类型、时代背景、能力体系、超自然要素、阵营势力、核心禁忌与规则。\n"
        "12. outline_update.chapter_line 优先概括主线推进、不可逆事件和关键转折；纯气氛或弱支线不要写得比主线更长。\n"
        "13. outline_update.timeline_events 只保留关键时间节点；同一事件不要换个说法重复写，label 要尽量稳定。\n"
        "14. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "chapter_summary_md": "详细章节剧情梗概，建议分为多个自然段或 Markdown 小节，长度不能低于要求，不得摘抄原文或截取 document 前缀",\n'
        '  "chapter_summary_short": "一到两句话的短剧情梗概",\n'
        '  "importance_score": 0,\n'
        '  "importance_reason": "说明为什么这章重要或不重要",\n'
        '  "related_chapters": [{"document_title_index": 0, "score": 0, "reason": "关联原因"}],\n'
        '  "document_character_mentions": [{"doc_id": 1, "character_keywords": ["角色甲", "角色乙"], "character_evidence": {"角色甲": ["...角色甲..."], "角色乙": ["...角色乙..."]}}],\n'
        '  "world_update": {"should_update": false, "changes": [{"section": "能力体系", "summary": "新增/修正内容", "evidence": "证据"}]},\n'
        '  "character_updates": [{"canonical_name": "角色甲", "aliases": [], "personality": [], "occupations": [], "age_update": null, "abilities": [], "recent_activity": "", "relationships": []}],\n'
        '  "outline_update": {"chapter_line": "[12] 章节名: 本章发生了什么", "timeline_events": [{"label": "事件名", "participants": ["角色甲"], "summary": "事件概括"}]}\n'
        "}\n\n"
        "输入数据如下，请严格按 JSON 返回，不要附加解释。\n\n"
        + json.dumps(prompt_input, ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt
