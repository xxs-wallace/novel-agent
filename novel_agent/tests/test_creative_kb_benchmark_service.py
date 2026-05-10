from __future__ import annotations

import json
from pathlib import Path

from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.fragment_clusters_repo import FragmentClustersRepo
from novel_agent.app.schemas.creative_kb_benchmark_schema import (
    CreativeKBBenchmarkInput,
    KBClusterReviewReport,
    KBFragmentCardReviewReport,
    KBRetrievalReviewReport,
    KBWriterABReport,
)
from novel_agent.app.schemas.creative_kb_schema import (
    CoarseRetrievalResult,
    CreativeKBBuildResult,
    CreativeKBRetrievalResult,
    ExpandedReferenceFragment,
    FragmentCard,
    FragmentCluster,
    RerankResult,
    RerankScore,
    StyleFeatures,
)
from novel_agent.app.services.creative_kb_benchmark_service import CreativeKBBenchmarkService
from novel_agent.app.services.creative_kb_reviewer_service import CreativeKBReviewerService
from novel_agent.app.services.creative_kb_writer_ab_service import CreativeKBWriterABService


def _source_text() -> str:
    paragraphs = [
        "雨停之前，林清一直站在旧站台边，她把想说的话压在喉咙里，只让手指慢慢松开伞柄。",
        "对面的人没有催她，只是把车票折成很小的一片，像把刚刚的争执也折进沉默里面。",
        "巷口忽然传来急促脚步声，巡夜灯从墙面扫过来，所有人都意识到刚刚的平静只是短暂停顿。",
        "林清先把纸袋塞进怀里，又回头确认同伴还跟着，她没有解释，只低声说现在必须换路。",
        "他们在废弃书库里找到一张旧图，图上的标记和先前的传闻吻合，却故意漏掉了最关键的门牌。",
        "她看完之后没有立刻下结论，只把图纸翻到背面，发现那行小字来自很多年前的同一场事故。",
        "门外的脚步声越来越近，窗框被风撞出细响，林清终于明白有人一直在引他们来到这里。",
        "她把图纸塞回信封，示意同伴先走，自己则留在阴影里等待那个熟悉的敲门节奏。",
    ]
    return "\n\n".join(paragraphs) + "\n"


def _card(
    *,
    fragment_id: str,
    doc_id: str,
    cluster_id: str,
    content_summary: str,
    narrative_function: list[str],
    emotion_tags: list[str],
    relationship_state: list[str],
    preferred_tags: list[str],
    context_dependency_level: str = "low",
) -> FragmentCard:
    return FragmentCard(
        fragment_id=fragment_id,
        doc_id=doc_id,
        document_title="Benchmark Prefix",
        document_title_index="1",
        cluster_id=cluster_id,
        is_cluster_representative=True,
        source_path="/tmp/source.txt",
        source_offsets=(0, 80),
        source_excerpt=content_summary,
        content_summary=content_summary,
        narrative_function=narrative_function,
        narrative_function_text=" / ".join(narrative_function),
        scene_space_tags=["雨夜"],
        event_tags=preferred_tags,
        emotion_tags=emotion_tags,
        emotion_mechanism_text="通过动作、停顿和短对白维持情绪压力。",
        expression_mode_tags=["动作描写"],
        preferred_tags=preferred_tags,
        pov_mode="近距离第三人称",
        character_focus=["林清"],
        character_temperament=["克制"],
        character_relation_text="关系阶段保持克制推进。",
        relationship_state=relationship_state,
        continuity_phase="承接推进",
        style_features=StyleFeatures(
            sentence_rhythm="中短句",
            dialogue_density="低",
            interiority_density="中",
            imagery_density="中",
        ),
        style_profile_text="中短句、低对白、动作承接。",
        transferability_score=0.85,
        context_dependency_level=context_dependency_level,  # type: ignore[arg-type]
    )


