from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from novel_agent.app.orchestrators import (
    RestrictedWriterExecutor,
    WriterInteractiveWorkflow,
    WriterLayeredGenerationOrchestrator,
    WriterRollbackManager,
)
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.schemas.narrative_memory_schema import MemoryQueryBudget
from novel_agent.app.schemas.orchestration_schema import (
    ExtractedCharacterMention,
    ExtractedCharacterMentions,
    OutlineSeedPacket,
    PlanningNotebook,
    ResearchBudget,
    ResearchRequest,
    ResearchResult,
    SufficiencyDecision,
    TraceableSource,
)
from novel_agent.app.services.narrative_memory_query_service import NarrativeMemoryQueryService
from novel_agent.app.services.outline_research_service import (
    CharacterMentionExtractor,
    CharacterMentionResolver,
    OutlineResearchContextBroker,
    OutlineResearchLoopController,
    OutlineResearchModelAdapter,
    OutlineSeedPacketBuilder,
    StoryDetailResolver,
)
from novel_agent.runs.layout import RunLayout
from novel_agent.runs.writer import RunWriter
from novel_agent.tests.test_writer_layered_generation_orchestrator import (
    FakeWriterModelClient,
    _seed_assets,
    _seed_document,
    _seed_fragment_card,
    _seed_knowledge_docs,
    _seed_profile,
)


def _load_run_data(run_writer: RunWriter, run_id: str, name: str) -> dict[str, Any]:
    path = run_writer.layout.run_dir(run_id) / name
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _build_db_and_orchestrator(
    tmp_path: Path,
    *,
    adapter: OutlineResearchModelAdapter | None = None,
) -> tuple[NovelAgentDB, WriterLayeredGenerationOrchestrator]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _seed_knowledge_docs(repo_root)
    db = NovelAgentDB(tmp_path / "writer-outline.db")
    run_writer = RunWriter(layout=RunLayout(base_dir=tmp_path / "runs"))
    orchestrator = WriterLayeredGenerationOrchestrator(
        repo_root=repo_root,
        run_writer=run_writer,
        model_client=FakeWriterModelClient(),  # type: ignore[arg-type]
        outline_research_adapter=adapter,
    )
    return db, orchestrator


def _seed_base_memory(conn, *, book_id: str, repo_root: Path) -> None:
    _seed_assets(conn, book_id=book_id, repo_root=repo_root)
    _seed_document(conn, book_id=book_id)
    _seed_profile(conn, book_id=book_id, canonical_name="沈青")
    _seed_fragment_card(conn)


def _seed_chapter(
    conn,
    *,
    book_id: str,
    index: int,
    title: str,
    summary: str,
    mentioned: list[str],
    status: str = "committed",
) -> None:
    ChaptersRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "document_title_index": index,
            "chapter_title": title,
            "source_doc_start_id": 1,
            "source_doc_end_id": 1,
            "source_doc_count": 1,
            "source_total_chars": 1000,
            "summary_intermediate": [],
            "summary_md": summary,
            "summary_short": summary,
            "summary_status": status,
            "summary_evidence_window": f"{index}-{index}",
            "summary_target_range": f"{index}-{index}",
            "importance_score": 8,
            "importance_reason": "outline research fixture",
            "related_chapters": [],
            "mentioned_characters": mentioned,
            "world_update": {"灵脉封禁": "不能无代价突破"},
            "outline_update": {
                "outcome": "事件结束后两人只达成有限合作。",
                "timeline_events": [
                    {
                        "event_id": f"chapter-{index}:event-01-trust-conflict",
                        "label": "旧案证据信任冲突",
                        "summary": summary,
                        "participants": mentioned,
                        "source_doc_ids": [1],
                        "source_doc_range": "1",
                    }
                ],
            },
            "outline_status": status,
            "outline_evidence_window": f"{index}-{index}",
            "outline_target_range": f"{index}-{index}",
            "close_read_run_id": "test",
            "created_at": "now",
            "updated_at": "now",
        },
    )


