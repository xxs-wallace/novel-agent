from __future__ import annotations

from novel_agent.app.schemas.context_assembly_schema import ContextAssemblyPayload
from novel_agent.app.schemas.creative_kb_schema import ExpandedReferenceFragment, SceneBrief
from novel_agent.app.schemas.orchestration_schema import WriterInputBundle
from novel_agent.app.schemas.smoke_schema import (
    AuthorizedInputs,
    DocumentsCutoff,
    LoadedSmokeSample,
    LoadedSmokeStep,
    SmokeSampleConfig,
    SmokeTextArtifact,
)
from novel_agent.app.services.smoke_compare_service import SmokeCompareService


def _build_sample(*, mode: str = "chapter_authorized") -> LoadedSmokeSample:
    config = SmokeSampleConfig(
        sample_id=f"sample-{mode}",
        book_id="book-1",
        target_chapter_id="chapter-3",
        mode=mode,  # type: ignore[arg-type]
        anchor_context_path="/tmp/anchor.md",
        recent_window_refs=["/tmp/recent.md"],
        documents_cutoff=DocumentsCutoff(max_document_title_index="2"),
        reference_truth_path="/tmp/truth.md",
    )
    return LoadedSmokeSample(
        config=config,
        sample_path="/tmp/sample.json",
        steps=[
            LoadedSmokeStep(
                step_id="step-1",
                anchor_context=SmokeTextArtifact(path="/tmp/anchor.md", text="上一段停在林清没有直接回应。"),
                recent_window=[
                    SmokeTextArtifact(path="/tmp/recent.md", text="最近窗口里两人一直维持未和解的对峙状态。")
                ],
                reference_truth=SmokeTextArtifact(
                    path="/tmp/truth.md",
                    text="林清在雨里沉默了几秒，开口时仍压着悲意，没有让这场对峙立刻结束。",
                ),
            )
        ],
    )


def _build_writer_input_bundle() -> WriterInputBundle:
    return WriterInputBundle(
        anchor_context="上一段停在林清没有直接回应。",
        recent_window_summary="最近窗口里两人一直维持未和解的对峙状态。",
        scene_brief=SceneBrief(
            scene_objective="两人在雨中对峙，关系维持未和解状态。",
            emotional_goal="压住悲伤，保留余波",
            conflict_goal="保持当前冲突，不让问题过早解决",
            narrative_function=["承接推进"],
            emotion_mode=["克制表达"],
            character_temperament=["克制"],
            relationship_state=["未和解"],
            style_need=["中短句"],
            must_avoid=["避免设定冲突", "直接和解"],
            preferred_tags=["雨天", "对峙"],
        ),
        reference_fragments=[
            ExpandedReferenceFragment(
                fragment_id="frag-1",
                doc_id="doc-1",
                source_path="/tmp/ref.md",
                source_excerpt="林清没有立刻回应，只是把伞柄握得更紧。",
                content_summary="雨中对峙，关系仍未和解。",
                style_profile_text="克制压抑，中短句。",
            )
        ],
        context_payload=ContextAssemblyPayload(
            chapter_context=[],
            world_summary_md="现代都市背景，没有超自然设定。",
            character_profiles=[],
            story_outline_md="# 第3章\n两人在雨中对峙，关系维持未和解状态。",
            missing_context=[],
        ),
        sources=[{"path": "/tmp/ref.md", "snippet": "林清没有立刻回应，只是把伞柄握得更紧。"}],
    )


def test_smoke_compare_service_returns_borderline_or_better_report() -> None:
    sample = _build_sample()
    writer_input_bundle = _build_writer_input_bundle()
    authorized_inputs = AuthorizedInputs(
        prefix_facts={"documents_cutoff": "2"},
        current_unit_plan={
            "chapter_goal": "两人在雨中对峙，关系维持未和解状态。",
            "emotional_goal": "压住悲伤，保留余波",
            "conflict_goal": "保持当前冲突，不让问题过早解决",
            "must_avoid": ["避免设定冲突", "直接和解"],
        },
        scene_brief_seed={"scene_objective": "两人在雨中对峙，关系维持未和解状态。"},
        related_character_names=["林清"],
        target_length_chars=1200,
    )

    report = SmokeCompareService().compare(
        sample=sample,
        authorized_inputs=authorized_inputs,
        writer_input_bundle=writer_input_bundle,
        generated_text="林清在雨里沉默了几秒，仍没有让这场对峙立刻结束，只把伞柄握得更紧。",
    )

    assert report.hard_gate.passed is True
    assert report.scores.character_consistency is not None and report.scores.character_consistency >= 1.0
    assert report.scores.world_rule_compliance == 1.0
    assert report.scores.retrieval_effectiveness is not None and report.scores.retrieval_effectiveness > 0.0
    assert report.decision in {"pass", "borderline"}
    assert report.evidence_refs


def test_smoke_compare_service_marks_forbidden_reveal_as_fail() -> None:
    sample = _build_sample()
    writer_input_bundle = _build_writer_input_bundle()
    authorized_inputs = AuthorizedInputs(
        current_unit_plan={"must_avoid": ["直接和解"]},
        related_character_names=["林清"],
        target_length_chars=1200,
    )

    report = SmokeCompareService().compare(
        sample=sample,
        authorized_inputs=authorized_inputs,
        writer_input_bundle=writer_input_bundle,
        generated_text="林清忽然决定直接和解，还顺手施展了魔法。",
    )

    assert report.hard_gate.passed is False
    assert report.decision == "fail"
    assert report.weighted_score == 0.0
    assert any(issue.type == "forbidden_reveal" for issue in report.hard_gate.fatal_issues)