class _FakeCreativeKBFacade:
    def __init__(
        self,
        *,
        cards_repo: FragmentCardsRepo,
        clusters_repo: FragmentClustersRepo,
        empty: bool = False,
    ) -> None:
        self.cards_repo = cards_repo
        self.clusters_repo = clusters_repo
        self.empty = empty

    def build_creative_kb(self, conn, *, documents, commit_batch_size=1024, progress_callback=None):  # noqa: ANN001
        _ = commit_batch_size
        _ = progress_callback
        if self.empty:
            return CreativeKBBuildResult(warnings=["fake empty kb"])

        cards = [
            _card(
                fragment_id="frag-emotion",
                doc_id=str(documents[0].doc_id),
                cluster_id="cluster-emotion",
                content_summary="雨夜里用沉默和动作收束关系张力。",
                narrative_function=["情绪停顿", "关系收束"],
                emotion_tags=["克制", "迟疑"],
                relationship_state=["对峙后未完全和解"],
                preferred_tags=["告别", "停顿"],
            ),
            _card(
                fragment_id="frag-action",
                doc_id=str(documents[1].doc_id),
                cluster_id="cluster-action",
                content_summary="外部脚步逼近，角色用行动推进局面。",
                narrative_function=["冲突升级", "行动推进"],
                emotion_tags=["紧张", "压迫"],
                relationship_state=["临时协作"],
                preferred_tags=["追逐", "对抗", "调查"],
            ),
            _card(
                fragment_id="frag-info",
                doc_id=str(documents[2].doc_id),
                cluster_id="cluster-info",
                content_summary="旧图纸揭示线索并承接既有事故设定。",
                narrative_function=["信息揭示", "设定承接"],
                emotion_tags=["惊疑", "克制"],
                relationship_state=["信息不对称"],
                preferred_tags=["线索", "调查", "秘密"],
            ),
            _card(
                fragment_id="frag-decoy",
                doc_id=str(documents[3].doc_id),
                cluster_id="cluster-decoy",
                content_summary="高上下文依赖的旧事故余波片段。",
                narrative_function=["余波整理"],
                emotion_tags=["疲惫"],
                relationship_state=["共同承担后果"],
                preferred_tags=["余波", "整理"],
                context_dependency_level="high",
            ),
        ]
        clusters = [
            FragmentCluster("cluster-emotion", "情绪停顿", "frag-emotion", 1, "singleton"),
            FragmentCluster("cluster-action", "行动推进", "frag-action", 1, "singleton"),
            FragmentCluster("cluster-info", "信息揭示", "frag-info", 1, "singleton"),
            FragmentCluster("cluster-decoy", "高依赖余波", "frag-decoy", 1, "singleton"),
        ]
        self.cards_repo.upsert_cards(conn, cards)
        self.clusters_repo.upsert_clusters(conn, clusters)
        return CreativeKBBuildResult(
            built_fragment_count=len(cards),
            built_cluster_count=len(clusters),
            representative_count=len(cards),
            fragment_ids=[card.fragment_id for card in cards],
            cluster_ids=[cluster.cluster_id for cluster in clusters],
        )


class _FakeRetrievalFacade:
    def build_scene_brief_and_retrieve(
        self,
        conn,  # noqa: ANN001
        *,
        retrieval_input,
        scene_brief,
        include_coarse_result=False,
        expand_reference_fragments=False,
    ) -> CreativeKBRetrievalResult:
        _ = conn
        _ = retrieval_input
        _ = include_coarse_result
        _ = expand_reference_fragments
        narrative_function = set(scene_brief.narrative_function)
        if "冲突升级" in narrative_function:
            selected_id = "frag-action"
        elif "信息揭示" in narrative_function:
            selected_id = "frag-info"
        else:
            selected_id = "frag-emotion"
        scores = [
            RerankScore(candidate_id=selected_id, cluster_id="cluster-a", final_score=0.9, reason="matches case"),
            RerankScore(candidate_id="frag-decoy", cluster_id="cluster-decoy", final_score=0.3, reason="decoy"),
        ]
        return CreativeKBRetrievalResult(
            scene_brief=scene_brief,
            coarse_result=CoarseRetrievalResult(
                candidate_fragment_ids=[selected_id, "frag-decoy"],
                coarse_scores={selected_id: 1.0, "frag-decoy": 0.2},
            ),
            rerank_result=RerankResult(scores=scores, selected_fragment_ids=[selected_id]),
            reference_fragments=[
                ExpandedReferenceFragment(
                    fragment_id=selected_id,
                    doc_id="1",
                    source_path="/tmp/source.txt",
                    source_excerpt="fake selected excerpt",
                    content_summary="fake selected summary",
                    style_profile_text="fake selected style",
                )
            ],
        )


class _FakeReviewerModelClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.prompts: list[dict[str, str]] = []

    def generate_json(self, *, system_prompt: str, user_prompt: str):  # noqa: ANN201
        self.prompts.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if not self.responses:
            raise RuntimeError("No fake reviewer response configured")
        return self.responses.pop(0), "{}"


class _FakeWriter:
    def __init__(self) -> None:
        self.execution_inputs: list[dict[str, object]] = []

    def generate_draft_from_execution_input(self, execution_input: dict[str, object]) -> str:
        self.execution_inputs.append(execution_input)
        variant = dict(execution_input.get("kb_variant") or {}).get("name")
        bundle = dict(execution_input.get("style_reference_bundle") or {})
        reference_count = len(bundle.get("references") or [])
        return f"{variant} draft with {reference_count} references"


