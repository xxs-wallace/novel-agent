from __future__ import annotations

import re
from typing import Any, Mapping

from ..prompts.chapter_event_list_prompt import build_chapter_event_list_prompt
from ..utils.text_utils import normalize_whitespace, split_sentences

DEFAULT_CHAPTER_EVENT_LIST_MAX_EVENTS = 8


class ChapterEventListService:
    """Builds chapter-level timeline_events from an existing summary_md."""

    def __init__(
        self,
        *,
        model_client: Any | None = None,
        max_events: int = DEFAULT_CHAPTER_EVENT_LIST_MAX_EVENTS,
    ) -> None:
        self.model_client = model_client
        self.max_events = max(1, int(max_events))

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
        existing_events = self._normalize_events(existing.get("timeline_events"))
        fallback_events = self.fallback_events(
            summary_md=summary_md,
            existing_timeline_events=existing_events,
        )
        fallback = {
            "chapter_line": self._fallback_chapter_line(
                document_title_index=document_title_index,
                chapter_title=chapter_title,
                chapter_summary_short=chapter_summary_short,
                existing_chapter_line=str(existing.get("chapter_line") or ""),
            ),
            "timeline_events": fallback_events,
        }
        if not self._should_use_model():
            return fallback

        prompt_input = {
            "book_id": book_id,
            "document_title_index": document_title_index,
            "chapter_title": chapter_title,
            "source_doc_range": source_doc_range,
            "summary_md": summary_md,
            "chapter_summary_short": chapter_summary_short,
            "existing_timeline_events": existing_events,
        }
        system_prompt, user_prompt = build_chapter_event_list_prompt(prompt_input)
        payload, _raw = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: fallback,
            use_fallback_on_error=bool(getattr(getattr(self.model_client, "settings", None), "dry_run", False)),
        )
        if not isinstance(payload, Mapping):
            return fallback

        events = self._normalize_events(payload.get("timeline_events"))
        if not events:
            events = fallback_events
        chapter_line = normalize_whitespace(str(payload.get("chapter_line") or "")) or fallback["chapter_line"]
        return {"chapter_line": chapter_line, "timeline_events": events}

    def fallback_events(
        self,
        *,
        summary_md: str,
        existing_timeline_events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        plot_items = self._plot_items(summary_md)
        events: list[dict[str, Any]] = []
        for item in plot_items[: self.max_events]:
            summary = normalize_whitespace(item)
            if not summary:
                continue
            events.append(
                {
                    "label": self._event_label(summary),
                    "participants": [],
                    "summary": summary,
                }
            )
        if events:
            return events
        return self._normalize_events(existing_timeline_events or [])

    def _should_use_model(self) -> bool:
        if self.model_client is None:
            return False
        settings = getattr(self.model_client, "settings", None)
        return not bool(getattr(settings, "dry_run", False))

    def _normalize_events(self, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        events: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            summary = normalize_whitespace(str(item.get("summary") or ""))
            label = normalize_whitespace(str(item.get("label") or "")) or self._event_label(summary)
            if not summary and not label:
                continue
            participants = item.get("participants", [])
            normalized_participants = (
                [normalize_whitespace(str(name)) for name in participants if normalize_whitespace(str(name))]
                if isinstance(participants, list)
                else []
            )
            event = dict(item)
            event["label"] = label or summary[:24]
            event["participants"] = sorted(set(normalized_participants))
            event["summary"] = summary or label
            events.append(event)
            if len(events) >= self.max_events:
                break
        return events

    def _plot_items(self, summary_md: str) -> list[str]:
        sections = self._summary_sections(summary_md)
        raw_items = sections.get("剧情事件链") or []
        items: list[str] = []
        for item in raw_items:
            text = normalize_whitespace(item[2:] if item.startswith("- ") else item)
            text = self._strip_outline_label(text)
            if text:
                items.append(text)
        if items:
            return items
        fallback = normalize_whitespace(summary_md)
        return split_sentences(fallback) or ([fallback] if fallback else [])

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
    def _event_label(summary: str) -> str:
        text = normalize_whitespace(summary)
        if not text:
            return ""
        first_sentence = (split_sentences(text) or [text])[0]
        match = re.match(r"^(.{2,24}?)(?:，|。|；|、|:|：)", first_sentence)
        return normalize_whitespace(match.group(1) if match else first_sentence[:24])

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
        summary = normalize_whitespace(chapter_summary_short)
        return f"[{document_title_index}] {chapter_title}: {summary}" if summary else f"[{document_title_index}] {chapter_title}"
