from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..prompts.source_arc_prompt import build_plot_summary_unit_prompt
from ..schemas.source_arc_schema import ChapterPlotSummary, PlotSummaryCompressionResult, PlotSummaryUnit
from ..utils.text_utils import normalize_whitespace, safe_excerpt


DEFAULT_SOURCE_ARC_COMPRESSION_THRESHOLD_CHARS = 12 * 1024
DEFAULT_PLOT_SUMMARY_WINDOW_SIZE = 8
DEFAULT_PLOT_SUMMARY_OVERLAP_SIZE = 2
DEFAULT_PLOT_SUMMARY_UNIT_SUMMARY_CHARS = 360


class PlotSummaryUnitCompressionService:
    def __init__(
        self,
        *,
        threshold_chars: int = DEFAULT_SOURCE_ARC_COMPRESSION_THRESHOLD_CHARS,
        window_size: int = DEFAULT_PLOT_SUMMARY_WINDOW_SIZE,
        overlap_size: int = DEFAULT_PLOT_SUMMARY_OVERLAP_SIZE,
        per_summary_excerpt_chars: int = DEFAULT_PLOT_SUMMARY_UNIT_SUMMARY_CHARS,
        model_client: Any | None = None,
    ) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be greater than 0")
        if overlap_size < 0:
            raise ValueError("overlap_size must be non-negative")
        if overlap_size >= window_size:
            raise ValueError("overlap_size must be smaller than window_size")
        self.threshold_chars = max(0, threshold_chars)
        self.window_size = window_size
        self.overlap_size = overlap_size
        self.stride = window_size - overlap_size
        self.per_summary_excerpt_chars = max(80, per_summary_excerpt_chars)
        self.model_client = model_client

    def compress_if_needed(self, summaries: Sequence[ChapterPlotSummary]) -> PlotSummaryCompressionResult:
        ordered = self._ordered_summaries(summaries)
        total_chars = self.total_summary_chars(ordered)
        if total_chars <= self.threshold_chars:
            return PlotSummaryCompressionResult(
                used_compression=False,
                total_summary_chars=total_chars,
                threshold_chars=self.threshold_chars,
                window_size=self.window_size,
                overlap_size=self.overlap_size,
                stride=self.stride,
                units=[],
            )
        return PlotSummaryCompressionResult(
            used_compression=True,
            total_summary_chars=total_chars,
            threshold_chars=self.threshold_chars,
            window_size=self.window_size,
            overlap_size=self.overlap_size,
            stride=self.stride,
            units=self.compress(ordered),
        )

    def compress(self, summaries: Sequence[ChapterPlotSummary]) -> list[PlotSummaryUnit]:
        ordered = self._ordered_summaries(summaries)
        if not ordered:
            return []
        units: list[PlotSummaryUnit] = []
        start = 0
        while start < len(ordered):
            end = min(start + self.window_size, len(ordered))
            window = ordered[start:end]
            previous_overlap = window[: self.overlap_size] if units else []
            fallback_unit = self._build_unit(
                index=len(units) + 1,
                window=window,
                overlap_items=previous_overlap,
            )
            unit = self._build_unit_with_model(window=window, fallback_unit=fallback_unit)
            units.append(unit)
            if end >= len(ordered):
                break
            start += self.stride
        return units

    def total_summary_chars(self, summaries: Sequence[ChapterPlotSummary]) -> int:
        return sum(len(self._summary_text(item)) for item in summaries)

    def _build_unit(
        self,
        *,
        index: int,
        window: Sequence[ChapterPlotSummary],
        overlap_items: Sequence[ChapterPlotSummary],
    ) -> PlotSummaryUnit:
        start_index = window[0].document_title_index
        end_index = window[-1].document_title_index
        lines: list[str] = []
        for item in window:
            summary = safe_excerpt(self._summary_text(item), limit=self.per_summary_excerpt_chars)
            lines.append(f"[{item.document_title_index}] {item.chapter_title}: {summary}")

        boundary_events = self._boundary_events(window)
        continuity_hooks = self._continuity_hooks(window)
        unit_summary = "\n".join(lines)
        return PlotSummaryUnit(
            unit_id=f"plot-summary-unit-{index:04d}",
            source_doc_ids=self._unique_doc_ids(window),
            source_title_indexes=[item.document_title_index for item in window],
            overlap_doc_ids=self._unique_doc_ids(overlap_items),
            overlap_title_indexes=[item.document_title_index for item in overlap_items],
            start_document_title_index=start_index,
            end_document_title_index=end_index,
            unit_summary=unit_summary,
            continuity_hooks=continuity_hooks,
            boundary_events=boundary_events,
            major_character_state_changes=self._extract_by_keywords(
                window,
                ("决定", "选择", "意识到", "开始", "变得", "身份", "状态", "心理", "内心"),
            ),
            relationship_movements=self._extract_by_keywords(
                window,
                ("关系", "信任", "误会", "和解", "告白", "冲突", "对话", "合作", "背叛"),
            ),
            world_or_rule_reveals=self._extract_by_keywords(
                window,
                ("世界", "规则", "设定", "能力", "组织", "血统", "禁忌", "真相", "秘密"),
            ),
            uncertainty_notes=[],
        )

    def _build_unit_with_model(
        self,
        *,
        window: Sequence[ChapterPlotSummary],
        fallback_unit: PlotSummaryUnit,
    ) -> PlotSummaryUnit:
        if not self._should_use_model():
            return fallback_unit
        system_prompt, user_prompt = build_plot_summary_unit_prompt(
            window=window,
            overlap_title_indexes=fallback_unit.overlap_title_indexes,
            fallback_payload=fallback_unit.to_dict(),
        )
        payload, _ = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=fallback_unit.to_dict,
            use_fallback_on_error=True,
        )
        if not isinstance(payload, dict):
            return fallback_unit
        return self._unit_from_payload(payload=payload, fallback_unit=fallback_unit)

    def _unit_from_payload(self, *, payload: dict[str, Any], fallback_unit: PlotSummaryUnit) -> PlotSummaryUnit:
        return PlotSummaryUnit(
            unit_id=fallback_unit.unit_id,
            source_doc_ids=fallback_unit.source_doc_ids,
            source_title_indexes=fallback_unit.source_title_indexes,
            overlap_doc_ids=fallback_unit.overlap_doc_ids,
            overlap_title_indexes=fallback_unit.overlap_title_indexes,
            start_document_title_index=fallback_unit.start_document_title_index,
            end_document_title_index=fallback_unit.end_document_title_index,
            unit_summary=self._payload_text(payload, "unit_summary", fallback_unit.unit_summary),
            continuity_hooks=self._payload_str_list(payload, "continuity_hooks", fallback_unit.continuity_hooks),
            boundary_events=self._payload_str_list(payload, "boundary_events", fallback_unit.boundary_events),
            major_character_state_changes=self._payload_str_list(
                payload,
                "major_character_state_changes",
                fallback_unit.major_character_state_changes,
            ),
            relationship_movements=self._payload_str_list(
                payload,
                "relationship_movements",
                fallback_unit.relationship_movements,
            ),
            world_or_rule_reveals=self._payload_str_list(
                payload,
                "world_or_rule_reveals",
                fallback_unit.world_or_rule_reveals,
            ),
            uncertainty_notes=self._payload_str_list(payload, "uncertainty_notes", fallback_unit.uncertainty_notes),
        )

    def _payload_text(self, payload: dict[str, Any], key: str, fallback: str) -> str:
        value = payload.get(key)
        text = normalize_whitespace(str(value or ""))
        return text or fallback

    def _payload_str_list(self, payload: dict[str, Any], key: str, fallback: list[str]) -> list[str]:
        value = payload.get(key)
        if not isinstance(value, list):
            return list(fallback)
        items = [normalize_whitespace(str(item)) for item in value if normalize_whitespace(str(item))]
        return items or list(fallback)

    def _should_use_model(self) -> bool:
        if self.model_client is None:
            return False
        settings = getattr(self.model_client, "settings", None)
        return not bool(getattr(settings, "dry_run", False))

    def _boundary_events(self, window: Sequence[ChapterPlotSummary]) -> list[str]:
        if len(window) == 1:
            item = window[0]
            return [f"[{item.document_title_index}] {safe_excerpt(self._summary_text(item), limit=120)}"]
        first = window[0]
        last = window[-1]
        return [
            f"start[{first.document_title_index}]: {safe_excerpt(self._summary_text(first), limit=120)}",
            f"end[{last.document_title_index}]: {safe_excerpt(self._summary_text(last), limit=120)}",
        ]

    def _continuity_hooks(self, window: Sequence[ChapterPlotSummary]) -> list[str]:
        hooks: list[str] = []
        for item in window[-2:]:
            text = self._summary_text(item)
            if text:
                hooks.append(f"[{item.document_title_index}] {safe_excerpt(text, limit=120)}")
        return hooks

    def _extract_by_keywords(
        self,
        window: Sequence[ChapterPlotSummary],
        keywords: Sequence[str],
        *,
        limit: int = 4,
    ) -> list[str]:
        matches: list[str] = []
        for item in window:
            text = self._summary_text(item)
            if not text or not any(keyword in text for keyword in keywords):
                continue
            matches.append(f"[{item.document_title_index}] {safe_excerpt(text, limit=120)}")
            if len(matches) >= limit:
                break
        return matches

    def _unique_doc_ids(self, summaries: Sequence[ChapterPlotSummary]) -> list[int]:
        ordered: list[int] = []
        seen: set[int] = set()
        for item in summaries:
            for doc_id in item.source_doc_ids:
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                ordered.append(doc_id)
        return ordered

    def _ordered_summaries(self, summaries: Sequence[ChapterPlotSummary]) -> list[ChapterPlotSummary]:
        return sorted(summaries, key=lambda item: item.document_title_index)

    def _summary_text(self, item: ChapterPlotSummary) -> str:
        return normalize_whitespace(item.summary_md or item.summary_short)
