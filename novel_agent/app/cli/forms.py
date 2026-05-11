from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _split_items(value: str) -> list[str]:
    normalized = value.replace("，", ",").replace("；", ";").replace("\n", ";")
    items: list[str] = []
    for chunk in normalized.replace(";", ",").split(","):
        item = chunk.strip()
        if item:
            items.append(item)
    return items


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "是", "允许", "需要", "开"}


def _positive_int(value: str, default: int) -> int:
    try:
        parsed = int(value.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


@dataclass(slots=True)
class WriterIntentForm:
    major_characters: list[str] = field(default_factory=list)
    desired_actions: list[str] = field(default_factory=list)
    avoidances: list[str] = field(default_factory=list)
    preferred_outcome: str = ""
    notes: str = ""
    user_world_notes: str = ""
    target_chapter_count: int = 3
    chapter_count: int = 3
    target_total_chars: int = 12000
    default_chapter_target_chars: int = 4000
    pacing_profile: str = "均衡推进"
    length_distribution_notes: str = ""
    conflict_climax: str = ""
    emotional_climax: str = ""
    target_chapter_index: int = 0
    must_foreshadow: list[str] = field(default_factory=list)
    must_not_resolve_before: list[str] = field(default_factory=list)
    payoff_expectation: str = ""
    allow_character_cast: bool = True

    def to_intent_payload(self) -> dict[str, Any]:
        return {
            "major_characters": list(self.major_characters),
            "desired_actions": list(self.desired_actions),
            "avoidances": list(self.avoidances),
            "preferred_outcome": self.preferred_outcome,
            "notes": self.notes,
            "allow_character_cast": self.allow_character_cast,
            "story_scale": self.to_story_scale_payload(),
            "climax_plan": self.to_climax_plan_payload(),
        }

    def to_start_writer_kwargs(self) -> dict[str, Any]:
        return {
            "intent_payload": self.to_intent_payload(),
            "user_world_notes": self.user_world_notes,
            "target_chapter_count": self.target_chapter_count,
            "chapter_count": self.chapter_count,
        }

    def to_story_scale_payload(self) -> dict[str, Any]:
        target_total = self.target_total_chars
        default_target = self.default_chapter_target_chars
        if target_total > 0 and default_target <= 0:
            default_target = max(1, target_total // max(1, self.target_chapter_count))
        if default_target > 0 and target_total <= 0:
            target_total = default_target * max(1, self.target_chapter_count)
        return {
            "target_chapter_count": self.target_chapter_count,
            "target_total_chars": target_total,
            "default_chapter_target_chars": default_target,
            "pacing_profile": self.pacing_profile,
            "length_distribution_notes": self.length_distribution_notes,
        }

    def to_climax_plan_payload(self) -> dict[str, Any]:
        return {
            "conflict_climax": self.conflict_climax,
            "emotional_climax": self.emotional_climax,
            "target_chapter_index": self.target_chapter_index,
            "must_foreshadow": list(self.must_foreshadow),
            "must_not_resolve_before": list(self.must_not_resolve_before),
            "payoff_expectation": self.payoff_expectation,
        }

    @classmethod
    def from_template_text(cls, text: str) -> "WriterIntentForm":
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

        target_chapter_count = _positive_int(
            values.get("全书规划章节数", "") or values.get("本批章节数", ""),
            3,
        )
        target_total_chars = _positive_int(values.get("目标总字数", ""), target_chapter_count * 4000)
        default_chapter_target_chars = _positive_int(
            values.get("默认单章字数", ""),
            max(1, target_total_chars // max(1, target_chapter_count)),
        )

        return cls(
            major_characters=_split_items(values.get("主要角色", "")),
            desired_actions=_split_items(values.get("续写目标", "")),
            avoidances=_split_items(values.get("避免项", "")),
            preferred_outcome=values.get("期望结果", "").strip(),
            notes=values.get("补充说明", "").strip(),
            user_world_notes=values.get("世界观补充", "").strip(),
            target_chapter_count=target_chapter_count,
            chapter_count=_positive_int(values.get("生成梗概数", ""), 3),
            target_total_chars=target_total_chars,
            default_chapter_target_chars=default_chapter_target_chars,
            pacing_profile=values.get("节奏类型", "").strip() or "均衡推进",
            length_distribution_notes=values.get("长度分配说明", "").strip(),
            conflict_climax=values.get("冲突高潮", "").strip(),
            emotional_climax=values.get("情绪高潮", "").strip(),
            target_chapter_index=_positive_int(values.get("高潮章节位置", ""), 0),
            must_foreshadow=_split_items(values.get("必须铺垫", "")),
            must_not_resolve_before=_split_items(values.get("不得提前解决", "")),
            payoff_expectation=values.get("回收预期", "").strip(),
            allow_character_cast=_truthy(values.get("允许新角色", "是")),
        )

    def render_template(self) -> str:
        return "\n".join(
            [
                "# Writer 启动向导：请按字段填写；逗号或分号可拆成多条。",
                f"主要角色: {', '.join(self.major_characters)}",
                f"续写目标: {'; '.join(self.desired_actions)}",
                f"避免项: {'; '.join(self.avoidances)}",
                f"期望结果: {self.preferred_outcome}",
                f"补充说明: {self.notes}",
                f"世界观补充: {self.user_world_notes}",
                f"全书规划章节数: {self.target_chapter_count}",
                f"生成梗概数: {self.chapter_count}",
                f"目标总字数: {self.target_total_chars}",
                f"默认单章字数: {self.default_chapter_target_chars}",
                f"节奏类型: {self.pacing_profile}",
                f"长度分配说明: {self.length_distribution_notes}",
                f"冲突高潮: {self.conflict_climax}",
                f"情绪高潮: {self.emotional_climax}",
                f"高潮章节位置: {self.target_chapter_index}",
                f"必须铺垫: {'; '.join(self.must_foreshadow)}",
                f"不得提前解决: {'; '.join(self.must_not_resolve_before)}",
                f"回收预期: {self.payoff_expectation}",
                f"允许新角色: {'是' if self.allow_character_cast else '否'}",
            ]
        )

    @classmethod
    def from_goal_text(cls, goal_text: str) -> "WriterIntentForm":
        goal = goal_text.strip()
        return cls(desired_actions=[goal] if goal else [])


@dataclass(slots=True)
class ChapterAcceptanceForm:
    status: str
    feedback_text: str = ""
    reason_code: str = ""
    target_chars: int = 0
    min_chars: int = 0
    max_chars: int = 0
    must_preserve: list[str] = field(default_factory=list)
    must_change: list[str] = field(default_factory=list)
    forbidden_carryover: list[str] = field(default_factory=list)
    requested_length_direction: str = ""

    @classmethod
    def for_status(cls, status: str, *, target_chars: int = 0) -> "ChapterAcceptanceForm":
        normalized = status.strip().lower()
        reason_by_status = {
            "accepted": "approved",
            "revise_length": "length_or_pacing_revision_requested",
            "replan_chapter": "chapter_plan_revision_requested",
            "discarded": "discarded_by_user",
        }
        target = target_chars if target_chars > 0 else 4000
        return cls(
            status=normalized,
            reason_code=reason_by_status.get(normalized, normalized),
            target_chars=target,
            min_chars=max(1, target * 85 // 100),
            max_chars=max(target, target * 115 // 100),
            must_change=["需要调整章节规划"] if normalized == "replan_chapter" else [],
        )

    @classmethod
    def from_template_text(cls, text: str, *, default_status: str = "") -> "ChapterAcceptanceForm":
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
        status = values.get("决策", default_status).strip() or default_status
        return cls(
            status=status,
            feedback_text=values.get("反馈", "").strip(),
            reason_code=values.get("原因代码", "").strip(),
            target_chars=_positive_int(values.get("目标字数", ""), 0),
            min_chars=_positive_int(values.get("最小字数", ""), 0),
            max_chars=_positive_int(values.get("最大字数", ""), 0),
            must_preserve=_split_items(values.get("必须保留", "")),
            must_change=_split_items(values.get("必须修改", "")),
            forbidden_carryover=_split_items(values.get("禁止沿用", "")),
            requested_length_direction=values.get("长度建议", "").strip(),
        )

    def render_template(self) -> str:
        lines = [
            "# 章节验收表单：补齐字段后 Ctrl+Enter 提交。",
            f"决策: {self.status}",
            f"原因代码: {self.reason_code}",
            f"反馈: {self.feedback_text}",
        ]
        if self.status == "revise_length":
            lines.extend(
                [
                    f"目标字数: {self.target_chars}",
                    f"最小字数: {self.min_chars}",
                    f"最大字数: {self.max_chars}",
                    "必须保留: " + "; ".join(self.must_preserve),
                ]
            )
        if self.status == "replan_chapter":
            lines.extend(
                [
                    "必须保留: " + "; ".join(self.must_preserve),
                    "必须修改: " + "; ".join(self.must_change),
                    "禁止沿用: " + "; ".join(self.forbidden_carryover),
                    f"长度建议: {self.requested_length_direction}",
                ]
            )
        return "\n".join(lines)

    def to_workflow_payload(self) -> dict[str, Any]:
        normalized = self.status.strip().lower()
        if normalized not in {"accepted", "revise_length", "replan_chapter", "discarded"}:
            raise ValueError("决策必须是 accepted / revise_length / replan_chapter / discarded。")
        payload: dict[str, Any] = {
            "status": normalized,
            "reason_code": self.reason_code or self._default_reason_code(normalized),
            "feedback_text": self.feedback_text,
        }
        if normalized == "revise_length":
            target = self.target_chars or 4000
            min_chars = self.min_chars or max(1, target * 85 // 100)
            max_chars = self.max_chars or max(target, target * 115 // 100)
            if not min_chars <= target <= max_chars:
                raise ValueError("最小字数必须 <= 目标字数 <= 最大字数。")
            payload["length_plan_update"] = {
                "target_chars": target,
                "min_chars": min_chars,
                "max_chars": max_chars,
                "reason_code": payload["reason_code"],
                "feedback_text": self.feedback_text,
                "preserve_story_direction": True,
            }
        if normalized == "replan_chapter":
            must_change = list(self.must_change) or [self.feedback_text or "调整章节目标、事件安排或展开方式"]
            payload["chapter_replan_request"] = {
                "reason_code": payload["reason_code"],
                "feedback_text": self.feedback_text,
                "replan_scope": "current_chapter",
                "must_preserve": list(self.must_preserve),
                "must_change": must_change,
                "forbidden_carryover": list(self.forbidden_carryover),
                "requested_length_direction": {"notes": self.requested_length_direction}
                if self.requested_length_direction
                else None,
            }
        return payload

    @staticmethod
    def _default_reason_code(status: str) -> str:
        return {
            "accepted": "approved",
            "revise_length": "length_or_pacing_revision_requested",
            "replan_chapter": "chapter_plan_revision_requested",
            "discarded": "discarded_by_user",
        }.get(status, status)
