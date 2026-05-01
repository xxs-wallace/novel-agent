from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..constants import DEFAULT_MEMORY_ROOT, DEFAULT_WORLD_SUMMARY_MAX_CHARS
from ..llm import JsonModelClient
from ..prompts.world_summary_prompt import build_world_summary_prompt
from ..utils.text_utils import clamp_text, normalize_whitespace, safe_excerpt


WORLD_TEMPLATE = """# 世界观设定

- 作品：{book_id}

## 世界类型

## 时代背景

## 能力体系

## 超自然要素

## 阵营势力

## 核心禁忌与规则

## 结构化更新记录
"""

WORLD_SUMMARY_TEMPLATE = """# 世界观概要

## 世界类型

## 时代背景

## 能力体系

## 超自然要素

## 阵营势力

## 核心禁忌与规则
"""

WORLD_SECTION_ORDER = (
    "世界类型",
    "时代背景",
    "能力体系",
    "超自然要素",
    "阵营势力",
    "核心禁忌与规则",
)
WORLD_LOG_SECTION = "结构化更新记录"
WORLD_SECTION_ALIASES = {
    "世界类型": "世界类型",
    "时代背景": "时代背景",
    "能力体系": "能力体系",
    "超能力体系": "能力体系",
    "超能力与规则体系": "能力体系",
    "超自然要素": "超自然要素",
    "超自然生物/特殊物品": "超自然要素",
    "超自然生物": "超自然要素",
    "特殊物品": "超自然要素",
    "阵营势力": "阵营势力",
    "阵营与势力": "阵营势力",
    "核心禁忌与规则": "核心禁忌与规则",
    "禁忌与规则": "核心禁忌与规则",
    "规则变更记录": WORLD_LOG_SECTION,
    "本轮补充": WORLD_LOG_SECTION,
    "结构化更新记录": WORLD_LOG_SECTION,
}
SECTION_KEYWORDS = {
    "世界类型": ("世界类型", "都市", "校园", "末世", "异世界", "架空", "现实映射", "近未来", "现代都市"),
    "时代背景": ("时代背景", "年代", "时代", "纪元", "王朝", "近代", "现代", "未来", "战争时期"),
    "能力体系": ("能力", "术式", "修行", "血统", "法术", "觉醒", "规则体系"),
    "超自然要素": ("超自然", "神", "鬼", "遗迹", "圣遗物", "特殊物品", "秘宝", "异兽"),
    "阵营势力": ("势力", "阵营", "组织", "学院", "家族", "教会", "军团", "集团"),
    "核心禁忌与规则": ("禁忌", "规则", "代价", "约束", "不能", "必须", "禁止", "限制"),
}
WORLD_LOG_LIMIT = 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class WorldChange:
    section: str
    summary: str
    evidence: str


