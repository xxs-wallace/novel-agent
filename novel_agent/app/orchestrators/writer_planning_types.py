from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_string_list(items: Sequence[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


@dataclass(slots=True)
class ResolvedCharacterRef:
    name: str
    resolved_to: str

    def __post_init__(self) -> None:
        self.name = _normalize_text(self.name)
        self.resolved_to = _normalize_text(self.resolved_to)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NamedNewCharacter:
    name: str
    reason: str

    def __post_init__(self) -> None:
        self.name = _normalize_text(self.name)
        self.reason = _normalize_text(self.reason)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class UnfilledRoleSlot:
    slot_id: str
    slot_type: str
    reason: str

    def __post_init__(self) -> None:
        self.slot_id = _normalize_text(self.slot_id)
        self.slot_type = _normalize_text(self.slot_type)
        self.reason = _normalize_text(self.reason)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterRequirementReport:
    named_existing_characters: list[ResolvedCharacterRef] = field(default_factory=list)
    named_new_characters: list[NamedNewCharacter] = field(default_factory=list)
    unfilled_role_slots: list[UnfilledRoleSlot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "named_existing_characters": [item.to_dict() for item in self.named_existing_characters],
            "named_new_characters": [item.to_dict() for item in self.named_new_characters],
            "unfilled_role_slots": [item.to_dict() for item in self.unfilled_role_slots],
        }


@dataclass(slots=True)
class IntroductionWindow:
    batch_id: str = ""
    chapter_range: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.batch_id = _normalize_text(self.batch_id)
        self.chapter_range = _normalize_string_list(self.chapter_range)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntroductionWindow":
        return cls(
            batch_id=str(data.get("batch_id") or ""),
            chapter_range=[str(item) for item in (data.get("chapter_range") or [])],
        )


@dataclass(slots=True)
class CharacterCastRequirement:
    slot_id: str
    faction: str = ""
    role_type: str = ""
    count: int = 1
    required_traits: list[str] = field(default_factory=list)
    forbidden_traits: list[str] = field(default_factory=list)
    must_connect_to: list[str] = field(default_factory=list)
    introduction_window: IntroductionWindow = field(default_factory=IntroductionWindow)

    def __post_init__(self) -> None:
        self.slot_id = _normalize_text(self.slot_id)
        self.faction = _normalize_text(self.faction)
        self.role_type = _normalize_text(self.role_type)
        self.count = max(1, int(self.count))
        self.required_traits = _normalize_string_list(self.required_traits)
        self.forbidden_traits = _normalize_string_list(self.forbidden_traits)
        self.must_connect_to = _normalize_string_list(self.must_connect_to)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "faction": self.faction,
            "role_type": self.role_type,
            "count": self.count,
            "required_traits": list(self.required_traits),
            "forbidden_traits": list(self.forbidden_traits),
            "must_connect_to": list(self.must_connect_to),
            "introduction_window": self.introduction_window.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterCastRequirement":
        intro = data.get("introduction_window")
        return cls(
            slot_id=str(data.get("slot_id") or ""),
            faction=str(data.get("faction") or ""),
            role_type=str(data.get("role_type") or ""),
            count=int(data.get("count") or 1),
            required_traits=[str(item) for item in (data.get("required_traits") or [])],
            forbidden_traits=[str(item) for item in (data.get("forbidden_traits") or [])],
            must_connect_to=[str(item) for item in (data.get("must_connect_to") or [])],
            introduction_window=IntroductionWindow.from_dict(intro) if isinstance(intro, dict) else IntroductionWindow(),
        )


@dataclass(slots=True)
class CharacterCastRequest:
    request_id: str
    source_layer: str
    reason: str
    requirements: list[CharacterCastRequirement] = field(default_factory=list)
    generation_seed: int = 0

    def __post_init__(self) -> None:
        self.request_id = _normalize_text(self.request_id)
        self.source_layer = _normalize_text(self.source_layer)
        self.reason = _normalize_text(self.reason)
        self.generation_seed = max(0, int(self.generation_seed))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source_layer": self.source_layer,
            "reason": self.reason,
            "requirements": [item.to_dict() for item in self.requirements],
            "generation_seed": self.generation_seed,
        }


@dataclass(slots=True)
class RelationshipEntry:
    target_character: str
    initial_state: str
    allowed_target_state_in_this_batch: str = ""

    def __post_init__(self) -> None:
        self.target_character = _normalize_text(self.target_character)
        self.initial_state = _normalize_text(self.initial_state)
        self.allowed_target_state_in_this_batch = _normalize_text(self.allowed_target_state_in_this_batch)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RelationshipEntry":
        return cls(
            target_character=str(data.get("target_character") or ""),
            initial_state=str(data.get("initial_state") or ""),
            allowed_target_state_in_this_batch=str(data.get("allowed_target_state_in_this_batch") or ""),
        )


@dataclass(slots=True)
class CharacterSeedInput:
    seed_id: str
    display_name_hint: str = ""
    faction: str = ""
    core_concept: str = ""
    must_keep: list[str] = field(default_factory=list)
    must_avoid: list[str] = field(default_factory=list)
    relationship_entry: RelationshipEntry | None = None
    world_constraints: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.seed_id = _normalize_text(self.seed_id)
        self.display_name_hint = _normalize_text(self.display_name_hint)
        self.faction = _normalize_text(self.faction)
        self.core_concept = _normalize_text(self.core_concept)
        self.must_keep = _normalize_string_list(self.must_keep)
        self.must_avoid = _normalize_string_list(self.must_avoid)
        self.world_constraints = _normalize_string_list(self.world_constraints)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_id": self.seed_id,
            "display_name_hint": self.display_name_hint,
            "faction": self.faction,
            "core_concept": self.core_concept,
            "must_keep": list(self.must_keep),
            "must_avoid": list(self.must_avoid),
            "relationship_entry": self.relationship_entry.to_dict() if self.relationship_entry else None,
            "world_constraints": list(self.world_constraints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterSeedInput":
        relationship_entry = data.get("relationship_entry")
        return cls(
            seed_id=str(data.get("seed_id") or ""),
            display_name_hint=str(data.get("display_name_hint") or ""),
            faction=str(data.get("faction") or ""),
            core_concept=str(data.get("core_concept") or ""),
            must_keep=[str(item) for item in (data.get("must_keep") or [])],
            must_avoid=[str(item) for item in (data.get("must_avoid") or [])],
            relationship_entry=RelationshipEntry.from_dict(relationship_entry)
            if isinstance(relationship_entry, dict)
            else None,
            world_constraints=[str(item) for item in (data.get("world_constraints") or [])],
        )


@dataclass(slots=True)
class PlannedRelationshipEntry:
    target_character: str
    initial_state: str
    ceiling_before_freeze_e: str = ""

    def __post_init__(self) -> None:
        self.target_character = _normalize_text(self.target_character)
        self.initial_state = _normalize_text(self.initial_state)
        self.ceiling_before_freeze_e = _normalize_text(self.ceiling_before_freeze_e)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlannedRelationshipEntry":
        return cls(
            target_character=str(data.get("target_character") or ""),
            initial_state=str(data.get("initial_state") or ""),
            ceiling_before_freeze_e=str(data.get("ceiling_before_freeze_e") or ""),
        )


@dataclass(slots=True)
class FirstIntroductionPlan:
    batch_id: str
    chapter_id: str
    scene_function: str

    def __post_init__(self) -> None:
        self.batch_id = _normalize_text(self.batch_id)
        self.chapter_id = _normalize_text(self.chapter_id)
        self.scene_function = _normalize_text(self.scene_function)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FirstIntroductionPlan":
        return cls(
            batch_id=str(data.get("batch_id") or ""),
            chapter_id=str(data.get("chapter_id") or ""),
            scene_function=str(data.get("scene_function") or ""),
        )


@dataclass(slots=True)
class PlannedCharacterProfile:
    planned_character_id: str
    status: str
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    faction: str = ""
    narrative_role: str = ""
    core_personality: list[str] = field(default_factory=list)
    surface_identity: str = ""
    hidden_pressure: list[str] = field(default_factory=list)
    ability_scope: list[str] = field(default_factory=list)
    ability_limits: list[str] = field(default_factory=list)
    relationship_entry_points: list[PlannedRelationshipEntry] = field(default_factory=list)
    first_introduction_plan: FirstIntroductionPlan | None = None
    must_not_reveal_early: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.planned_character_id = _normalize_text(self.planned_character_id)
        self.status = _normalize_text(self.status) or "planned"
        self.canonical_name = _normalize_text(self.canonical_name)
        self.aliases = _normalize_string_list(self.aliases)
        self.faction = _normalize_text(self.faction)
        self.narrative_role = _normalize_text(self.narrative_role)
        self.core_personality = _normalize_string_list(self.core_personality)
        self.surface_identity = _normalize_text(self.surface_identity)
        self.hidden_pressure = _normalize_string_list(self.hidden_pressure)
        self.ability_scope = _normalize_string_list(self.ability_scope)
        self.ability_limits = _normalize_string_list(self.ability_limits)
        self.must_not_reveal_early = _normalize_string_list(self.must_not_reveal_early)
        normalized_sources: list[dict[str, str]] = []
        for item in self.sources:
            if not isinstance(item, dict):
                continue
            normalized_sources.append({str(key): _normalize_text(value) for key, value in item.items()})
        self.sources = normalized_sources

    def to_dict(self) -> dict[str, Any]:
        return {
            "planned_character_id": self.planned_character_id,
            "status": self.status,
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "faction": self.faction,
            "narrative_role": self.narrative_role,
            "core_personality": list(self.core_personality),
            "surface_identity": self.surface_identity,
            "hidden_pressure": list(self.hidden_pressure),
            "ability_scope": list(self.ability_scope),
            "ability_limits": list(self.ability_limits),
            "relationship_entry_points": [item.to_dict() for item in self.relationship_entry_points],
            "first_introduction_plan": self.first_introduction_plan.to_dict() if self.first_introduction_plan else None,
            "must_not_reveal_early": list(self.must_not_reveal_early),
            "sources": [dict(item) for item in self.sources],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlannedCharacterProfile":
        relationship_entry_points = data.get("relationship_entry_points") or []
        first_introduction_plan = data.get("first_introduction_plan")
        return cls(
            planned_character_id=str(data.get("planned_character_id") or ""),
            status=str(data.get("status") or "planned"),
            canonical_name=str(data.get("canonical_name") or ""),
            aliases=[str(item) for item in (data.get("aliases") or [])],
            faction=str(data.get("faction") or ""),
            narrative_role=str(data.get("narrative_role") or ""),
            core_personality=[str(item) for item in (data.get("core_personality") or [])],
            surface_identity=str(data.get("surface_identity") or ""),
            hidden_pressure=[str(item) for item in (data.get("hidden_pressure") or [])],
            ability_scope=[str(item) for item in (data.get("ability_scope") or [])],
            ability_limits=[str(item) for item in (data.get("ability_limits") or [])],
            relationship_entry_points=[
                PlannedRelationshipEntry.from_dict(item)
                for item in relationship_entry_points
                if isinstance(item, dict)
            ],
            first_introduction_plan=FirstIntroductionPlan.from_dict(first_introduction_plan)
            if isinstance(first_introduction_plan, dict)
            else None,
            must_not_reveal_early=[str(item) for item in (data.get("must_not_reveal_early") or [])],
            sources=[
                {str(key): str(value) for key, value in item.items()}
                for item in (data.get("sources") or [])
                if isinstance(item, dict)
            ],
        )


@dataclass(slots=True)
class CastPlanBinding:
    planned_character_id: str
    slot_id: str

    def __post_init__(self) -> None:
        self.planned_character_id = _normalize_text(self.planned_character_id)
        self.slot_id = _normalize_text(self.slot_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CharacterCastPlan:
    cast_plan_id: str
    book_id: str
    depends_on: dict[str, str] = field(default_factory=dict)
    planned_characters: list[CastPlanBinding] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    must_not_consume: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cast_plan_id = _normalize_text(self.cast_plan_id)
        self.book_id = _normalize_text(self.book_id)
        self.depends_on = {str(key): _normalize_text(value) for key, value in self.depends_on.items()}
        self.open_questions = _normalize_string_list(self.open_questions)
        self.must_not_consume = _normalize_string_list(self.must_not_consume)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cast_plan_id": self.cast_plan_id,
            "book_id": self.book_id,
            "depends_on": dict(self.depends_on),
            "planned_characters": [item.to_dict() for item in self.planned_characters],
            "open_questions": list(self.open_questions),
            "must_not_consume": list(self.must_not_consume),
        }


@dataclass(slots=True)
class CharacterIntroductionItem:
    planned_character_id: str
    batch_id: str
    chapter_id: str
    required_scene_function: str
    required_relationship_effect: str = ""
    forbidden_moves: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.planned_character_id = _normalize_text(self.planned_character_id)
        self.batch_id = _normalize_text(self.batch_id)
        self.chapter_id = _normalize_text(self.chapter_id)
        self.required_scene_function = _normalize_text(self.required_scene_function)
        self.required_relationship_effect = _normalize_text(self.required_relationship_effect)
        self.forbidden_moves = _normalize_string_list(self.forbidden_moves)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterIntroductionItem":
        return cls(
            planned_character_id=str(data.get("planned_character_id") or ""),
            batch_id=str(data.get("batch_id") or ""),
            chapter_id=str(data.get("chapter_id") or ""),
            required_scene_function=str(data.get("required_scene_function") or ""),
            required_relationship_effect=str(data.get("required_relationship_effect") or ""),
            forbidden_moves=[str(item) for item in (data.get("forbidden_moves") or [])],
        )


@dataclass(slots=True)
class CharacterIntroductionPlan:
    introduction_items: list[CharacterIntroductionItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"introduction_items": [item.to_dict() for item in self.introduction_items]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterIntroductionPlan":
        raw_items = data.get("introduction_items") or []
        return cls(
            introduction_items=[
                CharacterIntroductionItem.from_dict(item) for item in raw_items if isinstance(item, dict)
            ]
        )


@dataclass(slots=True)
class PlanningReviewCheckpoint:
    review_stage: str
    status: str
    artifact_name: str
    artifact_path: str
    message: str
    depends_on_freeze: str = ""
    next_freeze_stage: str = ""

    def __post_init__(self) -> None:
        self.review_stage = _normalize_text(self.review_stage)
        self.status = _normalize_text(self.status)
        self.artifact_name = _normalize_text(self.artifact_name)
        self.artifact_path = _normalize_text(self.artifact_path)
        self.message = _normalize_text(self.message)
        self.depends_on_freeze = _normalize_text(self.depends_on_freeze)
        self.next_freeze_stage = _normalize_text(self.next_freeze_stage)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
