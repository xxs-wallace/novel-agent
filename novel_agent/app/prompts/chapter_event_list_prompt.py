from __future__ import annotations

import json
from typing import Any


def build_chapter_event_list_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Chapter Event List Agent。\n"
        "你只消费已经生成的章节摘要 summary_md，不读取原文。\n"
        "任务：把 summary_md 压缩成 Story Outline Memory 的章节级 event list。\n"
        "要求：\n"
        "1. timeline_events 必须按剧情发生顺序排列，通常 2-5 个；信息密度低时可以 1 个。\n"
        "2. 每个 event 是关键剧情推进，不要逐条复述 summary_md，不要写结构功能、读后感或抽象主题。\n"
        "3. event.summary 必须是浓缩剧情概括，保留起因、行动、冲突、转折、结果中最关键的信息。\n"
        "4. participants 只写该事件中实际参与或状态明显变化的角色名；证据不足可为空数组。\n"
        "5. 不要机械截断，不要以省略号结尾，不要复制原文句子或露骨细节。\n"
        "6. 如果 existing_timeline_events 已提供，只把它当作旧覆盖范围参考；优先依据 summary_md 重新压缩。\n"
        "7. 输出必须是单个 JSON 对象。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "chapter_line": "[章节序号] 章节名: 一句话主线推进",\n'
        '  "timeline_events": [\n'
        '    {"label": "短事件名", "participants": ["角色名"], "summary": "关键剧情事件概括"}\n'
        "  ]\n"
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(_event_list_prompt_input(prompt_input), ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def _event_list_prompt_input(prompt_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": prompt_input.get("book_id"),
        "document_title_index": prompt_input.get("document_title_index"),
        "chapter_title": prompt_input.get("chapter_title"),
        "source_doc_range": prompt_input.get("source_doc_range", ""),
        "chapter_summary_short": prompt_input.get("chapter_summary_short", ""),
        "summary_md": prompt_input.get("summary_md", ""),
        "existing_timeline_events": prompt_input.get("existing_timeline_events", []),
    }