class _FakeWriterABReviewer:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def build_writer_ab_prompt_artifact(self, *, payload: dict[str, object]) -> dict[str, object]:
        return {
            "review_type": "writer_ab",
            "input": payload,
            "system_prompt": "Writer A/B fake system",
            "user_prompt": json.dumps(payload, ensure_ascii=False),
        }

    def review_writer_ab(self, *, payload: dict[str, object]) -> KBWriterABReport:
        self.payloads.append(payload)
        return KBWriterABReport(
            decision="pass",
            score=0.64,
            winner="kb_enabled",
            variant_scores={"kb_enabled": 0.70, "kb_disabled": 0.52, "kb_random": 0.38},
            negative_transfer_issues=["kb_random 引入错误关系阶段"],
            summary="kb_enabled 相比 no-KB 和 random references 有可观测增益。",
            checks={
                "synopsis_coverage": "pass",
                "recent_window_coherence": "pass",
                "emotion_mechanism_quality": "pass",
                "relationship_state_fit": "pass",
                "style_stability": "pass",
                "negative_transfer_from_references": "borderline",
            },
        )


def _fragment_review_payload(score: float = 0.74) -> dict[str, object]:
    return {
        "decision": "pass",
        "score": score,
        "summary": "card 忠实且可迁移。",
        "checks": {
            "faithfulness": "pass",
            "retrievability": "pass",
            "narrative_function": "pass",
            "emotion_mechanism": "pass",
            "relationship_facts": "pass",
            "style_transferability": "pass",
            "context_dependency_risk": "pass",
        },
        "issues": [],
    }


def _cluster_review_payload(score: float = 0.66) -> dict[str, object]:
    return {
        "decision": "pass",
        "score": score,
        "summary": "cluster 近重复合理，代表片段可用。",
        "checks": {
            "near_duplicate_fit": "pass",
            "false_merge_risk": "pass",
            "representative_quality": "pass",
        },
        "issues": [],
    }


def _retrieval_review_payload(
    score: float = 0.68,
    *,
    top1_status: str = "pass",
    context_status: str = "pass",
) -> dict[str, object]:
    return {
        "decision": "pass" if score >= 0.60 else "borderline",
        "score": score,
        "summary": "selected references 相对 decoy 更适合当前 SceneBrief。",
        "checks": {
            "top1_beats_decoys": top1_status,
            "selected_fragments_match_scene_brief": "pass",
            "scene_function_fit": "pass",
            "emotion_mechanism_fit": "pass",
            "relationship_state_fit": "pass",
            "style_reference_value": "pass",
            "transferability": "pass",
            "cluster_diversity": "pass",
            "context_dependency_risk": context_status,
            "negative_transfer_risk": "pass",
        },
        "selected_fragment_ids": ["frag-emotion"],
        "decoy_fragment_ids": ["frag-decoy"],
        "issues": [],
    }


def _writer_ab_review_payload() -> dict[str, object]:
    return {
        "decision": "pass",
        "score": 0.64,
        "winner": "kb_enabled",
        "variant_scores": {
            "kb_enabled": 0.70,
            "kb_disabled": 0.52,
            "kb_random": 0.38,
        },
        "negative_transfer_issues": ["kb_random 引入错误关系阶段"],
        "summary": "kb_enabled 相比 no-KB 和 random references 有可观测增益。",
        "checks": {
            "synopsis_coverage": "pass",
            "recent_window_coherence": "pass",
            "emotion_mechanism_quality": "pass",
            "relationship_state_fit": "pass",
            "style_stability": "pass",
            "negative_transfer_from_references": "borderline",
        },
        "issues": [],
    }


def test_kb_quality_review_report_schemas_round_trip() -> None:
    card_report = KBFragmentCardReviewReport(
        fragment_id="frag-1",
        doc_id="doc-1",
        decision="pass",
        score=0.73,
        summary="建卡质量可用。",
        checks={
            "faithfulness": "pass",
            "retrievability": "pass",
            "narrative_function": "borderline",
            "emotion_mechanism": "pass",
            "relationship_facts": "pass",
            "style_transferability": "pass",
            "context_dependency_risk": "borderline",
        },
        issues=["上下文依赖略高"],
    )
    cluster_report = KBClusterReviewReport(
        cluster_id="cluster-1",
        representative_fragment_id="frag-1",
        member_fragment_ids=["frag-1", "frag-2"],
        decision="borderline",
        score=0.55,
        summary="同簇机制接近，但代表片段优势有限。",
        checks={
            "near_duplicate_fit": "pass",
            "false_merge_risk": "borderline",
            "representative_quality": "borderline",
        },
        issues=["代表片段优势不明显"],
    )
    retrieval_report = KBRetrievalReviewReport(
        case_id="case-001",
        decision="pass",
        score=0.67,
        summary="top references 优于 decoy。",
        checks={
            "top1_beats_decoys": "pass",
            "selected_fragments_match_scene_brief": "pass",
            "scene_function_fit": "pass",
            "emotion_mechanism_fit": "pass",
            "relationship_state_fit": "pass",
            "style_reference_value": "pass",
            "transferability": "pass",
            "cluster_diversity": "pass",
            "context_dependency_risk": "borderline",
            "negative_transfer_risk": "pass",
        },
        selected_fragment_ids=["frag-1"],
        decoy_fragment_ids=["frag-9"],
        issues=[],
    )
    writer_ab_report = KBWriterABReport(
        decision="pass",
        score=0.64,
        winner="kb_enabled",
        variant_scores={"kb_enabled": 0.70, "kb_disabled": 0.52, "kb_random": 0.38},
        negative_transfer_issues=["kb_random 引入错误关系阶段"],
        summary="kb_enabled 有稳定增益。",
        checks={
            "synopsis_coverage": "pass",
            "recent_window_coherence": "pass",
            "emotion_mechanism_quality": "pass",
            "relationship_state_fit": "pass",
            "style_stability": "pass",
            "negative_transfer_from_references": "borderline",
        },
    )

    assert KBFragmentCardReviewReport.from_dict(card_report.to_dict()).to_dict() == card_report.to_dict()
    assert KBClusterReviewReport.from_dict(cluster_report.to_dict()).to_dict() == cluster_report.to_dict()
    assert KBRetrievalReviewReport.from_dict(retrieval_report.to_dict()).to_dict() == retrieval_report.to_dict()
    assert KBWriterABReport.from_dict(writer_ab_report.to_dict()).to_dict() == writer_ab_report.to_dict()


