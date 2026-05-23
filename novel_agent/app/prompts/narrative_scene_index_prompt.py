from __future__ import annotations

import json
from typing import Any


def build_narrative_scene_index_prompt(prompt_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "你是 Narrative Scene Indexer。\n"
        "你只负责基于当前小说的 Memory 摘要与连续原文窗口，抽取叙事场景索引卡。\n"
        "任务目标：识别窗口内完整或跨边界延续的场景，判断其在整部小说中的结构功能。\n"
        "要求：\n"
        "1. 必须同时参考 previous_context_summary、raw_document_window 和 next_context_summary。\n"
        "2. 不要只因为某段冲突强就判为重要；日常基线、关系铺垫、过渡、余波、设定揭示也可能重要。\n"
        "3. 如果一个场景跨越多个 documents，source_doc_ids 必须覆盖完整可见范围。\n"
        "4. 不要输出与窗口原文或上下文摘要无关的角色、设定或事件。\n"
        "5. summary 必须是事实型概括，不要改写成续写建议。\n"
        "6. summary_sufficiency 只能使用 sufficient、needs_raw_for_dialogue、needs_raw_for_emotional_texture、needs_raw_for_author_statement、needs_model_review。\n"
        "7. status 通常为 provisional；只有窗口内原文和前后摘要足以确认场景边界与功能时才可输出 committed。\n"
        "8. 输出必须是单个 JSON 对象，不要附加解释、代码块或分析过程。\n"
    )
    user_prompt = (
        "请按以下 JSON schema 返回：\n"
        "{\n"
        '  "scene_cards": [\n'
        "    {\n"
        '      "label": "场景标签",\n'
        '      "summary": "该连续场景发生了什么，以及为什么重要",\n'
        '      "scene_type": "daily_baseline | relationship_setup | relationship_turning_point | emotional_climax | plot_turning_point | world_reveal | mystery_setup | transition_bridge | aftermath | resolution",\n'
        '      "participants": ["角色名"],\n'
        '      "source_doc_ids": [1, 2],\n'
        '      "source_title_indexes": [1],\n'
        '      "scene_boundary": {"start_doc_id": "1", "end_doc_id": "2", "boundary_confidence": 0.8, "overlap_window_id": "scene-window-0001"},\n'
        '      "trigger": "场景触发条件或前因",\n'
        '      "turning_point": "场景内最重要的变化或选择",\n'
        '      "outcome": "场景结果",\n'
        '      "character_pressure": ["人物压力、欲望或矛盾"],\n'
        '      "relationship_movements": ["关系变化"],\n'
        '      "world_or_mystery_signals": ["设定揭示、谜团或伏笔"],\n'
        '      "future_consequence": "该场景对后续剧情的影响",\n'
        '      "query_facets": ["人物性格", "关系转折"],\n'
        '      "importance_facets": ["relationship_turning_point"],\n'
        '      "summary_sufficiency": "sufficient",\n'
        '      "raw_read_reason": "",\n'
        '      "status": "provisional",\n'
        '      "confidence": 0.8\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(_scene_index_prompt_input(prompt_input), ensure_ascii=False, indent=2)
    )
    return system_prompt, user_prompt


def _scene_index_prompt_input(prompt_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": prompt_input.get("book_id"),
        "window_id": prompt_input.get("window_id"),
        "previous_context_summary": prompt_input.get("previous_context_summary", ""),
        "raw_document_window": prompt_input.get("raw_document_window", []),
        "next_context_summary": prompt_input.get("next_context_summary", ""),
        "character_context": prompt_input.get("character_context", []),
        "world_context": prompt_input.get("world_context", ""),
        "source_doc_ids": prompt_input.get("source_doc_ids", []),
        "overlap_doc_ids": prompt_input.get("overlap_doc_ids", []),
        "output_policy": {
            "allowed_scene_types": [
                "daily_baseline",
                "relationship_setup",
                "relationship_turning_point",
                "emotional_climax",
                "plot_turning_point",
                "world_reveal",
                "mystery_setup",
                "transition_bridge",
                "aftermath",
                "resolution",
            ],
            "do_not_invent_outside_window": True,
            "prefer_compact_cards": True,
        },
    }
