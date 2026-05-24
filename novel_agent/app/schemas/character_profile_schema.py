from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EvidenceLevel = Literal["explicit", "inferred"]
ProfileFieldType = Literal["fact", "inference"]


@dataclass(slots=True)
class ProfileAttributeItem:
    value: str
    field_type: ProfileFieldType
    evidence_level: EvidenceLevel
    source_chapter_indexes: list[int] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterAbilityItem:
    type: str
    name: str
    summary: str
    field_type: ProfileFieldType
    evidence_level: EvidenceLevel
    source_chapter_indexes: list[int] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterAgeItem:
    label: str
    chapter_range: str
    reason: str
    field_type: ProfileFieldType
    evidence_level: EvidenceLevel
    source_chapter_indexes: list[int] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterRelationshipItem:
    target_name: str
    relation_type: str
    sentiment_state: str
    status_summary: str
    field_type: ProfileFieldType
    evidence_level: EvidenceLevel
    address_terms: list[str] = field(default_factory=list)
    source_chapter_indexes: list[int] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)
    last_updated_chapter_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterStoryEventItem:
    event_id: str
    label: str
    summary: str
    source_chapter_indexes: list[int] = field(default_factory=list)
    source_doc_ids: list[int] = field(default_factory=list)
    source_doc_range: str = ""
    participants: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterProfileSnapshot:
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    profile_summary_md: str = ""
    speaking_character_status: str = "unknown"
    personhood_evidence_summary: str = ""
    evidence_level: EvidenceLevel = "inferred"
    personality: list[ProfileAttributeItem] = field(default_factory=list)
    occupations: list[ProfileAttributeItem] = field(default_factory=list)
    age_timeline: list[CharacterAgeItem] = field(default_factory=list)
    abilities: list[CharacterAbilityItem] = field(default_factory=list)
    recent_activity: list[ProfileAttributeItem] = field(default_factory=list)
    relationships: list[CharacterRelationshipItem] = field(default_factory=list)
    story_events: list[CharacterStoryEventItem] = field(default_factory=list)
    chapter_indexes: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "profile_summary_md": self.profile_summary_md,
            "speaking_character_status": self.speaking_character_status,
            "personhood_evidence_summary": self.personhood_evidence_summary,
            "evidence_level": self.evidence_level,
            "personality": [item.to_dict() for item in self.personality],
            "occupations": [item.to_dict() for item in self.occupations],
            "age_timeline": [item.to_dict() for item in self.age_timeline],
            "abilities": [item.to_dict() for item in self.abilities],
            "recent_activity": [item.to_dict() for item in self.recent_activity],
            "relationships": [item.to_dict() for item in self.relationships],
            "story_events": [item.to_dict() for item in self.story_events],
            "chapter_indexes": list(self.chapter_indexes),
        }
