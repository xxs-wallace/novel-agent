from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...runs.writer import RunWriter
from ..prompts.writer_planning_prompt import (
    build_batch_plan_prompt,
    build_book_continuation_plan_prompt,
    build_chapter_package_prompt,
    build_character_cast_prompt,
    build_world_expansion_prompt,
)
from ..repos.assets_repo import AssetsRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..repos.documents_repo import DocumentsRepo
from ..schemas.orchestration_schema import (
    EVIDENCE_LEVEL_ALIASES,
    EVIDENCE_LEVELS,
    BatchPlan,
    BookContinuationPlan,
    ChapterBrief,
    ChapterLengthBudget,
    ChapterLengthPlan,
    ChapterPackage,
    ChapterStructureHint,
    ContinuationIntent,
    EvidenceItem,
    FreezeRecord,
    ModelingCheckItem,
    ModelingStatus,
    OutlineResearchQuestionSet,
    OutlineSeedPacket,
    PlanningFact,
    PlanningNotebook,
    RelationshipTarget,
    ResearchBudget,
    SufficiencyDecision,
    TraceableSource,
    WorldConstraintRule,
    WorldExpansionPack,
)
from ..services.character_mention_service import CharacterMentionService
from ..services.outline_research_service import (
    CharacterMentionExtractor,
    CharacterMentionResolver,
    HeuristicOutlineResearchModelAdapter,
    ModelOutlineResearchModelAdapter,
    OutlineResearchContextBroker,
    OutlineResearchLoopController,
    OutlineResearchModelAdapter,
    OutlineResearchRunResult,
    OutlineSeedPacketBuilder,
)
from .writer_planning_types import (
    CastPlanBinding,
    CharacterCastPlan,
    CharacterCastRequest,
    CharacterCastRequirement,
    CharacterIntroductionPlan,
    CharacterRequirementReport,
    CharacterSeedInput,
    IntroductionWindow,
    NamedNewCharacter,
    PlannedCharacterProfile,
    PlanningReviewCheckpoint,
    ResolvedCharacterRef,
    UnfilledRoleSlot,
)


