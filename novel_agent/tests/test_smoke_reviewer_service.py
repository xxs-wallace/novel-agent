from __future__ import annotations

from novel_agent.app.schemas.smoke_schema import (
    AuthorizedInputs,
    DocumentsCutoff,
    LoadedSmokeSample,
    LoadedSmokeStep,
    SmokeSampleConfig,
    SmokeTextArtifact,
)
from novel_agent.app.services.continuation_generation_service import ContinuationGenerationResult
from novel_agent.app.services.smoke_reviewer_service import SmokeReviewerService
from novel_agent.schemas import RunConfig


def _sample_and_step() -> tuple[LoadedSmokeSample, LoadedSmokeStep]:
    step = LoadedSmokeStep(
        step_id="step-1",
        anchor_context=SmokeTextArtifact(path="anchor.md", text="上一段停在两人雨中对峙。"),
        recent_window=[
            SmokeTextArtifact(path="recent.md", text="最近剧情里，人物没有和解，仍在雨中压着情绪交谈。")
        ],
        reference_truth=SmokeTextArtifact(path="truth.md", text="原文下一段里，人物继续在雨中对峙。"),
    )
    sample = LoadedSmokeSample(
        config=SmokeSampleConfig(
            sample_id="sample-1",
            book_id="book-1",
            target_chapter_id="chapter-2",
            anchor_context_path="anchor.md",
            recent_window_refs=["recent.md"],
            documents_cutoff=DocumentsCutoff(max_document_title_index="1"),
            reference_truth_path="truth.md",
        ),
        sample_path="sample.json",
        steps=[step],
    )
    return sample, step


def test_smoke_reviewer_report_schema_is_stable() -> None:
    sample, step = _sample_and_step()
    service = _reviewer_service(
        '{"decision":"borderline","score":0.58,"summary":"模型认为基本可读。",'
        '"checks":{"non_empty_length":{"status":"pass","score":1,"summary":"非空"},'
        '"recent_window_coherence":{"status":"borderline","score":0.55,"summary":"部分承接"},'
        '"logic_flow":{"status":"pass","score":0.7,"summary":"逻辑尚可"},'
        '"outline_alignment":{"status":"borderline","score":0.5,"summary":"规划贴合一般"},'
        '"reference_direction_alignment":{"status":"borderline","score":0.5,"summary":"方向部分一致"}},'
        '"issues":[]}'
    )

    report = service.review(
        sample=sample,
        step=step,
        authorized_inputs=AuthorizedInputs(
            current_unit_plan={
                "chapter_goal": "承接最近剧情窗口，推进雨中对峙。",
                "emotional_goal": "保持克制情绪。",
                "conflict_goal": "不要让冲突立刻解决。",
            }
        ),
        generated_text="雨声还在继续，人物把话压低，顺着刚才的对峙继续追问，没有让局面立刻和解。",
    )

    payload = report.to_dict()
    assert set(payload) == {
        "decision",
        "score",
        "summary",
        "checks",
        "issues",
        "generated_chars",
        "reference_truth_chars",
    }
    assert payload["decision"] in {"pass", "borderline", "fail"}
    assert {
        "recent_window_coherence",
        "logic_flow",
        "outline_alignment",
        "reference_direction_alignment",
    }.issubset(payload["checks"])
    assert payload["generated_chars"] > 0
    assert payload["reference_truth_chars"] == len(step.reference_truth.text)


def test_smoke_reviewer_empty_output_fails() -> None:
    sample, step = _sample_and_step()
    report = _reviewer_service(
        '{"decision":"fail","score":0,"summary":"模型认为生成为空。",'
        '"checks":{"non_empty_length":{"status":"fail","score":0,"summary":"空输出"}},'
        '"issues":[{"type":"empty_output","severity":"fatal","message":"生成文本为空","evidence":""}]}'
    ).review(
        sample=sample,
        step=step,
        authorized_inputs=AuthorizedInputs(),
        generated_text="",
    )

    assert report.decision == "fail"
    assert report.score == 0.0
    assert report.issues[0].type == "empty_output"


