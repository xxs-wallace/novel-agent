from __future__ import annotations

import re
from typing import Any, Mapping

from ..prompts.chapter_outline_segment_prompt import build_chapter_outline_segment_prompt
from ..utils.text_utils import normalize_whitespace, split_sentences


CHAPTER_OUTLINE_SEGMENT_TARGET_CHARS = 260


class ChapterOutlineSegmentService:
    """Builds a chapter-level continuous outline segment from summary_md."""

    def __init__(
        self,
        *,
        model_client: Any | None = None,
        target_chars: int = CHAPTER_OUTLINE_SEGMENT_TARGET_CHARS,
    ) -> None:
        self.model_client = model_client
        self.target_chars = max(120, int(target_chars))

    def build_outline_update(
        self,
        *,
        book_id: str,
        document_title_index: int,
        chapter_title: str,
        summary_md: str,
        chapter_summary_short: str = "",
        source_doc_range: str = "",
        existing_outline_update: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = dict(existing_outline_update or {})
        fallback = {
            "chapter_line": self._fallback_chapter_line(
                document_title_index=document_title_index,
                chapter_title=chapter_title,
                chapter_summary_short=chapter_summary_short,
                existing_chapter_line=str(existing.get("chapter_line") or ""),
            ),
            "outline_segment": self.fallback_outline_segment(
                summary_md=summary_md,
                chapter_summary_short=chapter_summary_short,
            ),
            "compression_notes": "fallback",
        }
        if self.model_client is None:
            raise RuntimeError("ChapterOutlineSegmentService requires an available model_client")

        prompt_input = {
            "book_id": book_id,
            "document_title_index": document_title_index,
            "chapter_title": chapter_title,
            "source_doc_range": source_doc_range,
            "summary_md": summary_md,
            "chapter_summary_short": chapter_summary_short,
        }
        system_prompt, user_prompt = build_chapter_outline_segment_prompt(prompt_input)
        payload, _raw = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: fallback,
            use_fallback_on_error=bool(getattr(getattr(self.model_client, "settings", None), "dry_run", False)),
        )
        if not isinstance(payload, Mapping):
            raise RuntimeError("Chapter outline segment model returned a non-object JSON payload")

        chapter_line = normalize_whitespace(str(payload.get("chapter_line") or "")) or fallback["chapter_line"]
        outline_segment = normalize_whitespace(str(payload.get("outline_segment") or ""))
        if not self._is_usable_outline_segment(outline_segment):
            raise RuntimeError("Chapter outline segment model returned no usable outline_segment")
        return {
            "chapter_line": chapter_line,
            "outline_segment": outline_segment,
            "compression_notes": normalize_whitespace(str(payload.get("compression_notes") or "")),
        }

    def fallback_outline_segment(self, *, summary_md: str, chapter_summary_short: str = "") -> str:
        plot_items = self._plot_items(summary_md)
        if not plot_items:
            return normalize_whitespace(chapter_summary_short or summary_md)
        plot_text = normalize_whitespace(" ".join(plot_items))
        if len(plot_text) <= self.target_chars * 1.25:
            return plot_text
        selected = self._select_representative_sentences(split_sentences(plot_text) or plot_items)
        return normalize_whitespace("".join(selected)) if selected else plot_text

    @staticmethod
    def _is_usable_outline_segment(value: str) -> bool:
        text = normalize_whitespace(value)
        if not text:
            return False
        if text.endswith("...") or text.endswith("……"):
            return False
        return True

    def _select_representative_sentences(self, sentences: list[str]) -> list[str]:
        cleaned = [normalize_whitespace(sentence) for sentence in sentences if normalize_whitespace(sentence)]
        if len(cleaned) <= 2:
            return cleaned
        candidates = [cleaned[0]]
        middle = cleaned[len(cleaned) // 2]
        if middle not in candidates:
            candidates.append(middle)
        if cleaned[-1] not in candidates:
            candidates.append(cleaned[-1])
        selected: list[str] = []
        for sentence in candidates:
            if not selected or len("".join(selected)) + len(sentence) <= self.target_chars * 1.4:
                selected.append(sentence)
        return selected or candidates[:1]

    def _plot_items(self, summary_md: str) -> list[str]:
        sections = self._summary_sections(summary_md)
        raw_items = sections.get("剧情事件链") or []
        items: list[str] = []
        for item in raw_items:
            text = normalize_whitespace(item[2:] if item.startswith("- ") else item)
            text = self._strip_outline_label(text)
            if text:
                items.append(text)
        return items

    @staticmethod
    def _summary_sections(summary_md: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {"剧情事件链": []}
        current = "剧情事件链"
        aliases = {
            "剧情事件链": "剧情事件链",
            "剧情推进": "剧情事件链",
            "剧情": "剧情事件链",
            "事件链": "剧情事件链",
            "情节链": "剧情事件链",
        }
        for raw_line in str(summary_md or "").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("## "):
                current = aliases.get(stripped[3:].strip(), "")
                continue
            if stripped.startswith("### "):
                current = aliases.get(stripped[4:].strip(), "")
                continue
            if current == "剧情事件链":
                sections.setdefault(current, []).append(stripped if stripped.startswith("- ") else f"- {stripped}")
        return sections

    @staticmethod
    def _strip_outline_label(text: str) -> str:
        return re.sub(r"^(起点|背景|触发|行动/冲突|行动|冲突|转折/结果|转折|结果|后续铺垫|铺垫)[:：]\s*", "", text).strip()

    @staticmethod
    def _fallback_chapter_line(
        *,
        document_title_index: int,
        chapter_title: str,
        chapter_summary_short: str,
        existing_chapter_line: str,
    ) -> str:
        existing = normalize_whitespace(existing_chapter_line)
        if existing:
            return existing
        title = normalize_whitespace(chapter_title) or "未命名章节"
        summary = normalize_whitespace(chapter_summary_short)
        return f"[{document_title_index}] {title}: {summary}".rstrip(": ")