CREATIVE_KB_TABLES = ("fragment_cards", "fragment_clusters")
FREEZE_A_ARTIFACTS = (
    "book_continuation_plan.json",
    "world_expansion_pack.json",
    "character_requirement_report.json",
    "character_cast_request.json",
    "character_cast_plan.json",
    "planned_character_profiles.json",
    "character_introduction_plan.json",
)
REVIEW_BUNDLE_NAME = "run_dir"


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_string_list(items: list[object] | tuple[object, ...] | set[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _append_unique(items: list[str], value: str) -> list[str]:
    text = _normalize_text(value)
    if text and text not in items:
        items.append(text)
    return items


@dataclass(slots=True)
class FreezeABundle:
    modeling_status: ModelingStatus
    continuation_intent: ContinuationIntent
    book_continuation_plan: BookContinuationPlan
    world_expansion_pack: WorldExpansionPack
    character_requirement_report: CharacterRequirementReport
    character_cast_request: CharacterCastRequest | None = None
    planned_character_profiles: list[PlannedCharacterProfile] = field(default_factory=list)
    character_cast_plan: CharacterCastPlan | None = None
    character_introduction_plan: CharacterIntroductionPlan | None = None


class WriterLayeredGenerationOrchestrator:
    def __init__(
        self,
        *,
        repo_root: Path,
        run_writer: RunWriter,
        model_client: Any | None = None,
        documents_repo: DocumentsRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        assets_repo: AssetsRepo | None = None,
        mention_service: CharacterMentionService | None = None,
        outline_research_adapter: OutlineResearchModelAdapter | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.run_writer = run_writer
        self.model_client = model_client
        self.documents_repo = documents_repo or DocumentsRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.assets_repo = assets_repo or AssetsRepo()
        self.mention_service = mention_service or CharacterMentionService()
        self.character_mention_extractor = CharacterMentionExtractor(self.mention_service)
        self.character_mention_resolver = CharacterMentionResolver(self.character_profiles_repo)
        self.outline_seed_builder = OutlineSeedPacketBuilder(
            repo_root=repo_root,
            assets_repo=self.assets_repo,
            character_profiles_repo=self.character_profiles_repo,
            documents_repo=self.documents_repo,
        )
        self.outline_research_controller = OutlineResearchLoopController(
            broker=OutlineResearchContextBroker(
                repo_root=repo_root,
                assets_repo=self.assets_repo,
                character_profiles_repo=self.character_profiles_repo,
            ),
            model_adapter=outline_research_adapter
            or ModelOutlineResearchModelAdapter(model_client=model_client),
        )

    def check_modeling_status(self, conn: sqlite3.Connection, *, book_id: str) -> ModelingStatus:
        checks: list[ModelingCheckItem] = []
        missing_steps: list[str] = []
        sources: list[TraceableSource] = []

        document_count = self.documents_repo.count_by_book(conn, book_id=book_id)
        documents_ready = document_count > 0
        if not documents_ready:
            missing_steps.append("documents.not_indexed")
        checks.append(
            ModelingCheckItem(
                name="documents_index",
                ready=documents_ready,
                detail=f"documents={document_count}",
                source_paths=["sqlite:documents"],
            )
        )

        profile_rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        profiles_ready = bool(profile_rows)
        if not profiles_ready:
            missing_steps.append("memory.character_profiles")
        checks.append(
            ModelingCheckItem(
                name="character_profiles",
                ready=profiles_ready,
                detail=f"profiles={len(profile_rows)}",
                source_paths=["sqlite:character_profiles"],
            )
        )

        assets = self.assets_repo.get(conn, book_id=book_id)
        outline_path = self._resolve_asset_path(assets, "outline_markdown_path")
        world_summary_path = self._resolve_asset_path(assets, "world_summary_path")

        outline_ready = outline_path is not None and outline_path.exists() and bool(
            outline_path.read_text(encoding="utf-8", errors="replace").strip()
        )
        if not outline_ready:
            missing_steps.append("memory.story_outline")
        checks.append(
            ModelingCheckItem(
                name="story_outline",
                ready=outline_ready,
                detail=str(outline_path) if outline_path else "missing",
                source_paths=[str(outline_path)] if outline_path else [],
            )
        )
        if outline_path is not None:
            sources.append(
                TraceableSource(
                    type="outline",
                    path=str(outline_path),
                    evidence_level="structured_state",
                )
            )

        world_ready = world_summary_path is not None and world_summary_path.exists() and bool(
            world_summary_path.read_text(encoding="utf-8", errors="replace").strip()
        )
        if not world_ready:
            missing_steps.append("memory.world_summary")
        checks.append(
            ModelingCheckItem(
                name="world_summary",
                ready=world_ready,
                detail=str(world_summary_path) if world_summary_path else "missing",
                source_paths=[str(world_summary_path)] if world_summary_path else [],
            )
        )
        if world_summary_path is not None:
            sources.append(
                TraceableSource(
                    type="world_summary",
                    path=str(world_summary_path),
                    evidence_level="structured_state",
                )
            )

        creative_kb_ready = self._creative_kb_ready(conn)
        if not creative_kb_ready:
            missing_steps.append("creative_kb.fragment_cards")
        checks.append(
            ModelingCheckItem(
                name="creative_kb",
                ready=creative_kb_ready,
                detail="fragment_cards available" if creative_kb_ready else "missing fragment_cards data",
                source_paths=["sqlite:fragment_cards", "sqlite:fragment_clusters"],
            )
        )

        source_arc_path = self.repo_root / ".memory" / "arcs" / f"{book_id}.source_arc_map.json"
        source_arc_ready = source_arc_path.exists() and bool(
            source_arc_path.read_text(encoding="utf-8", errors="replace").strip()
        )
        checks.append(
            ModelingCheckItem(
                name="source_arc_map",
                ready=source_arc_ready,
                detail=str(source_arc_path) if source_arc_ready else "missing optional SourceArcMap",
                source_paths=[str(source_arc_path)] if source_arc_ready else [],
            )
        )
        if source_arc_ready:
            sources.append(
                TraceableSource(
                    type="source_arc_map",
                    path=str(source_arc_path),
                    evidence_level="structured_state",
                )
            )

        structure_pattern_paths = self._structure_pattern_paths(book_id)
        ready_pattern_paths = [
            path
            for path in structure_pattern_paths
            if path.exists() and bool(path.read_text(encoding="utf-8", errors="replace").strip())
        ]
        checks.append(
            ModelingCheckItem(
                name="narrative_structure_patterns",
                ready=bool(ready_pattern_paths),
                detail=(
                    f"patterns={len(ready_pattern_paths)}"
                    if ready_pattern_paths
                    else "missing optional NarrativeStructurePattern / ArcPatternCard artifacts"
                ),
                source_paths=[str(path) for path in ready_pattern_paths],
            )
        )
        for path in ready_pattern_paths:
            sources.append(
                TraceableSource(
                    type="narrative_structure_pattern",
                    path=str(path),
                    evidence_level="structured_state",
                )
            )

        required_check_names = {
            "documents_index",
            "character_profiles",
            "story_outline",
            "world_summary",
            "creative_kb",
        }
        ready_for_continuation = all(item.ready for item in checks if item.name in required_check_names)
        return ModelingStatus(
            book_id=book_id,
            ready_for_continuation=ready_for_continuation,
            checks=checks,
            missing_modeling_steps=missing_steps,
            sources=sources,
        )

    def _structure_pattern_paths(self, book_id: str) -> list[Path]:
        structure_dir = self.repo_root / ".memory" / "structure_patterns"
        arcs_dir = self.repo_root / ".memory" / "arcs"
        return [
            structure_dir / f"{book_id}.narrative_structure_patterns.json",
            structure_dir / f"{book_id}.arc_pattern_cards.json",
            arcs_dir / f"{book_id}.narrative_structure_patterns.json",
            arcs_dir / f"{book_id}.arc_pattern_cards.json",
        ]

    def build_continuation_intent(self, payload: Mapping[str, Any]) -> ContinuationIntent:
        raw_major_characters = [str(item) for item in (payload.get("major_characters") or [])]
        raw_text = "\n".join(
            [
                *raw_major_characters,
                *[str(item) for item in (payload.get("desired_actions") or [])],
                str(payload.get("preferred_outcome") or ""),
            ]
        )
        _ = raw_text
        character_candidates = self.mention_service.clean_names(raw_major_characters)
        major_characters: list[str] = []
        for _, candidate in sorted(enumerate(character_candidates), key=lambda item: (-len(item[1]), item[0])):
            if any(len(existing) > len(candidate) and candidate in existing for existing in major_characters):
                continue
            major_characters.append(candidate)
        return ContinuationIntent(
            major_characters=major_characters,
            desired_actions=[str(item) for item in (payload.get("desired_actions") or [])],
            avoidances=[str(item) for item in (payload.get("avoidances") or [])],
            preferred_outcome=str(payload.get("preferred_outcome") or ""),
            notes=str(payload.get("notes") or ""),
            story_scale=self._normalize_story_scale(payload.get("story_scale")),
            climax_plan=self._normalize_climax_plan(payload.get("climax_plan")),
            sources=[
                TraceableSource(
                    type="user_input",
                    path="interactive:continuation_intent",
                    evidence_level="structured_state",
                    snippet=_normalize_text(raw_text)[:400],
                )
            ],
        )

    @staticmethod
    def _normalize_story_scale(value: object) -> dict[str, Any]:
        source = value if isinstance(value, Mapping) else {}
        target_chapter_count = int(source.get("target_chapter_count") or 0)
        target_total_chars = int(source.get("target_total_chars") or 0)
        default_chapter_target_chars = int(source.get("default_chapter_target_chars") or 0)
        if target_chapter_count > 0 and target_total_chars > 0 and default_chapter_target_chars <= 0:
            default_chapter_target_chars = max(1, target_total_chars // target_chapter_count)
        if target_chapter_count > 0 and default_chapter_target_chars > 0 and target_total_chars <= 0:
            target_total_chars = target_chapter_count * default_chapter_target_chars
        return {
            "target_chapter_count": max(0, target_chapter_count),
            "target_total_chars": max(0, target_total_chars),
            "default_chapter_target_chars": max(0, default_chapter_target_chars),
            "pacing_profile": str(source.get("pacing_profile") or ""),
            "length_distribution_notes": str(source.get("length_distribution_notes") or ""),
        }

    @staticmethod
    def _normalize_climax_plan(value: object) -> dict[str, Any]:
        source = value if isinstance(value, Mapping) else {}
        return {
            "conflict_climax": str(source.get("conflict_climax") or ""),
            "emotional_climax": str(source.get("emotional_climax") or ""),
            "target_chapter_index": int(source.get("target_chapter_index") or 0),
            "must_foreshadow": [str(item) for item in (source.get("must_foreshadow") or [])],
            "must_not_resolve_before": [str(item) for item in (source.get("must_not_resolve_before") or [])],
            "payoff_expectation": str(source.get("payoff_expectation") or ""),
        }

    @staticmethod
    def _fallback_chapter_outline_slots(
        *,
        count: int,
        default_chars: int,
        highlights: list[str],
        climax_plan: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        target_index = int(climax_plan.get("target_chapter_index") or 0)
        slots: list[dict[str, Any]] = []
        for index in range(1, max(1, count) + 1):
            if target_index and index == target_index:
                plot_function = "承接前文铺垫并推进到阶段高潮"
            elif index == 1:
                plot_function = "承接上文并建立本轮续写目标"
            elif index == count:
                plot_function = "阶段收束并保留下一轮钩子"
            else:
                plot_function = highlights[min(index - 1, len(highlights) - 1)] if highlights else "推进阶段目标"
            slots.append(
                {
                    "chapter_index": index,
                    "target_chars": max(1, default_chars),
                    "plot_function": plot_function,
                    "setup_targets": list(climax_plan.get("must_foreshadow") or []) if index < (target_index or count) else [],
                    "payoff_targets": [str(climax_plan.get("payoff_expectation") or "")]
                    if target_index and index == target_index and climax_plan.get("payoff_expectation")
                    else [],
                    "must_not_consume": list(climax_plan.get("must_not_resolve_before") or []),
                }
            )
        return slots

    def prepare_freeze_a(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        intent_payload: Mapping[str, Any],
        user_world_notes: str = "",
        character_seed_payloads: list[Mapping[str, Any]] | None = None,
        roster_hint_payloads: list[Mapping[str, Any]] | None = None,
        auto_confirm: bool = False,
    ) -> dict[str, Any]:
        modeling_status = self.check_modeling_status(conn, book_id=book_id)
        self.run_writer.write_json(run_id, "modeling_status.json", modeling_status)
        if not modeling_status.ready_for_continuation:
            raise ValueError(
                "建模状态未满足续写要求: " + ", ".join(modeling_status.missing_modeling_steps)
            )

        intent = self.build_continuation_intent(intent_payload)
        self.run_writer.write_json(run_id, "continuation_intent.json", intent)
        research = self.prepare_outline_research(
            conn,
            run_id=run_id,
            book_id=book_id,
            intent=intent,
            intent_payload=intent_payload,
            confirmed_new_character_names=[
                str(item.get("display_name_hint") or "")
                for item in (character_seed_payloads or [])
                if isinstance(item, Mapping)
            ],
            budget=ResearchBudget(),
        )
        if research.sufficiency_decision.status in {"needs_user_input", "blocked"}:
            return self._outline_research_wait_payload(run_id=run_id, research=research)

        book_plan = self._plan_book_continuation_after_research(
            conn,
            book_id=book_id,
            intent=intent,
            planning_notebook=research.planning_notebook,
            sufficiency_decision=research.sufficiency_decision,
        )
        world_pack = self.plan_world_expansion(
            conn,
            book_id=book_id,
            intent=intent,
            book_plan=book_plan,
            user_world_notes=user_world_notes,
        )
        requirement_report = self._analyze_character_requirements_after_research(
            conn,
            book_id=book_id,
            intent=intent,
            book_plan=book_plan,
            character_resolutions=research.seed_packet.character_resolutions,
        )
        seeds = [
            CharacterSeedInput.from_dict(dict(item))
            for item in (character_seed_payloads or [])
            if isinstance(item, Mapping)
        ]
        roster_hints = [dict(item) for item in (roster_hint_payloads or []) if isinstance(item, Mapping)]
        cast_request = self.build_character_cast_request(
            requirement_report=requirement_report,
            character_seeds=seeds,
            roster_hints=roster_hints,
        )
        allow_character_cast = bool(intent_payload.get("allow_character_cast", True))

        planned_character_profiles: list[PlannedCharacterProfile] = []
        character_cast_plan: CharacterCastPlan | None = None
        character_introduction_plan: CharacterIntroductionPlan | None = None
        if allow_character_cast and cast_request is not None and cast_request.requirements:
            planned_character_profiles, character_cast_plan, character_introduction_plan = self.plan_character_cast(
                book_id=book_id,
                intent=intent,
                book_plan=book_plan,
                world_pack=world_pack,
                requirement_report=requirement_report,
                cast_request=cast_request,
                character_seeds=seeds,
            )

        self.run_writer.write_json(run_id, "book_continuation_plan.json", book_plan)
        self.run_writer.write_json(run_id, "world_expansion_pack.json", world_pack)
        self.run_writer.write_json(run_id, "character_requirement_report.json", requirement_report)
        if cast_request is not None:
            self.run_writer.write_json(run_id, "character_cast_request.json", cast_request)
        if planned_character_profiles:
            self.run_writer.write_json(run_id, "planned_character_profiles.json", planned_character_profiles)
        if character_cast_plan is not None:
            self.run_writer.write_json(run_id, "character_cast_plan.json", character_cast_plan)
        if character_introduction_plan is not None:
            self.run_writer.write_json(run_id, "character_introduction_plan.json", character_introduction_plan)

        run_dir = self.run_writer.layout.run_dir(run_id)
        checkpoint = PlanningReviewCheckpoint(
            review_stage="freeze_a_review",
            status="needs_review",
            artifact_name=REVIEW_BUNDLE_NAME,
            artifact_path=str(run_dir / "book_continuation_plan.json"),
            message="请审阅全书规划、世界观补全与人物补充文件，确认后进入 Freeze A。",
            next_freeze_stage="freeze_a",
        )
        self.run_writer.write_json(run_id, "freeze_a_review_checkpoint.json", checkpoint)

        bundle = FreezeABundle(
            modeling_status=modeling_status,
            continuation_intent=intent,
            book_continuation_plan=book_plan,
            world_expansion_pack=world_pack,
            character_requirement_report=requirement_report,
            character_cast_request=cast_request,
            planned_character_profiles=planned_character_profiles,
            character_cast_plan=character_cast_plan,
            character_introduction_plan=character_introduction_plan,
        )
        if auto_confirm:
            self.confirm_freeze_a(run_id=run_id)
        return self._freeze_a_bundle_to_dict(bundle)

    def prepare_outline_research(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        intent: ContinuationIntent,
        intent_payload: Mapping[str, Any],
        budget: ResearchBudget | None = None,
        notebook: PlanningNotebook | None = None,
        user_answers: Mapping[str, str] | None = None,
        confirmed_new_character_names: Sequence[str] | None = None,
    ) -> OutlineResearchRunResult:
        mentions = self.character_mention_extractor.extract(intent_payload)
        confirmations = {
            name: True for name in (confirmed_new_character_names or []) if str(name).strip()
        }
        if isinstance(intent_payload.get("user_new_character_confirmations"), Mapping):
            confirmations.update(
                {
                    str(key): bool(value)
                    for key, value in (intent_payload.get("user_new_character_confirmations") or {}).items()
                }
            )
        resolutions = self.character_mention_resolver.resolve(
            conn,
            book_id=book_id,
            mentions=mentions,
            user_new_character_confirmations=confirmations,
        )
        seed_packet = self.outline_seed_builder.build(
            conn,
            book_id=book_id,
            intent=intent,
            mentions=mentions,
            resolutions=resolutions,
        )
        result = self.outline_research_controller.run(
            conn,
            book_id=book_id,
            seed_packet=seed_packet,
            budget=budget or ResearchBudget(),
            notebook=notebook,
            user_answers=user_answers,
        )
        self._write_outline_research_artifacts(run_id=run_id, result=result)
        return result

    def continue_outline_research_with_user_input(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        user_answers: Mapping[str, str],
        user_world_notes: str = "",
        character_seed_payloads: list[Mapping[str, Any]] | None = None,
        roster_hint_payloads: list[Mapping[str, Any]] | None = None,
        auto_confirm: bool = False,
    ) -> dict[str, Any]:
        intent_payload = self._load_run_json(run_id, "continuation_intent.json")
        intent = self._continuation_intent_from_dict(intent_payload)
        seed_payload = self._load_run_json(run_id, "outline_seed_packet.json")
        notebook_payload = self._load_run_json(run_id, "planning_notebook.json")
        seed_packet = OutlineSeedPacket.from_dict(seed_payload)
        notebook = PlanningNotebook.from_dict(notebook_payload)
        research = self.outline_research_controller.run(
            conn,
            book_id=book_id,
            seed_packet=seed_packet,
            budget=ResearchBudget(max_rounds=1, max_requests_per_round=3, max_total_requests=3),
            notebook=notebook,
            user_answers=user_answers,
        )
        self._write_outline_research_artifacts(run_id=run_id, result=research)
        if research.sufficiency_decision.status in {"needs_user_input", "blocked"}:
            return self._outline_research_wait_payload(run_id=run_id, research=research)
        return self._prepare_freeze_a_from_research(
            conn,
            run_id=run_id,
            book_id=book_id,
            intent=intent,
            research=research,
            user_world_notes=user_world_notes,
            character_seed_payloads=character_seed_payloads,
            roster_hint_payloads=roster_hint_payloads,
            auto_confirm=auto_confirm,
        )

    def _prepare_freeze_a_from_research(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        intent: ContinuationIntent,
        research: OutlineResearchRunResult,
        user_world_notes: str = "",
        character_seed_payloads: list[Mapping[str, Any]] | None = None,
        roster_hint_payloads: list[Mapping[str, Any]] | None = None,
        auto_confirm: bool = False,
    ) -> dict[str, Any]:
        modeling_status = self.check_modeling_status(conn, book_id=book_id)
        self.run_writer.write_json(run_id, "modeling_status.json", modeling_status)
        if not modeling_status.ready_for_continuation:
            raise ValueError(
                "建模状态未满足续写要求: " + ", ".join(modeling_status.missing_modeling_steps)
            )
        book_plan = self._plan_book_continuation_after_research(
            conn,
            book_id=book_id,
            intent=intent,
            planning_notebook=research.planning_notebook,
            sufficiency_decision=research.sufficiency_decision,
        )
        world_pack = self.plan_world_expansion(
            conn,
            book_id=book_id,
            intent=intent,
            book_plan=book_plan,
            user_world_notes=user_world_notes,
        )
        requirement_report = self._analyze_character_requirements_after_research(
            conn,
            book_id=book_id,
            intent=intent,
            book_plan=book_plan,
            character_resolutions=research.seed_packet.character_resolutions,
        )
        seeds = [
            CharacterSeedInput.from_dict(dict(item))
            for item in (character_seed_payloads or [])
            if isinstance(item, Mapping)
        ]
        roster_hints = [dict(item) for item in (roster_hint_payloads or []) if isinstance(item, Mapping)]
        cast_request = self.build_character_cast_request(
            requirement_report=requirement_report,
            character_seeds=seeds,
            roster_hints=roster_hints,
        )
        planned_character_profiles: list[PlannedCharacterProfile] = []
        character_cast_plan: CharacterCastPlan | None = None
        character_introduction_plan: CharacterIntroductionPlan | None = None
        if cast_request is not None and cast_request.requirements:
            planned_character_profiles, character_cast_plan, character_introduction_plan = self.plan_character_cast(
                book_id=book_id,
                intent=intent,
                book_plan=book_plan,
                world_pack=world_pack,
                requirement_report=requirement_report,
                cast_request=cast_request,
                character_seeds=seeds,
            )

        self.run_writer.write_json(run_id, "book_continuation_plan.json", book_plan)
        self.run_writer.write_json(run_id, "world_expansion_pack.json", world_pack)
        self.run_writer.write_json(run_id, "character_requirement_report.json", requirement_report)
        if cast_request is not None:
            self.run_writer.write_json(run_id, "character_cast_request.json", cast_request)
        if planned_character_profiles:
            self.run_writer.write_json(run_id, "planned_character_profiles.json", planned_character_profiles)
        if character_cast_plan is not None:
            self.run_writer.write_json(run_id, "character_cast_plan.json", character_cast_plan)
        if character_introduction_plan is not None:
            self.run_writer.write_json(run_id, "character_introduction_plan.json", character_introduction_plan)
        run_dir = self.run_writer.layout.run_dir(run_id)
        checkpoint = PlanningReviewCheckpoint(
            review_stage="freeze_a_review",
            status="needs_review",
            artifact_name=REVIEW_BUNDLE_NAME,
            artifact_path=str(run_dir / "book_continuation_plan.json"),
            message="请审阅全书规划、世界观补全与人物补充文件，确认后进入 Freeze A。",
            next_freeze_stage="freeze_a",
        )
        self.run_writer.write_json(run_id, "freeze_a_review_checkpoint.json", checkpoint)
        bundle = FreezeABundle(
            modeling_status=modeling_status,
            continuation_intent=intent,
            book_continuation_plan=book_plan,
            world_expansion_pack=world_pack,
            character_requirement_report=requirement_report,
            character_cast_request=cast_request,
            planned_character_profiles=planned_character_profiles,
            character_cast_plan=character_cast_plan,
            character_introduction_plan=character_introduction_plan,
        )
        if auto_confirm:
            self.confirm_freeze_a(run_id=run_id)
        return self._freeze_a_bundle_to_dict(bundle)

    def _plan_book_continuation_after_research(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        intent: ContinuationIntent,
        planning_notebook: PlanningNotebook,
        sufficiency_decision: SufficiencyDecision,
    ) -> BookContinuationPlan:
        try:
            return self.plan_book_continuation(
                conn,
                book_id=book_id,
                intent=intent,
                planning_notebook=planning_notebook,
                sufficiency_decision=sufficiency_decision,
            )
        except TypeError:
            return self.plan_book_continuation(conn, book_id=book_id, intent=intent)

    def _analyze_character_requirements_after_research(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        intent: ContinuationIntent,
        book_plan: BookContinuationPlan,
        character_resolutions: Sequence[Any],
    ) -> CharacterRequirementReport:
        try:
            return self.analyze_character_requirements(
                conn,
                book_id=book_id,
                intent=intent,
                book_plan=book_plan,
                character_resolutions=character_resolutions,
            )
        except TypeError:
            return self.analyze_character_requirements(
                conn,
                book_id=book_id,
                intent=intent,
                book_plan=book_plan,
            )

    def _write_outline_research_artifacts(self, *, run_id: str, result: OutlineResearchRunResult) -> None:
        self.run_writer.write_json(run_id, "outline_seed_packet.json", result.seed_packet)
        self.run_writer.write_json(
            run_id,
            "extracted_character_mentions.json",
            {"mentions": [item.to_dict() for item in result.seed_packet.extracted_character_mentions]},
        )
        self.run_writer.write_json(
            run_id,
            "character_resolution.json",
            {"resolutions": [item.to_dict() for item in result.seed_packet.character_resolutions]},
        )
        self.run_writer.write_json(run_id, "outline_research_trace.json", result.trace)
        self.run_writer.write_json(run_id, "memory_query_trace.json", {"items": result.memory_query_trace})
        self.run_writer.write_json(run_id, "memory_query_decision_log.json", {"items": result.memory_query_decision_log})
        self.run_writer.write_json(run_id, "model_reasoning_debug.json", {"items": result.model_reasoning_debug})
        self.run_writer.write_json(run_id, "planning_notebook.json", result.planning_notebook)
        self.run_writer.write_json(run_id, "sufficiency_decision.json", result.sufficiency_decision)
        self.run_writer.write_json(run_id, "generated_outline.json", dict(result.generated_outline))

    def _outline_research_wait_payload(self, *, run_id: str, research: OutlineResearchRunResult) -> dict[str, Any]:
        run_dir = self.run_writer.layout.run_dir(run_id)
        stage = (
            "outline_research_user_input"
            if research.sufficiency_decision.status == "needs_user_input"
            else "outline_research_blocked"
        )
        checkpoint = PlanningReviewCheckpoint(
            review_stage=stage,
            status=research.sufficiency_decision.status,
            artifact_name="sufficiency_decision.json",
            artifact_path=str(run_dir / "sufficiency_decision.json"),
            message="大纲研究需要补充信息后才能继续。" if stage == "outline_research_user_input" else "前置建模不足，暂不生成正式全书规划。",
            next_freeze_stage="freeze_a",
        )
        self.run_writer.write_json(run_id, "outline_research_checkpoint.json", checkpoint)
        payload = {
            "status": research.sufficiency_decision.status,
            "stage": stage,
            "checkpoint": checkpoint.to_dict(),
            "outline_seed_packet": research.seed_packet.to_dict(),
            "planning_notebook": research.planning_notebook.to_dict(),
            "sufficiency_decision": research.sufficiency_decision.to_dict(),
        }
        if stage == "outline_research_user_input":
            question_set = self._build_outline_research_question_set(run_id=run_id, research=research)
            self.run_writer.write_outline_research_question_set(run_id, question_set)
            payload["question_set"] = question_set.to_dict()
        return payload

    def _build_outline_research_question_set(
        self,
        *,
        run_id: str,
        research: OutlineResearchRunResult,
    ) -> OutlineResearchQuestionSet:
        run_dir = self.run_writer.layout.run_dir(run_id)
        return OutlineResearchQuestionSet.from_sufficiency_decision(
            run_id=run_id,
            decision=research.sufficiency_decision,
            source_artifact_id=f"writer:{run_id}:sufficiency-decision",
            artifact_path=str(run_dir / "outline_research_question_set.json"),
        )

    def confirm_freeze_a(self, *, run_id: str, artifact_overrides: Mapping[str, str] | None = None) -> dict[str, str]:
        artifact_names = [
            "book_continuation_plan.json",
            "world_expansion_pack.json",
            "character_requirement_report.json",
            "character_cast_request.json",
            "character_cast_plan.json",
            "planned_character_profiles.json",
            "character_introduction_plan.json",
        ]
        payloads = self._load_artifact_payloads(run_id, artifact_names, artifact_overrides)
        frozen_payloads = {
            name: payload
            for name, payload in payloads.items()
            if payload is not None and name in FREEZE_A_ARTIFACTS
        }
        return self.run_writer.write_freeze_record(
            run_id,
            FreezeRecord(
                freeze_stage="freeze_a",
                summary="BookContinuationPlan + WorldExpansionPack + CharacterCastPlan 已确认冻结。",
            ),
            artifact_payloads=frozen_payloads,
        )

    def prepare_batch_plan(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        target_chapter_count: int = 3,
        auto_confirm: bool = False,
    ) -> dict[str, Any]:
        self._require_freeze(run_id, "freeze_a")
        book_plan = self._load_book_plan_from_frozen_artifact(run_id, "freeze_a", "book_continuation_plan.json")
        world_pack = self._load_world_pack_from_frozen_artifact(run_id, "freeze_a", "world_expansion_pack.json")
        cast_plan = self._load_optional_json_from_frozen_artifact(run_id, "freeze_a", "character_cast_plan.json")

        batch_plan = self.plan_batch(
            conn,
            book_id=book_id,
            book_plan=book_plan,
            world_pack=world_pack,
            character_cast_plan=cast_plan,
            target_chapter_count=target_chapter_count,
        )
        batch_plan_path = self.run_writer.write_json(run_id, "batch_plan.json", batch_plan)
        checkpoint = PlanningReviewCheckpoint(
            review_stage="batch_plan_review",
            status="needs_review",
            artifact_name="batch_plan.json",
            artifact_path=str(batch_plan_path),
            message="请审阅并可修改 batch_plan.json，确认后继续进入 Freeze B。",
            depends_on_freeze="freeze_a",
            next_freeze_stage="freeze_b",
        )
        self.run_writer.write_json(run_id, "batch_review_checkpoint.json", checkpoint)
        if auto_confirm:
            self.confirm_batch_plan(run_id=run_id)
        return {
            "batch_plan": batch_plan.to_dict(),
            "review_checkpoint": checkpoint.to_dict(),
        }

    def confirm_batch_plan(self, *, run_id: str, artifact_path: str | None = None) -> dict[str, str]:
        payload = self._load_json_data(Path(artifact_path)) if artifact_path else self._load_run_json(run_id, "batch_plan.json")
        return self.run_writer.write_freeze_record(
            run_id,
            FreezeRecord(
                freeze_stage="freeze_b",
                summary="BatchPlan 已审阅确认。",
                depends_on=["freeze_a"],
            ),
            artifact_payloads={"batch_plan.json": payload},
        )

    def prepare_chapter_package(
        self,
        *,
        run_id: str,
        book_id: str,
        chapter_count: int = 3,
        auto_confirm: bool = False,
    ) -> dict[str, Any]:
        self._require_freeze(run_id, "freeze_b")
        batch_plan = self._load_batch_plan_from_frozen_artifact(run_id, "freeze_b", "batch_plan.json")
        introduction_plan = self._load_optional_json_from_frozen_artifact(
            run_id,
            "freeze_a",
            "character_introduction_plan.json",
        )
        story_structure_kb = self._load_doc_excerpt(
            self.repo_root / "novel_agent" / "docs" / "story_structure_knowledge_base.md"
        )
        relationship_arc_kb = self._load_doc_excerpt(
            self.repo_root / "novel_agent" / "docs" / "relationship_arc_knowledge_base.md"
        )

        chapter_package = self.plan_chapter_package(
            book_id=book_id,
            batch_plan=batch_plan,
            character_introduction_plan=introduction_plan,
            story_structure_kb=story_structure_kb,
            relationship_arc_kb=relationship_arc_kb,
            chapter_count=chapter_count,
        )
        chapter_package_path = self.run_writer.write_json(run_id, "chapter_package.json", chapter_package)
        checkpoint = PlanningReviewCheckpoint(
            review_stage="chapter_package_review",
            status="needs_review",
            artifact_name="chapter_package.json",
            artifact_path=str(chapter_package_path),
            message="请审阅并可修改 chapter_package.json，确认后继续进入 Freeze C。",
            depends_on_freeze="freeze_b",
            next_freeze_stage="freeze_c",
        )
        self.run_writer.write_json(run_id, "chapter_review_checkpoint.json", checkpoint)
        if auto_confirm:
            self.confirm_chapter_package(run_id=run_id)
        return {
            "chapter_package": chapter_package.to_dict(),
            "review_checkpoint": checkpoint.to_dict(),
        }

    def confirm_chapter_package(self, *, run_id: str, artifact_path: str | None = None) -> dict[str, str]:
        payload = (
            self._load_json_data(Path(artifact_path))
            if artifact_path
            else self._load_run_json(run_id, "chapter_package.json")
        )
        return self.run_writer.write_freeze_record(
            run_id,
            FreezeRecord(
                freeze_stage="freeze_c",
                summary="ChapterPackage 已审阅确认。",
                depends_on=["freeze_b"],
            ),
            artifact_payloads={"chapter_package.json": payload},
        )

    def prepare_chapter_length_plan(
        self,
        *,
        run_id: str,
        auto_confirm: bool = False,
    ) -> dict[str, Any]:
        self._require_freeze(run_id, "freeze_c")
        chapter_package = self._load_frozen_artifact(run_id, "freeze_c", "chapter_package.json")
        if not isinstance(chapter_package, Mapping):
            raise ValueError("frozen chapter_package.json must be an object")
        plan = self.plan_chapter_length(self._chapter_package_from_dict(chapter_package))
        plan_path = self.run_writer.write_json(run_id, "chapter_length_plan.json", plan)
        checkpoint = PlanningReviewCheckpoint(
            review_stage="chapter_length_review",
            status="needs_review",
            artifact_name="chapter_length_plan.json",
            artifact_path=str(plan_path),
            message="请审阅并可修改 chapter_length_plan.json，确认后继续进入 Freeze D。",
            depends_on_freeze="freeze_c",
            next_freeze_stage="freeze_d",
        )
        self.run_writer.write_json(run_id, "length_review_checkpoint.json", checkpoint)
        if auto_confirm:
            self.confirm_chapter_length_plan(run_id=run_id)
        return {
            "chapter_length_plan": plan.to_dict(),
            "review_checkpoint": checkpoint.to_dict(),
        }

    def confirm_chapter_length_plan(self, *, run_id: str, artifact_path: str | None = None) -> dict[str, str]:
        payload = (
            self._load_json_data(Path(artifact_path))
            if artifact_path
            else self._load_run_json(run_id, "chapter_length_plan.json")
        )
        if not isinstance(payload, Mapping):
            raise ValueError("chapter_length_plan.json must contain an object")
        plan = self._chapter_length_plan_from_dict(payload)
        path = self.run_writer.write_json(run_id, "chapter_length_plan.json", plan)
        return {"chapter_length_plan.json": str(path)}

    def plan_chapter_length(self, chapter_package: ChapterPackage) -> ChapterLengthPlan:
        source_targets = [chapter.target_word_count for chapter in chapter_package.chapters if chapter.target_word_count > 0]
        default_words = int(sum(source_targets) / len(source_targets)) if source_targets else 1200
        default_target = self._words_to_chars(default_words)
        budgets: list[ChapterLengthBudget] = []
        focus_chapter_ids: list[str] = []
        climax_chapter_ids: list[str] = []
        for index, chapter in enumerate(chapter_package.chapters):
            is_climax = self._is_climax_chapter(chapter, index=index, total=len(chapter_package.chapters))
            is_focus = is_climax or self._is_focus_chapter(chapter)
            multiplier = 1.35 if is_climax else 1.2 if is_focus else 1.0
            target_chars = max(1, int(self._words_to_chars(chapter.target_word_count) * multiplier))
            min_chars, max_chars = self._length_bounds(target_chars)
            if is_focus:
                focus_chapter_ids.append(chapter.chapter_id)
            if is_climax:
                climax_chapter_ids.append(chapter.chapter_id)
            budgets.append(
                ChapterLengthBudget(
                    chapter_id=chapter.chapter_id,
                    target_chars=target_chars,
                    min_chars=min_chars,
                    max_chars=max_chars,
                    is_focus_chapter=is_focus,
                    focus_reason=self._focus_reason(chapter, is_climax=is_climax) if is_focus else "",
                    expansion_notes=self._length_expansion_notes(chapter, is_focus=is_focus),
                    source_chapter_target_word_count=chapter.target_word_count,
                )
            )
        default_min, default_max = self._length_bounds(default_target)
        return ChapterLengthPlan(
            plan_id=f"length-plan-{chapter_package.package_id or chapter_package.batch_id}",
            batch_id=chapter_package.batch_id,
            default_target_chars=default_target,
            default_min_chars=default_min,
            default_max_chars=default_max,
            budgets=budgets,
            focus_chapter_ids=focus_chapter_ids,
            climax_chapter_ids=climax_chapter_ids,
            review_notes=["Freeze C 后生成；用户确认后作为 Freeze D 的章节长度预算。"],
            sources=[
                TraceableSource(
                    type="freeze_c",
                    path="freezes/freeze_c/chapter_package.json",
                    evidence_level="structured_state",
                )
            ],
        )

    def plan_book_continuation(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        intent: ContinuationIntent,
        planning_notebook: PlanningNotebook | None = None,
        sufficiency_decision: SufficiencyDecision | None = None,
    ) -> BookContinuationPlan:
        outline_path = self._get_required_asset_path(conn, book_id=book_id, field_name="outline_markdown_path")
        world_summary_path = self._get_required_asset_path(conn, book_id=book_id, field_name="world_summary_path")
        if planning_notebook is not None and sufficiency_decision is not None:
            outline_markdown = json.dumps(
                {
                    "planning_notebook": planning_notebook.to_dict(),
                    "sufficiency_decision": sufficiency_decision.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
            world_summary_markdown = "World details were accessed through Outline Research Loop evidence only."
        else:
            outline_markdown = outline_path.read_text(encoding="utf-8", errors="replace")
            world_summary_markdown = world_summary_path.read_text(encoding="utf-8", errors="replace")
        system_prompt, user_prompt = build_book_continuation_plan_prompt(
            book_id=book_id,
            continuation_intent=intent.to_dict(),
            outline_markdown=outline_markdown,
            world_summary_markdown=world_summary_markdown,
        )
        payload = self._generate_json_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._fallback_book_plan(
                book_id=book_id,
                intent=intent,
                outline_path=outline_path,
                world_summary_path=world_summary_path,
            ),
        )
        if not isinstance(payload, dict):
            payload = self._fallback_book_plan(
                book_id=book_id,
                intent=intent,
                outline_path=outline_path,
                world_summary_path=world_summary_path,
            )
        payload.setdefault("plan_id", f"{book_id}-book-plan")
        payload.setdefault("book_id", book_id)
        if sufficiency_decision is not None:
            existing_sources = [item for item in (payload.get("sources") or []) if isinstance(item, dict)]
            existing_sources.append(
                {
                    "type": "outline_research",
                    "path": "planning_notebook.json",
                    "evidence_level": "structured_state",
                    "snippet": sufficiency_decision.status,
                    "note": "Book plan generated after Outline Research Loop.",
                }
            )
            payload["sources"] = existing_sources
            if sufficiency_decision.status == "proceed_with_assumptions":
                payload["assumptions"] = [item.to_dict() for item in sufficiency_decision.assumptions]
                open_questions = [str(item) for item in (payload.get("open_questions") or [])]
                for gap in sufficiency_decision.optional_gaps:
                    if gap not in open_questions:
                        open_questions.append(gap)
                payload["open_questions"] = open_questions
        return self._book_plan_from_dict(payload)

    def plan_world_expansion(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        intent: ContinuationIntent,
        book_plan: BookContinuationPlan,
        user_world_notes: str,
    ) -> WorldExpansionPack:
        world_summary_path = self._get_required_asset_path(conn, book_id=book_id, field_name="world_summary_path")
        world_summary_markdown = world_summary_path.read_text(encoding="utf-8", errors="replace")
        system_prompt, user_prompt = build_world_expansion_prompt(
            book_id=book_id,
            continuation_intent=intent.to_dict(),
            book_continuation_plan=book_plan.to_dict(),
            world_summary_markdown=world_summary_markdown,
            user_world_notes=user_world_notes,
        )
        payload = self._generate_json_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._fallback_world_expansion(
                book_id=book_id,
                intent=intent,
                book_plan=book_plan,
                user_world_notes=user_world_notes,
                world_summary_path=world_summary_path,
            ),
        )
        if not isinstance(payload, dict):
            payload = self._fallback_world_expansion(
                book_id=book_id,
                intent=intent,
                book_plan=book_plan,
                user_world_notes=user_world_notes,
                world_summary_path=world_summary_path,
            )
        payload.setdefault("pack_id", f"{book_id}-world-pack")
        payload.setdefault("book_id", book_id)
        return self._world_pack_from_dict(payload)

    def analyze_character_requirements(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        intent: ContinuationIntent,
        book_plan: BookContinuationPlan,
        character_resolutions: Sequence[Any] | None = None,
    ) -> CharacterRequirementReport:
        try:
            rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        except sqlite3.OperationalError:
            rows = []
        known_name_map: dict[str, str] = {}
        for row in rows:
            canonical = _normalize_text(row["canonical_name"])
            if canonical:
                known_name_map[canonical] = canonical
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
            except json.JSONDecodeError:
                aliases = []
            for alias in aliases:
                text = _normalize_text(alias)
                if text:
                    known_name_map[text] = canonical

        raw_names = list(intent.major_characters)
        cleaned_names = self.mention_service.clean_names(raw_names)
        unconfirmed_missing_names: set[str] = set()
        confirmed_missing_names: set[str] = set()
        for resolution in character_resolutions or []:
            status = getattr(resolution, "status", "")
            name = getattr(resolution, "mention_text", "")
            if status == "missing" and getattr(resolution, "confirmed_new_character", False):
                confirmed_missing_names.add(str(name))
            elif status in {"missing", "ambiguous"}:
                unconfirmed_missing_names.add(str(name))
        named_existing: list[ResolvedCharacterRef] = []
        named_new: list[NamedNewCharacter] = []
        for name in cleaned_names:
            resolved = known_name_map.get(name)
            if resolved:
                named_existing.append(ResolvedCharacterRef(name=name, resolved_to=resolved))
            elif name not in unconfirmed_missing_names or name in confirmed_missing_names or character_resolutions is None:
                named_new.append(
                    NamedNewCharacter(
                        name=name,
                        reason="用户续写意图中显式提及，但当前 Character Memory 未命中。",
                    )
                )

        slot_inputs = [*intent.desired_actions, intent.notes, book_plan.continuation_goal, *book_plan.stage_highlights]
        role_slots = self._infer_role_slots(slot_inputs)
        return CharacterRequirementReport(
            named_existing_characters=named_existing,
            named_new_characters=named_new,
            unfilled_role_slots=role_slots,
        )

    def build_character_cast_request(
        self,
        *,
        requirement_report: CharacterRequirementReport,
        character_seeds: list[CharacterSeedInput],
        roster_hints: list[dict[str, Any]],
    ) -> CharacterCastRequest | None:
        requirements: list[CharacterCastRequirement] = []
        for index, named_new in enumerate(requirement_report.named_new_characters, start=1):
            requirements.append(
                CharacterCastRequirement(
                    slot_id=f"named-new-{index:02d}",
                    role_type="显式命名角色",
                    required_traits=["承接既有剧情功能"],
                    forbidden_traits=["喧宾夺主", "无铺垫关系跃迁"],
                    introduction_window=IntroductionWindow(batch_id="batch-01", chapter_range=["batch01-ch01", "batch01-ch03"]),
                )
            )
        for slot in requirement_report.unfilled_role_slots:
            requirements.append(
                CharacterCastRequirement(
                    slot_id=slot.slot_id,
                    faction=self._infer_faction_from_slot(slot.slot_type),
                    role_type=slot.slot_type,
                    required_traits=["服务当前批次冲突"],
                    forbidden_traits=["提前消费终局秘密"],
                    introduction_window=IntroductionWindow(batch_id="batch-01", chapter_range=["batch01-ch01", "batch01-ch03"]),
                )
            )
        for index, hint in enumerate(roster_hints, start=1):
            requirements.append(
                CharacterCastRequirement(
                    slot_id=str(hint.get("slot_id") or f"roster-hint-{index:02d}"),
                    faction=str(hint.get("faction") or ""),
                    role_type=str(hint.get("role_type") or "候选角色"),
                    count=int(hint.get("count") or 1),
                    required_traits=[str(item) for item in (hint.get("required_traits") or [])],
                    forbidden_traits=[str(item) for item in (hint.get("forbidden_traits") or [])],
                    must_connect_to=[str(item) for item in (hint.get("must_connect_to") or [])],
                    introduction_window=IntroductionWindow.from_dict(
                        dict(hint.get("introduction_window") or {})
                    ),
                )
            )
        if not requirements and not character_seeds:
            return None
        reason_parts = []
        if requirement_report.named_new_characters:
            reason_parts.append("存在显式命名新角色")
        if requirement_report.unfilled_role_slots:
            reason_parts.append("存在角色功能位缺口")
        if character_seeds:
            reason_parts.append("用户提供了角色雏形")
        return CharacterCastRequest(
            request_id="cast-request-01",
            source_layer="layer1c",
            reason="；".join(reason_parts) or "需要补充计划角色",
            requirements=requirements,
            generation_seed=42,
        )

    def plan_character_cast(
        self,
        *,
        book_id: str,
        intent: ContinuationIntent,
        book_plan: BookContinuationPlan,
        world_pack: WorldExpansionPack,
        requirement_report: CharacterRequirementReport,
        cast_request: CharacterCastRequest,
        character_seeds: list[CharacterSeedInput],
    ) -> tuple[list[PlannedCharacterProfile], CharacterCastPlan, CharacterIntroductionPlan]:
        system_prompt, user_prompt = build_character_cast_prompt(
            book_id=book_id,
            requirement_report=requirement_report.to_dict(),
            cast_request=cast_request.to_dict(),
            continuation_intent=intent.to_dict(),
            book_continuation_plan=book_plan.to_dict(),
            world_expansion_pack=world_pack.to_dict(),
            character_seeds=[item.to_dict() for item in character_seeds],
        )
        payload = self._generate_json_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._fallback_character_cast(
                book_id=book_id,
                requirement_report=requirement_report,
                cast_request=cast_request,
                character_seeds=character_seeds,
                book_plan=book_plan,
                world_pack=world_pack,
            ),
        )
        if not isinstance(payload, dict):
            payload = self._fallback_character_cast(
                book_id=book_id,
                requirement_report=requirement_report,
                cast_request=cast_request,
                character_seeds=character_seeds,
                book_plan=book_plan,
                world_pack=world_pack,
            )
        planned_profiles = [
            PlannedCharacterProfile.from_dict(item)
            for item in (payload.get("planned_character_profiles") or [])
            if isinstance(item, dict)
        ]
        cast_plan_payload = payload.get("character_cast_plan") or {}
        cast_plan = CharacterCastPlan(
            cast_plan_id=str(cast_plan_payload.get("cast_plan_id") or "cast-plan-01"),
            book_id=book_id,
            depends_on={
                "book_continuation_plan_id": book_plan.plan_id,
                "world_expansion_pack_id": world_pack.pack_id,
            },
            planned_characters=[
                CastPlanBinding(
                    planned_character_id=str(item.get("planned_character_id") or ""),
                    slot_id=str(item.get("slot_id") or ""),
                )
                for item in (cast_plan_payload.get("planned_characters") or [])
                if isinstance(item, dict)
            ],
            open_questions=[str(item) for item in (cast_plan_payload.get("open_questions") or [])],
            must_not_consume=[str(item) for item in (cast_plan_payload.get("must_not_consume") or [])],
        )
        intro_plan_payload = payload.get("character_introduction_plan") or {}
        introduction_plan = CharacterIntroductionPlan.from_dict(dict(intro_plan_payload))
        return planned_profiles, cast_plan, introduction_plan

    def plan_batch(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        book_plan: BookContinuationPlan,
        world_pack: WorldExpansionPack,
        character_cast_plan: dict[str, Any] | None,
        target_chapter_count: int,
    ) -> BatchPlan:
        system_prompt, user_prompt = build_batch_plan_prompt(
            book_id=book_id,
            book_continuation_plan=book_plan.to_dict(),
            world_expansion_pack=world_pack.to_dict(),
            character_cast_plan=character_cast_plan,
            target_chapter_count=target_chapter_count,
        )
        payload = self._generate_json_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._fallback_batch_plan(
                conn=conn,
                book_id=book_id,
                book_plan=book_plan,
                world_pack=world_pack,
                character_cast_plan=character_cast_plan,
                target_chapter_count=target_chapter_count,
            ),
        )
        if not isinstance(payload, dict):
            payload = self._fallback_batch_plan(
                conn=conn,
                book_id=book_id,
                book_plan=book_plan,
                world_pack=world_pack,
                character_cast_plan=character_cast_plan,
                target_chapter_count=target_chapter_count,
            )
        payload.setdefault("batch_id", "batch-01")
        payload.setdefault("book_id", book_id)
        effective_count = max(1, int(target_chapter_count or book_plan.target_chapter_count or 1))
        payload.setdefault("target_chapter_count", effective_count)
        payload.setdefault("target_total_chars", int(book_plan.target_total_chars or 0))
        payload.setdefault("default_chapter_target_chars", int(book_plan.default_chapter_target_chars or 0))
        if not isinstance(payload.get("chapter_outline_slots"), list) or not payload.get("chapter_outline_slots"):
            payload["chapter_outline_slots"] = [
                dict(item) for item in book_plan.chapter_outline_slots[:effective_count] if isinstance(item, Mapping)
            ]
        return self._batch_plan_from_dict(payload)

    def plan_chapter_package(
        self,
        *,
        book_id: str,
        batch_plan: BatchPlan,
        character_introduction_plan: dict[str, Any] | None,
        story_structure_kb: str,
        relationship_arc_kb: str,
        chapter_count: int,
    ) -> ChapterPackage:
        system_prompt, user_prompt = build_chapter_package_prompt(
            book_id=book_id,
            batch_plan=batch_plan.to_dict(),
            character_introduction_plan=character_introduction_plan,
            story_structure_kb=story_structure_kb,
            relationship_arc_kb=relationship_arc_kb,
            chapter_count=chapter_count,
        )
        payload = self._generate_json_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._fallback_chapter_package(
                batch_plan=batch_plan,
                character_introduction_plan=character_introduction_plan,
                chapter_count=chapter_count,
            ),
        )
        if not isinstance(payload, dict):
            payload = self._fallback_chapter_package(
                batch_plan=batch_plan,
                character_introduction_plan=character_introduction_plan,
                chapter_count=chapter_count,
            )
        if not isinstance(payload.get("chapters"), list) or len(payload.get("chapters") or []) < max(1, int(chapter_count or 1)):
            fallback_payload = self._fallback_chapter_package(
                batch_plan=batch_plan,
                character_introduction_plan=character_introduction_plan,
                chapter_count=chapter_count,
            )
            fallback_chapters = [dict(item) for item in fallback_payload.get("chapters", []) if isinstance(item, Mapping)]
            chapters = [dict(item) for item in (payload.get("chapters") or []) if isinstance(item, Mapping)]
            chapters.extend(fallback_chapters[len(chapters) : max(1, int(chapter_count or 1))])
            payload["chapters"] = chapters
        payload.setdefault("package_id", f"{batch_plan.batch_id}-package")
        payload.setdefault("batch_id", batch_plan.batch_id)
        payload = self._constrain_chapter_package_to_batch_boundaries(
            payload=payload,
            batch_plan=batch_plan,
            chapter_count=chapter_count,
        )
        return self._chapter_package_from_dict(payload)

    def _constrain_chapter_package_to_batch_boundaries(
        self,
        *,
        payload: dict[str, Any],
        batch_plan: BatchPlan,
        chapter_count: int,
    ) -> dict[str, Any]:
        """Keep ChapterBrief planning bounded by the frozen BatchPlan."""
        constrained = dict(payload)
        chapters = [dict(item) for item in (constrained.get("chapters") or []) if isinstance(item, Mapping)]
        if not chapters:
            return constrained
        must_resolve = list(batch_plan.must_resolve) or ([batch_plan.batch_goal] if batch_plan.batch_goal else [])
        forbidden_consumption = list(batch_plan.must_not_consume)
        count = max(1, int(chapter_count or len(chapters) or 1))
        chapters = chapters[:count]
        slot_targets = self._chapter_package_target_word_counts(batch_plan=batch_plan, chapter_count=count)
        for index, chapter in enumerate(chapters):
            assigned_goal = must_resolve[min(index, len(must_resolve) - 1)] if must_resolve else ""
            if slot_targets:
                chapter["target_word_count"] = slot_targets[min(index, len(slot_targets) - 1)]
            if assigned_goal:
                goal = _normalize_text(chapter.get("goal"))
                if assigned_goal not in goal:
                    chapter["goal"] = assigned_goal
                plot_function = _normalize_text(chapter.get("plot_function"))
                if assigned_goal not in plot_function:
                    chapter["plot_function"] = assigned_goal
                must_include = _normalize_string_list(list(chapter.get("must_include") or []))
                _append_unique(must_include, assigned_goal)
                chapter["must_include"] = must_include
            forbidden = _normalize_string_list(list(chapter.get("forbidden") or []))
            for item in forbidden_consumption:
                _append_unique(forbidden, item)
            if batch_plan.exit_hook and index < count - 1:
                _append_unique(forbidden, f"不得提前消费批次出口钩子：{batch_plan.exit_hook}")
            _append_unique(forbidden, "不得新增 BatchPlan.must_resolve 之外的大型剧情节点。")
            chapter["forbidden"] = forbidden
            structure_hint = dict(chapter.get("structure_hint") or {})
            beats = _normalize_string_list(list(structure_hint.get("beats") or []))
            if assigned_goal and assigned_goal not in beats:
                beats.insert(0, assigned_goal)
            structure_hint["beats"] = beats
            if not _normalize_text(structure_hint.get("theory")):
                structure_hint["theory"] = "BatchPlan boundary contract"
            chapter["structure_hint"] = structure_hint
            if batch_plan.exit_hook and index == count - 1 and not _normalize_text(chapter.get("ending_hook")):
                chapter["ending_hook"] = batch_plan.exit_hook
        constrained["chapters"] = chapters
        review_notes = _normalize_string_list(list(constrained.get("review_notes") or []))
        _append_unique(review_notes, "ChapterBrief 已按 BatchPlan.must_resolve/must_not_consume 收紧剧情边界。")
        constrained["review_notes"] = review_notes
        return constrained

    def _chapter_package_target_word_counts(self, *, batch_plan: BatchPlan, chapter_count: int) -> list[int]:
        default_chars = int(batch_plan.default_chapter_target_chars or 0)
        slots = [dict(item) for item in batch_plan.chapter_outline_slots if isinstance(item, Mapping)]
        targets: list[int] = []
        for index in range(max(1, int(chapter_count or 1))):
            slot = slots[index] if index < len(slots) else {}
            raw_chars = int(
                slot.get("target_chars")
                or slot.get("estimated_chars")
                or slot.get("target_word_count")
                or default_chars
                or 0
            )
            if raw_chars <= 0 and batch_plan.target_total_chars and chapter_count:
                raw_chars = max(1, int(batch_plan.target_total_chars) // max(1, int(chapter_count)))
            if raw_chars <= 0:
                raw_chars = 4000
            targets.append(self._chars_to_words(raw_chars))
        return targets

    def _generate_json_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
    ) -> dict[str, Any] | list[Any]:
        if self.model_client is None:
            raise RuntimeError("Writer layered generation requires an available model_client")
        payload, _ = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=fallback_factory,
            use_fallback_on_error=False,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Writer layered generation model returned a non-object JSON payload")
        return payload

    def _fallback_book_plan(
        self,
        *,
        book_id: str,
        intent: ContinuationIntent,
        outline_path: Path,
        world_summary_path: Path,
    ) -> dict[str, Any]:
        highlights = intent.desired_actions[:3] or ["承接现有主线并推进一个阶段冲突"]
        story_scale = dict(intent.story_scale)
        climax_plan = dict(intent.climax_plan)
        target_chapter_count = int(story_scale.get("target_chapter_count") or 3)
        default_chars = int(story_scale.get("default_chapter_target_chars") or 4000)
        target_total = int(story_scale.get("target_total_chars") or target_chapter_count * default_chars)
        return {
            "plan_id": f"{book_id}-book-plan",
            "book_id": book_id,
            "continuation_goal": intent.desired_actions[0] if intent.desired_actions else "承接原作大纲推进后续主线。",
            "ending_direction": intent.preferred_outcome or "阶段性收束并保留后续张力。",
            "target_chapter_count": target_chapter_count,
            "target_total_chars": target_total,
            "default_chapter_target_chars": default_chars,
            "pacing_profile": str(story_scale.get("pacing_profile") or "均衡推进"),
            "length_distribution_notes": str(story_scale.get("length_distribution_notes") or ""),
            "climax_plan": climax_plan,
            "chapter_outline_slots": self._fallback_chapter_outline_slots(
                count=target_chapter_count,
                default_chars=default_chars,
                highlights=highlights,
                climax_plan=climax_plan,
            ),
            "stage_highlights": highlights,
            "character_arcs": [f"{name}在后续阶段需要出现可验证的选择变化" for name in intent.major_characters[:3]],
            "relationship_guardrails": ["关键关系只允许小步推进，不得跳过桥接事件。"],
            "must_preserve": ["原作既有人物性格、关系基础与主线矛盾。"],
            "open_questions": [] if intent.notes else ["部分细节证据不足，需在后续批次前继续检索。"],
            "evidence": [
                {
                    "claim": "续写必须承接现有大纲与世界观。",
                    "evidence_level": "structured_state",
                    "source_paths": [str(outline_path), str(world_summary_path)],
                    "note": "",
                }
            ],
            "sources": [
                {
                    "type": "outline",
                    "path": str(outline_path),
                    "evidence_level": "structured_state",
                    "snippet": "",
                    "note": "",
                },
                {
                    "type": "world_summary",
                    "path": str(world_summary_path),
                    "evidence_level": "structured_state",
                    "snippet": "",
                    "note": "",
                },
            ],
        }

    def _fallback_world_expansion(
        self,
        *,
        book_id: str,
        intent: ContinuationIntent,
        book_plan: BookContinuationPlan,
        user_world_notes: str,
        world_summary_path: Path,
    ) -> dict[str, Any]:
        required_for_plot = intent.desired_actions[:2] or [book_plan.continuation_goal]
        extra_open_items = [user_world_notes] if user_world_notes.strip() else []
        return {
            "pack_id": f"{book_id}-world-pack",
            "book_id": book_id,
            "required_for_plot": required_for_plot,
            "constraint_rules": [
                {
                    "topic": "世界规则延续",
                    "rule": "新增设定只能作为最小补完，不得推翻既有规则体系。",
                    "why_needed": "保证续写承接原作设定。",
                    "constrained_plots": required_for_plot,
                    "conflict_note": "",
                }
            ],
            "open_items": extra_open_items,
            "evidence": [
                {
                    "claim": "世界观补全必须服从现有摘要。",
                    "evidence_level": "structured_state",
                    "source_paths": [str(world_summary_path)],
                    "note": "",
                }
            ],
            "sources": [
                {
                    "type": "world_summary",
                    "path": str(world_summary_path),
                    "evidence_level": "structured_state",
                    "snippet": "",
                    "note": "",
                }
            ],
        }

    def _fallback_character_cast(
        self,
        *,
        book_id: str,
        requirement_report: CharacterRequirementReport,
        cast_request: CharacterCastRequest,
        character_seeds: list[CharacterSeedInput],
        book_plan: BookContinuationPlan,
        world_pack: WorldExpansionPack,
    ) -> dict[str, Any]:
        seed_map = {
            seed.display_name_hint: seed
            for seed in character_seeds
            if seed.display_name_hint
        }
        planned_profiles: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        introduction_items: list[dict[str, Any]] = []
        named_new_lookup = {f"named-new-{index:02d}": item for index, item in enumerate(requirement_report.named_new_characters, start=1)}
        for index, requirement in enumerate(cast_request.requirements, start=1):
            named_new = named_new_lookup.get(requirement.slot_id)
            seed = seed_map.get(named_new.name) if named_new else None
            canonical_name = (
                named_new.name
                if named_new is not None
                else seed.display_name_hint
                if seed and seed.display_name_hint
                else f"待定{requirement.role_type or '角色'}{index}"
            )
            planned_character_id = f"pc-{index:03d}"
            intro_batch = requirement.introduction_window.batch_id or "batch-01"
            intro_chapter = (
                requirement.introduction_window.chapter_range[0]
                if requirement.introduction_window.chapter_range
                else f"{intro_batch.replace('-', '')}-ch01"
            )
            relationship_entry_points = []
            if seed and seed.relationship_entry is not None:
                relationship_entry_points.append(
                    {
                        "target_character": seed.relationship_entry.target_character,
                        "initial_state": seed.relationship_entry.initial_state,
                        "ceiling_before_freeze_e": seed.relationship_entry.allowed_target_state_in_this_batch,
                    }
                )
            planned_profiles.append(
                {
                    "planned_character_id": planned_character_id,
                    "status": "planned",
                    "canonical_name": canonical_name,
                    "aliases": [],
                    "faction": seed.faction if seed and seed.faction else requirement.faction,
                    "narrative_role": requirement.role_type or "待补功能位",
                    "core_personality": seed.must_keep if seed and seed.must_keep else requirement.required_traits,
                    "surface_identity": seed.core_concept if seed and seed.core_concept else requirement.role_type,
                    "hidden_pressure": [],
                    "ability_scope": requirement.required_traits,
                    "ability_limits": [*requirement.forbidden_traits, *seed.world_constraints] if seed else requirement.forbidden_traits,
                    "relationship_entry_points": relationship_entry_points,
                    "first_introduction_plan": {
                        "batch_id": intro_batch,
                        "chapter_id": intro_chapter,
                        "scene_function": requirement.role_type or "填补角色功能位",
                    },
                    "must_not_reveal_early": world_pack.open_items[:1] or ["关键底牌"],
                    "sources": [{"type": "cast_request", "path": "character_cast_request.json"}],
                }
            )
            bindings.append({"planned_character_id": planned_character_id, "slot_id": requirement.slot_id})
            introduction_items.append(
                {
                    "planned_character_id": planned_character_id,
                    "batch_id": intro_batch,
                    "chapter_id": intro_chapter,
                    "required_scene_function": requirement.role_type or "角色补位",
                    "required_relationship_effect": relationship_entry_points[0]["ceiling_before_freeze_e"]
                    if relationship_entry_points
                    else "",
                    "forbidden_moves": requirement.forbidden_traits or ["提前交底"],
                }
            )
        return {
            "planned_character_profiles": planned_profiles,
            "character_cast_plan": {
                "cast_plan_id": f"{book_id}-cast-plan",
                "depends_on": {
                    "book_continuation_plan_id": book_plan.plan_id,
                    "world_expansion_pack_id": world_pack.pack_id,
                },
                "planned_characters": bindings,
                "open_questions": [],
                "must_not_consume": ["计划角色在首次登场章不得越权推进关系或泄露终局秘密。"],
            },
            "character_introduction_plan": {"introduction_items": introduction_items},
        }

    def _fallback_batch_plan(
        self,
        *,
        conn: sqlite3.Connection,
        book_id: str,
        book_plan: BookContinuationPlan,
        world_pack: WorldExpansionPack,
        character_cast_plan: dict[str, Any] | None,
        target_chapter_count: int,
    ) -> dict[str, Any]:
        title_indexes = self.documents_repo.list_title_indexes(conn, book_id=book_id)
        start_index = (max(title_indexes) + 1) if title_indexes else 1
        end_index = start_index + max(1, target_chapter_count) - 1
        planned_beats: list[str] = []
        if character_cast_plan:
            for item in character_cast_plan.get("planned_characters", []) or []:
                if isinstance(item, dict):
                    planned_beats.append(
                        f"{item.get('planned_character_id', '')} 在本批次承担 {item.get('slot_id', '')}。"
                    )
        return {
            "batch_id": f"batch-{start_index:02d}",
            "book_id": book_id,
            "scope_start": f"chapter-{start_index}",
            "scope_end": f"chapter-{end_index}",
            "batch_goal": book_plan.continuation_goal,
            "emotional_arc": book_plan.relationship_guardrails[0] if book_plan.relationship_guardrails else "维持克制推进",
            "conflict_arc": world_pack.required_for_plot[0] if world_pack.required_for_plot else "推进主线冲突",
            "must_resolve": book_plan.stage_highlights[:2] or [book_plan.continuation_goal],
            "must_not_consume": book_plan.must_preserve[:1] + ["终局真相", "关系终局状态"],
            "planned_character_beats": planned_beats,
            "exit_hook": book_plan.open_questions[0] if book_plan.open_questions else "批次结尾引出新的未决问题。",
            "target_chapter_count": max(1, int(target_chapter_count or book_plan.target_chapter_count or 1)),
            "target_total_chars": int(book_plan.target_total_chars or 0),
            "default_chapter_target_chars": int(book_plan.default_chapter_target_chars or 0),
            "chapter_outline_slots": [
                dict(item) for item in book_plan.chapter_outline_slots[: max(1, int(target_chapter_count or 1))]
            ],
            "evidence": [
                {
                    "claim": "当前批次承接 Freeze A 冻结方向。",
                    "evidence_level": "structured_state",
                    "source_paths": ["freeze_a/book_continuation_plan.json", "freeze_a/world_expansion_pack.json"],
                    "note": "",
                }
            ],
            "sources": [
                {
                    "type": "book_plan",
                    "path": "freeze_a/book_continuation_plan.json",
                    "evidence_level": "structured_state",
                    "snippet": "",
                    "note": "",
                }
            ],
        }

    def _fallback_chapter_package(
        self,
        *,
        batch_plan: BatchPlan,
        character_introduction_plan: dict[str, Any] | None,
        chapter_count: int,
    ) -> dict[str, Any]:
        introduction_items = (
            list((character_introduction_plan or {}).get("introduction_items", []))
            if isinstance(character_introduction_plan, dict)
            else []
        )
        chapters: list[dict[str, Any]] = []
        batch_slug = batch_plan.batch_id.replace("-", "")
        for index in range(1, max(1, chapter_count) + 1):
            chapter_id = f"{batch_slug}-ch{index:02d}"
            intro_for_chapter = [
                item for item in introduction_items if isinstance(item, dict) and item.get("chapter_id") == chapter_id
            ]
            must_include = [batch_plan.must_resolve[min(index - 1, len(batch_plan.must_resolve) - 1)]]
            if intro_for_chapter:
                must_include.append(f"计划角色 {intro_for_chapter[0].get('planned_character_id', '')} 有限登场")
            chapters.append(
                {
                    "chapter_id": chapter_id,
                    "title": f"第{index}章 批次推进",
                    "goal": batch_plan.batch_goal,
                    "chapter_role": "批次执行章",
                    "plot_function": "承上启下",
                    "emotional_goal": batch_plan.emotional_arc,
                    "conflict_goal": batch_plan.conflict_arc,
                    "relationship_targets": [
                        {
                            "relation_type": "主关系线",
                            "current_state": "谨慎试探",
                            "target_state": "有限合作",
                            "allowed": True,
                            "required_bridge": ["共同危机", "实际行动证明"],
                        }
                    ],
                    "must_include": must_include,
                    "forbidden": batch_plan.must_not_consume,
                    "structure_hint": {"theory": "故事圆环", "beats": ["Need", "Go", "Search"]},
                    "ending_hook": batch_plan.exit_hook if index == chapter_count else "给下一章制造压力。",
                    "target_word_count": 1800,
                    "sources": [{"type": "batch_plan", "path": "batch_plan.json"}],
                }
            )
        return {
            "package_id": f"{batch_plan.batch_id}-package",
            "batch_id": batch_plan.batch_id,
            "package_goal": batch_plan.batch_goal,
            "review_notes": ["可逐章微调 ChapterBrief，但不得突破 BatchPlan 上限。"],
            "chapters": chapters,
            "sources": [{"type": "batch_plan", "path": "batch_plan.json"}],
        }

    def _words_to_chars(self, word_count: int) -> int:
        return max(1, int(word_count or 1200) * 2)

    def _chars_to_words(self, char_count: int) -> int:
        return max(1, int(round(max(1, int(char_count or 1)) / 2)))

    def _length_bounds(self, target_chars: int) -> tuple[int, int]:
        target = max(1, int(target_chars))
        return max(1, int(target * 0.85)), max(target, int(target * 1.2))

    def _is_focus_chapter(self, chapter: ChapterBrief) -> bool:
        marker_text = "\n".join(
            [
                chapter.chapter_role,
                chapter.plot_function,
                chapter.goal,
                chapter.conflict_goal,
                chapter.emotional_goal,
                chapter.ending_hook,
                *chapter.must_include,
            ]
        )
        focus_markers = ("关键", "转折", "揭示", "爆发", "高潮", "首次", "登场", "危机")
        return any(marker in marker_text for marker in focus_markers) or len(chapter.must_include) >= 3

    def _is_climax_chapter(self, chapter: ChapterBrief, *, index: int, total: int) -> bool:
        marker_text = "\n".join([chapter.chapter_role, chapter.plot_function, chapter.goal, chapter.ending_hook])
        return "高潮" in marker_text or "爆发" in marker_text or (total > 1 and index == total - 1)

    def _focus_reason(self, chapter: ChapterBrief, *, is_climax: bool) -> str:
        if is_climax:
            return "批次高潮或强冲突承接章，需要更充分的场面展开。"
        if chapter.must_include:
            return "必写点较多，需要为关键动作、对白和关系桥接预留篇幅。"
        return "章节承担关键转折，需要高于默认预算。"

    def _length_expansion_notes(self, chapter: ChapterBrief, *, is_focus: bool) -> list[str]:
        if not is_focus:
            return ["按默认节奏完成目标、关系桥接与章末钩子。"]
        notes = ["优先扩写关键动作链、关系桥接和情绪递进。"]
        if chapter.must_include:
            notes.append("确保 must_include 中每一项落到具体场景，而不是摘要带过。")
        if chapter.ending_hook:
            notes.append("章末钩子需要有清晰触发事件。")
        return notes

    def _freeze_a_bundle_to_dict(self, bundle: FreezeABundle) -> dict[str, Any]:
        return {
            "modeling_status": bundle.modeling_status.to_dict(),
            "continuation_intent": bundle.continuation_intent.to_dict(),
            "book_continuation_plan": bundle.book_continuation_plan.to_dict(),
            "world_expansion_pack": bundle.world_expansion_pack.to_dict(),
            "character_requirement_report": bundle.character_requirement_report.to_dict(),
            "character_cast_request": bundle.character_cast_request.to_dict() if bundle.character_cast_request else None,
            "planned_character_profiles": [item.to_dict() for item in bundle.planned_character_profiles],
            "character_cast_plan": bundle.character_cast_plan.to_dict() if bundle.character_cast_plan else None,
            "character_introduction_plan": bundle.character_introduction_plan.to_dict()
            if bundle.character_introduction_plan
            else None,
        }

    def _resolve_asset_path(self, assets: sqlite3.Row | None, field_name: str) -> Path | None:
        if assets is None:
            return None
        raw_path = _normalize_text(assets[field_name]) if field_name in assets.keys() else ""
        if not raw_path:
            return None
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (self.repo_root / path).resolve()
        return path

    def _get_required_asset_path(self, conn: sqlite3.Connection, *, book_id: str, field_name: str) -> Path:
        assets = self.assets_repo.get(conn, book_id=book_id)
        path = self._resolve_asset_path(assets, field_name)
        if path is None or not path.exists():
            raise ValueError(f"缺少资产文件: {field_name}")
        return path

    def _creative_kb_ready(self, conn: sqlite3.Connection) -> bool:
        try:
            tables = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
                    CREATIVE_KB_TABLES,
                ).fetchall()
            }
            if not all(table in tables for table in CREATIVE_KB_TABLES):
                return False
            row = conn.execute("SELECT COUNT(*) AS count FROM fragment_cards").fetchone()
            return bool(row and int(row["count"]) > 0)
        except sqlite3.DatabaseError:
            return False

    def _require_freeze(self, run_id: str, freeze_stage: str) -> None:
        for record in self.run_writer.list_freeze_records(run_id):
            if record.freeze_stage == freeze_stage and record.status == "frozen":
                return
        raise ValueError(f"缺少已确认的 {freeze_stage}")

    def _load_artifact_payloads(
        self,
        run_id: str,
        artifact_names: list[str],
        overrides: Mapping[str, str] | None = None,
    ) -> dict[str, Any | None]:
        payloads: dict[str, Any | None] = {}
        for name in artifact_names:
            override_path = overrides.get(name) if overrides else None
            if override_path:
                path = Path(override_path)
                payloads[name] = self._load_json_data(path) if path.exists() else None
                continue
            try:
                payloads[name] = self._load_run_json(run_id, name)
            except FileNotFoundError:
                payloads[name] = None
        return payloads

    def _load_run_json(self, run_id: str, name: str) -> Any:
        path = self.run_writer.layout.run_dir(run_id) / name
        return self._load_json_data(path)

    def _load_json_data(self, path: Path) -> Any:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "data" in raw:
            return raw["data"]
        return raw

    def _load_frozen_artifact(self, run_id: str, freeze_stage: str, artifact_name: str) -> Any:
        for record in self.run_writer.list_freeze_records(run_id):
            if record.freeze_stage != freeze_stage:
                continue
            for artifact in record.artifacts:
                if artifact.name == artifact_name:
                    return self._load_json_data(Path(artifact.path))
        raise FileNotFoundError(f"未找到冻结产物: {freeze_stage}/{artifact_name}")

    def _load_optional_json_from_frozen_artifact(
        self,
        run_id: str,
        freeze_stage: str,
        artifact_name: str,
    ) -> dict[str, Any] | None:
        try:
            payload = self._load_frozen_artifact(run_id, freeze_stage, artifact_name)
        except FileNotFoundError:
            return None
        return dict(payload) if isinstance(payload, dict) else None

    def _load_book_plan_from_frozen_artifact(self, run_id: str, freeze_stage: str, artifact_name: str) -> BookContinuationPlan:
        payload = self._load_frozen_artifact(run_id, freeze_stage, artifact_name)
        if not isinstance(payload, dict):
            raise ValueError("冻结的 book plan 不是合法 JSON 对象")
        return self._book_plan_from_dict(payload)

    def _load_world_pack_from_frozen_artifact(self, run_id: str, freeze_stage: str, artifact_name: str) -> WorldExpansionPack:
        payload = self._load_frozen_artifact(run_id, freeze_stage, artifact_name)
        if not isinstance(payload, dict):
            raise ValueError("冻结的 world pack 不是合法 JSON 对象")
        return self._world_pack_from_dict(payload)

    def _load_batch_plan_from_frozen_artifact(self, run_id: str, freeze_stage: str, artifact_name: str) -> BatchPlan:
        payload = self._load_frozen_artifact(run_id, freeze_stage, artifact_name)
        if not isinstance(payload, dict):
            raise ValueError("冻结的 batch plan 不是合法 JSON 对象")
        return self._batch_plan_from_dict(payload)

    def _book_plan_from_dict(self, data: Mapping[str, Any]) -> BookContinuationPlan:
        story_scale = self._normalize_story_scale(data)
        return BookContinuationPlan(
            plan_id=str(data.get("plan_id") or ""),
            book_id=str(data.get("book_id") or ""),
            continuation_goal=str(data.get("continuation_goal") or ""),
            ending_direction=str(data.get("ending_direction") or ""),
            target_chapter_count=int(story_scale.get("target_chapter_count") or 0),
            target_total_chars=int(story_scale.get("target_total_chars") or 0),
            default_chapter_target_chars=int(story_scale.get("default_chapter_target_chars") or 0),
            pacing_profile=str(story_scale.get("pacing_profile") or ""),
            length_distribution_notes=str(story_scale.get("length_distribution_notes") or ""),
            climax_plan=self._normalize_climax_plan(data.get("climax_plan")),
            chapter_outline_slots=[
                dict(item) for item in (data.get("chapter_outline_slots") or []) if isinstance(item, Mapping)
            ],
            stage_highlights=[str(item) for item in (data.get("stage_highlights") or [])],
            character_arcs=[str(item) for item in (data.get("character_arcs") or [])],
            relationship_guardrails=[str(item) for item in (data.get("relationship_guardrails") or [])],
            must_preserve=[str(item) for item in (data.get("must_preserve") or [])],
            open_questions=[str(item) for item in (data.get("open_questions") or [])],
            assumptions=[
                PlanningFact.from_dict(item)
                for item in (data.get("assumptions") or [])
                if isinstance(item, Mapping)
            ],
            evidence=[
                self._evidence_item_from_dict(item) for item in (data.get("evidence") or []) if isinstance(item, Mapping)
            ],
            sources=[
                self._traceable_source_from_dict(item) for item in (data.get("sources") or []) if isinstance(item, Mapping)
            ],
        )

    def _continuation_intent_from_dict(self, data: Mapping[str, Any]) -> ContinuationIntent:
        return ContinuationIntent(
            major_characters=[str(item) for item in (data.get("major_characters") or [])],
            desired_actions=[str(item) for item in (data.get("desired_actions") or [])],
            avoidances=[str(item) for item in (data.get("avoidances") or [])],
            preferred_outcome=str(data.get("preferred_outcome") or ""),
            notes=str(data.get("notes") or ""),
            story_scale=dict(data.get("story_scale") or {}),
            climax_plan=dict(data.get("climax_plan") or {}),
            sources=[
                self._traceable_source_from_dict(item)
                for item in (data.get("sources") or [])
                if isinstance(item, Mapping)
            ],
        )

    def _world_pack_from_dict(self, data: Mapping[str, Any]) -> WorldExpansionPack:
        return WorldExpansionPack(
            pack_id=str(data.get("pack_id") or ""),
            book_id=str(data.get("book_id") or ""),
            required_for_plot=[str(item) for item in (data.get("required_for_plot") or [])],
            constraint_rules=[
                self._world_constraint_rule_from_dict(item)
                for item in (data.get("constraint_rules") or [])
                if isinstance(item, Mapping)
            ],
            open_items=[str(item) for item in (data.get("open_items") or [])],
            evidence=[
                self._evidence_item_from_dict(item) for item in (data.get("evidence") or []) if isinstance(item, Mapping)
            ],
            sources=[
                self._traceable_source_from_dict(item) for item in (data.get("sources") or []) if isinstance(item, Mapping)
            ],
        )

    def _batch_plan_from_dict(self, data: Mapping[str, Any]) -> BatchPlan:
        return BatchPlan(
            batch_id=str(data.get("batch_id") or ""),
            book_id=str(data.get("book_id") or ""),
            scope_start=str(data.get("scope_start") or ""),
            scope_end=str(data.get("scope_end") or ""),
            batch_goal=str(data.get("batch_goal") or ""),
            emotional_arc=str(data.get("emotional_arc") or ""),
            conflict_arc=str(data.get("conflict_arc") or ""),
            must_resolve=[str(item) for item in (data.get("must_resolve") or [])],
            must_not_consume=[str(item) for item in (data.get("must_not_consume") or [])],
            planned_character_beats=[str(item) for item in (data.get("planned_character_beats") or [])],
            exit_hook=str(data.get("exit_hook") or ""),
            target_chapter_count=int(data.get("target_chapter_count") or 0),
            target_total_chars=int(data.get("target_total_chars") or 0),
            default_chapter_target_chars=int(data.get("default_chapter_target_chars") or 0),
            chapter_outline_slots=[
                dict(item) for item in (data.get("chapter_outline_slots") or []) if isinstance(item, Mapping)
            ],
            evidence=[
                self._evidence_item_from_dict(item) for item in (data.get("evidence") or []) if isinstance(item, Mapping)
            ],
            sources=[
                self._traceable_source_from_dict(item) for item in (data.get("sources") or []) if isinstance(item, Mapping)
            ],
        )

    def _chapter_package_from_dict(self, data: Mapping[str, Any]) -> ChapterPackage:
        chapters: list[ChapterBrief] = []
        for chapter in data.get("chapters") or []:
            if not isinstance(chapter, Mapping):
                continue
            chapters.append(
                ChapterBrief(
                    chapter_id=str(chapter.get("chapter_id") or ""),
                    title=str(chapter.get("title") or ""),
                    goal=str(chapter.get("goal") or ""),
                    chapter_role=str(chapter.get("chapter_role") or ""),
                    plot_function=str(chapter.get("plot_function") or ""),
                    emotional_goal=str(chapter.get("emotional_goal") or ""),
                    conflict_goal=str(chapter.get("conflict_goal") or ""),
                    relationship_targets=[
                        RelationshipTarget(
                            relation_type=str(item.get("relation_type") or ""),
                            current_state=str(item.get("current_state") or ""),
                            target_state=str(item.get("target_state") or ""),
                            allowed=bool(item.get("allowed", True)),
                            required_bridge=[str(part) for part in (item.get("required_bridge") or [])],
                        )
                        for item in (chapter.get("relationship_targets") or [])
                        if isinstance(item, Mapping)
                    ],
                    must_include=[str(item) for item in (chapter.get("must_include") or [])],
                    forbidden=[str(item) for item in (chapter.get("forbidden") or [])],
                    structure_hint=ChapterStructureHint(
                        theory=str((chapter.get("structure_hint") or {}).get("theory") or ""),
                        beats=[
                            str(item)
                            for item in (((chapter.get("structure_hint") or {}).get("beats")) or [])
                        ],
                    ),
                    ending_hook=str(chapter.get("ending_hook") or ""),
                    target_word_count=int(chapter.get("target_word_count") or 1200),
                    sources=[
                        self._traceable_source_from_dict(item)
                        for item in (chapter.get("sources") or [])
                        if isinstance(item, Mapping)
                    ],
                )
            )
        return ChapterPackage(
            package_id=str(data.get("package_id") or ""),
            batch_id=str(data.get("batch_id") or ""),
            package_goal=str(data.get("package_goal") or ""),
            chapters=chapters,
            review_notes=[str(item) for item in (data.get("review_notes") or [])],
            sources=[
                self._traceable_source_from_dict(item) for item in (data.get("sources") or []) if isinstance(item, Mapping)
            ],
        )

    def _chapter_length_plan_from_dict(self, data: Mapping[str, Any]) -> ChapterLengthPlan:
        budgets: list[ChapterLengthBudget] = []
        for item in data.get("budgets") or []:
            if not isinstance(item, Mapping):
                continue
            budgets.append(
                ChapterLengthBudget(
                    chapter_id=str(item.get("chapter_id") or ""),
                    target_chars=int(item.get("target_chars") or 1),
                    min_chars=int(item.get("min_chars") or item.get("target_chars") or 1),
                    max_chars=int(item.get("max_chars") or item.get("target_chars") or 1),
                    is_focus_chapter=bool(item.get("is_focus_chapter", False)),
                    focus_reason=str(item.get("focus_reason") or ""),
                    expansion_notes=[str(note) for note in (item.get("expansion_notes") or [])],
                    source_chapter_target_word_count=int(item.get("source_chapter_target_word_count") or 0),
                )
            )
        return ChapterLengthPlan(
            plan_id=str(data.get("plan_id") or ""),
            batch_id=str(data.get("batch_id") or ""),
            default_target_chars=int(data.get("default_target_chars") or 1),
            default_min_chars=int(data.get("default_min_chars") or data.get("default_target_chars") or 1),
            default_max_chars=int(data.get("default_max_chars") or data.get("default_target_chars") or 1),
            budgets=budgets,
            focus_chapter_ids=[str(item) for item in (data.get("focus_chapter_ids") or [])],
            climax_chapter_ids=[str(item) for item in (data.get("climax_chapter_ids") or [])],
            review_notes=[str(item) for item in (data.get("review_notes") or [])],
            sources=[
                self._traceable_source_from_dict(item)
                for item in (data.get("sources") or [])
                if isinstance(item, Mapping)
            ],
        )

    def _traceable_source_from_dict(self, data: Mapping[str, Any]) -> TraceableSource:
        return TraceableSource(
            type=str(data.get("type") or ""),
            path=str(data.get("path") or ""),
            evidence_level=str(data.get("evidence_level") or "confirmed_analysis"),  # type: ignore[arg-type]
            snippet=str(data.get("snippet") or ""),
            note=str(data.get("note") or ""),
        )

    def _evidence_item_from_dict(self, data: Mapping[str, Any]) -> EvidenceItem:
        return EvidenceItem(
            claim=str(data.get("claim") or ""),
            evidence_level=self._safe_evidence_level(data.get("evidence_level")),  # type: ignore[arg-type]
            source_paths=[str(item) for item in (data.get("source_paths") or [])],
            note=str(data.get("note") or ""),
        )

    def _safe_evidence_level(self, value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        if normalized in EVIDENCE_LEVELS:
            return normalized
        alias_key = normalized.replace("_", " ")
        alias = EVIDENCE_LEVEL_ALIASES.get(normalized) or EVIDENCE_LEVEL_ALIASES.get(alias_key)
        if alias in EVIDENCE_LEVELS:
            return alias
        return "reasonable_inference"

    def _world_constraint_rule_from_dict(self, data: Mapping[str, Any]) -> WorldConstraintRule:
        return WorldConstraintRule(
            topic=str(data.get("topic") or ""),
            rule=str(data.get("rule") or ""),
            why_needed=str(data.get("why_needed") or ""),
            constrained_plots=[str(item) for item in (data.get("constrained_plots") or [])],
            conflict_note=str(data.get("conflict_note") or ""),
        )

    def _infer_role_slots(self, inputs: list[str]) -> list[UnfilledRoleSlot]:
        joined = "\n".join(text for text in inputs if text)
        slot_specs = (
            ("villain-pressure", "反派压力位", ("反派", "敌人", "追杀", "追捕", "压迫")),
            ("ally-support", "行动支援位", ("援军", "帮手", "支援", "接应", "联络")),
            ("informant", "情报中间人", ("线人", "情报", "内应", "卧底")),
            ("mentor-guide", "引导者", ("导师", "老师", "指引", "引路")),
        )
        inferred: list[UnfilledRoleSlot] = []
        for slot_id, slot_type, keywords in slot_specs:
            if any(keyword in joined for keyword in keywords):
                inferred.append(
                    UnfilledRoleSlot(
                        slot_id=slot_id,
                        slot_type=slot_type,
                        reason="续写意图或全书规划文本显示该功能位尚需角色承接。",
                    )
                )
        return inferred

    def _infer_faction_from_slot(self, slot_type: str) -> str:
        if any(keyword in slot_type for keyword in ("反派", "追杀", "敌")):
            return "对立方"
        if any(keyword in slot_type for keyword in ("支援", "情报", "引导")):
            return "友方"
        return ""

    def _load_doc_excerpt(self, path: Path, *, max_chars: int = 5000) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars].strip()
