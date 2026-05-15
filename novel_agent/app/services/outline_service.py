from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..constants import DEFAULT_MEMORY_ROOT, DEFAULT_OUTLINE_MAX_CHARS
from ..utils.text_utils import clamp_text, normalize_whitespace, safe_excerpt


OUTLINE_TEMPLATE = """# 故事大纲

## 主线概览
- 当前主角：
- 主线目标：
- 当前推进阶段：
- 主线核心矛盾：

## 分章节进度

## 关键时间节点

## 当前未解问题
"""

OUTLINE_SECTION_ORDER = ("主线概览", "分章节进度", "关键时间节点", "当前未解问题")
MAINLINE_KEYWORDS = (
    "主线",
    "真相",
    "目标",
    "决战",
    "身份",
    "危机",
    "转折",
    "背叛",
    "觉醒",
    "调查",
)
SIDE_BRANCH_KEYWORDS = ("支线", "日常", "插曲", "闲聊", "过场", "番外")


@dataclass(slots=True)
class OutlineChapterEntry:
    raw_line: str
    chapter_index: int | None
    importance_score: int | None = None

    @property
    def normalized_line(self) -> str:
        return normalize_whitespace(self.raw_line)


@dataclass(slots=True)
class OutlineTimelineEntry:
    label: str
    participants: list[str] = field(default_factory=list)
    summary: str = ""
    event_id: str = ""
    source_doc_range: str = ""
    source_doc_ids: list[int] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        normalized_participants = ",".join(sorted(self.participants))
        normalized_label = self._normalize_match_text(self.label)
        normalized_summary = self._normalize_match_text(self.summary)
        source_key = self._normalize_match_text(self.source_doc_range) if self.source_doc_range else ""
        if not source_key:
            source_key = ",".join(str(item) for item in sorted(set(self.source_doc_ids)))
        if source_key:
            return "||".join(
                [
                    normalized_label or normalized_summary,
                    self._normalize_match_text(normalized_participants),
                    source_key,
                ]
            )
        if normalized_label:
            return "||".join([normalized_label, self._normalize_match_text(normalized_participants)])
        return "||".join([normalized_summary, self._normalize_match_text(normalized_participants)])

    def render(self, *, compact: bool = False) -> str:
        summary = safe_excerpt(self.summary, 72) if compact else self.summary
        participant_text = ",".join(self.participants)
        source_parts = []
        if self.event_id:
            source_parts.append(f"事件：{self.event_id}")
        if self.source_doc_range:
            source_parts.append(f"documents：{self.source_doc_range}")
        source_text = f" | {' | '.join(source_parts)}" if source_parts else ""
        return f"- {self.label} | 人物：{participant_text} | {summary}{source_text}".rstrip()

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalize_whitespace(text)).lower()


@dataclass(slots=True)
class OutlineDocument:
    mainline_overview_lines: list[str] = field(default_factory=list)
    chapter_entries: list[OutlineChapterEntry] = field(default_factory=list)
    timeline_entries: list[OutlineTimelineEntry] = field(default_factory=list)
    unresolved_lines: list[str] = field(default_factory=list)


