from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ..schemas.source_arc_schema import ChapterPlotSummary, PlotSummaryUnit


def build_plot_summary_unit_prompt(
    *,
    window: Sequence[ChapterPlotSummary],
    overlap_title_indexes: Sequence[int],
    fallback_payload: dict[str, Any],
) -> tuple[str, str]:
    system_prompt = (
        "你是小说精读后的剧情梗概压缩 Agent。\n"
        "你的任务是把连续 document/chapter 级梗概压缩成一个更精简的剧情单元，用于后续篇章节奏分析。\n"
        "只输出严格 JSON，不要输出 Markdown 代码块、解释或额外字段。\n"
        "要求：保留主线事件、人物状态变化、关系推进、设定揭示、伏笔、转折边界和与相邻单元的衔接钩子。\n"
        "不要依赖关键词摘取；要基于输入整体理解后概括。\n"
    )
    user_prompt = (
        "请压缩以下连续 document/chapter 梗概。\n\n"
        f"overlap_title_indexes:\n{json.dumps(list(overlap_title_indexes), ensure_ascii=False)}\n\n"
        f"chapter_summaries:\n{json.dumps([_summary_payload(item) for item in window], ensure_ascii=False, indent=2)}\n\n"
        "输出 JSON 字段必须与 fallback_payload 相同，metadata 字段可以沿用 fallback_payload，但内容字段必须由你重新概括。\n"
        f"fallback_payload:\n{json.dumps(fallback_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_source_arc_map_prompt(
    *,
    book_id: str,
    summaries: Sequence[ChapterPlotSummary],
    plot_summary_units: Sequence[PlotSummaryUnit],
    story_outline_md: str = "",
    world_summary_md: str = "",
    character_profile_summaries: Sequence[str] = (),
    fallback_payload: dict[str, Any],
) -> tuple[str, str]:
    system_prompt = (
        "你是 Source Arc Mapping Agent。\n"
        "你基于 close-read 后的事实型梗概，生成源作品篇章地图 SourceArcMap。\n"
        "目标是从整体上判断小说用了多少篇幅描写日常、关系铺垫、过渡缓冲、设定揭示、剧情转折、冲突升级、高潮和收束。\n"
        "这不是续写模板，也不是创作建议；只记录源作品事实型结构。\n"
        "只输出严格 JSON，不要输出 Markdown 代码块、解释或额外字段。\n"
    )
    if plot_summary_units:
        source_payload: dict[str, Any] = {
            "input_type": "plot_summary_units",
            "plot_summary_units": [unit.to_dict() for unit in plot_summary_units],
        }
    else:
        source_payload = {
            "input_type": "chapter_summaries",
            "chapter_summaries": [_summary_payload(item) for item in summaries],
        }
    user_prompt = (
        f"book_id: {book_id}\n\n"
        "请生成 SourceArcMap。篇章边界应基于剧情功能和节奏变化，不要只按固定章节数切分。\n"
        "chapter_role_map 需要覆盖输入中的每个 chapter 或 plot summary unit，并说明其结构功能。\n"
        "source_arc_role 可使用：主线推进、过渡缓冲、日常关系、设定揭示、冲突升级、剧情转折、高潮、收束。\n"
        "pacing_notes 应明确该 arc 大约占用了多少 chapter/结构单元，以及它承担的是铺垫、转折、冲突还是收束。\n\n"
        f"story_outline_md:\n{story_outline_md.strip()}\n\n"
        f"world_summary_md:\n{world_summary_md.strip()}\n\n"
        f"character_profile_summaries:\n{json.dumps(list(character_profile_summaries), ensure_ascii=False, indent=2)}\n\n"
        f"source_inputs:\n{json.dumps(source_payload, ensure_ascii=False, indent=2)}\n\n"
        "输出 JSON 字段必须与 fallback_payload 相同。请重点重写 arcs 与其中的 chapter_role_map。\n"
        f"fallback_payload:\n{json.dumps(fallback_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def _summary_payload(item: ChapterPlotSummary) -> dict[str, Any]:
    return {
        "document_title_index": item.document_title_index,
        "chapter_title": item.chapter_title,
        "summary_md": item.summary_md,
        "summary_short": item.summary_short,
        "importance_score": item.importance_score,
        "source_doc_ids": item.source_doc_ids,
        "related_chapters": item.related_chapters,
    }