class _ScriptedResearchAdapter:
    def __init__(
        self,
        *,
        request_rounds: Sequence[Sequence[ResearchRequest | Mapping[str, Any]]] | None = None,
        decisions: Sequence[SufficiencyDecision | Mapping[str, Any]] | None = None,
    ) -> None:
        self.request_rounds = list(request_rounds or [])
        self.decisions = list(decisions or [])
        self.request_calls = 0
        self.decision_calls = 0

    def propose_research_requests(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        prior_results: Sequence[ResearchResult],
        budget_state: Mapping[str, Any],
    ) -> Sequence[ResearchRequest | Mapping[str, Any]]:
        index = min(self.request_calls, max(0, len(self.request_rounds) - 1))
        self.request_calls += 1
        return self.request_rounds[index] if self.request_rounds else []

    def decide_sufficiency(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        budget_state: Mapping[str, Any],
    ) -> SufficiencyDecision | Mapping[str, Any]:
        if self.decisions:
            index = min(self.decision_calls, len(self.decisions) - 1)
            self.decision_calls += 1
            return self.decisions[index]
        return SufficiencyDecision(decision_id="scripted-enough", status="enough")

    def generate_outline(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        sufficiency_decision: SufficiencyDecision,
    ) -> Mapping[str, Any]:
        return {}


class _AnswerAwareAdapter(_ScriptedResearchAdapter):
    def decide_sufficiency(
        self,
        *,
        seed_packet: OutlineSeedPacket,
        notebook: PlanningNotebook,
        budget_state: Mapping[str, Any],
    ) -> SufficiencyDecision:
        if any(fact.fact_status == "user_authorized" for fact in notebook.confirmed_facts):
            return SufficiencyDecision(decision_id="after-answer", status="enough", known_enough=["用户已授权阻塞边界。"])
        return SufficiencyDecision(
            decision_id="needs-answer",
            status="needs_user_input",
            blocking_gaps=["主要人物身份未确认"],
            user_questions=["顾迟是否为新增人物？"],
        )


def test_outline_research_schema_serialization_and_validation(tmp_path: Path) -> None:
    source = TraceableSource(type="story_outline", path=str(tmp_path / "outline.md"), evidence_level="structured_state")
    packet = OutlineSeedPacket(
        packet_id="packet-1",
        book_id="book-1",
        user_intent={"desired_actions": ["追查旧案"]},
        character_index=[{"name": "沈青", "aliases": ["阿青"], "role_hint": "主角"}],
        world_overview="世界观精炼摘要",
        historical_story_overview=[{"work_id": "book-1", "summary": "旧案仍未结束"}],
        sources=[source],
    )
    request = ResearchRequest(
        request_id="req-1",
        request_type="story_detail",
        query="最近一次信任冲突",
        purpose="判断是否能合作",
        priority="high",
    )
    result = ResearchResult(
        request_id=request.request_id,
        request_type=request.request_type,
        query=request.query,
        results=[{"summary": "两人冲突后只达成有限合作"}],
        fact_status="confirmed",
        sources=[source],
        confidence=0.8,
    )
    notebook = PlanningNotebook(notebook_id="nb-1")
    notebook.add_research_result(result)
    decision = SufficiencyDecision(decision_id="sd-1", status="enough", known_enough=["可规划"])
    run_writer = RunWriter(layout=RunLayout(base_dir=tmp_path / "runs"))

    run_writer.write_json("run-1", "outline_seed_packet.json", packet)
    run_writer.write_json("run-1", "outline_research_trace.json", {"rounds": [{"requests": [request.to_dict()]}]})
    run_writer.write_json("run-1", "planning_notebook.json", notebook)
    run_writer.write_json("run-1", "sufficiency_decision.json", decision)

    saved_packet = _load_run_data(run_writer, "run-1", "outline_seed_packet.json")
    saved_notebook = _load_run_data(run_writer, "run-1", "planning_notebook.json")
    assert saved_packet["sources"][0]["path"] == str(tmp_path / "outline.md")
    assert saved_notebook["confirmed_facts"][0]["fact_status"] == "confirmed"
    assert _load_run_data(run_writer, "run-1", "sufficiency_decision.json")["status"] == "enough"

    with pytest.raises(ValueError, match="request_type"):
        ResearchRequest(request_id="bad", request_type="sql", query="SELECT *")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="status"):
        SufficiencyDecision(decision_id="bad", status="maybe")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="user_questions"):
        SufficiencyDecision(decision_id="bad", status="needs_user_input")


