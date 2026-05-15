from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "壹": 1,
    "贰": 2,
    "叁": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
}
CHINESE_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
CHINESE_NUMBER_CHARS = "零〇一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟"
ROMAN_NUMERAL_PATTERN = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)
HEADING_PUNCTUATION_PATTERN = re.compile(r"[。！？!?；;“”]")
CHAPTER_KEYWORD_PATTERN = re.compile(r"(章|回|节|幕|卷|部|篇|Chapter|Part|Episode)", re.IGNORECASE)


@dataclass(slots=True)
class ChapterBoundaryCandidate:
    candidate_id: str
    source_path: str
    start_offset: int
    end_offset: int
    raw_heading: str
    normalized_heading: str
    normalized_ordinal: int | None
    boundary_type: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    format_family: str = ""

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.82 and self.boundary_type in {"chapter", "volume", "part"}

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ChapterBoundaryDetector:
    """Find chapter-like heading candidates without treating local rules as final truth."""

    def __init__(self, *, high_confidence_threshold: float = 0.82) -> None:
        self.high_confidence_threshold = high_confidence_threshold

    def detect(
        self,
        *,
        text: str,
        source_path: str,
        base_offset: int = 0,
        toc_markdown: str = "",
    ) -> list[ChapterBoundaryCandidate]:
        toc_headings = self._normalize_toc_headings(toc_markdown)
        candidates: list[ChapterBoundaryCandidate] = []
        for local_start, local_end, raw_line in self._iter_lines_with_offsets(text):
            heading = raw_line.strip()
            if not self._is_standalone_heading_line(heading):
                continue
            candidate = self._candidate_from_heading(
                heading=heading,
                source_path=source_path,
                start_offset=base_offset + local_start,
                end_offset=base_offset + local_end,
                toc_headings=toc_headings,
            )
            if candidate is not None:
                candidates.append(candidate)
        self._boost_repeated_sequences(candidates)
        return candidates

    def _iter_lines_with_offsets(self, text: str) -> Iterable[tuple[int, int, str]]:
        offset = 0
        for line in text.splitlines(keepends=True):
            line_start = offset
            line_end = offset + len(line)
            offset = line_end
            yield line_start, line_end, line
        if text and not text.endswith(("\n", "\r")):
            return

    def _candidate_from_heading(
        self,
        *,
        heading: str,
        source_path: str,
        start_offset: int,
        end_offset: int,
        toc_headings: set[str],
    ) -> ChapterBoundaryCandidate | None:
        normalized_heading = self._normalize_heading(heading)
        confidence = 0.0
        boundary_type = "scene"
        evidence: list[str] = ["standalone_short_line"]
        format_family = ""
        ordinal: int | None = None

        markdown_match = re.match(r"^(#{1,6})\s+(.+)$", heading)
        if markdown_match:
            normalized_heading = self._normalize_heading(markdown_match.group(2))
            ordinal = self._extract_ordinal(normalized_heading)
            boundary_type = self._infer_boundary_type(normalized_heading)
            confidence = 0.9 if boundary_type in {"chapter", "volume", "part"} else 0.74
            evidence.append("markdown_heading")
            format_family = "markdown_heading"

        if not format_family:
            matched = self._match_named_chapter_heading(heading)
            if matched is not None:
                ordinal, boundary_type, format_family = matched
                confidence = 0.92 if boundary_type in {"chapter", "volume", "part"} else 0.78
                evidence.append("heading_keyword")

        if not format_family:
            matched = self._match_english_heading(heading)
            if matched is not None:
                ordinal, boundary_type, format_family = matched
                confidence = 0.9
                evidence.append("english_heading")

        if not format_family:
            matched = self._match_parenthesized_heading(heading)
            if matched is not None:
                ordinal, format_family = matched
                boundary_type = "chapter"
                confidence = 0.82
                evidence.append("parenthesized_ordinal")

        if not format_family:
            matched = self._match_numbered_heading(heading)
            if matched is not None:
                ordinal, format_family = matched
                boundary_type = "chapter"
                confidence = 0.76
                evidence.append("numbered_heading")

        if not format_family:
            ordinal = self._parse_ordinal_token(heading)
            if ordinal is None:
                return None
            boundary_type = "chapter"
            confidence = 0.68
            evidence.append("bare_ordinal")
            format_family = "roman_numeral" if ROMAN_NUMERAL_PATTERN.fullmatch(heading) else "bare_ordinal"

        if normalized_heading in toc_headings:
            confidence += 0.1
            evidence.append("toc_match")
        if ordinal is not None:
            evidence.append("ordinal_sequence")
        confidence = min(confidence, 0.99)
        return ChapterBoundaryCandidate(
            candidate_id=self._candidate_id(source_path=source_path, start_offset=start_offset, heading=heading),
            source_path=source_path,
            start_offset=start_offset,
            end_offset=end_offset,
            raw_heading=heading,
            normalized_heading=normalized_heading,
            normalized_ordinal=ordinal,
            boundary_type=boundary_type,
            confidence=round(confidence, 3),
            evidence=evidence,
            format_family=format_family,
        )

    def _boost_repeated_sequences(self, candidates: list[ChapterBoundaryCandidate]) -> None:
        last_by_family: dict[str, ChapterBoundaryCandidate] = {}
        seen_by_family: dict[str, int] = {}
        for candidate in candidates:
            family = candidate.format_family
            seen_by_family[family] = seen_by_family.get(family, 0) + 1
            previous = last_by_family.get(family)
            ordinal = candidate.normalized_ordinal
            if seen_by_family[family] >= 2 and "repeated_book_pattern" not in candidate.evidence:
                candidate.evidence.append("repeated_book_pattern")
                candidate.confidence = round(min(candidate.confidence + 0.05, 0.99), 3)
            if (
                previous is not None
                and ordinal is not None
                and previous.normalized_ordinal is not None
                and ordinal == previous.normalized_ordinal + 1
            ):
                candidate.confidence = round(min(candidate.confidence + 0.08, 0.99), 3)
            last_by_family[family] = candidate

    def _match_named_chapter_heading(self, heading: str) -> tuple[int | None, str, str] | None:
        compact = re.sub(r"\s+", "", heading)
        match = re.match(rf"^第([{CHINESE_NUMBER_CHARS}0-9]+)(章|回|节|幕|卷|部|篇)", compact)
        if match:
            boundary_type = {
                "卷": "volume",
                "部": "part",
                "篇": "part",
                "幕": "part",
            }.get(match.group(2), "chapter")
            return self._parse_ordinal_token(match.group(1)), boundary_type, f"第N{match.group(2)}"
        match = re.match(rf"^(卷|章|幕|部|篇)([{CHINESE_NUMBER_CHARS}0-9]+)", compact)
        if match:
            boundary_type = {"卷": "volume", "部": "part", "篇": "part", "幕": "part"}.get(match.group(1), "chapter")
            return self._parse_ordinal_token(match.group(2)), boundary_type, f"{match.group(1)}N"
        for marker in ("序章", "序幕", "楔子", "尾声", "终章", "后记"):
            if compact.startswith(marker):
                return None, "chapter", marker
        return None

    def _match_english_heading(self, heading: str) -> tuple[int | None, str, str] | None:
        match = re.match(r"^(Chapter|Part|Episode)\s+([0-9IVXLCDM]+)\b", heading, re.IGNORECASE)
        if not match:
            return None
        keyword = match.group(1).lower()
        boundary_type = "part" if keyword == "part" else "chapter"
        return self._parse_ordinal_token(match.group(2)), boundary_type, f"{match.group(1).title()} N"

    def _match_parenthesized_heading(self, heading: str) -> tuple[int | None, str] | None:
        match = re.match(rf"^[（(]\s*([{CHINESE_NUMBER_CHARS}0-9IVXLCDM]+)\s*[）)]$", heading, re.IGNORECASE)
        if not match:
            return None
        return self._parse_ordinal_token(match.group(1)), "（N）"

    def _match_numbered_heading(self, heading: str) -> tuple[int | None, str] | None:
        match = re.match(rf"^([{CHINESE_NUMBER_CHARS}0-9]+)[\s._\-、]+(.+)$", heading)
        if not match:
            return None
        suffix = match.group(2).strip()
        if len(suffix) > 28 or HEADING_PUNCTUATION_PATTERN.search(suffix):
            return None
        return self._parse_ordinal_token(match.group(1)), "numbered_heading"

    def _is_standalone_heading_line(self, heading: str) -> bool:
        if not heading or len(heading) > 48:
            return False
        if heading.startswith(">"):
            return False
        if HEADING_PUNCTUATION_PATTERN.search(heading):
            return False
        if re.match(r"^\d{4}[-/年]\d{1,2}", heading):
            return False
        if heading.startswith("- ") and not CHAPTER_KEYWORD_PATTERN.search(heading):
            return False
        return True

    def _infer_boundary_type(self, heading: str) -> str:
        if re.search(r"(卷|Volume)", heading, re.IGNORECASE):
            return "volume"
        if re.search(r"(部|篇|幕|Part)", heading, re.IGNORECASE):
            return "part"
        if re.search(r"(章|回|节|Chapter|Episode|序章|楔子|尾声|终章)", heading, re.IGNORECASE):
            return "chapter"
        return "scene"

    def _extract_ordinal(self, heading: str) -> int | None:
        named = self._match_named_chapter_heading(heading)
        if named is not None:
            return named[0]
        english = self._match_english_heading(heading)
        if english is not None:
            return english[0]
        parenthesized = self._match_parenthesized_heading(heading)
        if parenthesized is not None:
            return parenthesized[0]
        numbered = self._match_numbered_heading(heading)
        if numbered is not None:
            return numbered[0]
        return None

    def _parse_ordinal_token(self, token: str) -> int | None:
        compact = token.strip().strip(".")
        if not compact:
            return None
        if compact.isdigit():
            return int(compact)
        if ROMAN_NUMERAL_PATTERN.fullmatch(compact):
            return self._roman_to_int(compact)
        if all(ch in CHINESE_NUMBER_CHARS for ch in compact):
            return self._chinese_to_int(compact)
        return None

    def _roman_to_int(self, token: str) -> int | None:
        values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        total = 0
        previous = 0
        for char in reversed(token.upper()):
            value = values.get(char)
            if value is None:
                return None
            if value < previous:
                total -= value
            else:
                total += value
                previous = value
        return total or None

    def _chinese_to_int(self, token: str) -> int | None:
        total = 0
        section = 0
        number = 0
        for char in token:
            if char in CHINESE_DIGITS:
                number = CHINESE_DIGITS[char]
                continue
            unit = CHINESE_UNITS.get(char)
            if unit is not None:
                section += (number or 1) * unit
                number = 0
                continue
            if char == "万":
                total += (section + number) * 10000
                section = 0
                number = 0
                continue
            return None
        return total + section + number or None

    def _normalize_toc_headings(self, toc_markdown: str) -> set[str]:
        headings: set[str] = set()
        for line in toc_markdown.splitlines():
            stripped = line.strip().lstrip("-*").strip()
            if not stripped or "目录" in stripped:
                continue
            headings.add(self._normalize_heading(stripped))
        return headings

    def _normalize_heading(self, heading: str) -> str:
        normalized = heading.strip().lstrip("#").strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.replace("　", " ")
        return normalized

    def _candidate_id(self, *, source_path: str, start_offset: int, heading: str) -> str:
        path_stem = Path(source_path).name or "source"
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", path_stem).strip("-") or "source"
        heading_key = re.sub(r"\s+", "-", heading.strip())[:24]
        heading_key = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff（）()]+", "", heading_key).strip("-")
        return f"{safe_stem}:{start_offset}:{heading_key or 'heading'}"
