from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DecisionOption:
    key: str
    label: str
    next_status: str
    workflow_action: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionAction:
    key: str
    workflow_action: str
    next_status: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionPanel:
    title: str
    artifact_path: str = ""
    summary: str = ""
    options: tuple[DecisionOption, ...] = ()

    @classmethod
    def chapter_acceptance(cls, *, draft_path: str, draft_chars: int = 0, target_chars: int = 0) -> "DecisionPanel":
        summary = f"草稿：{draft_path}"
        if draft_chars or target_chars:
            summary = f"{summary}\n字数：{draft_chars} / 目标 {target_chars or '未设置'}\n连续性：通过"
        return cls(
            title="请验收当前章节",
            artifact_path=draft_path,
            summary=summary,
            options=(
                DecisionOption("1", "接受本章", "请确认写回续写记忆", "accept_chapter", {"status": "accepted"}),
                DecisionOption("2", "调整字数后重写", "请确认章节长度与节奏", "revise_length", {"status": "revise_length"}),
                DecisionOption("3", "修改章节梗概后重写", "请调整章节规划后重写", "replan_chapter", {"status": "replan_chapter"}),
                DecisionOption("4", "作废本次草稿", "流程已暂停", "discard_chapter", {"status": "discarded"}),
                DecisionOption("5", "稍后再决定", "请验收当前章节", "defer_decision", {"status": ""}),
            ),
        )

    @classmethod
    def planning_review(cls, *, artifact_path: str, stage_label: str, next_status: str) -> "DecisionPanel":
        return cls(
            title=stage_label,
            artifact_path=artifact_path,
            summary=f"文件：{artifact_path}",
            options=(
                DecisionOption("s", "保存修改", stage_label, "save_artifact"),
                DecisionOption("c", "确认并继续", next_status, "confirm_current_step"),
                DecisionOption("b", "返回上一层", "返回上一层可修改节点", "go_back"),
                DecisionOption("w", "稍后继续", stage_label, "defer_decision"),
            ),
        )

    def choose(self, key: str) -> DecisionAction:
        normalized = key.strip().lower()
        for option in self.options:
            if normalized == option.key.lower() or normalized == option.label.lower():
                return DecisionAction(
                    key=option.key,
                    workflow_action=option.workflow_action,
                    next_status=option.next_status,
                    payload=dict(option.payload),
                )
        raise ValueError(f"未知决策选项：{key}")

    def render(self) -> str:
        lines = [self.title]
        if self.summary:
            lines.append("")
            lines.append(self.summary)
        lines.append("")
        for option in self.options:
            lines.append(f"[{option.key}] {option.label} -> {option.next_status}")
        return "\n".join(lines)