def test_character_mentions_resolve_existing_alias_ambiguous_missing_and_reject_new(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-mentions"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "顾迟",
                "aliases": ["顾先生", "先生"],
                "profile_summary_md": "已建档的协作者。",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "许先生",
                "aliases": ["先生"],
                "profile_summary_md": "另一个被称为先生的人物。",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

        mentions = ExtractedCharacterMentions(
            mentions=[
                ExtractedCharacterMention(text="沈青", source_text="让沈青追查旧案", confidence=0.9),
                ExtractedCharacterMention(text="顾先生", mention_type="alias", source_text="顾先生接应", confidence=0.8),
                ExtractedCharacterMention(text="先生", mention_type="title", source_text="先生出面", confidence=0.7),
                ExtractedCharacterMention(text="陆岑", source_text="陆岑不要新增", confidence=0.7),
            ]
        )
        resolutions = CharacterMentionResolver().resolve(conn, book_id=book_id, mentions=mentions)
        by_text = {item.mention_text: item for item in resolutions}

        report = orchestrator.analyze_character_requirements(
            conn,
            book_id=book_id,
            intent=orchestrator.build_continuation_intent({"major_characters": ["陆岑"], "desired_actions": ["追查旧案"]}),
            book_plan=orchestrator._book_plan_from_dict(  # noqa: SLF001
                {
                    "plan_id": "plan",
                    "book_id": book_id,
                    "continuation_goal": "追查旧案",
                }
            ),
            character_resolutions=[by_text["陆岑"]],
        )

    assert by_text["沈青"].status == "resolved"
    assert by_text["顾先生"].status == "resolved"
    assert by_text["顾先生"].matched_by == ["alias"]
    assert by_text["先生"].status == "ambiguous"
    assert len(by_text["先生"].candidate_matches) == 2
    assert by_text["陆岑"].status == "missing"
    assert "是否确认新增人物" in by_text["陆岑"].user_question
    assert report.named_new_characters == []


def test_outline_seed_packet_is_index_level_and_not_full_memory(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-seed"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        long_profile = "秘密档案" * 80
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "顾迟",
                "aliases": ["顾先生"],
                "profile_summary_md": long_profile,
                "created_at": "now",
                "updated_at": "now",
            },
        )
        world_path = orchestrator.repo_root / "memory" / "worlds" / f"{book_id}.world_summary.md"
        world_path.write_text("# 世界观概要\n\n## 灵脉封禁\n- 不能无代价突破。\n" + "完整世界观" * 300, encoding="utf-8")
        conn.commit()

        intent = orchestrator.build_continuation_intent(
            {
                "major_characters": ["沈青", "顾迟"],
                "desired_actions": ["让沈青和顾迟追查旧案证据"],
                "story_scale": {"target_chapter_count": 3, "default_chapter_target_chars": 4000},
                "climax_plan": {"conflict_climax": "公开对抗"},
            }
        )
        mentions = orchestrator.character_mention_extractor.extract({"major_characters": ["沈青", "顾迟"]})
        resolutions = orchestrator.character_mention_resolver.resolve(conn, book_id=book_id, mentions=mentions)
        packet = OutlineSeedPacketBuilder(repo_root=orchestrator.repo_root).build(
            conn,
            book_id=book_id,
            intent=intent,
            mentions=mentions,
            resolutions=resolutions,
        )

    serialized = packet.to_dict()
    assert serialized["story_scale"]["target_chapter_count"] == 3
    assert serialized["climax_input"]["conflict_climax"] == "公开对抗"
    assert any(item["name"] == "顾迟" for item in serialized["character_index"])
    assert len(serialized["world_overview"]) <= 903
    assert "秘密档案" * 20 not in json.dumps(serialized["character_index"], ensure_ascii=False)
    assert "完整世界观" * 80 not in serialized["world_overview"]


