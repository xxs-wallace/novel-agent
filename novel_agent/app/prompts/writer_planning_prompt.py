from __future__ import annotations

import json
from typing import Any, Sequence


def build_book_continuation_plan_prompt(
    *,
    book_id: str,
    continuation_intent: dict[str, Any],
    outline_markdown: str,
    world_summary_markdown: str,
) -> tuple[str, str]:
    system_prompt = (
        "你是小说续写 Layer 1 全书续写规划助手。\n"
        "你的任务是基于用户的简化续写方向、已有故事大纲和世界观摘要，输出保守、可执行的 BookContinuationPlan。\n"
        "你必须只输出严格 JSON，不要输出解释、Markdown、代码块或多余文字。\n"
        "硬约束：\n"
        "1. 不得脱离原有大纲另起炉灶。\n"
        "2. 不得擅自改变核心角色人格、既有重大结局或关键关系基础。\n"
        "3. 每项关键判断都要提供 evidence_level 和 source_paths。\n"
        "4. 证据不足时，将内容写入 open_questions，不要硬编。\n"
        "5. continuation_intent.desired_actions 与 preferred_outcome 是本次规划边界；"
        "stage_highlights 只能拆解或复述该边界，不得新增未授权高潮、地点跳转、势力或替代主线。\n"
        "6. continuation_intent.story_scale 与 climax_plan 是正式规划输入；"
        "必须归并进 BookContinuationPlan，不得只作为备注。\n"
    )
    user_prompt = (
        f"book_id: {book_id}\n\n"
        "简化续写方向：\n"
        f"{json.dumps(continuation_intent, ensure_ascii=False, indent=2)}\n\n"
        "已有故事大纲：\n"
        f"{outline_markdown}\n\n"
        "当前世界观摘要：\n"
        f"{world_summary_markdown}\n\n"
        "请只输出如下 JSON 结构：\n"
        f"{json.dumps(_book_plan_example(), ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_world_expansion_prompt(
    *,
    book_id: str,
    continuation_intent: dict[str, Any],
    book_continuation_plan: dict[str, Any],
    world_summary_markdown: str,
    user_world_notes: str,
) -> tuple[str, str]:
    system_prompt = (
        "你是小说续写 Layer 1B 世界观补全助手。\n"
        "你的任务是识别后续剧情真正需要但当前世界观摘要中不充分的设定，并生成最小必要的 WorldExpansionPack。\n"
        "你必须只输出严格 JSON。\n"
        "硬约束：\n"
        "1. 新设定必须服务于已给定剧情方向。\n"
        "2. 如与当前世界观存在潜在冲突，必须写入 conflict_note 或 open_items。\n"
        "3. 不允许为了显得宏大而无约束扩写设定。\n"
    )
    user_prompt = (
        f"book_id: {book_id}\n\n"
        "续写方向：\n"
        f"{json.dumps(continuation_intent, ensure_ascii=False, indent=2)}\n\n"
        "BookContinuationPlan：\n"
        f"{json.dumps(book_continuation_plan, ensure_ascii=False, indent=2)}\n\n"
        "当前世界观摘要：\n"
        f"{world_summary_markdown}\n\n"
        "用户补充/修订世界观：\n"
        f"{user_world_notes or '(无)'}\n\n"
        "请只输出如下 JSON 结构：\n"
        f"{json.dumps(_world_expansion_example(), ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_character_cast_prompt(
    *,
    book_id: str,
    requirement_report: dict[str, Any],
    cast_request: dict[str, Any],
    continuation_intent: dict[str, Any],
    book_continuation_plan: dict[str, Any],
    world_expansion_pack: dict[str, Any],
    character_seeds: list[dict[str, Any]],
) -> tuple[str, str]:
    system_prompt = (
        "你是小说续写 Layer 1C 人物补充助手。\n"
        "你的任务是根据角色缺位报告、用户角色雏形、全书规划和世界观限制，生成受约束的计划角色方案。\n"
        "你必须只输出严格 JSON。\n"
        "硬约束：\n"
        "1. 区分显式命名新角色与隐式角色功能位。\n"
        "2. 计划角色是 planned，不是正式 Character Memory。\n"
        "3. 不得让角色在首次登场前提前消费终局秘密、关键关系跃迁或未确认世界规则。\n"
        "4. 证据不足时可以保留 open_questions，但不要自由发明大型设定。\n"
    )
    user_prompt = (
        f"book_id: {book_id}\n\n"
        "CharacterRequirementReport：\n"
        f"{json.dumps(requirement_report, ensure_ascii=False, indent=2)}\n\n"
        "CharacterCastRequest：\n"
        f"{json.dumps(cast_request, ensure_ascii=False, indent=2)}\n\n"
        "续写方向：\n"
        f"{json.dumps(continuation_intent, ensure_ascii=False, indent=2)}\n\n"
        "BookContinuationPlan：\n"
        f"{json.dumps(book_continuation_plan, ensure_ascii=False, indent=2)}\n\n"
        "WorldExpansionPack：\n"
        f"{json.dumps(world_expansion_pack, ensure_ascii=False, indent=2)}\n\n"
        "CharacterSeedInputs：\n"
        f"{json.dumps(character_seeds, ensure_ascii=False, indent=2)}\n\n"
        "请只输出如下 JSON 结构：\n"
        f"{json.dumps(_character_cast_example(), ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_batch_plan_prompt(
    *,
    book_id: str,
    book_continuation_plan: dict[str, Any],
    world_expansion_pack: dict[str, Any],
    character_cast_plan: dict[str, Any] | None,
    target_chapter_count: int,
    chapters: Sequence[str],
) -> tuple[str, str]:
    system_prompt = (
        "你是小说续写 Layer 2 批次剧情规划助手。\n"
        "你的任务是基于 Freeze A 已冻结的上游产物生成当前批次 BatchPlan。\n"
        "你必须只输出严格 JSON。\n"
        "硬约束：\n"
        "1. BatchPlan 必须承接 BookContinuationPlan，不得绕开全书方向。\n"
        "2. 必须写出 must_resolve、must_not_consume、exit_hook。\n"
        "3. 若存在 CharacterCastPlan，必须为首次登场角色预留批次级执行位置。\n"
        "4. must_resolve 只能是 BookContinuationPlan.continuation_goal/stage_highlights 的忠实拆解；"
        "不得把 WorldExpansionPack 或 CharacterCastPlan 中的背景信息升级成新的剧情主线。\n"
        "5. must_not_consume 必须继承 BookContinuationPlan.must_preserve 与 WorldExpansionPack.open_items 中不应提前消费的信息。\n"
        "6. exit_hook 只能停在当前批次边界上的悬念，不得直接写成下一批次的完整事件。\n"
        "7. 必须继承 BookContinuationPlan 的 target_chapter_count、target_total_chars、default_chapter_target_chars "
        "以及当前批次覆盖的 chapter_outline_slots；不得擅自缩短用户授权的章节数或字数。\n"
        "8. chapters 是后端根据 Writer Memory document_title_index 计算并冻结的章节列表，必须原样输出；"
        "不得自行推导、改写、重排章节编号，也不要输出 scope_start 或 scope_end。\n"
    )
    user_prompt = (
        f"book_id: {book_id}\n"
        f"目标批次章节数: {target_chapter_count}\n\n"
        "后端已冻结的当前批次章节列表：\n"
        f"{json.dumps(list(chapters), ensure_ascii=False, indent=2)}\n\n"
        "BookContinuationPlan：\n"
        f"{json.dumps(book_continuation_plan, ensure_ascii=False, indent=2)}\n\n"
        "WorldExpansionPack：\n"
        f"{json.dumps(world_expansion_pack, ensure_ascii=False, indent=2)}\n\n"
        "CharacterCastPlan：\n"
        f"{json.dumps(character_cast_plan or {}, ensure_ascii=False, indent=2)}\n\n"
        "请只输出如下 JSON 结构：\n"
        f"{json.dumps(_batch_plan_example(), ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_chapter_package_prompt(
    *,
    book_id: str,
    batch_plan: dict[str, Any],
    character_introduction_plan: dict[str, Any] | None,
    story_structure_kb: str,
    relationship_arc_kb: str,
    chapter_count: int,
) -> tuple[str, str]:
    boundary_contract = _chapter_boundary_contract(batch_plan=batch_plan, chapter_count=chapter_count)
    system_prompt = (
        "你是小说续写 Layer 3 章节包规划助手。\n"
        "你的任务是基于 BatchPlan 生成最近一批章节的 ChapterPackage，并内嵌可执行的 ChapterBrief。\n"
        "你必须只输出严格 JSON。\n"
        "硬约束：\n"
        "1. 每章都要有 goal、emotional_goal、conflict_goal、ending_hook。\n"
        "2. 每章都要给出 relationship_targets，并标注 required_bridge。\n"
        "3. 若涉及计划角色首次登场，必须编入对应章节。\n"
        "4. 可以参考剧情结构与关系弧线知识库，但不得覆盖上游冻结事实。\n"
        "5. Creative KB 与结构知识只能作为表达、节奏和桥接参考，不得替换 BatchPlan 或用户授权目标。\n"
        "6. 不得新增上游目标未授权的大型新事件、新势力、新规则或替代主线。\n"
        "7. 每个 ChapterBrief.goal、plot_function、must_include 必须对应章节边界契约 assigned_must_resolve，"
        "可以细化为场景动作，但不得扩写到 other_batch_must_resolve 或 exit_hook 之后。\n"
        "8. 每章 forbidden 必须包含 batch_forbidden_consumption；非最后一章不得提前消费 batch_exit_hook。\n"
        "9. 剧情结构知识库和关系弧线知识库只能用于节奏安排，若它们暗示的事件超出章节边界契约，必须忽略。\n"
        "10. target_word_count 必须服从章节边界契约中的 target_chars；若契约给出 10000 字，"
        "target_word_count 应为 5000，因为后续长度规划会把该字段换算为正文目标字数。\n"
    )
    user_prompt = (
        f"book_id: {book_id}\n"
        f"目标章节数: {chapter_count}\n\n"
        "BatchPlan：\n"
        f"{json.dumps(batch_plan, ensure_ascii=False, indent=2)}\n\n"
        "章节边界契约（只用于约束输出，不要额外输出 boundary_contract 字段）：\n"
        f"{json.dumps(boundary_contract, ensure_ascii=False, indent=2)}\n\n"
        "CharacterIntroductionPlan：\n"
        f"{json.dumps(character_introduction_plan or {}, ensure_ascii=False, indent=2)}\n\n"
        "剧情结构知识库摘录：\n"
        f"{story_structure_kb}\n\n"
        "关系弧线知识库摘录：\n"
        f"{relationship_arc_kb}\n\n"
        "请只输出如下 JSON 结构：\n"
        f"{json.dumps(_chapter_package_example(), ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def _chapter_boundary_contract(*, batch_plan: dict[str, Any], chapter_count: int) -> dict[str, Any]:
    must_resolve = [str(item).strip() for item in (batch_plan.get("must_resolve") or []) if str(item).strip()]
    if not must_resolve:
        goal = str(batch_plan.get("batch_goal") or "").strip()
        must_resolve = [goal] if goal else []
    count = max(1, int(chapter_count or 1))
    default_chars = int(batch_plan.get("default_chapter_target_chars") or 0)
    slots = [dict(item) for item in (batch_plan.get("chapter_outline_slots") or []) if isinstance(item, dict)]
    chapter_boundaries: list[dict[str, Any]] = []
    for index in range(count):
        assigned = must_resolve[min(index, len(must_resolve) - 1)] if must_resolve else ""
        other = [item for item in must_resolve if item != assigned]
        slot = slots[index] if index < len(slots) else {}
        target_chars = int(
            slot.get("target_chars")
            or slot.get("estimated_chars")
            or default_chars
            or (int(batch_plan.get("target_total_chars") or 0) // count if batch_plan.get("target_total_chars") else 0)
            or 4000
        )
        chapter_boundaries.append(
            {
                "chapter_order": index + 1,
                "assigned_must_resolve": assigned,
                "other_batch_must_resolve": other,
                "may_use_batch_exit_hook": index == count - 1,
                "target_chars": target_chars,
            }
        )
    return {
        "batch_goal": str(batch_plan.get("batch_goal") or "").strip(),
        "batch_forbidden_consumption": [
            str(item).strip() for item in (batch_plan.get("must_not_consume") or []) if str(item).strip()
        ],
        "batch_exit_hook": str(batch_plan.get("exit_hook") or "").strip(),
        "chapter_boundaries": chapter_boundaries,
    }


def _book_plan_example() -> dict[str, Any]:
    return {
        "plan_id": "bcp-001",
        "continuation_goal": "承接原作主线，推进下一阶段核心冲突。",
        "ending_direction": "阶段性胜利但留下更大未决项。",
        "target_chapter_count": 12,
        "target_total_chars": 48000,
        "default_chapter_target_chars": 4000,
        "pacing_profile": "慢热铺垫后段爆发",
        "length_distribution_notes": "前两章偏短，中后段冲突章展开。",
        "climax_plan": {
            "conflict_climax": "主角在公开对抗中迫使幕后势力暴露关键代价",
            "emotional_climax": "主角必须在保全关系与追求真相之间作出选择",
            "target_chapter_index": 10,
            "must_foreshadow": ["旧案证据的来源"],
            "must_not_resolve_before": ["幕后主使身份"],
            "payoff_expectation": "回收旧案线索并让读者看到关系选择的代价",
        },
        "chapter_outline_slots": [
            {
                "chapter_index": 1,
                "target_chars": 3800,
                "plot_function": "承接上文并建立新目标",
                "setup_targets": ["旧案新线索"],
                "payoff_targets": [],
                "must_not_consume": ["幕后主使身份"],
            }
        ],
        "stage_highlights": ["阶段高潮一", "阶段高潮二"],
        "character_arcs": ["主角从犹疑转向承担"],
        "relationship_guardrails": ["关系只允许推进到有限合作"],
        "must_preserve": ["既有核心人物关系基础"],
        "open_questions": ["某设定证据不足，需要确认"],
        "evidence": [
            {
                "claim": "当前主线仍围绕旧案调查",
                "evidence_level": "confirmed_analysis",
                "source_paths": ["memory/outlines/book.outline.md"],
                "note": "",
            }
        ],
    }


def _world_expansion_example() -> dict[str, Any]:
    return {
        "pack_id": "wep-001",
        "required_for_plot": ["解释新阶段冲突所需的最小设定"],
        "constraint_rules": [
            {
                "topic": "组织边界",
                "rule": "该组织只能提供有限情报支持，不能直接出动压平冲突。",
                "why_needed": "避免后续剧情失去压力",
                "constrained_plots": ["追捕线", "潜入线"],
                "conflict_note": "",
            }
        ],
        "open_items": ["是否存在更上层指挥者仍证据不足"],
        "evidence": [
            {
                "claim": "现有体系不支持无代价的新能力",
                "evidence_level": "structured_state",
                "source_paths": ["memory/worlds/book.world_summary.md"],
                "note": "",
            }
        ],
    }


def _character_cast_example() -> dict[str, Any]:
    return {
        "planned_character_profiles": [
            {
                "planned_character_id": "pc-001",
                "status": "planned",
                "canonical_name": "顾迟",
                "aliases": [],
                "faction": "友方",
                "narrative_role": "行动支援 / 信息延迟揭示",
                "core_personality": ["冷静", "克制"],
                "surface_identity": "临时联络员",
                "hidden_pressure": ["与旧案有关联"],
                "ability_scope": ["情报收集"],
                "ability_limits": ["不能越权调动官方力量"],
                "relationship_entry_points": [
                    {
                        "target_character": "沈青",
                        "initial_state": "互相试探",
                        "ceiling_before_freeze_e": "有限信任",
                    }
                ],
                "first_introduction_plan": {
                    "batch_id": "batch-01",
                    "chapter_id": "batch01-ch02",
                    "scene_function": "危机支援",
                },
                "must_not_reveal_early": ["终局身份"],
                "sources": [{"type": "character_seed", "path": "runs/.../character_seed_input.json"}],
            }
        ],
        "character_cast_plan": {
            "cast_plan_id": "cast-plan-001",
            "depends_on": {
                "book_continuation_plan_id": "bcp-001",
                "world_expansion_pack_id": "wep-001",
            },
            "planned_characters": [{"planned_character_id": "pc-001", "slot_id": "ally-01"}],
            "open_questions": [],
            "must_not_consume": ["首次登场章不得暴露终局秘密"],
        },
        "character_introduction_plan": {
            "introduction_items": [
                {
                    "planned_character_id": "pc-001",
                    "batch_id": "batch-01",
                    "chapter_id": "batch01-ch02",
                    "required_scene_function": "危机支援",
                    "required_relationship_effect": "建立有限合作",
                    "forbidden_moves": ["直接交底"],
                }
            ]
        },
    }


def _batch_plan_example() -> dict[str, Any]:
    return {
        "batch_id": "batch-01",
        "chapters": ["chapter-11", "chapter-12", "chapter-13"],
        "batch_goal": "推进调查线并完成一次关系站队",
        "emotional_arc": "由紧绷防备转向有限信任",
        "conflict_arc": "追捕压力持续抬升",
        "must_resolve": ["让主角完成一次主动选择"],
        "must_not_consume": ["终局真相", "关系最终确认"],
        "planned_character_beats": ["pc-001 在本批次首次提供支援"],
        "exit_hook": "新的线索指向更大势力",
        "target_chapter_count": 3,
        "target_total_chars": 30000,
        "default_chapter_target_chars": 10000,
        "chapter_outline_slots": [
            {
                "chapter_index": 1,
                "target_chars": 10000,
                "plot_function": "解决当前困境并打开新秩序入口",
            }
        ],
        "evidence": [
            {
                "claim": "当前批次应优先承接追捕线",
                "evidence_level": "confirmed_analysis",
                "source_paths": ["runs/.../book_continuation_plan.json"],
                "note": "",
            }
        ],
    }


def _chapter_package_example() -> dict[str, Any]:
    return {
        "package_id": "chapter-package-01",
        "package_goal": "完成一批三章的紧张推进",
        "review_notes": ["第二章承担关系站队和新角色有限登场"],
        "chapters": [
            {
                "chapter_id": "batch01-ch01",
                "title": "雨夜之前",
                "goal": "迫使两人进入合作局面",
                "chapter_role": "关系推进章",
                "plot_function": "承上启下",
                "emotional_goal": "由防备转向有限信任",
                "conflict_goal": "在外部追捕中求生",
                "relationship_targets": [
                    {
                        "relation_type": "友情",
                        "current_state": "试探",
                        "target_state": "有限合作",
                        "allowed": True,
                        "required_bridge": ["共同危机", "公开站队"],
                    }
                ],
                "must_include": ["雨夜逃亡"],
                "forbidden": ["突然告白"],
                "structure_hint": {"theory": "故事圆环", "beats": ["Need", "Go", "Search"]},
                "ending_hook": "他们发现新的追踪痕迹",
                "target_word_count": 1800,
                "sources": [{"type": "batch_plan", "path": "runs/.../batch_plan.json"}],
            }
        ],
    }
