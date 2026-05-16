from __future__ import annotations

import re
from typing import Any, Mapping

from ..prompts.chapter_event_summary_prompt import build_chapter_event_summary_prompt
from ..utils.text_utils import normalize_whitespace, split_sentences

CHAPTER_EVENT_SUMMARY_TARGET_CHARS = 260


class ChapterEventSummaryService:
    """Builds a chapter-level event_summary from an existing summary_md."""

    def __init__(
        self,
        *,
        model_client: Any | None = None,
        target_chars: int = CHAPTER_EVENT_SUMMARY_TARGET_CHARS,
    ) -> None:
        self.model_client = model_client
        self.target_chars = max(120, int(target_chars))

    def summarize(
        self,
        *,
        book_id: str,
        document_title_index: int,
        chapter_title: str,
        summary_md: str,
        chapter_summary_short: str = "",
        source_doc_range: str = "",
        chapter_event_list: list[dict[str, Any]] | None = None,
        existing_timeline_events: list[dict[str, Any]] | None = None,
    ) -> str:
        event_list = chapter_event_list if chapter_event_list is not None else existing_timeline_events
        fallback = self.fallback_summary(
            summary_md=summary_md,
            chapter_summary_short=chapter_summary_short,
            chapter_event_list=event_list,
        )
        if not self._should_use_model():
            return fallback
        prompt_input = {
            "book_id": book_id,
            "document_title_index": document_title_index,
            "chapter_title": chapter_title,
            "source_doc_range": source_doc_range,
            "summary_md": summary_md,
            "chapter_summary_short": chapter_summary_short,
            "chapter_event_list": event_list or [],
        }
        system_prompt, user_prompt = build_chapter_event_summary_prompt(prompt_input)
        payload, _raw = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: {"event_summary": fallback, "compression_notes": "fallback"},
            use_fallback_on_error=bool(getattr(getattr(self.model_client, "settings", None), "dry_run", False)),
        )
        if not isinstance(payload, Mapping):
            return fallback
        event_summary = normalize_whitespace(str(payload.get("event_summary") or ""))
        return event_summary if self._is_usable_summary(event_summary) else fallback

    def fallback_summary(
        self,
        *,
        summary_md: str,
        chapter_summary_short: str = "",
        chapter_event_list: list[dict[str, Any]] | None = None,
        existing_timeline_events: list[dict[str, Any]] | None = None,
    ) -> str:
        event_list = chapter_event_list if chapter_event_list is not None else existing_timeline_events
        timeline_summary = self._timeline_summary(event_list or [])
        if timeline_summary:
            timeline_sentences = split_sentences(timeline_summary)
            if len(timeline_summary) <= self.target_chars * 1.25:
                return timeline_summary
            selected = self._select_representative_sentences(timeline_sentences)
            if selected:
                return normalize_whitespace("".join(selected))
        plot_items = self._plot_items(summary_md)
        if not plot_items:
            return timeline_summary or normalize_whitespace(chapter_summary_short or summary_md)
        plot_text = normalize_whitespace(" ".join(plot_items))
        sentences = split_sentences(plot_text)
        if len(plot_text) <= self.target_chars * 1.25:
            return plot_text
        selected = self._select_representative_sentences(sentences or plot_items)
        if selected:
            return normalize_whitespace("".join(selected))
        return plot_text

    def _should_use_model(self) -> bool:
        if self.model_client is None:
            return False
        settings = getattr(self.model_client, "settings", None)
        return not bool(getattr(settings, "dry_run", False))

    @staticmethod
    def _is_usable_summary(summary: str) -> bool:
        text = normalize_whitespace(summary)
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
    def _timeline_summary(events: list[dict[str, Any]]) -> str:
        summaries: list[str] = []
        for event in events:
            if not isinstance(event, Mapping):
                continue
            summary = normalize_whitespace(str(event.get("summary") or event.get("label") or ""))
            if summary and not summary.endswith("..."):
                summaries.append(summary)
        return normalize_whitespace(" ".join(summaries))