def test_context_broker_resolvers_sources_trimming_dedup_and_story_queries(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-broker"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_profile(conn, book_id=book_id, canonical_name="顾迟")
        _seed_chapter(
            conn,
            book_id=book_id,
            index=11,
            title="第十一章 信任裂缝",
            summary="沈青和顾迟因为旧案证据来源爆发最近一次信任冲突，结束后只保持有限合作。",
            mentioned=["沈青", "顾迟"],
        )
        conn.commit()

        broker = OutlineResearchContextBroker(repo_root=orchestrator.repo_root)
        requests = [
            ResearchRequest(request_id="story-1", request_type="story_detail", query="最近一次信任冲突的经过和结果", priority="high"),
            ResearchRequest(request_id="story-dup", request_type="story_detail", query="最近一次信任冲突的经过和结果", priority="high"),
            ResearchRequest(request_id="char-1", request_type="character_profile", name="沈青", query="关系状态和能力边界", priority="high"),
            ResearchRequest(request_id="world-1", request_type="world_concept", concept="灵脉封禁", query="规则限制代价", priority="medium"),
            ResearchRequest(request_id="structure-1", request_type="structure_pattern", query="调查过渡到公开对抗", priority="low"),
        ]
        results = broker.resolve_requests(
            conn,
            book_id=book_id,
            requests=requests,
            budget=ResearchBudget(max_total_requests=4, max_return_tokens_per_request=120),
        )
        story_result = next(item for item in results if item.request_type == "story_detail")
        character_result = next(item for item in results if item.request_type == "character_profile")
        world_result = next(item for item in results if item.request_type == "world_concept")

        resolver = StoryDetailResolver()
        source_result = resolver.resolve(
            conn,
            book_id=book_id,
            request=ResearchRequest(request_id="source", request_type="story_detail", query="旧案证据伏笔来源", priority="high"),
            max_chars=500,
        )
        outcome_result = resolver.resolve(
            conn,
            book_id=book_id,
            request=ResearchRequest(request_id="outcome", request_type="story_detail", query="信任冲突事件结果", priority="high"),
            max_chars=500,
        )

    assert len(results) == 4
    assert [item.request_id for item in results].count("story-1") == 1
    assert story_result.fact_status == "confirmed"
    assert "relationship_state" in story_result.covered_facets
    assert story_result.sources[0].path.startswith("sqlite:chapters")
    assert character_result.fact_status == "candidate"
    assert character_result.results[0]["fact_status"] == "candidate"
    assert world_result.sources
    assert all(item.summary_size <= 360 for item in results)
    assert source_result.results
    assert source_result.results[0]["source_doc_ids"] == [1]
    assert source_result.results[0]["source_doc_range"] == "1"
    assert outcome_result.results[0]["outcome"]


def test_narrative_memory_query_btree_drills_to_documents_and_trace(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-memory-query"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_chapter(
            conn,
            book_id=book_id,
            index=11,
            title="第十一章 信任裂缝",
            summary="沈青和顾迟因为旧案证据来源爆发最近一次信任冲突，结束后只保持有限合作。",
            mentioned=["沈青", "顾迟"],
        )
        conn.commit()

        service = NarrativeMemoryQueryService(repo_root=orchestrator.repo_root)
        root = service.root_scan(
            conn,
            book_id=book_id,
            query="信任冲突的经过和后果",
            budget=MemoryQueryBudget(max_root_candidates=4, max_child_candidates=4),
        )
        events = service.drill_down(
            conn,
            book_id=book_id,
            state=root,
            selected_ids=[root.current_candidates[0]["id"]],
            query_suffix="确认相关事件",
            selection_reason="root summary covers the conflict",
            confidence=0.8,
        )
        chapters = service.drill_down(
            conn,
            book_id=book_id,
            state=events,
            selected_ids=[events.current_candidates[0]["id"]],
            query_suffix="展开章节摘要",
            selection_reason="event mentions trust conflict",
            confidence=0.8,
        )
        documents = service.drill_down(
            conn,
            book_id=book_id,
            state=chapters,
            selected_ids=[chapters.current_candidates[0]["id"]],
            query_suffix="查看原始片段",
            selection_reason="chapter has source doc range",
            confidence=0.8,
        )
        bundle = service.resolve_document_refs(conn, book_id=book_id, doc_ids=[1], excerpt_budget=120)

    assert root.current_level == "event_summary"
    assert root.current_candidates[0]["start_event_id"]
    assert events.current_level == "event"
    assert events.current_candidates[0]["event_id"].startswith("chapter-11:event")
    assert chapters.current_level == "chapter"
    assert documents.current_level == "document"
    assert bundle.excerpts[0]["doc_id"] == 1
    assert any(item["operation"] == "drill_down" for item in documents.trace)


def test_character_mention_extractor_ignores_notes_and_avoidances_for_person_detection() -> None:
    extractor = CharacterMentionExtractor()

    mentions = extractor.extract(
        {
            "major_characters": ["沈青"],
            "desired_actions": ["沈青追查旧案"],
            "avoidances": ["不要把隐藏新人物写成已有角色"],
            "notes": "prefix snapshot includes 顾迟 and 冯施耐德 for debugging only",
        }
    )

    names = [item.text for item in mentions.mentions]
    assert "沈青" in names
    assert "顾迟" not in names
    assert "冯施耐德" not in names
    assert "隐藏新人物" not in names


def test_character_mention_extractor_uses_explicit_major_characters_only() -> None:
    extractor = CharacterMentionExtractor()

    mentions = extractor.extract(
        {
            "major_characters": ["路明非"],
            "desired_actions": [
                "路明非经历危机后，学院教授暂时搁置报告，导师继续观察。"
            ]
        }
    )

    names = [item.text for item in mentions.mentions]
    assert "路明非" in names
    assert "经历" not in names
    assert "危机" not in names
    assert "时搁置" not in names


def test_outline_research_loop_multi_round_budget_assumptions_and_blocked(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-loop"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        conn.commit()

        intent = orchestrator.build_continuation_intent({"desired_actions": ["追查旧案线索"]})
        mentions = orchestrator.character_mention_extractor.extract({"desired_actions": ["沈青追查旧案线索"]})
        resolutions = orchestrator.character_mention_resolver.resolve(conn, book_id=book_id, mentions=mentions)
        seed = orchestrator.outline_seed_builder.build(
            conn,
            book_id=book_id,
            intent=intent,
            mentions=mentions,
            resolutions=resolutions,
        )

        controller = OutlineResearchLoopController(
            broker=OutlineResearchContextBroker(repo_root=orchestrator.repo_root),
            model_adapter=_ScriptedResearchAdapter(
                request_rounds=[
                    [ResearchRequest(request_id="r1", request_type="story_detail", query="追查旧案线索")],
                    [ResearchRequest(request_id="r2", request_type="character_profile", name="沈青", query="关系状态")],
                ],
                decisions=[SufficiencyDecision(decision_id="enough", status="enough", known_enough=["两轮完成"])],
            ),
        )
        multi = controller.run(conn, book_id=book_id, seed_packet=seed, budget=ResearchBudget(max_rounds=2))

        assumption_controller = OutlineResearchLoopController(
            broker=OutlineResearchContextBroker(repo_root=orchestrator.repo_root),
            model_adapter=_ScriptedResearchAdapter(
                request_rounds=[
                    [
                        ResearchRequest(request_id="r1", request_type="story_detail", query="追查旧案线索"),
                        ResearchRequest(request_id="r2", request_type="character_profile", name="沈青", query="关系状态"),
                    ]
                ],
                decisions=[
                    {
                        "decision_id": "assume",
                        "status": "proceed_with_assumptions",
                        "known_enough": ["索引可支撑草案"],
                        "optional_gaps": ["缺少低风险过渡细节"],
                        "assumptions": [{"claim": "过渡细节暂按低风险假设处理", "fact_status": "assumption"}],
                    }
                ],
            ),
        )
        assumed = assumption_controller.run(
            conn,
            book_id=book_id,
            seed_packet=seed,
            budget=ResearchBudget(max_rounds=1, max_total_requests=1),
        )

        blocked_controller = OutlineResearchLoopController(
            broker=OutlineResearchContextBroker(repo_root=orchestrator.repo_root),
            model_adapter=_ScriptedResearchAdapter(
                decisions=[
                    {
                        "decision_id": "blocked",
                        "status": "blocked",
                        "blocking_gaps": ["没有历史大纲"],
                        "required_actions": ["先补齐 story_outline"],
                    }
                ],
            ),
        )
        blocked = blocked_controller.run(conn, book_id=book_id, seed_packet=seed, budget=ResearchBudget(max_rounds=1))

    assert len(multi.trace["rounds"]) == 2
    assert multi.sufficiency_decision.status == "enough"
    assert assumed.trace["final_budget_state"]["exhausted"] is True
    assert assumed.sufficiency_decision.status == "proceed_with_assumptions"
    assert assumed.planning_notebook.assumptions[0].fact_status == "assumption"
    assert blocked.sufficiency_decision.status == "blocked"
    assert blocked.sufficiency_decision.required_actions == ["先补齐 story_outline"]


def test_workflow_needs_user_input_then_continues_without_unconfirmed_character_cast(tmp_path: Path) -> None:
    db, planner = _build_db_and_orchestrator(tmp_path, adapter=_AnswerAwareAdapter())
    executor = RestrictedWriterExecutor(repo_root=planner.repo_root, run_writer=planner.run_writer)
    workflow = WriterInteractiveWorkflow(
        planner=planner,
        executor=executor,
        rollback_manager=WriterRollbackManager(run_writer=planner.run_writer),
        run_writer=planner.run_writer,
    )
    book_id = "book-user-input"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=planner.repo_root)
        conn.commit()

        initial = workflow.prepare_planning(
            conn,
            run_id="run-user-input",
            book_id=book_id,
            product_mode="assist",
            intent_payload={"major_characters": ["沈青", "顾迟"], "desired_actions": ["沈青追查旧案"]},
        )
        continued = workflow.continue_after_outline_research_input(
            conn,
            run_id="run-user-input",
            book_id=book_id,
            product_mode="assist",
            user_answers={"顾迟是否为新增人物？": "不是新增人物，本轮不加入。"},
        )

    state = workflow.load_workflow_state(run_id="run-user-input")
    assert initial["stage"] == "outline_research_user_input"
    assert initial["sufficiency_decision"]["user_questions"] == ["顾迟是否为新增人物？"]
    assert initial["question_set"]["question_set_id"] == "outline-research-run-user-input-needs-answer"
    question_set = _load_run_data(planner.run_writer, "run-user-input", "outline_research_question_set.json")
    assert question_set["run_id"] == "run-user-input"
    assert question_set["questions"][0]["question_id"] == "q1"
    assert question_set["actions"]["submit"] == "continue_after_outline_research_input"
    assert state["current_stage"] == "freeze_a_review"
    assert continued["character_requirement_report"]["named_new_characters"] == []
    submission = _load_run_data(planner.run_writer, "run-user-input", "outline_research_answer_submission.json")
    assert submission["answer_text"] == "不是新增人物，本轮不加入。"
    assert submission["user_answers"] == [{"question_id": "q1", "answer_text": "不是新增人物，本轮不加入。"}]
    assert _load_run_data(planner.run_writer, "run-user-input", "planning_notebook.json")["confirmed_facts"][0]["fact_status"] == "user_authorized"


def test_outline_research_missing_required_answer_does_not_fabricate_user_evidence(tmp_path: Path) -> None:
    db, planner = _build_db_and_orchestrator(tmp_path, adapter=_AnswerAwareAdapter())
    executor = RestrictedWriterExecutor(repo_root=planner.repo_root, run_writer=planner.run_writer)
    workflow = WriterInteractiveWorkflow(
        planner=planner,
        executor=executor,
        rollback_manager=WriterRollbackManager(run_writer=planner.run_writer),
        run_writer=planner.run_writer,
    )
    book_id = "book-missing-answer"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=planner.repo_root)
        conn.commit()

        initial = workflow.prepare_planning(
            conn,
            run_id="run-missing-answer",
            book_id=book_id,
            product_mode="assist",
            intent_payload={"major_characters": ["沈青", "顾迟"], "desired_actions": ["沈青追查旧案"]},
        )
        result = workflow.continue_after_outline_research_input(
            conn,
            run_id="run-missing-answer",
            book_id=book_id,
            product_mode="assist",
            question_set_id=initial["question_set"]["question_set_id"],
            answer_text="",
            user_answers=[],
        )

    assert result["stage"] == "outline_research_user_input"
    assert result["missing_required_questions"] == ["q1"]
    assert workflow.load_workflow_state(run_id="run-missing-answer")["current_stage"] == "outline_research_user_input"
    notebook = _load_run_data(planner.run_writer, "run-missing-answer", "planning_notebook.json")
    assert [fact for fact in notebook["confirmed_facts"] if fact["fact_status"] == "user_authorized"] == []
    assert not (planner.run_writer.layout.run_dir("run-missing-answer") / "outline_research_answer_submission.json").exists()


