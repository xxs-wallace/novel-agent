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

    def _load_json_payload(self, path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            return dict(raw["data"])
        return dict(raw) if isinstance(raw, dict) else {"items": raw}

    def _summarize_json(self, path: Path, payload: Mapping[str, Any], *, stage: str) -> ArtifactSummary:
        name = path.name
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
    def _short_value(value: object) -> str:
        if isinstance(value, (str, int, float, bool)):
            return str(value)[:180]
        if isinstance(value, list):
            return "；".join(str(item)[:80] for item in value[:4])
        if isinstance(value, Mapping):
            return "，".join(f"{key}={item}"[:80] for key, item in list(value.items())[:4])
        return ""
