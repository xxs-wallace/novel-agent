from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ArtifactSummary:
    path: Path
    title: str
    sections: list[tuple[str, str]]
    preview: str = ""
    collapsed: bool = False
    next_action: str = ""
    technical_details: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        lines = [self.title, f"文件：{self.path}"]
        for label, value in self.sections:
            if value:
                lines.append(f"{label}：{value}")
        if self.preview:
            lines.append("预览：")
            lines.append(self.preview)
        if self.next_action:
            lines.append(f"下一步：{self.next_action}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ArtifactSaveResult:
    path: Path
    saved: bool
    message: str
    validation_error: str = ""


class ArtifactPresenter:
    """Builds summaries and edit/save validation for JSON and Markdown artifacts."""

    LARGE_PREVIEW_CHARS = 1200
    FIELD_EDITABLE_ARTIFACTS = (
        "book_continuation_plan",
        "batch_plan",
        "chapter_package",
        "chapter_length_plan",
        "chapter_execution_input",
    )

    def summarize(self, path: Path | str, *, stage: str = "", target_chars: int | None = None) -> ArtifactSummary:
        artifact_path = Path(path)
        if not artifact_path.exists():
            return ArtifactSummary(
                path=artifact_path,
                title="产物尚未生成",
                sections=[("恢复建议", "请先运行对应流程，或检查路径是否正确")],
                technical_details={"stage": stage},
            )
        if artifact_path.suffix.lower() == ".json":
            payload = self._load_json_payload(artifact_path)
            return self._summarize_json(artifact_path, payload, stage=stage)
        text = artifact_path.read_text(encoding="utf-8", errors="replace")
        return self._summarize_text(artifact_path, text, stage=stage, target_chars=target_chars)

    def validate_text(self, path: Path | str, text: str) -> str:
        artifact_path = Path(path)
        if artifact_path.suffix.lower() != ".json":
            return ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return f"当前文件不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}"
        if not isinstance(payload, (dict, list)):
            return "JSON artifact 顶层必须是对象或数组。"
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if isinstance(payload, dict) and "budgets" in payload and not isinstance(payload["budgets"], list):
            return "章节长度计划里的 budgets 必须是列表。"
        if isinstance(payload, dict) and "chapters" in payload and not isinstance(payload["chapters"], list):
            return "章节梗概里的 chapters 必须是列表。"
        return ""

    def save_text(self, path: Path | str, text: str) -> ArtifactSaveResult:
        artifact_path = Path(path)
        validation_error = self.validate_text(artifact_path, text)
        if validation_error:
            return ArtifactSaveResult(
                path=artifact_path,
                saved=False,
                message="保存前需要先修正文件内容",
                validation_error=validation_error,
            )
        artifact_path.write_text(text, encoding="utf-8")
        return ArtifactSaveResult(path=artifact_path, saved=True, message="已保存你的修改")

    def edit_model(self, path: Path | str) -> dict[str, Any]:
        artifact_path = Path(path)
        text = artifact_path.read_text(encoding="utf-8", errors="replace") if artifact_path.exists() else ""
        return {
            "path": str(artifact_path),
            "text": text,
            "syntax": "json" if artifact_path.suffix.lower() == ".json" else "markdown",
            "validation_error": self.validate_text(artifact_path, text),
        }

    def field_edit_model(self, path: Path | str) -> dict[str, Any]:
        artifact_path = Path(path)
        if artifact_path.suffix.lower() != ".json" or not self._supports_field_edit(artifact_path):
            return self.edit_model(artifact_path)
        payload = self._load_json_payload(artifact_path) if artifact_path.exists() else {}
        text = self._render_field_template(artifact_path, payload)
        return {
            "path": str(artifact_path),
            "text": text,
            "syntax": "markdown",
            "validation_error": "",
            "field_edit": True,
        }

    def save_field_text(self, path: Path | str, text: str) -> ArtifactSaveResult:
        artifact_path = Path(path)
        if artifact_path.suffix.lower() != ".json" or not self._supports_field_edit(artifact_path):
            return self.save_text(artifact_path, text)
        try:
            payload = self._load_json_payload(artifact_path)
            updated = self._apply_field_updates(artifact_path, payload, self._parse_field_text(text))
        except (json.JSONDecodeError, ValueError) as exc:
            return ArtifactSaveResult(
                path=artifact_path,
                saved=False,
                message="保存前需要先修正字段内容",
                validation_error=str(exc),
            )
        artifact_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        return ArtifactSaveResult(path=artifact_path, saved=True, message="已保存你的修改")

    def _load_json_payload(self, path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            return dict(raw["data"])
        return dict(raw) if isinstance(raw, dict) else {"items": raw}

    def _supports_field_edit(self, path: Path) -> bool:
        return any(name in path.name for name in self.FIELD_EDITABLE_ARTIFACTS)

    def _render_field_template(self, path: Path, payload: Mapping[str, Any]) -> str:
        name = path.name
        if "book_continuation_plan" in name:
            climax = payload.get("climax_plan") if isinstance(payload.get("climax_plan"), Mapping) else {}
            return "\n".join(
                [
                    "# 字段化编辑：全书续写规划",
                    f"全书目标: {payload.get('continuation_goal') or ''}",
                    f"终局方向: {payload.get('ending_direction') or ''}",
                    f"目标章节数: {payload.get('target_chapter_count') or ''}",
                    f"目标总字数: {payload.get('target_total_chars') or ''}",
                    f"默认单章字数: {payload.get('default_chapter_target_chars') or ''}",
                    f"节奏类型: {payload.get('pacing_profile') or ''}",
                    f"长度分配说明: {payload.get('length_distribution_notes') or ''}",
                    f"冲突高潮: {climax.get('conflict_climax') or '' if isinstance(climax, Mapping) else ''}",
                    f"情绪高潮: {climax.get('emotional_climax') or '' if isinstance(climax, Mapping) else ''}",
                    f"高潮章节位置: {climax.get('target_chapter_index') or '' if isinstance(climax, Mapping) else ''}",
                    f"必须铺垫: {self._join_list(climax.get('must_foreshadow') if isinstance(climax, Mapping) else [])}",
                    f"不得提前解决: {self._join_list(climax.get('must_not_resolve_before') if isinstance(climax, Mapping) else [])}",
                    f"回收预期: {climax.get('payoff_expectation') or '' if isinstance(climax, Mapping) else ''}",
                    f"阶段高潮: {self._join_list(payload.get('stage_highlights'))}",
                    f"必须保留: {self._join_list(payload.get('must_preserve'))}",
                    f"未决问题: {self._join_list(payload.get('open_questions'))}",
                ]
            )
        if "batch_plan" in name:
            return "\n".join(
                [
                    "# 字段化编辑：本批剧情大纲",
                    f"本批目标: {payload.get('batch_goal') or payload.get('stage_goal') or ''}",
                    f"入口: {payload.get('scope_start') or payload.get('entry_hook') or ''}",
                    f"冲突: {payload.get('conflict_arc') or payload.get('main_conflict') or payload.get('central_conflict') or ''}",
                    f"中点: {payload.get('midpoint') or payload.get('turning_point') or ''}",
                    f"出口钩子: {payload.get('exit_hook') or payload.get('expected_closure') or ''}",
                    f"禁止提前消费: {self._join_list(payload.get('must_not_consume') or payload.get('forbidden_early_consumption') or payload.get('forbidden_items'))}",
                ]
            )
        if "chapter_package" in name:
            chapters = [item for item in (payload.get("chapters") or []) if isinstance(item, Mapping)]
            lines = ["# 字段化编辑：章节标题与梗概"]
            for index, chapter in enumerate(chapters[:12], start=1):
                lines.extend(
                    [
                        f"章节{index}标题: {chapter.get('chapter_title') or chapter.get('title') or ''}",
                        f"章节{index}目标: {chapter.get('chapter_goal') or chapter.get('goal') or ''}",
                        f"章节{index}冲突目标: {chapter.get('conflict_goal') or chapter.get('conflict_target') or ''}",
                        f"章节{index}关系推进: {chapter.get('relationship_goal') or chapter.get('relationship_progression') or ''}",
                        f"章节{index}必须出现: {self._join_list(chapter.get('must_include') or chapter.get('must_appear'))}",
                        f"章节{index}禁止项: {self._join_list(chapter.get('forbidden_items') or chapter.get('must_not_include'))}",
                    ]
                )
            return "\n".join(lines)
        if "chapter_length_plan" in name:
            budgets = [item for item in (payload.get("budgets") or []) if isinstance(item, Mapping)]
            budget_lines = [
                f"{item.get('chapter_id') or ''}={item.get('target_chars') or ''}/{item.get('min_chars') or ''}/{item.get('max_chars') or ''}"
                for item in budgets
            ]
            return "\n".join(
                [
                    "# 字段化编辑：章节长度计划",
                    f"默认目标字数: {payload.get('default_target_chars') or ''}",
                    f"重点章节: {self._join_list(payload.get('focus_chapter_ids'))}",
                    f"高潮章节: {self._join_list(payload.get('climax_chapter_ids'))}",
                    "单章预算: " + "; ".join(budget_lines),
                ]
            )
        if "chapter_execution_input" in name:
            return "\n".join(
                [
                    "# 字段化编辑：本章写作材料",
                    f"章节 brief: {payload.get('chapter_brief') or payload.get('chapter_title') or payload.get('chapter_id') or ''}",
                    f"长度预算: {self._format_mapping(payload.get('length_budget'))}",
                    f"事实约束: {self._join_list(payload.get('fact_constraints') or payload.get('memory_constraints'))}",
                    f"风格参考: {self._join_list(payload.get('style_references') or payload.get('creative_references'))}",
                    f"人物门禁: {self._join_list(payload.get('planned_character_constraints') or payload.get('character_gates'))}",
                    f"禁止项: {self._join_list(payload.get('forbidden_items') or payload.get('forbidden_carryover'))}",
                ]
            )
        return json.dumps(dict(payload), ensure_ascii=False, indent=2)

    @staticmethod
    def _parse_field_text(text: str) -> dict[str, str]:
        values: dict[str, str] = {}
        current_key = ""
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                current_key = key.strip()
                values[current_key] = value.strip()
                continue
            if current_key:
                values[current_key] = f"{values.get(current_key, '').strip()}\n{line.strip()}".strip()
        return values

    def _apply_field_updates(self, path: Path, payload: Mapping[str, Any], values: Mapping[str, str]) -> dict[str, Any]:
        name = path.name
        updated = dict(payload)
        if "book_continuation_plan" in name:
            self._set_text(updated, values, "全书目标", "continuation_goal")
            self._set_text(updated, values, "终局方向", "ending_direction")
            self._set_int(updated, values, "目标章节数", "target_chapter_count")
            self._set_int(updated, values, "目标总字数", "target_total_chars")
            self._set_int(updated, values, "默认单章字数", "default_chapter_target_chars")
            self._set_text(updated, values, "节奏类型", "pacing_profile")
            self._set_text(updated, values, "长度分配说明", "length_distribution_notes")
            climax = dict(updated.get("climax_plan") if isinstance(updated.get("climax_plan"), Mapping) else {})
            self._set_text(climax, values, "冲突高潮", "conflict_climax")
            self._set_text(climax, values, "情绪高潮", "emotional_climax")
            self._set_int(climax, values, "高潮章节位置", "target_chapter_index")
            self._set_list(climax, values, "必须铺垫", "must_foreshadow")
            self._set_list(climax, values, "不得提前解决", "must_not_resolve_before")
            self._set_text(climax, values, "回收预期", "payoff_expectation")
            updated["climax_plan"] = climax
            self._set_list(updated, values, "阶段高潮", "stage_highlights")
            self._set_list(updated, values, "必须保留", "must_preserve")
            self._set_list(updated, values, "未决问题", "open_questions")
            return updated
        if "batch_plan" in name:
            self._set_text(updated, values, "本批目标", "batch_goal")
            self._set_text(updated, values, "入口", "entry_hook")
            self._set_text(updated, values, "冲突", "conflict_arc")
            self._set_text(updated, values, "中点", "midpoint")
            self._set_text(updated, values, "出口钩子", "exit_hook")
            self._set_list(updated, values, "禁止提前消费", "must_not_consume")
            return updated
        if "chapter_package" in name:
            chapters = [dict(item) for item in (updated.get("chapters") or []) if isinstance(item, Mapping)]
            for index, chapter in enumerate(chapters, start=1):
                self._set_text(chapter, values, f"章节{index}标题", "chapter_title")
                self._set_text(chapter, values, f"章节{index}目标", "chapter_goal")
                self._set_text(chapter, values, f"章节{index}冲突目标", "conflict_goal")
                self._set_text(chapter, values, f"章节{index}关系推进", "relationship_goal")
                self._set_list(chapter, values, f"章节{index}必须出现", "must_include")
                self._set_list(chapter, values, f"章节{index}禁止项", "forbidden_items")
            updated["chapters"] = chapters
            return updated
        if "chapter_length_plan" in name:
            self._set_int(updated, values, "默认目标字数", "default_target_chars")
            self._set_list(updated, values, "重点章节", "focus_chapter_ids")
            self._set_list(updated, values, "高潮章节", "climax_chapter_ids")
            if "单章预算" in values:
                updated["budgets"] = self._parse_budget_lines(values["单章预算"])
            return updated
        if "chapter_execution_input" in name:
            self._set_text(updated, values, "章节 brief", "chapter_brief")
            self._set_list(updated, values, "事实约束", "fact_constraints")
            self._set_list(updated, values, "风格参考", "style_references")
            self._set_list(updated, values, "人物门禁", "planned_character_constraints")
            self._set_list(updated, values, "禁止项", "forbidden_items")
            return updated
        return updated

    def _summarize_json(self, path: Path, payload: Mapping[str, Any], *, stage: str) -> ArtifactSummary:
        name = path.name
        if "character_requirement_report" in name:
            return self._summarize_character_requirement_report(path, payload, stage=stage)
        if "character_seed" in name:
            return self._summarize_character_seed_input(path, payload, stage=stage)
        if "character_cast_request" in name:
            return self._summarize_character_cast_request(path, payload, stage=stage)
        if "planned_character_profiles" in name:
            return self._summarize_planned_character_profiles(path, payload, stage=stage)
        if "character_cast_plan" in name:
            return self._summarize_character_cast_plan(path, payload, stage=stage)
        if "character_introduction_plan" in name:
            return self._summarize_character_introduction_plan(path, payload, stage=stage)
        if "book_continuation_plan" in name:
            return self._summarize_book_continuation_plan(path, payload, stage=stage)
        if "batch_plan" in name or stage == "batch_review":
            return ArtifactSummary(
                path=path,
                title="本批剧情大纲摘要",
                sections=[
                    ("阶段目标", self._first_text(payload, "stage_goal", "goal", "batch_goal")),
                    ("主要冲突", self._first_text(payload, "main_conflict", "central_conflict", "conflict")),
                    ("情绪节奏", self._first_text(payload, "emotional_pacing", "pacing_notes", "mood")),
                    ("预计收束点", self._first_text(payload, "expected_closure", "exit_state", "ending_state")),
                    ("禁止提前消费", self._join_list(payload.get("forbidden_early_consumption") or payload.get("forbidden_items"))),
                    ("待确认问题", self._join_list(payload.get("open_questions") or payload.get("unresolved_questions"))),
                ],
                collapsed=len(json.dumps(payload, ensure_ascii=False)) > 3000,
                next_action="确认后生成章节标题与梗概",
                technical_details={"stage": stage, "keys": sorted(str(key) for key in payload.keys())},
            )
        if "chapter_package" in name or stage in {"chapter_review", "wait_chapter_review"}:
            return self._summarize_chapter_package(path, payload, stage=stage)
        if "chapter_length_plan" in name or stage == "wait_length_review":
            budgets = [item for item in payload.get("budgets", []) if isinstance(item, Mapping)]
            budget_lines = [
                f"{item.get('chapter_id', '未命名章节')} {item.get('target_chars', '?')} 字"
                for item in budgets[:6]
            ]
            return ArtifactSummary(
                path=path,
                title="章节长度计划摘要",
                sections=[
                    ("默认目标字数", str(payload.get("default_target_chars") or "")),
                    ("重点章节", self._join_list(payload.get("focus_chapter_ids"))),
                    ("单章预算", "；".join(budget_lines)),
                    ("展开建议", self._join_list(payload.get("review_notes") or payload.get("expansion_notes"))),
                ],
                collapsed=len(budgets) > 6,
                next_action="确认后整理本章写作材料",
                technical_details={"stage": stage, "budget_count": len(budgets)},
            )
        if "chapter_execution_input" in name or stage == "freeze_d_review":
            return ArtifactSummary(
                path=path,
                title="本章写作材料摘要",
                sections=[
                    ("章节", self._first_text(payload, "chapter_title", "chapter_id")),
                    ("长度预算", self._format_mapping(payload.get("length_budget"))),
                    ("事实约束", self._join_list(payload.get("fact_constraints") or payload.get("memory_constraints"))),
                    ("风格参考", self._join_list(payload.get("style_references") or payload.get("creative_references"))),
                    ("禁止项", self._join_list(payload.get("forbidden_items") or payload.get("forbidden_carryover"))),
                ],
                collapsed=True,
                next_action="确认后生成正文草稿",
                technical_details={"stage": stage},
            )
        if "continuity_report" in name:
            return ArtifactSummary(
                path=path,
                title="连续性检查摘要",
                sections=[
                    ("连续性", "通过" if payload.get("canon_ready") else "需要检查"),
                    ("问题", self._join_list(payload.get("issues") or payload.get("blocking_issues"))),
                    ("写回提示", self._join_list(payload.get("writeback_notes"))),
                ],
                next_action="确认后更新续写记忆",
                technical_details={"stage": stage},
            )
        sections = [(key, self._short_value(value)) for key, value in list(payload.items())[:8]]
        return ArtifactSummary(
            path=path,
            title="产物摘要",
            sections=sections,
            collapsed=len(payload) > 8,
            technical_details={"stage": stage, "keys": sorted(str(key) for key in payload.keys())},
        )

    def _summarize_book_continuation_plan(
        self,
        path: Path,
        payload: Mapping[str, Any],
        *,
        stage: str,
    ) -> ArtifactSummary:
        climax_plan = payload.get("climax_plan") if isinstance(payload.get("climax_plan"), Mapping) else {}
        slots = [item for item in (payload.get("chapter_outline_slots") or []) if isinstance(item, Mapping)]
        slot_lines = []
        for slot in slots[:6]:
            chapter_index = slot.get("chapter_index") or "?"
            target_chars = slot.get("target_chars") or "?"
            function = slot.get("plot_function") or ""
            slot_lines.append(f"第{chapter_index}章 {target_chars}字: {function}")
        return ArtifactSummary(
            path=path,
            title="全书续写规划摘要",
            sections=[
                ("全书目标", self._first_text(payload, "continuation_goal")),
                ("目标规模", self._format_scale(payload)),
                ("节奏", self._first_text(payload, "pacing_profile", "length_distribution_notes")),
                ("终局方向", self._first_text(payload, "ending_direction")),
                ("冲突高潮", self._short_value(climax_plan.get("conflict_climax") if isinstance(climax_plan, Mapping) else "")),
                ("情绪高潮", self._short_value(climax_plan.get("emotional_climax") if isinstance(climax_plan, Mapping) else "")),
                ("高潮位置", str(climax_plan.get("target_chapter_index") or "") if isinstance(climax_plan, Mapping) else ""),
                ("章节 slot", "；".join(slot_lines)),
                ("必须保留", self._join_list(payload.get("must_preserve"))),
                ("未决问题", self._join_list(payload.get("open_questions"))),
            ],
            collapsed=len(slots) > 6,
            next_action="确认后冻结全书规划，并进入本批剧情大纲",
            technical_details={"stage": stage, "slot_count": len(slots), "keys": sorted(str(key) for key in payload.keys())},
        )

    def _summarize_character_requirement_report(
        self,
        path: Path,
        payload: Mapping[str, Any],
        *,
        stage: str,
    ) -> ArtifactSummary:
        existing = [item for item in (payload.get("named_existing_characters") or []) if isinstance(item, Mapping)]
        new_characters = [item for item in (payload.get("named_new_characters") or []) if isinstance(item, Mapping)]
        role_slots = [item for item in (payload.get("unfilled_role_slots") or []) if isinstance(item, Mapping)]
        return ArtifactSummary(
            path=path,
            title="角色需求解析摘要",
            sections=[
                ("已有人物", "；".join(self._character_existing_line(item) for item in existing[:8])),
                ("新角色候选", "；".join(self._character_new_line(item) for item in new_characters[:8])),
                ("剧情缺位角色", "；".join(self._role_slot_line(item) for item in role_slots[:8])),
            ],
            collapsed=len(existing) + len(new_characters) + len(role_slots) > 8,
            next_action="确认角色需求后生成或审阅人物补充方案",
            technical_details={
                "stage": stage,
                "named_existing_count": len(existing),
                "named_new_count": len(new_characters),
                "role_slot_count": len(role_slots),
            },
        )

    def _summarize_character_cast_request(
        self,
        path: Path,
        payload: Mapping[str, Any],
        *,
        stage: str,
    ) -> ArtifactSummary:
        requirements = [item for item in (payload.get("requirements") or []) if isinstance(item, Mapping)]
        lines = [self._cast_requirement_line(item) for item in requirements[:8]]
        return ArtifactSummary(
            path=path,
            title="角色补充请求摘要",
            sections=[
                ("为什么需要补角色", self._first_text(payload, "reason")),
                ("角色需求", "；".join(lines)),
            ],
            collapsed=len(requirements) > 8,
            next_action="根据这些需求生成计划人物卡",
            technical_details={"stage": stage, "requirement_count": len(requirements), "request_id": payload.get("request_id")},
        )

    def _summarize_character_seed_input(
        self,
        path: Path,
        payload: Mapping[str, Any],
        *,
        stage: str,
    ) -> ArtifactSummary:
        seeds = self._extract_seed_inputs(payload)
        lines = [self._seed_input_line(item) for item in seeds[:6]]
        return ArtifactSummary(
            path=path,
            title="新角色雏形摘要",
            sections=[
                ("角色雏形", "；".join(lines)),
                ("必须保留", self._join_list([value for item in seeds for value in (item.get("must_keep") or [])])),
                ("必须避免", self._join_list([value for item in seeds for value in (item.get("must_avoid") or [])])),
                ("世界观限制", self._join_list([value for item in seeds for value in (item.get("world_constraints") or [])])),
            ],
            collapsed=len(seeds) > 6,
            next_action="确认后扩展为计划人物卡",
            technical_details={
                "stage": stage,
                "seed_count": len(seeds),
                "seed_ids": [str(item.get("seed_id") or "") for item in seeds],
            },
        )

    def _summarize_planned_character_profiles(
        self,
        path: Path,
        payload: Mapping[str, Any],
        *,
        stage: str,
    ) -> ArtifactSummary:
        profiles = self._extract_profiles(payload)
        lines = [self._planned_profile_line(item) for item in profiles[:6]]
        return ArtifactSummary(
            path=path,
            title="计划人物卡片摘要",
            sections=[
                ("计划人物", "；".join(lines)),
                ("禁止提前揭示", self._join_list([secret for item in profiles for secret in (item.get("must_not_reveal_early") or [])])),
            ],
            collapsed=len(profiles) > 6,
            next_action="确认计划人物后进入角色方案审阅",
            technical_details={
                "stage": stage,
                "profile_count": len(profiles),
                "planned_character_ids": [str(item.get("planned_character_id") or "") for item in profiles],
            },
        )

    def _summarize_character_cast_plan(
        self,
        path: Path,
        payload: Mapping[str, Any],
        *,
        stage: str,
    ) -> ArtifactSummary:
        profiles_by_id = self._load_sibling_profiles(path)
        bindings = [item for item in (payload.get("planned_characters") or []) if isinstance(item, Mapping)]
        binding_lines = [self._cast_binding_line(item, profiles_by_id) for item in bindings[:8]]
        return ArtifactSummary(
            path=path,
            title="角色方案审阅摘要",
            sections=[
                ("计划进入本批", "；".join(line for line in binding_lines if line)),
                ("不得提前消费", self._join_list(payload.get("must_not_consume"))),
                ("未决问题", self._join_list(payload.get("open_questions"))),
            ],
            collapsed=len(bindings) > 8,
            next_action="确认后这些计划人物会随全书规划冻结",
            technical_details={
                "stage": stage,
                "binding_count": len(bindings),
                "planned_character_ids": [str(item.get("planned_character_id") or "") for item in bindings],
                "cast_plan_id": payload.get("cast_plan_id"),
            },
        )

    def _summarize_character_introduction_plan(
        self,
        path: Path,
        payload: Mapping[str, Any],
        *,
        stage: str,
    ) -> ArtifactSummary:
        profiles_by_id = self._load_sibling_profiles(path)
        items = [item for item in (payload.get("introduction_items") or []) if isinstance(item, Mapping)]
        lines = [self._introduction_line(item, profiles_by_id) for item in items[:8]]
        return ArtifactSummary(
            path=path,
            title="首次登场安排摘要",
            sections=[("登场安排", "；".join(lines))],
            collapsed=len(items) > 8,
            next_action="确认后写入章节包与批次规划边界",
            technical_details={
                "stage": stage,
                "introduction_count": len(items),
                "planned_character_ids": [str(item.get("planned_character_id") or "") for item in items],
            },
        )

    def _summarize_chapter_package(self, path: Path, payload: Mapping[str, Any], *, stage: str) -> ArtifactSummary:
        chapters = [item for item in payload.get("chapters", []) if isinstance(item, Mapping)]
        lines = []
        for chapter in chapters[:5]:
            title = chapter.get("chapter_title") or chapter.get("title") or chapter.get("chapter_id") or "未命名章节"
            goal = chapter.get("chapter_goal") or chapter.get("goal") or chapter.get("relationship_goal") or ""
            lines.append(f"{title}: {goal}")
        return ArtifactSummary(
            path=path,
            title="章节标题与梗概摘要",
            sections=[
                ("章节目标", "；".join(lines)),
                ("冲突目标", self._join_list(payload.get("conflict_goals") or payload.get("conflicts"))),
                ("关系推进", self._join_list(payload.get("relationship_goals") or payload.get("relationship_progression"))),
                ("禁止写入", self._join_list(payload.get("forbidden_items") or payload.get("forbidden_carryover"))),
                ("待确认问题", self._join_list(payload.get("open_questions") or payload.get("review_notes"))),
            ],
            collapsed=len(chapters) > 5,
            next_action="确认后规划章节长度",
            technical_details={"stage": stage, "chapter_count": len(chapters)},
        )

    def _summarize_text(
        self,
        path: Path,
        text: str,
        *,
        stage: str,
        target_chars: int | None,
    ) -> ArtifactSummary:
        preview = text[: self.LARGE_PREVIEW_CHARS]
        sections = [
            ("当前字数", str(len(text))),
            ("目标字数", str(target_chars or "")),
        ]
        return ArtifactSummary(
            path=path,
            title="正文草稿摘要" if path.suffix.lower() == ".md" else "文本产物摘要",
            sections=sections,
            preview=preview,
            collapsed=len(text) > self.LARGE_PREVIEW_CHARS,
            next_action="请验收当前章节" if "draft" in path.name else "",
            technical_details={"stage": stage},
        )

    @staticmethod
    def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _join_list(value: object) -> str:
        if isinstance(value, list):
            return "；".join(str(item).strip() for item in value if str(item).strip())
        if isinstance(value, str):
            return value.strip()
        return ""

    @staticmethod
    def _format_mapping(value: object) -> str:
        if not isinstance(value, Mapping):
            return ""
        return "，".join(f"{key}={item}" for key, item in value.items())

    @staticmethod
    def _set_text(target: dict[str, Any], values: Mapping[str, str], label: str, key: str) -> None:
        if label in values:
            target[key] = values[label].strip()

    @staticmethod
    def _set_int(target: dict[str, Any], values: Mapping[str, str], label: str, key: str) -> None:
        if label not in values or not values[label].strip():
            return
        try:
            parsed = int(values[label].strip())
        except ValueError as exc:
            raise ValueError(f"{label} 必须是整数。") from exc
        if parsed < 0:
            raise ValueError(f"{label} 不能小于 0。")
        target[key] = parsed

    @staticmethod
    def _set_list(target: dict[str, Any], values: Mapping[str, str], label: str, key: str) -> None:
        if label in values:
            target[key] = ArtifactPresenter._split_items(values[label])

    @staticmethod
    def _split_items(value: str) -> list[str]:
        normalized = value.replace("，", ",").replace("；", ";").replace("\n", ";")
        items: list[str] = []
        for chunk in normalized.replace(";", ",").split(","):
            item = chunk.strip()
            if item:
                items.append(item)
        return items

    @staticmethod
    def _parse_budget_lines(value: str) -> list[dict[str, Any]]:
        budgets: list[dict[str, Any]] = []
        for chunk in ArtifactPresenter._split_items(value):
            if "=" not in chunk:
                raise ValueError("单章预算格式应为 chapter_id=target/min/max。")
            chapter_id, raw_budget = chunk.split("=", 1)
            numbers = [part.strip() for part in raw_budget.split("/") if part.strip()]
            if not chapter_id.strip() or not numbers:
                raise ValueError("单章预算格式应为 chapter_id=target/min/max。")
            try:
                target_chars = int(numbers[0])
                min_chars = int(numbers[1]) if len(numbers) > 1 else target_chars
                max_chars = int(numbers[2]) if len(numbers) > 2 else target_chars
            except ValueError as exc:
                raise ValueError("单章预算里的 target/min/max 必须是整数。") from exc
            budgets.append(
                {
                    "chapter_id": chapter_id.strip(),
                    "target_chars": target_chars,
                    "min_chars": min_chars,
                    "max_chars": max_chars,
                }
            )
        return budgets

    @staticmethod
    def _format_scale(payload: Mapping[str, Any]) -> str:
        parts = []
        if payload.get("target_chapter_count"):
            parts.append(f"{payload.get('target_chapter_count')}章")
        if payload.get("target_total_chars"):
            parts.append(f"总计约{payload.get('target_total_chars')}字")
        if payload.get("default_chapter_target_chars"):
            parts.append(f"默认单章{payload.get('default_chapter_target_chars')}字")
        return "，".join(parts)

    @staticmethod
    def _short_value(value: object) -> str:
        if isinstance(value, (str, int, float, bool)):
            return str(value)[:180]
        if isinstance(value, list):
            return "；".join(str(item)[:80] for item in value[:4])
        if isinstance(value, Mapping):
            return "，".join(f"{key}={item}"[:80] for key, item in list(value.items())[:4])
        return ""

    @staticmethod
    def _character_existing_line(item: Mapping[str, Any]) -> str:
        name = str(item.get("name") or "").strip()
        resolved_to = str(item.get("resolved_to") or "").strip()
        return f"{name} -> {resolved_to}" if name and resolved_to and name != resolved_to else name or resolved_to

    @staticmethod
    def _character_new_line(item: Mapping[str, Any]) -> str:
        name = str(item.get("name") or "").strip()
        reason = str(item.get("reason") or "").strip()
        return f"{name}: {reason}" if reason else name

    @staticmethod
    def _role_slot_line(item: Mapping[str, Any]) -> str:
        role_type = str(item.get("slot_type") or item.get("role_type") or "未命名功能位").strip()
        reason = str(item.get("reason") or "").strip()
        return f"{role_type}: {reason}" if reason else role_type

    @staticmethod
    def _cast_requirement_line(item: Mapping[str, Any]) -> str:
        role_type = str(item.get("role_type") or "未命名功能位").strip()
        faction = str(item.get("faction") or "").strip()
        count = item.get("count") or 1
        traits = ArtifactPresenter._join_list(item.get("required_traits"))
        window = item.get("introduction_window")
        window_text = ""
        if isinstance(window, Mapping):
            chapters = ArtifactPresenter._join_list(window.get("chapter_range"))
            if chapters:
                window_text = f"，登场窗口 {chapters}"
        prefix = f"{faction}·{role_type}" if faction else role_type
        suffix = f"，需要 {traits}" if traits else ""
        return f"{prefix} x{count}{suffix}{window_text}"

    @staticmethod
    def _planned_profile_line(item: Mapping[str, Any]) -> str:
        name = str(item.get("canonical_name") or "未命名角色").strip()
        faction = str(item.get("faction") or "").strip()
        role = str(item.get("narrative_role") or "").strip()
        intro = item.get("first_introduction_plan")
        intro_text = ""
        if isinstance(intro, Mapping):
            chapter_id = str(intro.get("chapter_id") or "").strip()
            scene_function = str(intro.get("scene_function") or "").strip()
            if chapter_id or scene_function:
                intro_text = f"，首次登场 {chapter_id} {scene_function}".strip()
        parts = [part for part in [name, faction, role] if part]
        return " / ".join(parts) + intro_text

    @staticmethod
    def _extract_profiles(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        raw_profiles = payload.get("planned_character_profiles")
        if raw_profiles is None and isinstance(payload.get("items"), list):
            raw_profiles = payload.get("items")
        if raw_profiles is None and "planned_character_id" in payload:
            raw_profiles = [payload]
        return [item for item in (raw_profiles or []) if isinstance(item, Mapping)]

    @staticmethod
    def _extract_seed_inputs(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        raw_seeds = payload.get("character_seed_inputs") or payload.get("character_seeds") or payload.get("seeds")
        if raw_seeds is None and isinstance(payload.get("items"), list):
            raw_seeds = payload.get("items")
        if raw_seeds is None and "seed_id" in payload:
            raw_seeds = [payload]
        return [item for item in (raw_seeds or []) if isinstance(item, Mapping)]

    @staticmethod
    def _seed_input_line(item: Mapping[str, Any]) -> str:
        name = str(item.get("display_name_hint") or "未命名角色").strip()
        faction = str(item.get("faction") or "").strip()
        concept = str(item.get("core_concept") or "").strip()
        relationship_entry = item.get("relationship_entry")
        relationship = ""
        if isinstance(relationship_entry, Mapping):
            target = str(relationship_entry.get("target_character") or "").strip()
            state = str(relationship_entry.get("initial_state") or "").strip()
            if target or state:
                relationship = f"关系入口 {target} {state}".strip()
        return " / ".join(part for part in [name, faction, concept, relationship] if part)

    def _load_sibling_profiles(self, path: Path) -> dict[str, Mapping[str, Any]]:
        profiles_path = path.with_name("planned_character_profiles.json")
        if not profiles_path.exists():
            return {}
        try:
            payload = self._load_json_payload(profiles_path)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
        profiles = self._extract_profiles(payload)
        return {
            str(item.get("planned_character_id") or ""): item
            for item in profiles
            if str(item.get("planned_character_id") or "")
        }

    @staticmethod
    def _cast_binding_line(item: Mapping[str, Any], profiles_by_id: Mapping[str, Mapping[str, Any]]) -> str:
        character_id = str(item.get("planned_character_id") or "").strip()
        profile = profiles_by_id.get(character_id, {})
        name = str(profile.get("canonical_name") or "").strip()
        role = str(profile.get("narrative_role") or "").strip()
        if name:
            return f"{name}{f' / {role}' if role else ''}"
        return "计划人物"

    @staticmethod
    def _introduction_line(item: Mapping[str, Any], profiles_by_id: Mapping[str, Mapping[str, Any]]) -> str:
        character_id = str(item.get("planned_character_id") or "").strip()
        profile = profiles_by_id.get(character_id, {})
        name = str(profile.get("canonical_name") or "计划人物").strip()
        chapter_id = str(item.get("chapter_id") or "").strip()
        scene_function = str(item.get("required_scene_function") or "").strip()
        relationship_effect = str(item.get("required_relationship_effect") or "").strip()
        forbidden = ArtifactPresenter._join_list(item.get("forbidden_moves"))
        parts = [name]
        if chapter_id:
            parts.append(chapter_id)
        if scene_function:
            parts.append(scene_function)
        if relationship_effect:
            parts.append(relationship_effect)
        line = " / ".join(parts)
        return f"{line}；禁止：{forbidden}" if forbidden else line