def test_proceed_with_assumptions_writes_formal_book_plan_assumptions(tmp_path: Path) -> None:
    adapter = _ScriptedResearchAdapter(
        decisions=[
            {
                "decision_id": "assume",
                "status": "proceed_with_assumptions",
                "known_enough": ["用户意图足够"],
                "optional_gaps": ["缺少低风险转场细节"],
                "assumptions": [{"claim": "转场细节作为草案假设处理", "fact_status": "assumption"}],
            }
        ]
    )
    db, orchestrator = _build_db_and_orchestrator(tmp_path, adapter=adapter)
    book_id = "book-assumptions"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        conn.commit()
        bundle = orchestrator.prepare_freeze_a(
            conn,
            run_id="run-assumptions",
            book_id=book_id,
            intent_payload={"major_characters": ["沈青"], "desired_actions": ["追查旧案线索"]},
        )

    assert bundle["book_continuation_plan"]["assumptions"][0]["fact_status"] == "assumption"
    assert "缺少低风险转场细节" in bundle["book_continuation_plan"]["open_questions"]
    assert _load_run_data(orchestrator.run_writer, "run-assumptions", "sufficiency_decision.json")["status"] == "proceed_with_assumptions"


def test_blocked_research_does_not_generate_formal_book_plan(tmp_path: Path) -> None:
    adapter = _ScriptedResearchAdapter(
        decisions=[
            {
                "decision_id": "blocked",
                "status": "blocked",
                "blocking_gaps": ["缺少历史大纲"],
                "required_actions": ["先运行 close-read 大纲建模"],
            }
        ]
    )
    db, orchestrator = _build_db_and_orchestrator(tmp_path, adapter=adapter)
    book_id = "book-blocked"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        conn.commit()
        result = orchestrator.prepare_freeze_a(
            conn,
            run_id="run-blocked",
            book_id=book_id,
            intent_payload={"major_characters": ["沈青"], "desired_actions": ["追查旧案线索"]},
        )

    run_dir = orchestrator.run_writer.layout.run_dir("run-blocked")
    assert result["stage"] == "outline_research_blocked"
    assert result["sufficiency_decision"]["required_actions"] == ["先运行 close-read 大纲建模"]
    assert not (run_dir / "book_continuation_plan.json").exists()
    assert (run_dir / "outline_research_trace.json").exists()
