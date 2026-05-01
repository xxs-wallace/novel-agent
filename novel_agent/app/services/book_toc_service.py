from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BookTocSnapshot:
    source_path: str
    heading: str
    toc_markdown: str
    entry_count: int


class BookTocService:
    def extract_from_paths(self, ordered_paths: list[Path], *, sample_chars: int = 16_000) -> BookTocSnapshot | None:
        remaining = sample_chars
        for path in ordered_paths:
            if remaining <= 0:
                break
            text = path.read_text(encoding="utf-8", errors="replace")[:remaining]
            remaining -= len(text)
            snapshot = self.extract_from_text(text, source_path=path.as_posix())
            if snapshot is not None:
                return snapshot
        return None

    def extract_from_text(self, text: str, *, source_path: str) -> BookTocSnapshot | None:
        lines = text.splitlines()
        best_snapshot: BookTocSnapshot | None = None
        for index, line in enumerate(lines):
            if "目录" not in self._normalize(line):
                continue
            snapshot = self._extract_block(lines, start_index=index, source_path=source_path)
            if snapshot is None:
                continue
            if best_snapshot is None or snapshot.entry_count > best_snapshot.entry_count:
                best_snapshot = snapshot
        return best_snapshot

    def _extract_block(self, lines: list[str], *, start_index: int, source_path: str) -> BookTocSnapshot | None:
        heading = lines[start_index].strip() or "目录"
        entries: list[str] = []
        blank_streak = 0
        collected = False
        for raw_line in lines[start_index + 1 :]:
            stripped = raw_line.strip()
            if not stripped:
                if collected:
                    blank_streak += 1
                    if blank_streak >= 2:
                        break
                continue
            blank_streak = 0
            if self._is_toc_entry(stripped):
                entries.append(stripped)
                collected = True
                continue
            if collected and self._looks_like_new_section(stripped):
                break
            if collected:
                break
        if len(entries) < 3:
            return None
        toc_markdown = "\n".join([heading, *entries]).strip()
        return BookTocSnapshot(
            source_path=source_path,
            heading=heading,
            toc_markdown=toc_markdown,
            entry_count=len(entries),
        )

    def _is_toc_entry(self, line: str) -> bool:
        normalized = self._normalize(line)
        if line.startswith("- "):
            return True
        title_markers = ("开篇", "尾声", "楔子", "序章", "序幕", "序言", "前传", "正传")
        if any(marker in normalized for marker in title_markers):
            return True
        if normalized.startswith("第") and any(token in normalized for token in ("章", "幕", "卷", "回")):
            return True
        if "(p." in normalized or "p." in normalized:
            return True
        return False

    def _looks_like_new_section(self, line: str) -> bool:
        normalized = self._normalize(line)
        if line.startswith("#"):
            return True
        if normalized.startswith("版权信息"):
            return True
        if normalized.startswith("纸质版编目数据"):
            return True
        return False

    def _normalize(self, line: str) -> str:
        return (
            line.replace("　", " ")
            .replace("⽬", "目")
            .replace("⼀", "一")
            .replace("⼆", "二")
            .replace("⼋", "八")
            .replace("⾦", "金")
            .replace("⽩", "白")
            .replace("（", "(")
            .replace("）", ")")
            .replace("·", "·")
            .strip()
        )