class WorldStateService:
    def __init__(
        self,
        *,
        repo_root: Path,
        model_client: JsonModelClient | None = None,
        summary_max_chars: int = DEFAULT_WORLD_SUMMARY_MAX_CHARS,
        now_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.model_client = model_client
        self.summary_max_chars = summary_max_chars
        self.now_factory = now_factory or _utc_now

    def ensure_paths(self, book_id: str) -> tuple[Path, Path]:
        world_dir = self.repo_root / DEFAULT_MEMORY_ROOT / "worlds"
        world_dir.mkdir(parents=True, exist_ok=True)
        world_path = world_dir / f"{book_id}.world.md"
        summary_path = world_dir / f"{book_id}.world_summary.md"
        if not world_path.exists():
            world_path.write_text(WORLD_TEMPLATE.format(book_id=book_id), encoding="utf-8")
        if not summary_path.exists():
            summary_path.write_text(WORLD_SUMMARY_TEMPLATE, encoding="utf-8")
        return world_path, summary_path

    def apply_update(
        self,
        *,
        book_id: str,
        world_update: dict[str, object],
        updated_at: str | None = None,
    ) -> tuple[Path, Path]:
        world_path, summary_path = self.ensure_paths(book_id)
        sections = self._parse_world_sections(world_path.read_text(encoding="utf-8", errors="replace"))
        applied_at = updated_at or self.now_factory()
        log_lines = list(sections[WORLD_LOG_SECTION])
        should_update = bool(world_update.get("should_update"))
        if should_update:
            for change in self._normalize_changes(world_update.get("changes", [])):
                status = self._merge_change(sections, change)
                log_lines.append(self._render_log_line(change=change, applied_at=applied_at, status=status))
        sections[WORLD_LOG_SECTION] = log_lines[-WORLD_LOG_LIMIT:]
        world_path.write_text(self._render_world_markdown(book_id=book_id, sections=sections), encoding="utf-8")
        summary = self._build_summary(world_path.read_text(encoding="utf-8", errors="replace"))
        summary_path.write_text(summary, encoding="utf-8")
        return world_path, summary_path

    def _build_summary(self, world_markdown: str) -> str:
        fallback_text = self._build_structured_summary(world_markdown)
        if self.model_client is None or self.model_client.settings.dry_run:
            return fallback_text
        system_prompt, user_prompt = build_world_summary_prompt(world_markdown)
        text = self.model_client.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_text=fallback_text,
        )
        return clamp_text(text, self.summary_max_chars)

    def _build_structured_summary(self, world_markdown: str) -> str:
        sections = self._parse_world_sections(world_markdown)
        lines = ["# 世界观概要"]
        for section in WORLD_SECTION_ORDER:
            lines.append("")
            lines.append(f"## {section}")
            facts = sections[section][:2]
            if facts:
                lines.extend(facts)
            else:
                lines.append("- 暂缺")
        return clamp_text("\n".join(lines).strip() + "\n", self.summary_max_chars)

    def _parse_world_sections(self, world_markdown: str) -> dict[str, list[str]]:
        sections = {section: [] for section in (*WORLD_SECTION_ORDER, WORLD_LOG_SECTION)}
        heading_map = self._split_markdown_sections(world_markdown)
        if not heading_map:
            return sections
        for heading, lines in heading_map.items():
            canonical = self._canonicalize_section_name(heading)
            if heading == "__root__":
                self._ingest_root_lines(sections, lines)
                continue
            if canonical == WORLD_LOG_SECTION:
                self._ingest_log_lines(sections, lines)
                continue
            if heading == "基础信息":
                self._ingest_basic_info(sections, lines)
                continue
            if canonical in WORLD_SECTION_ORDER:
                self._append_fact_lines(sections[canonical], lines)
        for section in WORLD_SECTION_ORDER:
            sections[section] = self._dedupe_preserve_order(sections[section])
        sections[WORLD_LOG_SECTION] = self._dedupe_preserve_order(sections[WORLD_LOG_SECTION])[-WORLD_LOG_LIMIT:]
        return sections

    def _split_markdown_sections(self, markdown: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {"__root__": []}
        current_heading = "__root__"
        for raw_line in markdown.splitlines():
            line = raw_line.rstrip()
            if line.startswith("## "):
                current_heading = line[3:].strip()
                sections.setdefault(current_heading, [])
                continue
            sections.setdefault(current_heading, []).append(line)
        return sections

    def _ingest_root_lines(self, sections: dict[str, list[str]], lines: list[str]) -> None:
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            if stripped.startswith("- 世界类型："):
                value = stripped.split("：", 1)[1].strip()
                if value:
                    sections["世界类型"].append(f"- {value}")
            if stripped.startswith("- 时代背景："):
                value = stripped.split("：", 1)[1].strip()
                if value:
                    sections["时代背景"].append(f"- {value}")

    def _ingest_basic_info(self, sections: dict[str, list[str]], lines: list[str]) -> None:
        self._ingest_root_lines(sections, lines)

    def _ingest_log_lines(self, sections: dict[str, list[str]], lines: list[str]) -> None:
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            parsed_change = self._parse_legacy_log_change(stripped)
            if parsed_change is not None:
                self._merge_change(sections, parsed_change)
                sections[WORLD_LOG_SECTION].append(
                    self._render_log_line(
                        change=parsed_change,
                        applied_at="历史迁移",
                        status="迁移",
                    )
                )
                continue
            if stripped.startswith("- "):
                sections[WORLD_LOG_SECTION].append(stripped)

    def _append_fact_lines(self, target: list[str], lines: list[str]) -> None:
        for line in lines:
            fact_line = self._normalize_fact_line(line)
            if fact_line:
                target.append(fact_line)

    def _normalize_changes(self, raw_changes: object) -> list[WorldChange]:
        if not isinstance(raw_changes, list):
            return []
        changes: list[WorldChange] = []
        for item in raw_changes:
            if not isinstance(item, dict):
                continue
            summary = normalize_whitespace(str(item.get("summary", "")))
            if not summary:
                continue
            section = self._classify_section(str(item.get("section", "")), summary)
            evidence = normalize_whitespace(str(item.get("evidence", "")))
            changes.append(WorldChange(section=section, summary=summary, evidence=evidence))
        return changes

    def _classify_section(self, raw_section: str, summary: str) -> str:
        normalized_section = normalize_whitespace(raw_section)
        aliased = self._canonicalize_section_name(normalized_section)
        if aliased in WORLD_SECTION_ORDER:
            return aliased
        haystack = f"{normalized_section} {summary}"
        for section in WORLD_SECTION_ORDER:
            if any(keyword in haystack for keyword in SECTION_KEYWORDS[section]):
                return section
        return "核心禁忌与规则"

    def _canonicalize_section_name(self, raw_section: str) -> str:
        normalized = normalize_whitespace(raw_section)
        return WORLD_SECTION_ALIASES.get(normalized, normalized)

    def _merge_change(self, sections: dict[str, list[str]], change: WorldChange) -> str:
        target_lines = sections[change.section]
        candidate = f"- {change.summary}"
        normalized_candidate = self._normalize_for_match(change.summary)
        for line in target_lines:
            normalized_existing = self._normalize_for_match(line)
            if normalized_existing == normalized_candidate:
                return "重复"
        target_lines.append(candidate)
        sections[change.section] = self._dedupe_preserve_order(target_lines)
        return "新增"

    def _render_log_line(self, *, change: WorldChange, applied_at: str, status: str) -> str:
        evidence = change.evidence or "无"
        return (
            f"- 时间：{applied_at} | 分区：{change.section} | 摘要：{change.summary} | "
            f"证据：{safe_excerpt(evidence, 120)} | 处理：{status}"
        )

    def _render_world_markdown(self, *, book_id: str, sections: dict[str, list[str]]) -> str:
        lines = ["# 世界观设定", "", f"- 作品：{book_id}"]
        for section in WORLD_SECTION_ORDER:
            lines.append("")
            lines.append(f"## {section}")
            content_lines = sections[section] or ["- 待补充"]
            lines.extend(content_lines)
        lines.append("")
        lines.append(f"## {WORLD_LOG_SECTION}")
        lines.extend(sections[WORLD_LOG_SECTION] or ["- 暂无更新"])
        return "\n".join(lines).strip() + "\n"

    def _parse_legacy_log_change(self, line: str) -> WorldChange | None:
        match = re.match(r"- \[(?P<section>[^\]]+)\]\s*(?P<summary>.*?)(?:\s*\|\s*证据：(?P<evidence>.*))?$", line)
        if match is None:
            return None
        summary = normalize_whitespace(match.group("summary") or "")
        if not summary:
            return None
        return WorldChange(
            section=self._classify_section(match.group("section") or "", summary),
            summary=summary,
            evidence=normalize_whitespace(match.group("evidence") or ""),
        )

    def _normalize_fact_line(self, line: str) -> str:
        stripped = line.strip()
        if not stripped or stripped == "- 待补充":
            return ""
        if stripped.startswith("- "):
            fact = normalize_whitespace(stripped[2:])
            if not fact:
                return ""
            return f"- {fact}"
        if stripped.startswith("时间：") or stripped.startswith("- 时间："):
            return ""
        return f"- {normalize_whitespace(stripped)}"

    def _dedupe_preserve_order(self, lines: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            normalized = self._normalize_for_match(line)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(line)
        return deduped

    def _normalize_for_match(self, text: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalize_whitespace(text)).lower()
