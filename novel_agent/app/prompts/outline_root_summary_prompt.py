from __future__ import annotations

import json
from typing import Any


def build_outline_root_summary_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Outline Root Summary Agent。\n"
        "你只消费一组连续 outline segments 的压缩梗概，不读取原文。\n"
        "任务：把这些 segment 压缩为用于快速检索相关性的 root.summary。\n"
        "要求：\n"
        "1. root_summary 必须是连续自然语言，不要 Markdown、不要项目符号、不要逐 segment 罗列。\n"
        "2. 保留阶段主线、因果链、主要人物状态/关系变化、设定揭示、未解问题和阶段结果。\n"
        "3. 压缩时合并重复信息；不要机械拼接 segment 内容。\n"
        "4. 目标长度约 300-700 个中文字符；信息密度低时可以更短。\n"
        "5. 必须服务检索：让模型能先读 root_summary 判断是否需要展开下层 segment。\n"
        "6. 不要输出 timeline_events、event_ids 或事件数组。\n"
        "7. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "root_summary": "对连续 outline segments 的语义压缩摘要",\n'
        '  "compression_notes": "一句话说明保留了哪些检索信号，可为空"\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(_root_summary_prompt_input(prompt_input), ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def _root_summary_prompt_input(prompt_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": prompt_input.get("book_id"),
        "outline_root_id": prompt_input.get("outline_root_id"),
        "source_doc_range": prompt_input.get("source_doc_range", ""),
        "source_title_indexes": prompt_input.get("source_title_indexes", []),
        "segments": [
            {
                "outline_segment_id": item.get("outline_segment_id"),
                "source_doc_range": item.get("source_doc_range", ""),
                "source_title_indexes": item.get("source_title_indexes", []),
                "chapter_line": item.get("chapter_line", ""),
                "summary": item.get("summary", ""),
                "status": item.get("status", ""),
            }
            for item in prompt_input.get("segments", [])
            if isinstance(item, dict)
        ],
    }