def test_creative_kb_reviewer_service_parses_fake_llm_outputs() -> None:
    model_client = _FakeReviewerModelClient(
        [
            _fragment_review_payload(),
            _cluster_review_payload(),
            _retrieval_review_payload(),
            _writer_ab_review_payload(),
        ]
    )
    reviewer = CreativeKBReviewerService(model_client=model_client)
    card = _card(
        fragment_id="frag-1",
        doc_id="doc-1",
        cluster_id="cluster-1",
        content_summary="雨夜停顿收束关系。",
        narrative_function=["情绪停顿", "关系收束"],
        emotion_tags=["克制"],
        relationship_state=["未和解"],
        preferred_tags=["告别", "停顿"],
    )
    cluster = FragmentCluster("cluster-1", "雨夜停顿", "frag-1", 1, "same mechanism")

    card_report = reviewer.review_fragment_card(
        original_document_excerpt="原文里人物在雨夜沉默，关系没有立刻和解。",
        fragment_card=card,
    )
    cluster_report = reviewer.review_cluster(
        cluster=cluster,
        members=[card],
        representative_card=card,
    )
    retrieval_report = reviewer.review_retrieval_case(
        case_id="case-001",
        payload={
            "scene_brief": {"scene_objective": "关系收束"},
            "anchor_context": "雨夜对峙。",
            "recent_window_summary": "关系未和解。",
            "selected_references": [{"fragment_id": "frag-1"}],
            "decoy_references": [{"fragment_id": "frag-9"}],
            "rejected_high_score_references": [],
            "rerank_scores": [],
        },
    )
    writer_ab_report = reviewer.review_writer_ab(
        payload={
            "reference_story_synopsis": {"combined_synopsis": "关系停顿"},
            "reference_truth": "原文参考。",
            "variants": {
                "kb_enabled": {
                    "draft": "关系停顿写得稳定。",
                    "selected_fragment_ids": ["frag-1"],
                    "reference_fragment_summaries": [{"fragment_id": "frag-1"}],
                },
                "kb_disabled": {"draft": "空泛。", "selected_fragment_ids": [], "reference_fragment_summaries": []},
                "kb_random": {
                    "draft": "关系阶段错误。",
                    "selected_fragment_ids": ["frag-9"],
                    "reference_fragment_summaries": [{"fragment_id": "frag-9"}],
                },
            },
        }
    )

    assert card_report.decision == "pass"
    assert card_report.checks["faithfulness"] == "pass"
    assert cluster_report.checks["representative_quality"] == "pass"
    assert retrieval_report.checks["top1_beats_decoys"] == "pass"
    assert writer_ab_report.winner == "kb_enabled"
    assert writer_ab_report.variant_scores["kb_random"] == 0.38
    assert "fragment_card" in model_client.prompts[0]["user_prompt"]
    assert "member_cards" in model_client.prompts[1]["user_prompt"]
    assert "decoy" in model_client.prompts[2]["user_prompt"]
    assert "Writer A/B" in model_client.prompts[3]["system_prompt"]


