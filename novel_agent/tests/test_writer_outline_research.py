from __future__ import annotations

import json
import logging
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
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.schemas.narrative_memory_schema import MemoryQueryBudget, MemoryQueryState
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
    ModelOutlineResearchModelAdapter,
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
                "chapter_line": f"[{index}] {title}: {summary}",
                "outline_segment_id": f"outline-segment:chapter-{index}:docs-1",
                "outline_segment": summary,
                "outcome": "事件结束后两人只达成有限合作。",
                "source_doc_ids": [1],
                "source_doc_range": "1",
                "source_title_indexes": [index],
                "status": status,
            },
            "outline_status": status,
            "outline_evidence_window": f"{index}-{index}",
            "outline_target_range": f"{index}-{index}",
            "close_read_run_id": "test",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _write_scene_cards(repo_root: Path, *, book_id: str) -> Path:
    path = repo_root / ".memory" / "index_cards" / f"{book_id}.scene_cards.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "book_id": book_id,
                "scene_cards": [
                    {
                        "card_id": f"narrative-scene:{book_id}:trust-conflict",
                        "card_type": "narrative_scene",
                        "book_id": book_id,
                        "summary": "沈青和顾迟因为旧案证据来源爆发最近一次信任冲突，冲突后只保持有限合作。",
                        "source_doc_ids": ["1"],
                        "source_title_indexes": [11],
                        "source_doc_range": "1",
                        "query_facets": ["信任冲突", "旧案证据", "有限合作"],
                        "importance_facets": ["relationship_turning_point"],
                        "consumer_hints": ["outline_research", "writer", "analyzer"],
                        "summary_sufficiency": "needs_raw_for_emotional_texture",
                        "raw_read_reason": "如果要写现场对白和羞辱细节，需要回读原文质感。",
                        "status": "committed",
                        "confidence": 0.91,
                        "payload": {
                            "scene_type": "relationship_turning_point",
                            "label": "旧案证据信任冲突",
                            "participants": ["沈青", "顾迟"],
                            "trigger": "旧案证据来源被质疑。",
                            "turning_point": "两人的信任从默认协作转为有限合作。",
                            "outcome": "冲突结束后两人暂时保留合作，但关系降温。",
                            "relationship_movements": ["沈青与顾迟由互信转向有限合作"],
                            "future_consequence": "后续大纲不宜直接安排无条件信任配合。",
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


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


class _PromptLengthModelClient:
    model = "prompt-length-test-model"

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = dict(payload)
        self.calls: list[dict[str, str]] = []

    def generate_json(self, *, system_prompt: str, user_prompt: str, fallback_factory: Any, use_fallback_on_error: bool = False) -> tuple[dict[str, Any], str]:
        _ = fallback_factory, use_fallback_on_error
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return dict(self.payload), ""


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


def test_outline_research_needs_user_input_uses_concrete_model_questions() -> None:
    controller = OutlineResearchLoopController(
        broker=OutlineResearchContextBroker(repo_root=Path.cwd()),
        model_adapter=_ScriptedResearchAdapter(),
    )

    decision = controller._validated_decision(
        {
            "decision_id": "needs-role-answer",
            "status": "needs_user_input",
            "blocking_gaps": [
                {
                    "gap": "模型还无法判断“顾迟”是新增人物还是已有角色的隐藏身份",
                    "why_it_matters": "会影响人物档案、伏笔回收和高潮揭露节奏",
                    "question": "“顾迟”是新增人物，还是已有角色的隐藏身份？如果是已有角色，请说明是谁。",
                }
            ],
        }
    )

    assert decision.user_questions == ["“顾迟”是新增人物，还是已有角色的隐藏身份？如果是已有角色，请说明是谁。"]
    assert decision.blocking_gaps == ["模型还无法判断“顾迟”是新增人物还是已有角色的隐藏身份"]


def test_outline_research_rejects_abstract_needs_user_input_fallback() -> None:
    controller = OutlineResearchLoopController(
        broker=OutlineResearchContextBroker(repo_root=Path.cwd()),
        model_adapter=_ScriptedResearchAdapter(),
    )

    with pytest.raises(ValueError, match="concrete user_questions"):
        controller._validated_decision(
            {
                "decision_id": "bad-needs-input",
                "status": "needs_user_input",
                "blocking_gaps": ["缺少大纲规划所需的授权边界"],
            }
        )


def test_outline_research_asks_for_missing_climax_plan_before_formal_outline(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path, adapter=_ScriptedResearchAdapter())
    book_id = "book-climax-question"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        conn.commit()

        packet = OutlineSeedPacket(
            packet_id="packet-climax",
            book_id=book_id,
            user_intent={"desired_actions": ["继续调查旧案"]},
            story_scale={"target_chapter_count": 3},
            climax_input={
                "analysis_status": "needs_user_input",
                "user_questions": [
                    "这 3 章里你希望重点详细刻画的高潮或关键转折是什么？如果没有高潮、只是过渡剧情，也可以直接说“没有高潮，本批次为过渡剧情”。"
                ],
            },
        )
        result = OutlineResearchLoopController(
            broker=OutlineResearchContextBroker(repo_root=orchestrator.repo_root),
            model_adapter=_ScriptedResearchAdapter(decisions=[SufficiencyDecision(decision_id="enough", status="enough")]),
        ).run(conn, book_id=book_id, seed_packet=packet, budget=ResearchBudget(max_rounds=1))

    assert result.sufficiency_decision.status == "needs_user_input"
    assert result.sufficiency_decision.user_questions == [
        "这 3 章里你希望重点详细刻画的高潮或关键转折是什么？如果没有高潮、只是过渡剧情，也可以直接说“没有高潮，本批次为过渡剧情”。"
    ]


def test_outline_research_accepts_user_no_climax_answer(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path, adapter=_ScriptedResearchAdapter())
    book_id = "book-no-climax-answer"
    question = "这 3 章里你希望重点详细刻画的高潮或关键转折是什么？"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        conn.commit()

        packet = OutlineSeedPacket(
            packet_id="packet-no-climax",
            book_id=book_id,
            user_intent={"desired_actions": ["整理线索和关系"]},
            story_scale={"target_chapter_count": 3},
            climax_input={"analysis_status": "needs_user_input", "user_questions": [question]},
        )
        result = OutlineResearchLoopController(
            broker=OutlineResearchContextBroker(repo_root=orchestrator.repo_root),
            model_adapter=_ScriptedResearchAdapter(decisions=[SufficiencyDecision(decision_id="enough", status="enough")]),
        ).run(
            conn,
            book_id=book_id,
            seed_packet=packet,
            budget=ResearchBudget(max_rounds=1),
            user_answers={question: "没有高潮部分，本批次章节为过渡剧情。"},
        )

    assert result.sufficiency_decision.status == "enough"
    assert result.planning_notebook.confirmed_facts[0].fact_status == "user_authorized"


def test_outline_research_model_adapter_logs_prompt_lengths_for_broker_selection(caplog: Any) -> None:
    model_client = _PromptLengthModelClient(
        {
            "need_drill_down": False,
            "selected_ids": ["summary-1"],
            "query_suffix": "旧案线索",
            "reason": "候选摘要命中旧案线索",
            "confidence": 0.8,
            "need_sibling_scan": False,
        }
    )
    adapter = ModelOutlineResearchModelAdapter(model_client=model_client)
    state = MemoryQueryState(
        original_query="旧案线索下一步如何回收",
        current_level="event_summary",
        current_candidates=[
            {
                "id": "summary-1",
                "summary": "旧案线索仍未回收。",
                "page_type": "event_summary",
            }
        ],
    )
    request = ResearchRequest(
        request_id="req-log",
        request_type="story_detail",
        query="旧案线索下一步如何回收",
        purpose="确认 NarrativeInquiryBroker 候选选择 prompt 长度日志",
        priority="high",
    )

    caplog.set_level(logging.INFO, logger="novel_agent.app.services.outline_research_service")
    selection = adapter.select_memory_candidates(state=state, request=request)

    assert selection.selected_ids == ["summary-1"]
    messages = [
        record.getMessage()
        for record in caplog.records
        if "outline_research.model_prompt_stats" in record.getMessage()
    ]
    assert len(messages) == 1
    assert "stage=select_memory_candidates:event_summary" in messages[0]
    assert "system_chars=" in messages[0]
    assert "user_chars=" in messages[0]
    assert "total_bytes=" in messages[0]
    assert "旧案线索下一步如何回收" not in messages[0]


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


def test_outline_seed_packet_marks_latest_written_chapter_as_completed_anchor(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-continuation-boundary"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        DocumentsRepo().insert_document(
            conn,
            {
                "book_id": book_id,
                "path": "generated/chapter-0011.md",
                "scope": "generated",
                "title": "第十一章 已完成锚点",
                "document_title": "第十一章 已完成锚点",
                "document_title_index": 11,
                "inferred_chapter_no": 11,
                "content": "沈青已经完成上一段行动，下一章应写新的后续。",
                "content_chars": 24,
                "character_keywords": ["沈青"],
                "content_tags": ["writer_generated", "user_accepted"],
                "source_path": "generated/chapter-0011.md",
                "source_file_name": "chapter-0011.md",
                "source_start_offset": 0,
                "source_end_offset": 24,
                "ingestion_run_id": "run-1",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "document_title_index": 11,
                "chapter_title": "第十一章 已完成锚点",
                "source_doc_start_id": 2,
                "source_doc_end_id": 2,
                "source_doc_count": 1,
                "source_total_chars": 24,
                "summary_intermediate": [],
                "summary_md": "沈青已经完成上一段行动，顾迟确认下一章应写新的后续。",
                "summary_short": "沈青完成上一段行动，顾迟确认下一章应写新的后续。",
                "summary_status": "provisional",
                "summary_evidence_window": "11-11",
                "summary_target_range": "11-11",
                "importance_score": 80,
                "importance_reason": "writer writeback",
                "related_chapters": [],
                "mentioned_characters": ["沈青", "顾迟"],
                "world_update": {},
                "outline_update": {
                    "chapter_line": "[11] 第十一章 已完成锚点: 沈青完成上一段行动，顾迟确认下一章应写新的后续。",
                    "timeline_events": [
                        {
                            "label": "已完成行动",
                            "participants": ["沈青", "顾迟"],
                            "summary": "沈青完成上一段行动，顾迟确认下一章应写新的后续。",
                            "source_doc_ids": [2],
                            "source_doc_range": "2",
                        }
                    ],
                },
                "outline_status": "provisional",
                "outline_evidence_window": "11-11",
                "outline_target_range": "11-11",
                "close_read_run_id": "run-1",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

        intent = orchestrator.build_continuation_intent(
            {
                "desired_actions": ["继续最新已写回章节之后的剧情"],
                "story_scale": {"target_chapter_count": 1},
                "climax_plan": {"climax_mode": "none", "no_climax": True},
            }
        )
        mentions = orchestrator.character_mention_extractor.extract({})
        packet = OutlineSeedPacketBuilder(repo_root=orchestrator.repo_root).build(
            conn,
            book_id=book_id,
            intent=intent,
            mentions=mentions,
            resolutions=[],
        )

    serialized = packet.to_dict()
    boundary = serialized["continuation_boundary"]
    assert boundary["completed_anchor_document_title_index"] == 11
    assert boundary["next_document_title_index"] == 12
    assert boundary["completed_anchor_is_past_context"] is True
    assert "不得重写" in serialized["current_continuation_anchor"]
    assert "顾迟确认下一章应写新的后续" in serialized["current_continuation_anchor"]
    assert any(
        item.get("summary_level") == "chapter_summary" and item.get("ends_at") == "document_title_index=11"
        for item in serialized["historical_story_overview"]
    )
    assert "document_title_index=12" in boundary["instruction"]


def test_outline_seed_packet_limits_recent_chapter_overview_budget(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-recent-budget"
    long_summary = "这一章有大量需要压缩的剧情推进。" * 80
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        for index in range(1, 13):
            _seed_chapter(
                conn,
                book_id=book_id,
                index=index,
                title=f"第{index}章",
                summary=f"第{index}章: {long_summary}",
                mentioned=["沈青"],
            )
        conn.commit()

        intent = orchestrator.build_continuation_intent(
            {
                "desired_actions": ["继续最近章节之后的剧情"],
                "story_scale": {"target_chapter_count": 1},
                "climax_plan": {"climax_mode": "none", "no_climax": True},
            }
        )
        packet = OutlineSeedPacketBuilder(repo_root=orchestrator.repo_root).build(
            conn,
            book_id=book_id,
            intent=intent,
            mentions=orchestrator.character_mention_extractor.extract({}),
            resolutions=[],
        )

    chapter_items = [
        item
        for item in packet.to_dict()["historical_story_overview"]
        if item.get("summary_level") == "chapter_summary"
    ]
    total_summary_chars = sum(len(str(item.get("summary") or "")) for item in chapter_items)
    assert total_summary_chars <= OutlineSeedPacketBuilder.RECENT_CHAPTER_OVERVIEW_TOTAL_CHARS
    assert all(
        len(str(item.get("summary") or "")) <= OutlineSeedPacketBuilder.RECENT_CHAPTER_OVERVIEW_ITEM_CHARS
        for item in chapter_items
    )
    assert len(chapter_items) < OutlineSeedPacketBuilder.RECENT_CHAPTER_OVERVIEW_MAX_ITEMS
    assert chapter_items[-1]["ends_at"] == "document_title_index=12"


def test_model_sufficiency_prompt_forbids_questions_about_completed_anchor() -> None:
    client = FakeWriterModelClient()
    adapter = ModelOutlineResearchModelAdapter(model_client=client)
    packet = OutlineSeedPacket(
        packet_id="packet-1",
        book_id="book-1",
        user_intent={"desired_actions": ["继续最新章节之后的剧情"]},
        story_scale={"target_chapter_count": 1},
        climax_input={"climax_mode": "none", "no_climax": True},
        current_continuation_anchor="第十章 已完成锚点",
        continuation_boundary={
            "completed_anchor_document_title_index": 10,
            "next_document_title_index": 11,
            "completed_anchor_is_past_context": True,
        },
    )

    adapter.decide_sufficiency(seed_packet=packet, notebook=PlanningNotebook(notebook_id="nb-1"), budget_state={})

    system_prompt, user_prompt = client.json_calls[-1]
    assert "不得询问用户是否要详细描写" in system_prompt
    assert "next_document_title_index" in system_prompt
    assert "continuation_boundary" in user_prompt


def test_model_research_request_adapter_accepts_common_request_wrappers() -> None:
    client = _PromptLengthModelClient(
        {
            "research_requests": {
                "items": [
                    {
                        "request_type": "story_detail",
                        "query": "最近已写回章节后的续写依据",
                        "purpose": "确认下一批大纲承接点",
                        "priority": "high",
                    }
                ]
            }
        }
    )
    adapter = ModelOutlineResearchModelAdapter(model_client=client)
    packet = OutlineSeedPacket(
        packet_id="packet-1",
        book_id="book-1",
        user_intent={"desired_actions": ["继续最新章节之后的剧情"]},
        story_scale={"target_chapter_count": 1},
        climax_input={"climax_mode": "none", "no_climax": True},
    )

    requests = adapter.propose_research_requests(
        seed_packet=packet,
        notebook=PlanningNotebook(notebook_id="nb-1"),
        prior_results=[],
        budget_state={},
    )

    assert requests[0]["request_type"] == "story_detail"
    assert requests[0]["query"] == "最近已写回章节后的续写依据"


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


def test_outline_research_character_profile_pages_story_events_by_offset(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-character-page"
    story_events = [
        {"label": f"经历{i}", "summary": f"沈青第{i}段经历。", "source_doc_ids": [i + 1]}
        for i in range(10)
    ]
    story_events[8] = {
        "label": "后段关键经历",
        "summary": "沈青在后段经历中确认与顾迟只能有限合作。",
        "source_doc_ids": [9],
        "source_doc_range": "9",
        "outline_segment_id": "outline-segment:chapter-9:docs-9",
    }
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "沈青",
                "aliases": [],
                "profile_summary_md": "沈青长期调查旧案。",
                "story_events": story_events,
                "evidence_level": "confirmed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

        broker = OutlineResearchContextBroker(repo_root=orchestrator.repo_root)
        [result] = broker.resolve_requests(
            conn,
            book_id=book_id,
            requests=[
                ResearchRequest(
                    request_id="char-page",
                    request_type="character_profile",
                    name="沈青",
                    query="沈青经历分页",
                    priority="high",
                    metadata={"story_events_offset": 8, "story_events_char_budget": 99999},
                )
            ],
            budget=ResearchBudget(max_total_requests=1, max_return_tokens_per_request=900),
        )

    assert result.request_type == "character_profile"
    assert result.results[0]["story_events"][0].startswith("后段关键经历")
    assert result.results[0]["story_events_page"]["offset"] == 8
    assert result.results[0]["story_events_page"]["char_budget"] == 4096


def test_outline_research_character_profile_pagination_metadata_is_not_deduped(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-character-dedupe"
    story_events = [{"label": f"经历{i}", "summary": f"沈青第{i}段经历。"} for i in range(4)]
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "沈青",
                "aliases": [],
                "profile_summary_md": "沈青长期调查旧案。",
                "story_events": story_events,
                "evidence_level": "confirmed",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

        broker = OutlineResearchContextBroker(repo_root=orchestrator.repo_root)
        results = broker.resolve_requests(
            conn,
            book_id=book_id,
            requests=[
                ResearchRequest(
                    request_id="char-page-0",
                    request_type="character_profile",
                    name="沈青",
                    query="沈青经历分页",
                    priority="high",
                    metadata={"story_events_offset": 0, "story_events_char_budget": 80},
                ),
                ResearchRequest(
                    request_id="char-page-2",
                    request_type="character_profile",
                    name="沈青",
                    query="沈青经历分页",
                    priority="high",
                    metadata={"story_events_offset": 2, "story_events_char_budget": 80},
                ),
            ],
            budget=ResearchBudget(max_total_requests=2, max_return_tokens_per_request=900),
        )

    assert [item.request_id for item in results] == ["char-page-0", "char-page-2"]
    assert results[0].results[0]["story_events_page"]["offset"] == 0
    assert results[1].results[0]["story_events_page"]["offset"] == 2


def test_outline_research_story_detail_uses_narrative_scene_cards_first(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-scene-cards"
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
        _write_scene_cards(orchestrator.repo_root, book_id=book_id)
        conn.commit()

        broker = OutlineResearchContextBroker(repo_root=orchestrator.repo_root)
        results = broker.resolve_requests(
            conn,
            book_id=book_id,
            requests=[
                ResearchRequest(
                    request_id="story-scene",
                    request_type="story_detail",
                    query="最近一次信任冲突的经过和结果",
                    priority="high",
                    facets_needed=["relationship_state", "outcome"],
                )
            ],
            budget=ResearchBudget(max_total_requests=1, max_return_tokens_per_request=1000),
        )

    assert len(results) == 1
    result = results[0]
    assert result.request_type == "story_detail"
    assert result.results[0]["event_summary_level"] == "narrative_scene"
    assert result.results[0]["memory_query_protocol"] == "narrative_scene_card_search"
    assert result.results[0]["turning_point"] == "两人的信任从默认协作转为有限合作。"
    assert result.results[0]["relationship_movements"] == ["沈青与顾迟由互信转向有限合作"]
    assert result.results[0]["summary_sufficiency"] == "needs_raw_for_emotional_texture"
    assert "raw_read_recommended" in result.missing_facets
    scene_trace = [
        item
        for item in result.results[0]["memory_query_trace"]
        if item.get("operation") == "narrative_index_search"
    ]
    assert scene_trace
    assert scene_trace[0]["consumer"] == "outline_research"
    assert scene_trace[0]["target_card_types"] == ["narrative_scene"]


def test_story_detail_prefers_recent_generated_chapter_over_stale_scene_card(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    book_id = "book-generated-recent"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_chapter(
            conn,
            book_id=book_id,
            index=11,
            title="第十一章 信任裂缝",
            summary="沈青和顾迟因为旧案证据来源爆发早前一次信任冲突，结束后只保持有限合作。",
            mentioned=["沈青", "顾迟"],
        )
        _write_scene_cards(orchestrator.repo_root, book_id=book_id)
        doc_id = DocumentsRepo().insert_document(
            conn,
            {
                "book_id": book_id,
                "path": "generated/chapter-0012.md",
                "scope": "generated",
                "title": "第十二章 刚写回的信任冲突",
                "document_title": "第十二章 刚写回的信任冲突",
                "document_title_index": 12,
                "inferred_chapter_no": 12,
                "content": "沈青在最新写回章节中发现镜匣线索，顾迟确认下一步转向北塔。",
                "content_chars": 31,
                "character_keywords": ["沈青", "顾迟"],
                "content_tags": ["writer_generated", "user_accepted"],
                "source_path": "generated/chapter-0012.md",
                "source_file_name": "chapter-0012.md",
                "source_start_offset": 0,
                "source_end_offset": 31,
                "ingestion_run_id": "run-generated",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "document_title_index": 12,
                "chapter_title": "第十二章 刚写回的信任冲突",
                "source_doc_start_id": doc_id,
                "source_doc_end_id": doc_id,
                "source_doc_count": 1,
                "source_total_chars": 31,
                "summary_intermediate": [],
                "summary_md": "沈青在最新写回章节中发现镜匣线索，顾迟确认下一步转向北塔。",
                "summary_short": "沈青发现镜匣线索，顾迟确认下一步转向北塔。",
                "summary_status": "provisional",
                "summary_evidence_window": "12-12",
                "summary_target_range": "12-12",
                "importance_score": 80,
                "importance_reason": "writer writeback",
                "related_chapters": [],
                "mentioned_characters": ["沈青", "顾迟"],
                "world_update": {},
                "outline_update": {
                    "outcome": "下一步转向北塔。",
                    "timeline_events": [
                        {
                            "event_id": "chapter-12:event-01-generated",
                            "label": "镜匣线索转向北塔",
                            "summary": "沈青在最新写回章节中发现镜匣线索，顾迟确认下一步转向北塔。",
                            "participants": ["沈青", "顾迟"],
                            "source_doc_ids": [doc_id],
                            "source_doc_range": str(doc_id),
                        }
                    ],
                },
                "outline_status": "provisional",
                "outline_evidence_window": "12-12",
                "outline_target_range": "12-12",
                "close_read_run_id": "run-generated",
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

        resolver = StoryDetailResolver(repo_root=orchestrator.repo_root)
        result = resolver.resolve(
            conn,
            book_id=book_id,
            request=ResearchRequest(
                request_id="recent-generated",
                request_type="story_detail",
                query="上一批刚写回章节里的信任冲突和镜匣线索结果",
                priority="high",
            ),
            max_chars=500,
        )

    assert result.results[0]["memory_query_protocol"] == "recent_generated_chapter_summary"
    assert result.results[0]["source_doc_ids"] == [doc_id]
    assert "北塔" in result.results[0]["summary"]


def test_writer_writeback_character_events_are_scoped_from_state_delta(tmp_path: Path) -> None:
    executor = RestrictedWriterExecutor(
        repo_root=tmp_path,
        run_writer=RunWriter(layout=RunLayout(base_dir=tmp_path / "runs")),
        model_client=FakeWriterModelClient(),  # type: ignore[arg-type]
    )
    state_delta = {
        "mentioned_characters": ["沈青", "顾迟"],
        "outline_update": {
            "chapter_line": "[12] 第十二章: 沈青发现镜匣线索。",
            "outline_segment_id": "outline-segment:chapter-12:docs-42",
            "outline_segment": "沈青发现镜匣线索，顾迟确认下一步转向北塔。",
        },
    }

    events = executor._story_events_by_name_from_state_delta(  # noqa: SLF001
        state_delta=state_delta,
        chapter_index=12,
        doc_id=42,
    )
    activity = executor._recent_activity_for_character(  # noqa: SLF001
        name="沈青",
        state_delta=state_delta,
        fallback="第十二章",
    )

    assert events["沈青"][0]["source_doc_ids"] == [42]
    assert events["顾迟"][0]["source_chapter_indexes"] == [12]
    assert events["沈青"][0]["outline_segment_id"] == "outline-segment:chapter-12:docs-42"
    assert "北塔" in activity


def test_writer_state_delta_extracts_character_names_instead_of_plot_beats(tmp_path: Path) -> None:
    model_client = _PromptLengthModelClient(
        {
            "mentioned_characters": ["沈青", "林澈"],
            "outline_update": {
                "chapter_line": "[2] 新的会面: 沈青与林澈完成线索交接。",
                "outline_segment": "沈青与林澈完成线索交接。",
            },
            "world_update": {"should_update": False, "changes": []},
        }
    )
    executor = RestrictedWriterExecutor(
        repo_root=tmp_path,
        run_writer=RunWriter(layout=RunLayout(base_dir=tmp_path / "runs")),
        model_client=model_client,
    )
    execution_input = {
        "chapter_id": "chapter-2",
        "chapter_title": "新的会面",
        "document_title_index": 2,
        "chapter_brief": {
            "title": "新的会面",
            "goal": "沈青与林澈完成线索交接。",
            "must_include": ["沈青在旧码头完成调查，并把线索交给林澈。"],
        },
        "fact_inputs": {
            "character_profiles": [
                {"canonical_name": "沈青", "aliases": ["阿青"], "matched_names": []},
            ]
        },
    }

    state_delta = executor._extract_state_delta(  # noqa: SLF001
        execution_input=execution_input,
        draft_text="沈青把资料递给林澈，两人确认下一步行动。",
        blocked=False,
    )

    assert state_delta["mentioned_characters"] == ["沈青", "林澈"]
    assert "沈青在旧码头完成调查" not in json.dumps(state_delta, ensure_ascii=False)
    assert state_delta["outline_update"]["outline_segment"] == "沈青与林澈完成线索交接。"
    assert "timeline_events" not in state_delta["outline_update"]


def test_writer_writeback_creates_profile_for_model_extracted_new_character(tmp_path: Path) -> None:
    db, orchestrator = _build_db_and_orchestrator(tmp_path)
    executor = RestrictedWriterExecutor(
        repo_root=orchestrator.repo_root,
        run_writer=orchestrator.run_writer,
        model_client=FakeWriterModelClient(),  # type: ignore[arg-type]
    )
    book_id = "book-writeback-new-character"
    state_delta = {
        "mentioned_characters": ["沈青", "林澈"],
        "outline_update": {
            "chapter_line": "[2] 新的会面: 沈青与林澈完成线索交接。",
            "timeline_events": [
                {
                    "label": "线索交接",
                    "participants": ["沈青", "林澈"],
                    "summary": "沈青与林澈完成线索交接。",
                }
            ],
        },
    }
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        updates, activated = executor._build_character_updates(  # noqa: SLF001
            conn,
            book_id=book_id,
            execution_input={"chapter_title": "新的会面", "document_title_index": 2},
            state_delta=state_delta,
        )
        executor.character_profile_service.merge_updates(
            conn,
            book_id=book_id,
            chapter_index=2,
            doc_ids=[99],
            updates=updates,
            story_events_by_name=executor._story_events_by_name_from_state_delta(  # noqa: SLF001
                state_delta=state_delta,
                chapter_index=2,
                doc_id=99,
            ),
        )
        conn.commit()
        new_row = CharacterProfilesRepo().get(conn, book_id=book_id, canonical_name="林澈")

    assert activated == ["林澈"]
    assert new_row is not None
    assert "已通过审阅并写回" in str(new_row["personhood_evidence_summary"])


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
        segments = service.drill_down(
            conn,
            book_id=book_id,
            state=root,
            selected_ids=[root.current_candidates[0]["id"]],
            query_suffix="确认相关剧情段",
            selection_reason="root summary covers the conflict",
            confidence=0.8,
        )
        chapters = service.drill_down(
            conn,
            book_id=book_id,
            state=segments,
            selected_ids=[segments.current_candidates[0]["id"]],
            query_suffix="展开章节摘要",
            selection_reason="segment mentions trust conflict",
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

    assert root.current_level == "outline_root"
    assert root.current_candidates[0]["outline_segment_ids"]
    assert segments.current_level == "outline_segment"
    assert segments.current_candidates[0]["outline_segment_id"].startswith("outline-segment:chapter-11")
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

        intent = orchestrator.build_continuation_intent(
            {"desired_actions": ["追查旧案线索"], "climax_plan": {"no_climax": True, "climax_mode": "none"}}
        )
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
                intent_payload={
                    "major_characters": ["沈青", "顾迟"],
                    "desired_actions": ["沈青追查旧案"],
                    "climax_plan": {"no_climax": True, "climax_mode": "none"},
                },
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
                intent_payload={
                    "major_characters": ["沈青", "顾迟"],
                    "desired_actions": ["沈青追查旧案"],
                    "climax_plan": {"no_climax": True, "climax_mode": "none"},
                },
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


def test_outline_research_freeform_answer_can_satisfy_question_set(tmp_path: Path) -> None:
    db, planner = _build_db_and_orchestrator(tmp_path, adapter=_AnswerAwareAdapter())
    executor = RestrictedWriterExecutor(repo_root=planner.repo_root, run_writer=planner.run_writer)
    workflow = WriterInteractiveWorkflow(
        planner=planner,
        executor=executor,
        rollback_manager=WriterRollbackManager(run_writer=planner.run_writer),
        run_writer=planner.run_writer,
    )
    book_id = "book-freeform-answer"
    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_base_memory(conn, book_id=book_id, repo_root=planner.repo_root)
        conn.commit()

        initial = workflow.prepare_planning(
            conn,
            run_id="run-freeform-answer",
            book_id=book_id,
            product_mode="assist",
            intent_payload={
                "major_characters": ["沈青", "顾迟"],
                "desired_actions": ["沈青追查旧案"],
                "climax_plan": {"no_climax": True, "climax_mode": "none"},
            },
        )
        question_set_path = planner.run_writer.layout.run_dir("run-freeform-answer") / "outline_research_question_set.json"
        question_set_doc = json.loads(question_set_path.read_text(encoding="utf-8"))
        question_set_doc["data"]["questions"].append(
            {"question_id": "q2", "prompt": "下一章节奏偏快还是偏慢？", "required": True}
        )
        question_set_path.write_text(json.dumps(question_set_doc, ensure_ascii=False), encoding="utf-8")

        continued = workflow.continue_after_outline_research_input(
            conn,
            run_id="run-freeform-answer",
            book_id=book_id,
            product_mode="assist",
            question_set_id=initial["question_set"]["question_set_id"],
            answer_text="下一章先确认人物关系，再用慢节奏推进调查。",
            user_answers=[],
        )

    assert continued["character_requirement_report"]["named_new_characters"] == []
    state = workflow.load_workflow_state(run_id="run-freeform-answer")
    assert state["current_stage"] == "freeze_a_review"
    submission = _load_run_data(planner.run_writer, "run-freeform-answer", "outline_research_answer_submission.json")
    assert submission["answer_text"] == "下一章先确认人物关系，再用慢节奏推进调查。"
    assert submission["user_answers"] == []
    intent = _load_run_data(planner.run_writer, "run-freeform-answer", "continuation_intent.json")
    assert "下一章先确认人物关系" in intent["notes"]
    assert "顾迟是否为新增人物" in intent["raw_user_prompt"]
    assert "下一章先确认人物关系" in intent["raw_user_prompt"]
    notebook = _load_run_data(planner.run_writer, "run-freeform-answer", "planning_notebook.json")
    assert any(fact["fact_status"] == "user_authorized" for fact in notebook["confirmed_facts"])


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
                intent_payload={
                    "major_characters": ["沈青"],
                    "desired_actions": ["追查旧案线索"],
                    "climax_plan": {"no_climax": True, "climax_mode": "none"},
                },
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
