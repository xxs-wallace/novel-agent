from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..orchestrators import MainLayerOrchestrator
from ..repos.creative_kb_storage import init_creative_kb_schema
from ..repos.db import NovelAgentDB
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ...schemas import RunConfig
from ..schemas.creative_kb_schema import (
    CreativeKBRetrievalResult,
    ExpandedReferenceFragment,
    RerankResult,
    SceneBrief,
)
from ..schemas.orchestration_schema import WriterInputBundle
from ..schemas.smoke_schema import (
    AuthorizedInputs,
    LoadedSmokeSample,
    LoadedSmokeStep,
    PrefixRuntimeSnapshot,
    SmokeCompareReport,
    SmokeReviewerReport,
)
from ..services.continuation_generation_service import ContinuationGenerationService
from ..services.smoke_backfill_service import SmokeBackfillResult, SmokeBackfillService
from ..services.smoke_compare_service import SmokeCompareService
from ..services.smoke_authorized_inputs_service import SmokeAuthorizedInputsService
from ..services.smoke_prefix_snapshot_service import SmokePrefixSnapshotService
from ..services.smoke_reviewer_service import SmokeReviewerService
from ..services.smoke_sample_service import SmokeSampleService
from ...runs import RunLayout, RunWriter

SmokeTextGenerator = Callable[[str, WriterInputBundle, AuthorizedInputs], str]


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_string_list(items: object) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        text = items.strip()
        return [text] if text else []
    if not isinstance(items, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _default_text_generator(prompt: str, writer_input_bundle: WriterInputBundle, authorized_inputs: AuthorizedInputs) -> str:
    _ = prompt
    scene_brief = writer_input_bundle.scene_brief
    objective = _normalize_text(scene_brief.scene_objective) or "续写当前场景"
    emotional_goal = _normalize_text(scene_brief.emotional_goal)
    conflict_goal = _normalize_text(scene_brief.conflict_goal)
    excerpt = (
        writer_input_bundle.reference_fragments[0].source_excerpt.strip()
        if writer_input_bundle.reference_fragments
        else writer_input_bundle.anchor_context.strip()
    )
    lines = [objective]
    if emotional_goal:
        lines.append(f"情绪目标：{emotional_goal}")
    if conflict_goal:
        lines.append(f"冲突目标：{conflict_goal}")
    if excerpt:
        lines.append(excerpt)
    if authorized_inputs.related_character_names:
        lines.append("出场人物：" + "、".join(authorized_inputs.related_character_names))
    return "\n".join(line for line in lines if line).strip()


@dataclass(slots=True)
class SmokeStepRunResult:
    step_id: str
    target_segment_id: str | None
    authorized_inputs: AuthorizedInputs
    retrieval_result: CreativeKBRetrievalResult
    writer_input_bundle: WriterInputBundle
    prompt_text: str
    generated_text: str
    compare_report: SmokeCompareReport
    reviewer_report: SmokeReviewerReport | None = None
    backfill_result: SmokeBackfillResult | None = None


@dataclass(slots=True)
class SingleSampleSmokeRunResult:
    run_id: str
    sample: LoadedSmokeSample
    prefix_snapshot: PrefixRuntimeSnapshot
    step_results: list[SmokeStepRunResult]
    authorized_inputs: AuthorizedInputs
    retrieval_result: CreativeKBRetrievalResult
    writer_input_bundle: WriterInputBundle
    prompt_text: str
    generated_text: str
    compare_report: SmokeCompareReport
    reviewer_report: SmokeReviewerReport | None
    run_dir: str


class SingleSampleSmokeRunner:
    def __init__(
        self,
        *,
        source_db_path: Path,
        runs_dir: Path,
        repo_root: Path | None = None,
        sample_service: SmokeSampleService | None = None,
        prefix_snapshot_service: SmokePrefixSnapshotService | None = None,
        authorized_inputs_service: SmokeAuthorizedInputsService | None = None,
        compare_service: SmokeCompareService | None = None,
        reviewer_service: SmokeReviewerService | None = None,
        backfill_service: SmokeBackfillService | None = None,
        generation_service: ContinuationGenerationService | None = None,
        generation_config: RunConfig | None = None,
        orchestrator: MainLayerOrchestrator | None = None,
        run_writer: RunWriter | None = None,
        text_generator: SmokeTextGenerator | None = None,
        include_coarse_result: bool = False,
        reviewer_enabled: bool = True,
    ) -> None:
        self.source_db_path = source_db_path.expanduser().resolve()
        self.runs_dir = runs_dir.expanduser().resolve()
        self.repo_root = repo_root.expanduser().resolve() if repo_root is not None else Path.cwd()
        self.sample_service = sample_service or SmokeSampleService(repo_root=self.repo_root)
        self.prefix_snapshot_service = prefix_snapshot_service or SmokePrefixSnapshotService()
        self.authorized_inputs_service = authorized_inputs_service or SmokeAuthorizedInputsService()
        self.compare_service = compare_service or SmokeCompareService()
        self.reviewer_service = reviewer_service
        self.backfill_service = backfill_service or SmokeBackfillService()
        self.generation_config = generation_config
        if generation_service is not None and generation_config is None:
            raise ValueError("generation_config is required when generation_service is provided")
        self.generation_service = generation_service or (
            ContinuationGenerationService() if generation_config is not None else None
        )
        self.orchestrator = orchestrator or MainLayerOrchestrator(repo_root=self.repo_root)
        self.run_writer = run_writer or RunWriter(layout=RunLayout(base_dir=self.runs_dir))
        self.text_generator = text_generator or _default_text_generator
        self.include_coarse_result = include_coarse_result
        self.reviewer_enabled = reviewer_enabled

    def run(self, *, sample_path: str | Path) -> SingleSampleSmokeRunResult:
        run_id = uuid.uuid4().hex
        run_dir = self.run_writer.prepare_run_dir(run_id)
        sample = self.sample_service.load(sample_path)
        self.run_writer.write_json(run_id, "smoke_sample.json", sample)

        prefix_snapshot = self.prefix_snapshot_service.build(
            source_db_path=self.source_db_path,
            sample=sample.config,
            output_root=run_dir / "runtime",
        )
        self.run_writer.write_json(run_id, "prefix_runtime_snapshot.json", prefix_snapshot)
        step_results: list[SmokeStepRunResult] = []
        previous_generated_segment: str | None = None
        target_chapter_index = self._resolve_target_chapter_index(sample=sample, prefix_snapshot=prefix_snapshot)

        for step_number, step in enumerate(sample.steps, start=1):
            step_prefix = self._step_prefix(step_number=step_number, step=step)
            authorized_inputs = self.authorized_inputs_service.build(
                sample=sample,
                prefix_snapshot=prefix_snapshot,
                step=step,
                previous_generated_segment=previous_generated_segment,
            )
            self.run_writer.write_json(run_id, f"{step_prefix}/authorized_inputs.json", authorized_inputs)

            retrieval_result, writer_input_bundle = self._build_writer_bundle(
                sample=sample,
                step=step,
                prefix_snapshot=prefix_snapshot,
                authorized_inputs=authorized_inputs,
                previous_generated_segment=previous_generated_segment,
            )
            self.run_writer.write_json(run_id, f"{step_prefix}/scene_brief.json", retrieval_result.scene_brief)
            self.run_writer.write_json(run_id, f"{step_prefix}/retrieval_bundle.json", retrieval_result)
            self.run_writer.write_json(run_id, f"{step_prefix}/writer_input_bundle.json", writer_input_bundle)

            prompt_text = self._build_prompt(
                sample=sample,
                step=step,
                previous_generated_segment=previous_generated_segment,
                authorized_inputs=authorized_inputs,
                writer_input_bundle=writer_input_bundle,
            )
            generated_text = self._generate_text(
                run_id=run_id,
                artifact_prefix=step_prefix,
                prompt_text=prompt_text,
                writer_input_bundle=writer_input_bundle,
                authorized_inputs=authorized_inputs,
            )
            compare_report = self.compare_service.compare(
                sample=sample,
                step=step,
                authorized_inputs=authorized_inputs,
                writer_input_bundle=writer_input_bundle,
                generated_text=generated_text,
            )
            reviewer_report = self._review_generated_text(
                sample=sample,
                step=step,
                authorized_inputs=authorized_inputs,
                generated_text=generated_text,
            )
            self.run_writer.write_text(run_id, f"{step_prefix}/prompt.txt", prompt_text)
            self.run_writer.write_text(run_id, f"{step_prefix}/generated.txt", generated_text)
            self.run_writer.write_text(run_id, f"{step_prefix}/reference_truth.txt", step.reference_truth.text)
            self.run_writer.write_json(run_id, f"{step_prefix}/smoke_compare_report.json", compare_report)
            if reviewer_report is not None:
                self.run_writer.write_json(run_id, f"{step_prefix}/reviewer_report.json", reviewer_report)

            backfill_result: SmokeBackfillResult | None = None
            if step_number < len(sample.steps):
                backfill_result = self._backfill_generated_segment(
                    sample=sample,
                    step=step,
                    prefix_snapshot=prefix_snapshot,
                    chapter_index=target_chapter_index,
                    generated_text=generated_text,
                    authorized_inputs=authorized_inputs,
                )
                self.run_writer.write_json(run_id, f"{step_prefix}/backfill_result.json", backfill_result)

            step_results.append(
                SmokeStepRunResult(
                    step_id=step.step_id,
                    target_segment_id=step.target_segment_id,
                    authorized_inputs=authorized_inputs,
                    retrieval_result=retrieval_result,
                    writer_input_bundle=writer_input_bundle,
                    prompt_text=prompt_text,
                    generated_text=generated_text,
                    compare_report=compare_report,
                    reviewer_report=reviewer_report,
                    backfill_result=backfill_result,
                )
            )
            previous_generated_segment = generated_text

        final_step_result = step_results[-1]
        authorized_inputs = final_step_result.authorized_inputs
        retrieval_result = final_step_result.retrieval_result
        writer_input_bundle = final_step_result.writer_input_bundle
        prompt_text = final_step_result.prompt_text
        generated_text = final_step_result.generated_text
        compare_report = final_step_result.compare_report
        reviewer_report = final_step_result.reviewer_report

        self.run_writer.write_json(run_id, "authorized_inputs.json", authorized_inputs)
        self.run_writer.write_json(run_id, "scene_brief.json", retrieval_result.scene_brief)
        self.run_writer.write_json(run_id, "retrieval_bundle.json", retrieval_result)
        self.run_writer.write_json(run_id, "writer_input_bundle.json", writer_input_bundle)
        self.run_writer.write_text(run_id, "prompt.txt", prompt_text)
        self.run_writer.write_text(run_id, "generated.txt", generated_text)
        self.run_writer.write_text(run_id, "reference_truth.txt", sample.steps[-1].reference_truth.text)
        self.run_writer.write_json(run_id, "smoke_compare_report.json", compare_report)
        if reviewer_report is not None:
            self.run_writer.write_json(run_id, "reviewer_report.json", reviewer_report)
        self.run_writer.write_json(
            run_id,
            "smoke_run_summary.json",
            {
                "sample_id": sample.config.sample_id,
                "mode": sample.config.mode,
                "run_id": run_id,
                "step_count": len(step_results),
                "generated_chars": len(generated_text),
                "reference_truth_chars": len(sample.steps[-1].reference_truth.text),
                "selected_fragment_ids": list(retrieval_result.rerank_result.selected_fragment_ids),
                "decision": compare_report.decision,
                "weighted_score": compare_report.weighted_score,
                "reviewer": (
                    {
                        "decision": reviewer_report.decision,
                        "score": reviewer_report.score,
                        "summary": reviewer_report.summary,
                    }
                    if reviewer_report is not None
                    else None
                ),
                "steps": [
                    {
                        "step_id": item.step_id,
                        "target_segment_id": item.target_segment_id,
                        "decision": item.compare_report.decision,
                        "weighted_score": item.compare_report.weighted_score,
                        "reviewer": (
                            {
                                "decision": item.reviewer_report.decision,
                                "score": item.reviewer_report.score,
                                "summary": item.reviewer_report.summary,
                            }
                            if item.reviewer_report is not None
                            else None
                        ),
                        "updated_character_names": (
                            item.backfill_result.updated_character_names if item.backfill_result is not None else []
                        ),
                    }
                    for item in step_results
                ],
            },
        )

        return SingleSampleSmokeRunResult(
            run_id=run_id,
            sample=sample,
            prefix_snapshot=prefix_snapshot,
            step_results=step_results,
            authorized_inputs=authorized_inputs,
            retrieval_result=retrieval_result,
            writer_input_bundle=writer_input_bundle,
            prompt_text=prompt_text,
            generated_text=generated_text,
            compare_report=compare_report,
            reviewer_report=reviewer_report,
            run_dir=str(run_dir),
        )

    def _review_generated_text(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        authorized_inputs: AuthorizedInputs,
        generated_text: str,
    ) -> SmokeReviewerReport | None:
        if not self.reviewer_enabled:
            return None
        if self.reviewer_service is None:
            raise RuntimeError("reviewer_service with a real LLM config is required for smoke benchmark runs")
        return self.reviewer_service.review(
            sample=sample,
            step=step,
            authorized_inputs=authorized_inputs,
            generated_text=generated_text,
        )

    def _generate_text(
        self,
        *,
        run_id: str,
        artifact_prefix: str,
        prompt_text: str,
        writer_input_bundle: WriterInputBundle,
        authorized_inputs: AuthorizedInputs,
    ) -> str:
        if self.generation_service is None or self.generation_config is None:
            return self.text_generator(prompt_text, writer_input_bundle, authorized_inputs).strip()
        result = self.generation_service.generate(
            prompt=prompt_text,
            config=self.generation_config,
        )
        if self.generation_config.save_reasoning:
            self.run_writer.write_json(
                run_id,
                f"{artifact_prefix}/reasoning.json",
                {"steps": [item.to_dict() for item in result.reasoning_steps]},
            )
            self.run_writer.write_text(run_id, f"{artifact_prefix}/reasoning.md", result.reasoning_markdown)
        return result.generated_text.strip()

    def _build_writer_bundle(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        prefix_snapshot: PrefixRuntimeSnapshot,
        authorized_inputs: AuthorizedInputs,
        previous_generated_segment: str | None,
    ) -> tuple[CreativeKBRetrievalResult, WriterInputBundle]:
        db = NovelAgentDB(prefix_snapshot.db_path_obj)
        with db.connect() as conn:
            db.init_schema(conn)
            init_creative_kb_schema(conn)
            retrieval_result = self.orchestrator.run_online_creative_kb_path(
                conn,
                anchor_context=step.anchor_context.text,
                recent_window_summary=step.recent_window_summary,
                goal=self._resolve_goal(sample=sample, authorized_inputs=authorized_inputs),
                previous_generated_segment=previous_generated_segment,
                retrieval_context=self._build_retrieval_context(
                    sample=sample,
                    authorized_inputs=authorized_inputs,
                ),
                scene_plan=dict(authorized_inputs.scene_plan_seed),
                scene_brief=self._build_explicit_scene_brief(authorized_inputs),
                include_coarse_result=self.include_coarse_result,
                expand_reference_fragments=True,
            )
            retrieval_result = self._ensure_reference_fragments(
                conn,
                retrieval_result=retrieval_result,
            )
            context_payload = self.orchestrator.assemble_context_payload(
                conn,
                book_id=sample.config.book_id,
                document_title_index=prefix_snapshot.max_document_title_index,
                related_character_names=authorized_inputs.related_character_names,
            )
            writer_input_bundle = self.orchestrator.build_writer_input_bundle(
                anchor_context=step.anchor_context.text,
                recent_window_summary=step.recent_window_summary,
                retrieval_result=retrieval_result,
                context_payload=context_payload,
            )
        return retrieval_result, writer_input_bundle

    def _ensure_reference_fragments(
        self,
        conn,
        *,
        retrieval_result: CreativeKBRetrievalResult,
    ) -> CreativeKBRetrievalResult:
        if retrieval_result.rerank_result.selected_fragment_ids and retrieval_result.reference_fragments:
            return retrieval_result

        cards_repo = FragmentCardsRepo()
        cards = cards_repo.list_representatives(conn)
        if not cards:
            cards = cards_repo.list_all(conn)
        if not cards:
            return retrieval_result

        fallback_cards = cards[:2]
        fallback_ids = [card.fragment_id for card in fallback_cards]
        fallback_reference_fragments = [
            ExpandedReferenceFragment(
                fragment_id=card.fragment_id,
                doc_id=card.doc_id,
                source_path=card.source_path,
                source_excerpt=card.source_excerpt,
                content_summary=card.content_summary,
                style_profile_text=card.style_profile_text,
            )
            for card in fallback_cards
        ]
        return CreativeKBRetrievalResult(
            scene_brief=retrieval_result.scene_brief,
            rerank_result=RerankResult(
                scores=list(retrieval_result.rerank_result.scores),
                selected_fragment_ids=fallback_ids,
                selection_notes=(
                    retrieval_result.rerank_result.selection_notes + "; "
                    if retrieval_result.rerank_result.selection_notes
                    else ""
                )
                + "fallback representative fragments selected for smoke run",
            ),
            coarse_result=retrieval_result.coarse_result,
            reference_fragments=fallback_reference_fragments,
        )

    def _resolve_goal(
        self,
        *,
        sample: LoadedSmokeSample,
        authorized_inputs: AuthorizedInputs,
    ) -> str:
        if authorized_inputs.scene_brief_seed:
            return str(authorized_inputs.scene_brief_seed.get("scene_objective") or "")
        if authorized_inputs.current_unit_plan:
            return str(authorized_inputs.current_unit_plan.get("chapter_goal") or "")
        return f"续写 {sample.config.target_chapter_id} 的当前段落"

    def _build_retrieval_context(
        self,
        *,
        sample: LoadedSmokeSample,
        authorized_inputs: AuthorizedInputs,
    ) -> dict[str, list[str]]:
        return {
            "character_hits": list(authorized_inputs.related_character_names),
            "timeline_hits": [sample.config.target_chapter_id, sample.config.documents_cutoff.max_document_title_index],
            "lore_hits": _normalize_string_list(
                authorized_inputs.scene_brief_seed.get("preferred_tags")
                if authorized_inputs.scene_brief_seed
                else []
            ),
        }

    def _build_explicit_scene_brief(self, authorized_inputs: AuthorizedInputs) -> SceneBrief | None:
        if not authorized_inputs.scene_brief_seed:
            return None
        seed = dict(authorized_inputs.scene_brief_seed)
        if not seed.get("scene_objective"):
            return None
        return SceneBrief(
            scene_objective=str(seed.get("scene_objective") or ""),
            emotional_goal=str(seed.get("emotional_goal") or ""),
            conflict_goal=str(seed.get("conflict_goal") or ""),
            narrative_function=_normalize_string_list(seed.get("narrative_function")),
            emotion_mode=_normalize_string_list(seed.get("emotion_mode")),
            character_temperament=_normalize_string_list(seed.get("character_temperament")),
            relationship_state=_normalize_string_list(seed.get("relationship_state")),
            style_need=_normalize_string_list(seed.get("style_need")),
            must_avoid=_normalize_string_list(seed.get("must_avoid")),
            preferred_tags=_normalize_string_list(seed.get("preferred_tags")),
        )

    def _build_prompt(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        previous_generated_segment: str | None,
        authorized_inputs: AuthorizedInputs,
        writer_input_bundle: WriterInputBundle,
    ) -> str:
        scene_brief = writer_input_bundle.scene_brief
        prompt_payload = {
            "step_id": step.step_id,
            "scene_brief": scene_brief.to_dict(),
            "authorized_inputs": authorized_inputs.to_dict(),
            "previous_generated_segment": previous_generated_segment or "",
            "reference_fragments": [item.to_dict() for item in writer_input_bundle.reference_fragments],
            "context_payload": writer_input_bundle.context_payload.to_dict(),
        }
        prompt_json = json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        target_length_chars = max(0, int(authorized_inputs.target_length_chars or 0))
        length_hint = (
            f"目标长度：约 {target_length_chars} 字。即便真值片段较短，也应以扩写场景细节、动作、心理和对白的方式写得更充分。"
            if target_length_chars > 0
            else ""
        )
        return (
            f"你正在执行单样本冒烟续写。\n\n"
            f"锚点上下文：\n{step.anchor_context.text}\n\n"
            f"最近窗口摘要：\n{step.recent_window_summary}\n\n"
            f"{length_hint}\n\n"
            f"请基于下列结构化输入生成一段续写正文，保持与前缀一致，不要解释。\n\n"
            f"{prompt_json}"
        ).strip()

    def _backfill_generated_segment(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        prefix_snapshot: PrefixRuntimeSnapshot,
        chapter_index: int,
        generated_text: str,
        authorized_inputs: AuthorizedInputs,
    ) -> SmokeBackfillResult:
        db = NovelAgentDB(prefix_snapshot.db_path_obj)
        with db.connect() as conn:
            db.init_schema(conn)
            result = self.backfill_service.apply_generated_segment(
                conn,
                book_id=sample.config.book_id,
                chapter_index=chapter_index,
                step_id=step.step_id,
                generated_text=generated_text,
                prioritized_character_names=authorized_inputs.related_character_names,
            )
            conn.commit()
        return result

    def _step_prefix(self, *, step_number: int, step: LoadedSmokeStep) -> str:
        return f"step_{step_number}_{step.step_id}"

    def _resolve_target_chapter_index(
        self,
        *,
        sample: LoadedSmokeSample,
        prefix_snapshot: PrefixRuntimeSnapshot,
    ) -> int:
        digits = "".join(ch for ch in sample.config.target_chapter_id if ch.isdigit())
        if digits:
            return int(digits)
        return int(prefix_snapshot.max_document_title_index) + 1