def test_retrieval_decoy_builder_covers_all_types_and_missing_reasons() -> None:
    service = CreativeKBBenchmarkService()
    top = _card(
        fragment_id="frag-top",
        doc_id="1",
        cluster_id="cluster-main",
        content_summary="关系停顿。",
        narrative_function=["情绪停顿", "关系收束"],
        emotion_tags=["克制"],
        relationship_state=["对峙后未完全和解"],
        preferred_tags=["告别", "停顿"],
    )
    sibling = _card(
        fragment_id="frag-sibling",
        doc_id="2",
        cluster_id="cluster-main",
        content_summary="同簇关系停顿。",
        narrative_function=["情绪停顿"],
        emotion_tags=["克制"],
        relationship_state=["对峙后未完全和解"],
        preferred_tags=["告别"],
    )
    tag_similar = _card(
        fragment_id="frag-tag",
        doc_id="3",
        cluster_id="cluster-tag",
        content_summary="标签相似但关系阶段不同。",
        narrative_function=["情绪停顿"],
        emotion_tags=["克制"],
        relationship_state=["已经和解"],
        preferred_tags=["告别"],
    )
    high_dependency = _card(
        fragment_id="frag-high",
        doc_id="4",
        cluster_id="cluster-high",
        content_summary="高上下文依赖片段。",
        narrative_function=["余波整理"],
        emotion_tags=["疲惫"],
        relationship_state=["共同承担后果"],
        preferred_tags=["余波"],
        context_dependency_level="high",
    )
    rejected = _card(
        fragment_id="frag-rejected",
        doc_id="5",
        cluster_id="cluster-rejected",
        content_summary="未入选但分数较高。",
        narrative_function=["关系试探"],
        emotion_tags=["防备"],
        relationship_state=["互相试探"],
        preferred_tags=["试探"],
    )
    clusters_by_id = {
        "cluster-main": FragmentCluster("cluster-main", "关系停顿", "frag-top", 2, "same"),
        "cluster-tag": FragmentCluster("cluster-tag", "标签相似", "frag-tag", 1, "singleton"),
        "cluster-high": FragmentCluster("cluster-high", "高依赖", "frag-high", 1, "singleton"),
        "cluster-rejected": FragmentCluster("cluster-rejected", "高分未选", "frag-rejected", 1, "singleton"),
    }
    case = service.build_benchmark_cases(
        prefix_segments=["前文一。", "前文二。"],
        reference_segments=["参考一。", "参考二。", "参考三。"],
    )[0]

    payload = service._build_decoy_fragments(  # noqa: SLF001
        case=case,
        fragment_cards=[top, sibling, tag_similar, high_dependency, rejected],
        clusters_by_id=clusters_by_id,
        selected_ids=["frag-top"],
        rerank_scores=[
            RerankScore(candidate_id="frag-top", final_score=0.9),
            RerankScore(candidate_id="frag-rejected", final_score=0.7),
        ],
        coarse_scores={"frag-rejected": 0.8},
        seed=1,
    )

    decoy_types = {item["decoy_type"] for item in payload["decoy_references"]}
    assert {
        "random_decoy",
        "same_cluster_decoy",
        "tag_similar_decoy",
        "high_dependency_decoy",
        "rejected_high_score",
    } == decoy_types
    assert payload["missing_reasons"] == {}
    assert all(item["traceability"]["fragment_card"] for item in payload["decoy_references"])

    missing_payload = service._build_decoy_fragments(  # noqa: SLF001
        case=case,
        fragment_cards=[top],
        clusters_by_id={"cluster-main": clusters_by_id["cluster-main"]},
        selected_ids=["frag-top"],
        rerank_scores=[RerankScore(candidate_id="frag-top", final_score=0.9)],
        coarse_scores={},
        seed=1,
    )
    assert missing_payload["decoy_references"] == []
    assert set(missing_payload["missing_reasons"]) == {
        "random_decoy",
        "same_cluster_decoy",
        "tag_similar_decoy",
        "high_dependency_decoy",
        "rejected_high_score",
    }


def test_retrieval_review_aggregate_scores_and_guardrails() -> None:
    service = CreativeKBBenchmarkService()
    pass_report = KBRetrievalReviewReport(
        case_id="case-001",
        decision="pass",
        score=0.72,
        summary="pass",
        checks={name: "pass" for name in [
            "top1_beats_decoys",
            "selected_fragments_match_scene_brief",
            "scene_function_fit",
            "emotion_mechanism_fit",
            "relationship_state_fit",
            "style_reference_value",
            "transferability",
            "cluster_diversity",
            "context_dependency_risk",
            "negative_transfer_risk",
        ]},
        selected_fragment_ids=["frag-1"],
        decoy_fragment_ids=["frag-9"],
    ).to_dict()
    borderline_report = dict(pass_report, case_id="case-002", score=0.50, decision="borderline")
    top1_loses_report = KBRetrievalReviewReport.from_dict(
        {
            **pass_report,
            "case_id": "case-003",
            "score": 0.72,
            "decision": "pass",
            "checks": {**pass_report["checks"], "top1_beats_decoys": "fail"},
        }
    ).to_dict()
    high_dependency_report = KBRetrievalReviewReport.from_dict(
        {
            **pass_report,
            "case_id": "case-004",
            "score": 0.72,
            "decision": "pass",
            "checks": {**pass_report["checks"], "context_dependency_risk": "fail"},
        }
    ).to_dict()
    fail_report = KBRetrievalReviewReport(
        case_id="case-005",
        decision="fail",
        score=0.0,
        summary="empty",
        checks={name: "fail" for name in pass_report["checks"]},
        issues=["empty_selected_references"],
    ).to_dict()

    assert service._aggregate_retrieval_reports([pass_report])["decision"] == "pass"  # noqa: SLF001
    assert service._aggregate_retrieval_reports([borderline_report])["decision"] == "borderline"  # noqa: SLF001
    assert service._aggregate_retrieval_reports([fail_report])["decision"] == "fail"  # noqa: SLF001
    assert service._aggregate_retrieval_reports([top1_loses_report])["decision"] == "borderline"  # noqa: SLF001
    assert service._aggregate_retrieval_reports([high_dependency_report])["decision"] == "borderline"  # noqa: SLF001


