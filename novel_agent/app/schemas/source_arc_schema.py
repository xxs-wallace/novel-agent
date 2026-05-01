from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ChapterPlotSummary:
    document_title_index: int
    chapter_title: str
    summary_md: str
    summary_short: str = ""
    importance_score: int = 0
    source_total_chars: int = 0
    structure_signals: dict[str, Any] = field(default_factory=dict)
    source_doc_ids: list[int] = field(default_factory=list)
    related_chapters: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlotSummaryUnit:
    unit_id: str
    source_doc_ids: list[int]
    source_title_indexes: list[int]
    overlap_doc_ids: list[int]
    overlap_title_indexes: list[int]
    start_document_title_index: int
    end_document_title_index: int
    unit_summary: str
    continuity_hooks: list[str] = field(default_factory=list)
    boundary_events: list[str] = field(default_factory=list)
    major_character_state_changes: list[str] = field(default_factory=list)
    relationship_movements: list[str] = field(default_factory=list)
    world_or_rule_reveals: list[str] = field(default_factory=list)
    uncertainty_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlotSummaryCompressionResult:
    used_compression: bool
    total_summary_chars: int
    threshold_chars: int
    window_size: int
    overlap_size: int
    stride: int
    units: list[PlotSummaryUnit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["units"] = [unit.to_dict() for unit in self.units]
        return payload


@dataclass(slots=True)
class SourceArcChapterRole:
    document_title_index: int
    chapter_title: str
    role: str
    reason: str
    source_doc_ids: list[int] = field(default_factory=list)
    source_total_chars: int = 0
    structure_signals: dict[str, Any] = field(default_factory=dict)
    narrative_function_summary: str = ""
    emotional_setup_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceArc:
    book_id: str
    source_arc_id: str
    source_arc_title: str
    start_document_title_index: int
    end_document_title_index: int
    source_arc_role: str
    core_events: list[str] = field(default_factory=list)
    main_character_threads: list[str] = field(default_factory=list)
    world_or_rule_reveals: list[str] = field(default_factory=list)
    transition_from_previous: str = ""
    setup_for_next: str = ""
    pacing_notes: str = ""
    pacing_profile: dict[str, Any] = field(default_factory=dict)
    emotional_setup_notes: list[str] = field(default_factory=list)
    chapter_role_map: list[SourceArcChapterRole] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chapter_role_map"] = [item.to_dict() for item in self.chapter_role_map]
        return payload


@dataclass(slots=True)
class SourceArcMap:
    book_id: str
    generated_at: str
    source_summary_count: int
    used_compression: bool
    compression: PlotSummaryCompressionResult
    arcs: list[SourceArc] = field(default_factory=list)
    plot_summary_units: list[PlotSummaryUnit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "generated_at": self.generated_at,
            "source_summary_count": self.source_summary_count,
            "used_compression": self.used_compression,
            "compression": self.compression.to_dict(),
            "plot_summary_units": [unit.to_dict() for unit in self.plot_summary_units],
            "arcs": [arc.to_dict() for arc in self.arcs],
        }