def test_smoke_reviewer_input_excludes_character_world_and_retrieval_sections() -> None:
    _sample, step = _sample_and_step()
    service = _reviewer_service("{}")

    payload = service.build_input_payload(
        step=step,
        authorized_inputs=AuthorizedInputs(
            prefix_facts={
                "context_payload": {
                    "world_summary_md": "世界观摘要不应进入 reviewer 输入。",
                    "character_profiles": [{"canonical_name": "角色档案"}],
                }
            },
            current_unit_plan={
                "chapter_goal": "承接最近剧情窗口。",
                "relationship_targets": ["人物关系不应进入 reviewer 输入"],
                "related_character_names": ["人物名单不应进入 reviewer 输入"],
                "character_temperament": ["人物档案不应进入 reviewer 输入"],
            },
        ),
        generated_text="继续当前剧情。",
    )
    payload_text = str(payload)

    assert "world_summary" not in payload_text
    assert "character_profiles" not in payload_text
    assert "relationship_targets" not in payload_text
    assert "reference_fragments" not in payload_text
    assert "retrieval" not in payload_text


def test_smoke_reviewer_uses_model_prompt_with_reference_truth() -> None:
    sample, step = _sample_and_step()
    captured: dict[str, str] = {}

    class _FakeGenerationService:
        def generate(self, *, prompt: str, config: RunConfig) -> ContinuationGenerationResult:
            captured["prompt"] = prompt
            return ContinuationGenerationResult(
                generated_text=(
                    '{"decision":"pass","score":0.72,"summary":"模型认为生成基本接上。",'
                    '"checks":{"non_empty_length":{"status":"pass","score":1,"summary":"非空"},'
                    '"recent_window_coherence":{"status":"pass","score":0.7,"summary":"承接最近窗口"},'
                    '"logic_flow":{"status":"pass","score":0.8,"summary":"逻辑顺"},'
                    '"outline_alignment":{"status":"borderline","score":0.55,"summary":"大纲贴合一般"},'
                    '"reference_direction_alignment":{"status":"pass","score":0.65,"summary":"接近原文方向"}},'
                    '"issues":[]}'
                ),
                reasoning_steps=[],
                reasoning_markdown="",
            )

    service = SmokeReviewerService(
        generation_service=_FakeGenerationService(),  # type: ignore[arg-type]
        generation_config=_run_config(),
    )

    report = service.review(
        sample=sample,
        step=step,
        authorized_inputs=AuthorizedInputs(current_unit_plan={"chapter_goal": "推进雨中对峙。"}),
        generated_text="人物继续在雨中对峙，把话压低，局面没有立刻解决。",
    )

    assert report.decision == "pass"
    assert report.score == 0.72
    assert report.summary == "模型认为生成基本接上。"
    assert "reference_truth" in captured["prompt"]
    assert step.reference_truth.text in captured["prompt"]
    assert "stitched_recent_plus_generated" in captured["prompt"]
    assert "character_profiles" not in captured["prompt"]
    assert "world_summary" not in captured["prompt"]
    assert "reference_fragments" not in captured["prompt"]


def _reviewer_service(model_response: str) -> SmokeReviewerService:
    class _FakeGenerationService:
        def generate(self, *, prompt: str, config: RunConfig) -> ContinuationGenerationResult:
            return ContinuationGenerationResult(
                generated_text=model_response,
                reasoning_steps=[],
                reasoning_markdown="",
            )

    return SmokeReviewerService(
        generation_service=_FakeGenerationService(),  # type: ignore[arg-type]
        generation_config=_run_config(),
    )


def _run_config() -> RunConfig:
    return RunConfig(
        prompt=None,
        model_type="InferenceClientModel",
        model_id="fake-model",
        provider=None,
        api_base=None,
        api_key=None,
        thinking=None,
        reasoning_effort=None,
        save_reasoning=False,
        action_type="tool_calling",
        tools=[],
        imports=[],
        verbosity_level=1,
        dry_run=False,
    )