def test_writer_ab_variant_inputs_distinguish_enabled_disabled_random() -> None:
    service = CreativeKBWriterABService()
    selected_card = _card(
        fragment_id="frag-enabled",
        doc_id="1",
        cluster_id="cluster-enabled",
        content_summary="正式 rerank 选中的关系停顿参考。",
        narrative_function=["情绪停顿"],
        emotion_tags=["克制"],
        relationship_state=["对峙后未完全和解"],
        preferred_tags=["停顿"],
    )
    decoy_card = _card(
        fragment_id="frag-random",
        doc_id="2",
        cluster_id="cluster-random",
        content_summary="随机 decoy 参考。",
        narrative_function=["余波整理"],
        emotion_tags=["疲惫"],
        relationship_state=["共同承担后果"],
        preferred_tags=["余波"],
    )
    variants = service.build_variant_inputs(
        base_execution_input={
            "chapter_id": "chapter-1",
            "style_reference_bundle": {
                "selected_fragment_ids": ["frag-existing"],
                "references": [{"fragment_id": "frag-existing", "excerpt": "默认 smoke KB 参考"}],
            },
            "fact_inputs": {"benchmark_layer": "expansion"},
        },
        selected_references=[{"fragment_id": "frag-enabled", "fragment_card": selected_card.to_dict()}],
        decoy_references=[
            {
                "fragment_id": "frag-random",
                "fragment_card": decoy_card.to_dict(),
                "decoy_type": "random_decoy",
            }
        ],
        seed=3,
    )

    enabled_bundle = variants["kb_enabled"]["style_reference_bundle"]
    disabled_bundle = variants["kb_disabled"]["style_reference_bundle"]
    random_bundle = variants["kb_random"]["style_reference_bundle"]
    assert enabled_bundle["selected_fragment_ids"] == ["frag-enabled"]
    assert enabled_bundle["references"][0]["reference_source"] == "official_rerank_selected"
    assert disabled_bundle["references"] == []
    assert disabled_bundle["selected_fragment_ids"] == []
    assert variants["kb_disabled"]["kb_variant"]["is_no_kb_baseline"] is True
    assert random_bundle["selected_fragment_ids"] == ["frag-random"]
    assert random_bundle["references"][0]["reference_source"] == "random_decoy"
    assert random_bundle["references"][0]["reference_origin"] == "random_decoy"
    random_bundle["references"].append({"fragment_id": "mutated"})
    assert len(enabled_bundle["references"]) == 1


def test_agentic_smoke_default_variant_is_not_kb_disabled() -> None:
    service = CreativeKBWriterABService()

    variants = service.build_variant_inputs(
        base_execution_input={
            "chapter_id": "chapter-1",
            "style_reference_bundle": {
                "selected_fragment_ids": ["frag-smoke"],
                "references": [{"fragment_id": "frag-smoke", "excerpt": "前缀风格片段"}],
            },
        },
        selected_references=[],
        decoy_references=[],
    )

    assert CreativeKBWriterABService.agentic_smoke_default_variant() == "kb_enabled"
    assert variants["kb_enabled"]["kb_variant"]["is_no_kb_baseline"] is False
    assert variants["kb_enabled"]["style_reference_bundle"]["selected_fragment_ids"] == ["frag-smoke"]
    assert variants["kb_disabled"]["kb_variant"]["is_no_kb_baseline"] is True


