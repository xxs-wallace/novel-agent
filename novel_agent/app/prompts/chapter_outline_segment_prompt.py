from __future__ import annotations

import json
from typing import Any


def build_chapter_outline_segment_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Chapter Outline Segment Agent。\n"
        "你只消费已经生成的章节摘要 summary_md，不读取原文。\n"
        "任务：把 summary_md 压缩为 Story Outline Memory 的章节级连续剧情大纲。\n"
        "要求：\n"
        "1. chapter_line 是一句话主线推进，优先保留不可逆变化、关键选择、冲突结果和新揭示。\n"
        "2. outline_segment 必须是连续自然语言，不要 Markdown、不要项目符号、不要逐条拆事件。\n"
        "3. outline_segment 要保留剧情顺序、因果衔接、主要人物状态/关系变化、设定揭示、未解问题和阶段结果。\n"
        "4. 目标长度约 180-320 个中文字符；信息密度很低时可以更短，但必须明显短于 summary_md。\n"
        "5. 不要机械截断，不要以省略号结尾，不要复制原文句子或露骨细节。\n"
        "6. 输出必须是单个 JSON 对象。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "chapter_line": "[章节序号] 章节名: 一句话主线推进",\n'
        '  "outline_segment": "连续剧情压缩梗概",\n'
        '  "compression_notes": "一句话说明保留了哪些关键推进，可为空"\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(_outline_segment_prompt_input(prompt_input), ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def _outline_segment_prompt_input(prompt_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": prompt_input.get("book_id"),
        "document_title_index": prompt_input.get("document_title_index"),
        "chapter_title": prompt_input.get("chapter_title"),
        "source_doc_range": prompt_input.get("source_doc_range", ""),
        "chapter_summary_short": prompt_input.get("chapter_summary_short", ""),
        "summary_md": prompt_input.get("summary_md", ""),
    }
