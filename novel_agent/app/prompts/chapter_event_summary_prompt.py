from __future__ import annotations

import json
from typing import Any


def build_chapter_event_summary_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Chapter Event Summary Agent。\n"
        "你只消费已经生成的章节摘要 summary_md 和章节 event list，不读取原文。\n"
        "任务：把 chapter_event_list 压缩为章节级 event_summary，用于 Story Outline Memory。\n"
        "要求：\n"
        "1. event_summary 必须是连续自然语言，不要 Markdown、不要项目符号、不要 JSON 以外的解释。\n"
        "2. 必须概括 event list 的剧情推进，而不是复述 summary_md 的每个小标题或细节；保留事件顺序、因果衔接、关键人物状态/关系变化和结果。\n"
        "3. 目标长度约 180-260 个中文字符；信息密度很低时可以更短，信息密度很高时可以略长，但必须明显短于 summary_md。\n"
        "4. 不要机械截断，不要以省略号结尾，不要复制原文句子或露骨细节。\n"
        "5. summary_md 只用于校验 event list 是否漏掉关键因果；不要跳过 event list 直接重写全文摘要。\n"
        "6. 输出必须是单个 JSON 对象。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "event_summary": "压缩后的章节关键剧情事件摘要",\n'
        '  "compression_notes": "一句话说明保留了哪些关键推进，可为空"\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(_event_summary_prompt_input(prompt_input), ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def _event_summary_prompt_input(prompt_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": prompt_input.get("book_id"),
        "document_title_index": prompt_input.get("document_title_index"),
        "chapter_title": prompt_input.get("chapter_title"),
        "source_doc_range": prompt_input.get("source_doc_range", ""),
        "chapter_summary_short": prompt_input.get("chapter_summary_short", ""),
        "summary_md": prompt_input.get("summary_md", ""),
        "chapter_event_list": prompt_input.get("chapter_event_list", prompt_input.get("existing_timeline_events", [])),
    }