def test_writer_ab_runner_writes_variant_artifacts_and_aggregates_fake_review(tmp_path: Path) -> None:
    writer = _FakeWriter()
    reviewer = _FakeWriterABReviewer()
    service = CreativeKBWriterABService(writer=writer, reviewer_service=reviewer)
    selected_card = _card(
        fragment_id="frag-enabled",
        doc_id="1",
        cluster_id="cluster-enabled",
        content_summary="正式 KB 参考。",
        narrative_function=["情绪停顿"],
        emotion_tags=["克制"],
        relationship_state=["对峙后未完全和解"],
        preferred_tags=["停顿"],
    )
    decoy_card = _card(
        fragment_id="frag-decoy",
        doc_id="2",
        cluster_id="cluster-decoy",
        content_summary="随机 decoy 参考。",
        narrative_function=["余波整理"],
        emotion_tags=["疲惫"],
        relationship_state=["共同承担后果"],
        preferred_tags=["余波"],
    )

    summary = service.run(
        artifact_dir=tmp_path,
        base_execution_input={
            "chapter_id": "chapter-1",
            "chapter_brief": {"goal": "写关系停顿"},
            "style_reference_bundle": {"references": []},
        },
        reference_story_synopsis={"combined_synopsis": "人物在雨夜关系停顿。"},
        reference_truth="人物在雨夜没有立刻和解。",
        selected_references=[{"fragment_id": "frag-enabled", "fragment_card": selected_card.to_dict()}],
        decoy_references=[
            {
                "fragment_id": "frag-decoy",
                "fragment_card": decoy_card.to_dict(),
                "decoy_type": "random_decoy",
            }
        ],
        seed=11,
    )

    assert summary["status"] == "completed"
    assert summary["winner"] == "kb_enabled"
    assert summary["variant_scores"]["kb_random"] == 0.38
    assert len(writer.execution_inputs) == 3
    assert reviewer.payloads[0]["variants"]["kb_disabled"]["selected_fragment_ids"] == []
    assert reviewer.payloads[0]["variants"]["kb_random"]["selected_fragment_ids"] == ["frag-decoy"]
    for variant in ["kb_enabled", "kb_disabled", "kb_random"]:
        variant_dir = tmp_path / "writer_ab" / variant
        assert json.loads((variant_dir / "writer_execution_input.json").read_text(encoding="utf-8"))
        assert (variant_dir / "draft.md").read_text(encoding="utf-8")
        assert json.loads((variant_dir / "reviewer_report.json").read_text(encoding="utf-8"))
    assert json.loads((tmp_path / "writer_ab" / "writer_ab_reviewer_prompt.json").read_text(encoding="utf-8"))
    assert json.loads((tmp_path / "writer_ab" / "writer_ab_reviewer_report.json").read_text(encoding="utf-8"))


def test_creative_kb_benchmark_builds_three_stable_cases() -> None:
    service = CreativeKBBenchmarkService()

    cases = service.build_benchmark_cases(
        prefix_segments=[
            "第一段里，人物在雨夜里保持沉默，把矛盾暂时压下去。",
            "第二段里，外部脚步逼近，行动压力开始出现。",
            "第三段里，旧图纸和事故线索被再次提起。",
            "第四段里，人物关系仍然处在互相试探阶段。",
        ],
        reference_segments=[
            "参考一继续写关系停顿和未说出口的告别。",
            "参考二继续写脚步逼近后的转移和追逐。",
            "参考三继续写图纸背面的秘密和旧设定。",
        ],
        case_count=3,
        seed=123,
    )

    assert [case.case_id for case in cases] == ["case-001", "case-002", "case-003"]
    assert cases[0].category == "情绪停顿 / 关系收束"
    assert "冲突升级" in cases[1].scene_brief.narrative_function
    assert "信息揭示" in cases[2].expected_traits
    assert cases[0].to_dict()["scene_brief"]["must_avoid"]


