from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.narrative_memory_pages_repo import NarrativeMemoryPagesRepo
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, StyleFeatures
from novel_agent.app.schemas.narrative_memory_schema import NarrativeMemoryPage
from novel_agent.app.services.reviewer_smoke_service import (
    ReviewerSmokeConfig,
    ReviewerSmokeModelConfig,
    ReviewerSmokeModelingArtifacts,
    ReviewerSmokeService,
)


class _ReviewerSmokeFakeModel:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(model_name="reviewer-smoke-fake-model")
        self.calls: list[dict[str, str]] = []

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if "smoke 测试输入构造器" in system_prompt:
            return json.dumps(self._case_generation(user_prompt), ensure_ascii=False)
        reviewer_id = self._reviewer_id(user_prompt)
        if "评审计划" in system_prompt:
            return json.dumps(self._plan(reviewer_id), ensure_ascii=False)
        if "正式评审" in system_prompt:
            return json.dumps(self._report(reviewer_id), ensure_ascii=False)
        if "报告自检" in system_prompt:
            return json.dumps({"status": "ok", "notes_zh": "报告符合 smoke contract。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected prompt: {system_prompt}")

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        _ = fallback_factory, use_fallback_on_error
        return {
            "scores": [
                {
                    "candidate_id": "frag-1",
                    "continuity_fit": 8,
                    "scene_function_fit": 8,
                    "character_temperament_fit": 7,
                    "relationship_state_fit": 7,
                    "emotion_expression_fit": 8,
                    "style_fit": 8,
                    "transferability": 8,
                    "context_dependency_penalty": 2,
                    "reason": "适合作为 smoke KB 查询候选。",
                }
            ]
        }, "{}"

    def _case_generation(self, user_prompt: str) -> dict[str, Any]:
        reviewer_id = self._reviewer_id(user_prompt)
        text_by_reviewer = {
            "outline_plot_development": (
                "一、雨夜对峙之后，众人没有继续追查旧案，而是直接确认所有阻力已经退场。\n"
                "二、主角在清晨宣布改去处理一条全新的线索，旧有矛盾暂时搁置。\n"
                "三、章节末尾安排双方迅速达成共同目标，但中间缺少行动、代价和信息来源。"
            ),
            "chapter_synopsis_plot_character": (
                "本章从雨后的庭院开始。此前仍彼此戒备的两人忽然以多年同盟的姿态交换计划，"
                "其中一人主动替对方隐瞒旧案细节，并把仍未解决的误会当作早已冰释。"
                "随后他们决定离开原本的追查方向，转而接受一个陌生人的安排，章节结尾以轻松告别收束。"
            ),
            "local_draft_continuity": (
                "天色亮起来的时候，他们已经坐在热闹的酒楼里谈笑。昨夜那些没有说出口的话像从未存在，"
                "桌上的菜一道接一道端上来，众人很快把旧案处理结果总结完毕。"
                "他甚至笑着拍了拍同伴的肩，说接下来只需要按名单逐项完成，语气轻快得像在安排一次寻常远行。"
            ),
            "memory_draft_consistency": (
                "他站在门外，心里十分笃定：自己从未在雨夜与那个人对峙，也从不曾答应继续追查旧事。"
                "那些所谓的沉默和试探只是旁人的误会，他们之间一直亲密无间。"
                "因此他毫不犹豫地把旧案卷宗交给对方，仿佛这件事早在很久以前就已彻底结束。"
            ),
            "kb_draft_style_atmosphere": (
                "当前场景进入收尾阶段。主角快速完成情绪确认，随后对同伴说明下一步执行路径。"
                "雨声、沉默和停顿都被压缩成几句清楚的流程描述，人物只用简短口号表达决心。"
                "整个段落像一份进度记录，直接列出目标、风险和处理结果，没有继续积累夜色中的压迫感。"
            ),
        }
        return {
            "text": text_by_reviewer[reviewer_id],
            "construction_notes_zh": "从留出正文改造成自然目标，并植入对应风险。",
            "expected_issue_types": ["真实输入可触发对应 Reviewer 风险。"],
        }

    def _reviewer_id(self, text: str) -> str:
        for reviewer_id in (
            "outline_plot_development",
            "chapter_synopsis_plot_character",
            "local_draft_continuity",
            "memory_draft_consistency",
            "kb_draft_style_atmosphere",
        ):
            if reviewer_id in text:
                return reviewer_id
        return "local_draft_continuity"

    def _plan(self, reviewer_id: str) -> dict[str, Any]:
        tool_requests: list[dict[str, Any]] = []
        if reviewer_id == "outline_plot_development":
            tool_requests = [{"tool": "memory_query", "intent": "查询前序事件线索", "query": "关键事件 因果链"}]
        elif reviewer_id == "chapter_synopsis_plot_character":
            tool_requests = [{"tool": "memory_query", "intent": "查询人物关系状态", "query": "人物 关系 状态"}]
        elif reviewer_id == "memory_draft_consistency":
            tool_requests = [
                {"tool": "memory_query", "intent": "查询历史事件", "query": "历史事件"},
                {"tool": "memory_query", "intent": "查询人物关系", "query": "人物关系"},
            ]
        elif reviewer_id == "kb_draft_style_atmosphere":
            tool_requests = [{"tool": "kb_retrieval", "intent": "查询相似风格段落", "query": "文风 氛围 场景"}]
        return {
            "schema_version": "1.0",
            "reviewer_id": reviewer_id,
            "target_id": "target-from-model",
            "dimensions": ["连续性", "一致性"],
            "initial_risks": ["构造目标存在明显偏离，需要模型评审。"],
            "tool_requests": tool_requests,
            "can_judge_without_context": not bool(tool_requests),
            "notes_zh": "按 smoke 要求生成计划。",
        }

    def _report(self, reviewer_id: str) -> dict[str, Any]:
        category = {
            "outline_plot_development": "阶段推进",
            "chapter_synopsis_plot_character": "人物一致性",
            "local_draft_continuity": "局部承接",
            "memory_draft_consistency": "历史一致性",
            "kb_draft_style_atmosphere": "文风氛围",
        }[reviewer_id]
        return {
            "status": "success",
            "score": 61,
            "score_usage": "reference_only",
            "summary_zh": f"{category}存在明显问题，分数只作为参考。",
            "dimension_scores": {category: 61},
            "findings": [
                {
                    "finding_id": "finding-001",
                    "severity": "major",
                    "category": category,
                    "message_zh": f"{category}与授权证据或目标上下文不够一致。",
                    "evidence_refs": ["ev-target-001"],
                    "suggestion_zh": "补足过渡、因果和证据依据。",
                    "confidence": 0.8,
                }
            ],
            "evidence_refs": [
                {
                    "evidence_id": "ev-target-001",
                    "source_type": "target_text",
                    "source_id": "target-from-model",
                    "quote": "Reviewer Smoke 构造",
                    "summary_zh": "目标文本标记为 smoke 构造。",
                }
            ],
            "suggested_revision_focus": ["补足过渡与证据。"],
            "confidence": 0.8,
        }


def test_reviewer_smoke_service_writes_five_cases_and_summary(tmp_path: Path) -> None:
    repo_root = tmp_path
    output_root = tmp_path / "runs" / "reviewer_smoke"
    fake_model = _ReviewerSmokeFakeModel()

    def modeling_builder(config: ReviewerSmokeConfig, run_dir: Path, run_id: str) -> ReviewerSmokeModelingArtifacts:
        return _fake_modeling_artifacts(run_dir=run_dir, book_id=f"book-{run_id}")

    service = ReviewerSmokeService(
        repo_root=repo_root,
        model_client_factory=lambda _model_config: fake_model,  # type: ignore[return-value]
        modeling_builder=modeling_builder,
    )

    summary = service.run(
        ReviewerSmokeConfig(
            repo_root=repo_root,
            run_id="unit-smoke",
            output_root=output_root,
            model=ReviewerSmokeModelConfig(model_name="fake-model"),
        )
    )

    assert summary["status"] == "success"
    assert summary["score_usage"] == "reference_only"
    assert set(summary["reviewers"]) == {
        "outline_plot_development",
        "chapter_synopsis_plot_character",
        "local_draft_continuity",
        "memory_draft_consistency",
        "kb_draft_style_atmosphere",
    }
    assert summary["reviewers"]["memory_draft_consistency"]["memory_trace_present"] is True
    assert summary["reviewers"]["kb_draft_style_atmosphere"]["kb_trace_present"] is True
    assert summary["markdown_report_path"].endswith("reviewer_smoke_constructed_cases_and_reports.md")
    assert len(fake_model.calls) >= 20

    run_dir = output_root / "unit-smoke"
    assert (run_dir / "reviewer_smoke_constructed_cases_and_reports.md").exists()
    assert (run_dir / "modeling" / "source_manifest.json").exists()
    assert (run_dir / "modeling" / "memory_manifest.json").exists()
    assert (run_dir / "modeling" / "kb_manifest.json").exists()
    for reviewer_id in summary["reviewers"]:
        case_dir = run_dir / "cases" / reviewer_id
        assert (case_dir / "smoke_case.json").exists()
        assert (case_dir / "review_request.json").exists()
        assert (case_dir / "resolved_target.json").exists()
        assert (case_dir / "loop_trace.json").exists()
        assert (case_dir / "report.json").exists()
        assert (case_dir / "raw_model_responses").exists()
        smoke_case = json.loads((case_dir / "smoke_case.json").read_text(encoding="utf-8"))
        assert smoke_case["metadata"]["constructed_for_smoke"] is True
        assert smoke_case["metadata"]["heldout_text_used"] is True
        assert "虚假" not in smoke_case["text"]
        assert "constructed_for_smoke" not in smoke_case["text"]
        assert "最近真实正文窗口" not in smoke_case["text"]
        request = json.loads((case_dir / "review_request.json").read_text(encoding="utf-8"))
        assert request["target"]["metadata"]["constructed_for_smoke"] is True
        report = json.loads((case_dir / "report.json").read_text(encoding="utf-8"))
        assert report["score_usage"] == "reference_only"


def test_reviewer_smoke_service_returns_needs_model_when_model_client_cannot_build(tmp_path: Path) -> None:
    def raise_missing_model(_model_config: ReviewerSmokeModelConfig):
        raise RuntimeError("OpenAIModel API key is required for non-dry-run model access")

    service = ReviewerSmokeService(
        repo_root=tmp_path,
        model_client_factory=raise_missing_model,  # type: ignore[arg-type]
    )

    summary = service.run(
        ReviewerSmokeConfig(
            repo_root=tmp_path,
            run_id="missing-model",
            output_root=tmp_path / "runs" / "reviewer_smoke",
            model=ReviewerSmokeModelConfig(model_name="fake-model"),
        )
    )

    assert summary["status"] == "needs_model"
    assert "API key" in summary["error"]
    saved = json.loads((tmp_path / "runs" / "reviewer_smoke" / "missing-model" / "summary.json").read_text(encoding="utf-8"))
    assert saved["status"] == "needs_model"


def _fake_modeling_artifacts(*, run_dir: Path, book_id: str) -> ReviewerSmokeModelingArtifacts:
    modeling_dir = run_dir / "modeling"
    modeling_dir.mkdir(parents=True, exist_ok=True)
    source_dir = modeling_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    prefix_path = source_dir / "reviewer_smoke_prefix_source.txt"
    heldout_path = source_dir / "reviewer_smoke_heldout_source.txt"
    prefix_path.write_text("人物在雨中保持对峙，核心矛盾尚未解决。\n最近段落停在紧张沉默中。\n", encoding="utf-8")
    heldout_path.write_text(
        "雨声渐渐小了，门外的人仍没有离开。他把旧案卷宗按在袖中，知道这一夜还没有真正结束。\n"
        "对方低声问他是否还要继续追查，他没有立刻回答，只看着檐下积水映出的灯影。\n"
        "他们之间仍旧隔着许多没有说破的怀疑，谁也不能立刻相信谁。"
        "直到远处传来脚步声，他才把话压回喉咙里，准备沿着昨夜留下的线索继续往前走。\n"
        "巷口的灯忽明忽暗，像把每个人的影子都拉得很长。"
        "他知道若此刻退后，旧案里还没浮出的名字就会再次沉下去，"
        "而眼前这个人也不会再给他第二次开口的机会。\n",
        encoding="utf-8",
    )
    db_path = modeling_dir / "reviewer_smoke.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        doc_ids = []
        for index, content in enumerate(
            [
                "人物在雨中保持对峙，核心矛盾尚未解决，情绪仍然压着。",
                "其中一人提出继续追查旧事件，另一人暂时没有表态。",
                "最近段落停在紧张沉默中，场景仍在原处，动作没有完成。",
            ],
            start=1,
        ):
            doc_ids.append(
                DocumentsRepo().insert_document(
                    conn,
                    {
                        "book_id": book_id,
                        "content": content,
                        "path": f"doc-{index}.txt",
                        "scope": "body",
                        "document_title": f"段落 {index}",
                        "document_title_index": index,
                        "content_chars": len(content),
                        "source_path": "fake-source.txt",
                        "source_file_name": "fake-source.txt",
                        "source_start_offset": index * 100,
                        "source_end_offset": index * 100 + len(content),
                        "character_keywords": ["动态人物"],
                        "content_tags": ["对峙"],
                        "created_at": "2026-05-20T00:00:00Z",
                        "updated_at": "2026-05-20T00:00:00Z",
                    },
                )
            )
        pages_repo = NarrativeMemoryPagesRepo()
        pages_repo.upsert(
            conn,
            book_id=book_id,
            page=NarrativeMemoryPage(
                page_id="mem-summary-1",
                page_type="event_summary",
                summary="动态人物在雨中对峙，旧事件尚未解决，双方关系仍处于紧张状态。",
                child_refs=["event-1"],
                source_doc_ids=doc_ids[:2],
                source_doc_range="1-2",
                updated_at="2026-05-20T00:00:00Z",
            ),
        )
        pages_repo.upsert(
            conn,
            book_id=book_id,
            page=NarrativeMemoryPage(
                page_id="mem-summary-2",
                page_type="event_summary",
                summary="最近场景仍停在原地沉默，行动链没有完成，人物没有达成和解。",
                child_refs=["event-2"],
                source_doc_ids=doc_ids[1:],
                source_doc_range="2-3",
                updated_at="2026-05-20T00:00:00Z",
            ),
        )
        FragmentCardsRepo().upsert_cards(
            conn,
            [
                FragmentCard(
                    fragment_id="frag-1",
                    doc_id=str(doc_ids[0]),
                    document_title="段落 1",
                    document_title_index="1",
                    is_cluster_representative=True,
                    source_path="fake-source.txt",
                    source_offsets=(100, 140),
                    source_excerpt="人物在雨中保持对峙，核心矛盾尚未解决。",
                    content_summary="雨中对峙场景，以克制动作和压抑氛围推进。",
                    narrative_function=["局部承接"],
                    narrative_function_text="通过沉默和动作维持冲突压力。",
                    scene_space_tags=["雨中"],
                    event_tags=["对峙"],
                    emotion_tags=["压抑"],
                    emotion_mechanism_text="用停顿和细节积累紧张感。",
                    expression_mode_tags=["细节描写"],
                    preferred_tags=["对峙"],
                    pov_mode="第三人称",
                    character_focus=["动态人物"],
                    character_temperament=["克制"],
                    character_relation_text="关系紧张，未达成和解。",
                    relationship_state=["紧张"],
                    continuity_phase="承接",
                    style_features=StyleFeatures(
                        sentence_rhythm="中短句交替",
                        dialogue_density="低",
                        interiority_density="中",
                        imagery_density="中",
                    ),
                    style_profile_text="以克制动作、环境细节和压抑停顿形成氛围。",
                    transferability_score=0.8,
                    context_dependency_level="medium",
                )
            ],
        )
        conn.commit()

    source_manifest = {
        "schema_version": "1.0",
        "book_id": book_id,
        "inserted_documents": 3,
        "source_split": {
            "prefix_path": str(prefix_path),
            "heldout_path": str(heldout_path),
            "memory_kb_source_scope": "prefix_only",
            "review_target_source_scope": "heldout_transformed_only",
            "constructed_for_smoke_written_to_memory_or_kb": False,
        },
    }
    memory_manifest = {"schema_version": "1.0", "book_id": book_id, "page_count": 2}
    kb_manifest = {"schema_version": "1.0", "book_id": book_id, "built_fragment_count": 1}
    _write_json(modeling_dir / "source_manifest.json", source_manifest)
    _write_json(modeling_dir / "memory_manifest.json", memory_manifest)
    _write_json(modeling_dir / "kb_manifest.json", kb_manifest)
    return ReviewerSmokeModelingArtifacts(
        run_dir=run_dir,
        db_path=db_path,
        book_id=book_id,
        source_path=prefix_path,
        source_manifest=source_manifest,
        memory_manifest=memory_manifest,
        kb_manifest=kb_manifest,
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
