from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class DirectoryReadOrderItem:
    path: str
    sort_key: int
    reason: str


@dataclass(slots=True)
class DirectoryBookPlan:
    book_id: str
    book_name: str
    root_path: str
    selected_paths: list[str]
    ignored_paths: list[str] = field(default_factory=list)
    read_order: list[DirectoryReadOrderItem] = field(default_factory=list)
    confidence: float = 1.0


@dataclass(slots=True)
class DirectoryAnalysisOutput:
    strategy_type: Literal["single_file", "single_book_multi_file", "multi_book_directory"]
    books: list[DirectoryBookPlan]
    global_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SegmentationInputSegment:
    segment_id: int
    byte_length: int
    text: str
    boundary_candidate: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SegmentedDocumentOutput:
    document_local_id: int
    document_title: str
    document_title_index: int
    inferred_chapter_no: int | None
    segment_ids: list[int] = field(default_factory=list)
    character_keywords: list[str] = field(default_factory=list)
    content_tags: list[str] = field(default_factory=list)
    segmentation_reason: str = ""
    continuity_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SegmentationBatchSummary:
    chapter_count: int
    document_count: int
    new_characters: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SegmentationPromptOutput:
    documents: list[SegmentedDocumentOutput]
    batch_summary: SegmentationBatchSummary
    document_title_index_start: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_title_index_start": self.document_title_index_start,
            "documents": [doc.to_dict() for doc in self.documents],
            "batch_summary": asdict(self.batch_summary),
        }


@dataclass(slots=True)
class CloseReadInputDocument:
    doc_id: int
    document_title_index: int
    content: str
    character_keywords: list[str] = field(default_factory=list)
    content_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CloseReadInputCharacterProfile:
    canonical_name: str
    profile_summary_md: str


@dataclass(slots=True)
class CloseReadTokenBudget:
    document_chars_budget: int = 20_000
    outline_chars_budget: int = 10_240
    world_summary_chars_budget: int = 1_024
    character_profiles_chars_budget: int = 12_000


@dataclass(slots=True)
class CloseReadPromptInput:
    book_id: str
    current_title_index: int
    chapter_title: str
    source_total_chars: int
    summary_target_chars_min: int
    documents: list[CloseReadInputDocument]
    story_outline_md: str
    world_summary_md: str
    character_profiles: list[CloseReadInputCharacterProfile]
    token_budget: CloseReadTokenBudget = field(default_factory=CloseReadTokenBudget)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterEvidenceInputDocument:
    doc_id: int
    document_title_index: int
    document_title: str
    local_character_hints: list[str] = field(default_factory=list)
    content_chars: int = 0


@dataclass(slots=True)
class CharacterEvidenceBatchInput:
    character_evidence_batch_id: str
    book_id: str
    doc_ids: list[int]
    document_title_indexes: list[int]
    source_doc_start_id: int
    source_doc_end_id: int
    batch_text: str
    documents: list[CharacterEvidenceInputDocument] = field(default_factory=list)
    document_separator_hint: str = "[DOC doc_id=<id> title_index=<index> title=<title>] ... [/DOC]"
    existing_context_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterEvidencePromptInput:
    character_evidence_batch: CharacterEvidenceBatchInput

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterEvidenceCharacterOutput:
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    is_speaking_character: bool = False
    speaking_evidence: str = ""
    personhood_evidence: str = ""
    activity_or_state_evidence: str = ""
    relationship_evidence: str = ""
    source_doc_ids: list[int] = field(default_factory=list)
    source_title_indexes: list[int] = field(default_factory=list)
    candidate_type: str = "character"
    confidence: float = 0.0
    uncertainty_reason: str = ""


@dataclass(slots=True)
class CharacterEvidencePromptOutput:
    doc_id: int
    document_title_index: int
    characters: list[CharacterEvidenceCharacterOutput] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RelatedChapterScore:
    document_title_index: int
    score: int
    reason: str


@dataclass(slots=True)
class WorldEvidenceCandidateOutput:
    section: str
    summary: str
    evidence_hint: str
    source_doc_ids: list[int] = field(default_factory=list)
    source_title_indexes: list[int] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(slots=True)
class WorldChangeItem:
    section: str
    summary: str
    evidence: str


@dataclass(slots=True)
class WorldUpdateOutput:
    should_update: bool
    changes: list[WorldChangeItem] = field(default_factory=list)


@dataclass(slots=True)
class CharacterAbilityOutput:
    type: str
    name: str
    summary: str


@dataclass(slots=True)
class CharacterRelationshipOutput:
    target_name: str
    relation_type: str
    sentiment_state: str
    status_summary: str


@dataclass(slots=True)
class CharacterAgeUpdateOutput:
    label: str
    chapter_range: str
    reason: str


@dataclass(slots=True)
class CharacterUpdateOutput:
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    personality: list[str] = field(default_factory=list)
    occupations: list[str] = field(default_factory=list)
    age_update: CharacterAgeUpdateOutput | None = None
    abilities: list[CharacterAbilityOutput] = field(default_factory=list)
    recent_activity: str = ""
    relationships: list[CharacterRelationshipOutput] = field(default_factory=list)


@dataclass(slots=True)
class DocumentCharacterMentionOutput:
    doc_id: int
    character_keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OutlineTimelineEventOutput:
    label: str
    participants: list[str]
    summary: str


@dataclass(slots=True)
class OutlineUpdateOutput:
    chapter_line: str
    timeline_events: list[OutlineTimelineEventOutput] = field(default_factory=list)


@dataclass(slots=True)
class CloseReadPromptOutput:
    chapter_summary_md: str
    chapter_summary_short: str
    importance_score: int
    importance_reason: str
    related_chapters: list[RelatedChapterScore] = field(default_factory=list)
    document_character_mentions: list[DocumentCharacterMentionOutput] = field(default_factory=list)
    world_update: WorldUpdateOutput = field(default_factory=lambda: WorldUpdateOutput(should_update=False))
    character_updates: list[CharacterUpdateOutput] = field(default_factory=list)
    outline_update: OutlineUpdateOutput = field(default_factory=lambda: OutlineUpdateOutput(chapter_line=""))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