def test_creative_kb_benchmark_writes_parseable_artifacts_with_fake_facades(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text(_source_text(), encoding="utf-8")
    artifact_dir = tmp_path / "runs" / "creative_kb_benchmarks" / "fake-run"
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    reviewer_model_client = _FakeReviewerModelClient(
        [
            _fragment_review_payload(0.74),
            _fragment_review_payload(0.75),
            _fragment_review_payload(0.76),
            _cluster_review_payload(0.66),
            _cluster_review_payload(0.67),
            _retrieval_review_payload(0.68),
            _retrieval_review_payload(0.69),
            _retrieval_review_payload(0.70),
        ]
    )
    progress_events: list[dict[str, object]] = []
    service = CreativeKBBenchmarkService(
        repo_root=tmp_path,
        creative_kb_facade=_FakeCreativeKBFacade(
            cards_repo=cards_repo,
            clusters_repo=clusters_repo,
        ),  # type: ignore[arg-type]
        retrieval_facade=_FakeRetrievalFacade(),  # type: ignore[arg-type]
        model_client=reviewer_model_client,
        fragment_cards_repo=cards_repo,
        fragment_clusters_repo=clusters_repo,
        progress_callback=lambda event: progress_events.append(dict(event)),
    )

    result = service.run(
        CreativeKBBenchmarkInput(
            source_path=str(source_path),
            run_id="fake-run",
            case_count=3,
            enable_writer_ab=True,
            seed=7,
        )
    )

    assert result.status == "completed"
    assert Path(result.artifact_dir) == artifact_dir
    phases = [event.get("phase") for event in progress_events]
    assert "windows_start" in phases
    assert "creative_kb_build_start" in phases
    assert "retrieval_case_start" in phases
    assert "summary_written" in phases
    for filename in [
        "kb_build_result.json",
        "scene_brief_cases.json",
        "kb_reviewer_report.json",
        "summary.json",
        "fragment_cards_sample.json",
        "fragment_clusters_sample.json",
    ]:
        assert json.loads((artifact_dir / filename).read_text(encoding="utf-8"))
    assert (artifact_dir / "source_prefix.txt").read_text(encoding="utf-8").strip()
    assert (artifact_dir / "reference_truth.txt").read_text(encoding="utf-8").strip()

    summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == "fake-run"
    assert summary["case_summary"]["case_count"] == 3
    assert summary["retrieval_review_summary"]["decision"] == "pass"
    assert summary["writer_ab_summary"]["status"] == "pending_writer_ab"
    assert summary["writer_ab_summary"]["negative_transfer_issues"] == ["writer_not_configured"]

    kb_reviewer_report = json.loads((artifact_dir / "kb_reviewer_report.json").read_text(encoding="utf-8"))
    assert kb_reviewer_report["build_quality_review"]["status"] == "completed"
    assert kb_reviewer_report["retrieval_review"]["status"] == "completed"
    assert kb_reviewer_report["writer_ab_review"]["status"] == "pending_writer_ab"
    assert kb_reviewer_report["build_quality_review"]["fragment_card_review"]["sample_count"] == 3
    assert kb_reviewer_report["build_quality_review"]["cluster_review"]["sample_count"] == 2
    assert json.loads(
        (artifact_dir / "kb_build_reviews" / "fragment_card_review_reports.json").read_text(encoding="utf-8")
    )
    assert json.loads(
        (artifact_dir / "kb_build_reviews" / "fragment_cluster_review_reports.json").read_text(encoding="utf-8")
    )

    case_dir = artifact_dir / "retrieval_cases" / "case-001"
    for filename in [
        "scene_brief.json",
        "coarse_result.json",
        "rerank_result.json",
        "selected_reference_fragments.json",
        "decoy_fragments.json",
        "kb_retrieval_reviewer_prompt.json",
        "kb_retrieval_reviewer_report.json",
    ]:
        assert json.loads((case_dir / filename).read_text(encoding="utf-8")) is not None
    case_report = json.loads((case_dir / "kb_retrieval_reviewer_report.json").read_text(encoding="utf-8"))
    assert case_report["decision"] == "pass"
    decoy_payload = json.loads((case_dir / "decoy_fragments.json").read_text(encoding="utf-8"))
    assert "decoy_references" in decoy_payload
    assert "missing_reasons" in decoy_payload

    for variant in ["kb_enabled", "kb_disabled", "kb_random"]:
        variant_dir = artifact_dir / "writer_ab" / variant
        assert json.loads((variant_dir / "writer_execution_input.json").read_text(encoding="utf-8"))
        assert (variant_dir / "draft.md").exists()
        assert json.loads((variant_dir / "reviewer_report.json").read_text(encoding="utf-8"))


def test_creative_kb_benchmark_returns_readable_failure_for_empty_kb(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text(_source_text(), encoding="utf-8")
    artifact_dir = tmp_path / "empty-run"
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    service = CreativeKBBenchmarkService(
        repo_root=tmp_path,
        creative_kb_facade=_FakeCreativeKBFacade(
            cards_repo=cards_repo,
            clusters_repo=clusters_repo,
            empty=True,
        ),  # type: ignore[arg-type]
        retrieval_facade=_FakeRetrievalFacade(),  # type: ignore[arg-type]
        fragment_cards_repo=cards_repo,
        fragment_clusters_repo=clusters_repo,
    )

    result = service.run(
        CreativeKBBenchmarkInput(
            source_path=str(source_path),
            run_id="empty-run",
            artifact_dir=str(artifact_dir),
            case_count=3,
        )
    )

    assert result.status == "failed"
    assert "creative kb build produced no fragment_cards" in result.errors
    summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["retrieval_review_summary"]["decision"] == "fail"
    assert "empty_kb" in summary["retrieval_review_summary"]["case_reports"][0]["issues"]
    kb_reviewer_report = json.loads((artifact_dir / "kb_reviewer_report.json").read_text(encoding="utf-8"))
    assert kb_reviewer_report["build_quality_review"]["decision"] == "fail"
    assert "fragment_card sample count below target: 0/3" in kb_reviewer_report["build_quality_review"]["warnings"]