class OutlineService:
    def __init__(self, *, repo_root: Path, outline_max_chars: int = DEFAULT_OUTLINE_MAX_CHARS) -> None:
        self.repo_root = repo_root
        self.outline_max_chars = outline_max_chars

    def ensure_path(self, book_id: str) -> Path:
        outline_dir = self.repo_root / DEFAULT_MEMORY_ROOT / "outlines"
        outline_dir.mkdir(parents=True, exist_ok=True)
        path = outline_dir / f"{book_id}.outline.md"
        if not path.exists():
            path.write_text(OUTLINE_TEMPLATE, encoding="utf-8")
        return path

    def apply_update(
        self,
        *,
        book_id: str,
        chapter_line: str,
        timeline_events: list[dict[str, object]],
        importance_score: int | None = None,
    ) -> Path:
        path = self.ensure_path(book_id)
        document = self._parse_outline(path.read_text(encoding="utf-8", errors="replace"))
        normalized_chapter_line = normalize_whitespace(chapter_line)
        if normalized_chapter_line:
            document.chapter_entries = self._upsert_chapter_entry(
                entries=document.chapter_entries,
                chapter_line=normalized_chapter_line,
                importance_score=importance_score,
            )
        if timeline_events:
            document.timeline_entries = self._merge_timeline_entries(
                existing=document.timeline_entries,
                new_entries=self._normalize_timeline_events(timeline_events),
            )
        path.write_text(self._render_outline(document), encoding="utf-8")
        return path

    def _parse_outline(self, markdown: str) -> OutlineDocument:
        section_lines = self._split_markdown_sections(markdown)
        document = OutlineDocument(
            mainline_overview_lines=self._sanitize_plain_lines(section_lines.get("主线概览", [])),
            chapter_entries=self._parse_chapter_entries(section_lines.get("分章节进度", [])),
            timeline_entries=self._parse_timeline_entries(section_lines.get("关键时间节点", [])),
            unresolved_lines=self._sanitize_plain_lines(section_lines.get("当前未解问题", [])),
        )
        return document

    def _split_markdown_sections(self, markdown: str) -> dict[str, list[str]]:
        sections = {name: [] for name in OUTLINE_SECTION_ORDER}
        current_heading: str | None = None
        for raw_line in markdown.splitlines():
            line = raw_line.rstrip()
            if line.startswith("## "):
                heading = line[3:].strip()
                current_heading = heading if heading in sections else None
                continue
            if current_heading is None:
                continue
            sections[current_heading].append(line)
        return sections

    def _sanitize_plain_lines(self, lines: list[str]) -> list[str]:
        sanitized: list[str] = []
        seen: set[str] = set()
        for raw_line in lines:
            normalized = normalize_whitespace(raw_line)
            if not normalized:
                continue
            if normalized in {"- 待补充", "- 暂无更新"}:
                continue
            key = self._normalize_for_match(normalized)
            if not key or key in seen:
                continue
            seen.add(key)
            sanitized.append(normalized if normalized.startswith("- ") else f"- {normalized}")
        return sanitized

    def _parse_chapter_entries(self, lines: list[str]) -> list[OutlineChapterEntry]:
        entries: list[OutlineChapterEntry] = []
        seen: set[str] = set()
        for raw_line in lines:
            normalized = normalize_whitespace(raw_line)
            if not normalized.startswith("- "):
                continue
            text = normalized[2:]
            if text in {"暂无更新", "待补充"}:
                continue
            key = self._normalize_for_match(text)
            if not key or key in seen:
                continue
            seen.add(key)
            entries.append(
                OutlineChapterEntry(
                    raw_line=text,
                    chapter_index=self._extract_chapter_index(text),
                )
            )
        return entries

    def _parse_timeline_entries(self, lines: list[str]) -> list[OutlineTimelineEntry]:
        entries: list[OutlineTimelineEntry] = []
        for raw_line in lines:
            entry = self._parse_timeline_entry(raw_line)
            if entry is not None:
                entries.append(entry)
        return self._merge_timeline_entries(existing=[], new_entries=entries)

    def _parse_timeline_entry(self, raw_line: str) -> OutlineTimelineEntry | None:
        normalized = normalize_whitespace(raw_line)
        if not normalized.startswith("- "):
            return None
        if normalized in {"- 暂无更新", "- 待补充"}:
            return None
        parts = [part.strip() for part in normalized[2:].split("|")]
        if not parts:
            return None
        label = normalize_whitespace(parts[0])
        participants: list[str] = []
        summary = ""
        event_id = ""
        source_doc_range = ""
        for part in parts[1:]:
            if part.startswith("人物："):
                raw_participants = part.split("：", 1)[1]
                participants = self._clean_participants(raw_participants.split(","))
                continue
            if part.startswith("事件："):
                event_id = normalize_whitespace(part.split("：", 1)[1])
                continue
            if part.startswith("documents："):
                source_doc_range = normalize_whitespace(part.split("：", 1)[1])
                continue
            summary = normalize_whitespace(part)
        if not label and not summary:
            return None
        return OutlineTimelineEntry(
            label=label or "未命名事件",
            participants=participants,
            summary=summary,
            event_id=event_id,
            source_doc_range=source_doc_range,
            source_doc_ids=self._doc_ids_from_range(source_doc_range),
        )

    def _upsert_chapter_entry(
        self,
        *,
        entries: list[OutlineChapterEntry],
        chapter_line: str,
        importance_score: int | None,
    ) -> list[OutlineChapterEntry]:
        new_entry = OutlineChapterEntry(
            raw_line=chapter_line,
            chapter_index=self._extract_chapter_index(chapter_line),
            importance_score=self._normalize_importance_score(importance_score),
        )
        deduped: list[OutlineChapterEntry] = []
        replaced = False
        normalized_line = self._normalize_for_match(chapter_line)
        for entry in entries:
            if (
                new_entry.chapter_index is not None
                and entry.chapter_index is not None
                and entry.chapter_index == new_entry.chapter_index
            ):
                deduped.append(new_entry)
                replaced = True
                continue
            if self._normalize_for_match(entry.raw_line) == normalized_line:
                if not replaced:
                    deduped.append(new_entry)
                    replaced = True
                continue
            deduped.append(entry)
        if not replaced:
            deduped.append(new_entry)
        return sorted(
            deduped,
            key=lambda item: (
                item.chapter_index if item.chapter_index is not None else 10**9,
                item.raw_line,
            ),
        )

    def _normalize_timeline_events(self, timeline_events: list[dict[str, object]]) -> list[OutlineTimelineEntry]:
        normalized_entries: list[OutlineTimelineEntry] = []
        for event in timeline_events:
            if not isinstance(event, dict):
                continue
            label = normalize_whitespace(str(event.get("label", "")))
            summary = normalize_whitespace(str(event.get("summary", "")))
            event_id = normalize_whitespace(str(event.get("event_id", "")))
            source_doc_ids = self._safe_int_list(event.get("source_doc_ids"))
            source_doc_range = normalize_whitespace(str(event.get("source_doc_range", "")))
            if not source_doc_range and source_doc_ids:
                source_doc_range = self._doc_range_text(source_doc_ids)
            participants_raw = event.get("participants", [])
            participants = self._clean_participants(participants_raw if isinstance(participants_raw, list) else [])
            if not label and not summary:
                continue
            normalized_entries.append(
                OutlineTimelineEntry(
                    label=label or safe_excerpt(summary, 16),
                    participants=participants,
                    summary=summary,
                    event_id=event_id,
                    source_doc_range=source_doc_range,
                    source_doc_ids=source_doc_ids,
                )
            )
        return normalized_entries

    def _merge_timeline_entries(
        self,
        *,
        existing: list[OutlineTimelineEntry],
        new_entries: list[OutlineTimelineEntry],
    ) -> list[OutlineTimelineEntry]:
        merged: list[OutlineTimelineEntry] = []
        by_key: dict[str, OutlineTimelineEntry] = {}
        for entry in [*existing, *new_entries]:
            key = entry.dedupe_key
            if key in by_key:
                current = by_key[key]
                current.participants = self._clean_participants([*current.participants, *entry.participants])
                if len(entry.summary) > len(current.summary):
                    current.summary = entry.summary
                if len(entry.label) > len(current.label):
                    current.label = entry.label
                if entry.event_id and not current.event_id:
                    current.event_id = entry.event_id
                current.source_doc_ids = sorted({*current.source_doc_ids, *entry.source_doc_ids})
                if current.source_doc_ids:
                    current.source_doc_range = self._doc_range_text(current.source_doc_ids)
                elif entry.source_doc_range and not current.source_doc_range:
                    current.source_doc_range = entry.source_doc_range
                continue
            by_key[key] = OutlineTimelineEntry(
                label=entry.label,
                participants=list(entry.participants),
                summary=entry.summary,
                event_id=entry.event_id,
                source_doc_range=entry.source_doc_range,
                source_doc_ids=list(entry.source_doc_ids),
            )
            merged.append(by_key[key])
        return merged

    def _render_outline(self, document: OutlineDocument) -> str:
        working_document = OutlineDocument(
            mainline_overview_lines=list(document.mainline_overview_lines),
            chapter_entries=list(document.chapter_entries),
            timeline_entries=[
                OutlineTimelineEntry(
                    label=item.label,
                    participants=list(item.participants),
                    summary=item.summary,
                    event_id=item.event_id,
                    source_doc_range=item.source_doc_range,
                    source_doc_ids=list(item.source_doc_ids),
                )
                for item in document.timeline_entries
            ],
            unresolved_lines=list(document.unresolved_lines),
        )
        rendered = self._render_outline_document(working_document)
        if len(rendered) <= self.outline_max_chars:
            return rendered
        working_document.chapter_entries = self._compress_chapter_entries(working_document)
        rendered = self._render_outline_document(working_document)
        if len(rendered) <= self.outline_max_chars:
            return rendered
        rendered = self._render_outline_document(working_document, compact=True)
        return clamp_text(rendered, self.outline_max_chars)

    def _render_outline_document(self, document: OutlineDocument, *, compact: bool = False) -> str:
        lines = ["# 故事大纲", "", "## 主线概览"]
        lines.extend(document.mainline_overview_lines or ["- 待补充"])
        lines.append("")
        lines.append("## 分章节进度")
        if document.chapter_entries:
            for entry in document.chapter_entries:
                chapter_text = safe_excerpt(entry.raw_line, 96) if compact else entry.raw_line
                lines.append(f"- {chapter_text}")
        else:
            lines.append("- 暂无更新")
        lines.append("")
        lines.append("## 关键时间节点")
        if document.timeline_entries:
            for entry in document.timeline_entries:
                lines.append(entry.render(compact=compact))
        else:
            lines.append("- 暂无更新")
        lines.append("")
        lines.append("## 当前未解问题")
        lines.extend(document.unresolved_lines or ["- 待补充"])
        return "\n".join(lines).strip() + "\n"

    def _compress_chapter_entries(self, document: OutlineDocument) -> list[OutlineChapterEntry]:
        if len(document.chapter_entries) <= 1:
            return document.chapter_entries
        retained = list(document.chapter_entries)
        while len(retained) > 1:
            removable = min(
                retained,
                key=lambda entry: (
                    self._chapter_priority(entry),
                    -(entry.chapter_index if entry.chapter_index is not None else -1),
                    len(entry.raw_line),
                ),
            )
            retained.remove(removable)
            candidate = self._render_outline_document(
                OutlineDocument(
                    mainline_overview_lines=list(document.mainline_overview_lines),
                    chapter_entries=retained,
                    timeline_entries=[
                        OutlineTimelineEntry(
                            label=item.label,
                            participants=list(item.participants),
                            summary=item.summary,
                            event_id=item.event_id,
                            source_doc_range=item.source_doc_range,
                            source_doc_ids=list(item.source_doc_ids),
                        )
                        for item in document.timeline_entries
                    ],
                    unresolved_lines=list(document.unresolved_lines),
                ),
                compact=True,
            )
            if len(candidate) <= self.outline_max_chars:
                break
        return sorted(
            retained,
            key=lambda item: (
                item.chapter_index if item.chapter_index is not None else 10**9,
                item.raw_line,
            ),
        )

    def _chapter_priority(self, entry: OutlineChapterEntry) -> int:
        text = entry.raw_line
        score = entry.importance_score or 0
        score += sum(30 for keyword in MAINLINE_KEYWORDS if keyword in text)
        score -= sum(20 for keyword in SIDE_BRANCH_KEYWORDS if keyword in text)
        if entry.chapter_index is not None:
            score += min(entry.chapter_index, 40)
        return score

    def _clean_participants(self, raw_participants: Iterable[object]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw_participants:
            name = normalize_whitespace(str(item))
            if not name:
                continue
            key = self._normalize_for_match(name)
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(name)
        return cleaned

    def _extract_chapter_index(self, chapter_line: str) -> int | None:
        match = re.search(r"\[(\d+)\]", chapter_line)
        if match is None:
            return None
        return int(match.group(1))

    def _normalize_importance_score(self, importance_score: int | None) -> int | None:
        if importance_score is None:
            return None
        return max(0, min(100, int(importance_score)))

    def _safe_int_list(self, value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        cleaned: list[int] = []
        for item in value:
            try:
                cleaned.append(int(item))
            except (TypeError, ValueError):
                continue
        return sorted(set(cleaned))

    def _doc_range_text(self, doc_ids: list[int]) -> str:
        if not doc_ids:
            return ""
        return str(doc_ids[0]) if len(doc_ids) == 1 else f"{doc_ids[0]}-{doc_ids[-1]}"

    def _doc_ids_from_range(self, source_doc_range: str) -> list[int]:
        match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", source_doc_range)
        if match is None:
            return []
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if end < start:
            return [start]
        if end - start > 512:
            return [start, end]
        return list(range(start, end + 1))

    def _normalize_for_match(self, text: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalize_whitespace(text)).lower()
