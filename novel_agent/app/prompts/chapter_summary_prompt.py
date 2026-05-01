from __future__ import annotations

import json
from typing import Any


def build_chapter_summary_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    source_total_chars = int(prompt_input.get("source_total_chars", 0) or 0)
    summary_target_chars_min = int(prompt_input.get("summary_target_chars_min", 0) or 0)
    title_indexes = _title_indexes(prompt_input)
    system_prompt = (
        "你是小说精读 Reading Agent，只负责章节级剧情梗概（plot synopsis）。\n"
        "请基于 documents 输出严格 JSON；不要更新人物档案、世界观文档或故事大纲。\n"
        "要求：\n"
        "1. chapter_summary_md 必须是压缩后的剧情梗概，不是原文摘要、不是摘录、不是读后感，也不是 document 开头/结尾的前缀裁剪。\n"
        f"2. 当前正文总长度约为 {source_total_chars} 字，chapter_summary_md 至少 {summary_target_chars_min} 字。\n"
        "3. chapter_summary_md 必须按剧情事件链写清楚：起点/背景 -> 触发事件 -> 人物行动 -> 阻碍/冲突 -> 转折 -> 结果 -> 留给后文的悬念或铺垫。\n"
        "4. 禁止连续复述原文，禁止复制对白原句，禁止输出连续超过 18 个汉字或 30 个字符的原文片段。\n"
        "5. 可以概括性说明亲密、暴力、梦境、回忆、对话等内容，但不要保留露骨细节、环境铺陈或重复描写。\n"
        "6. 必须用 Markdown 小节组织 chapter_summary_md，且至少包含：剧情事件链、人物状态/关系变化、关键信息/设定、结构功能/节奏。\n"
        "7. 结构功能/节奏要说明本章主要承担日常铺垫、关系推进、过渡缓冲、设定揭示、冲突升级、剧情转折、高潮或收束中的哪些功能。\n"
        "8. 如果输入 documents 基本没有可概括剧情（如作者信息、扉页、目录、版权/出版信息、乱码、广告、极短无关片段），不要编造剧情；summary_quality 设为 low_signal_needs_review，并在 noise_documents 标出 doc_id 和原因。\n"
        "9. importance_score 表示该章节对长期记忆和后续续写一致性的价值，范围 0-100。\n"
        "10. world_evidence_candidates 只记录稳定世界观/规则/势力/能力/禁忌候选，不要写人物档案事实。\n"
        "11. world_signal_score 表示本批次是否值得额外运行 World Evidence Agent，范围 0-100；普通剧情推进应低分，设定密集或候选低置信但重要时高分。\n"
        "12. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    if len(title_indexes) > 1:
        system_prompt += (
            f"13. 本次 documents 跨越多个 document_title_index：{title_indexes}。\n"
            "   你必须返回 chapter_summaries 数组，每个 document_title_index 一个对象；"
            "每个对象只概括该章节自己的 documents，并遵守同样的 plot synopsis 规则。\n"
        )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "summary_quality": "plot_synopsis 或 low_signal_needs_review",\n'
        '  "chapter_summary_md": "Markdown。必须包含 ## 剧情事件链 / ## 人物状态/关系变化 / ## 关键信息/设定 / ## 结构功能/节奏。内容必须是剧情梗概，不得摘抄原文或截取 document 前缀",\n'
        '  "chapter_summary_short": "一到两句话概括本章剧情梗概，不得摘抄原文",\n'
        '  "importance_score": 0,\n'
        '  "importance_reason": "重要性原因",\n'
        '  "related_chapters": [{"document_title_index": 0, "score": 0, "reason": "关联原因"}],\n'
        '  "world_signal_score": 0,\n'
        '  "world_evidence_candidates": [{"section": "能力体系", "summary": "稳定设定候选", "evidence_hint": "简短证据说明", "source_doc_ids": [1], "confidence": 0.8}],\n'
        '  "noise_documents": [{"doc_id": 1, "document_title_index": 12, "reason": "目录/广告/乱码/极短无剧情等"}],\n'
        '  "chapter_summaries": [{"document_title_index": 12, "chapter_title": "章节名", "summary_quality": "plot_synopsis", "chapter_summary_md": "仅该章节的剧情梗概", "chapter_summary_short": "仅该章节的短剧情梗概", "importance_score": 0, "importance_reason": "原因", "related_chapters": [], "noise_documents": []}]\n'
        "}\n\n"
        "chapter_summary_md 示例结构：\n"
        "## 剧情事件链\n"
        "- 起点：...\n"
        "- 触发：...\n"
        "- 行动/冲突：...\n"
        "- 转折/结果：...\n"
        "- 后续铺垫：...\n\n"
        "## 人物状态/关系变化\n"
        "- ...\n\n"
        "## 关键信息/设定\n"
        "- ...\n\n"
        "## 结构功能/节奏\n"
        "- ...\n\n"
        "输入数据如下：\n"
        + json.dumps(_summary_prompt_input(prompt_input), ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def _title_indexes(prompt_input: dict[str, Any]) -> list[int]:
    return sorted(
        {
            int(doc.get("document_title_index"))
            for doc in prompt_input.get("documents", [])
            if isinstance(doc, dict) and str(doc.get("document_title_index", "")).isdigit()
        }
    )


def _summary_prompt_input(prompt_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": prompt_input.get("book_id"),
        "current_title_index": prompt_input.get("current_title_index"),
        "chapter_title": prompt_input.get("chapter_title"),
        "source_total_chars": prompt_input.get("source_total_chars"),
        "summary_target_chars_min": prompt_input.get("summary_target_chars_min"),
        "documents": prompt_input.get("documents", []),
    }
