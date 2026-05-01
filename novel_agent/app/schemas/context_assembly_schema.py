from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ChapterContextItem:
    document_title_index: str
    chapter_title: str
    summary_md: str
    importance_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterProfileContextItem:
    canonical_name: str
    profile_summary_md: str
    aliases: list[str] = field(default_factory=list)
    importance_score: int = 0
    speaking_character_status: str = "unknown"
    personhood_evidence_summary: str = ""
    evidence_level: str = "inferred"
    recent_activity_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceArcContextItem:
    source_arc_id: str
    source_arc_title: str
    start_document_title_index: int
    end_document_title_index: int
    source_arc_role: str
    core_events: list[str] = field(default_factory=list)
    transition_from_previous: str = ""
    setup_for_next: str = ""
    pacing_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextAssemblyPayload:
    chapter_context: list[ChapterContextItem] = field(default_factory=list)
    source_arc_context: list[SourceArcContextItem] = field(default_factory=list)
    world_summary_md: str = ""
    character_profiles: list[CharacterProfileContextItem] = field(default_factory=list)
    story_outline_md: str = ""
    missing_context: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_context": [item.to_dict() for item in self.chapter_context],
            "source_arc_context": [item.to_dict() for item in self.source_arc_context],
            "world_summary_md": self.world_summary_md,
            "character_profiles": [item.to_dict() for item in self.character_profiles],
            "story_outline_md": self.story_outline_md,
            "missing_context": list(self.missing_context),
        }
