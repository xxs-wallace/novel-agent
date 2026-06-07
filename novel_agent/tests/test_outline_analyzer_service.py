from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.schemas.narrative_inquiry_schema import (
    AnalyzerBudget,
    AnalyzerLoopOutput,
    AnalyzerNotebook,
    EvidenceBundle,
    NarrativeInquiryRequest,
)
from novel_agent.app.services.narrative_inquiry_broker import NarrativeInquiryBroker
from novel_agent.app.services.narrative_memory_query_service import NarrativeMemoryQueryService
from novel_agent.app.services.outline_analyzer_service import AnalyzerService, _compact_evidence_bundle, _compact_mapping


OutlineAnalyzerService = AnalyzerService


class ScriptedAnalyzerModel:
    def __init__(self, outputs: list[str], *, auto_intent: bool = True) -> None:
        self.outputs = list(outputs)
        self.prompts: list[dict[str, Any]] = []
        self.auto_intent = auto_intent

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        timeout_seconds: int | None = None,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        include_reasoning_content: bool | None = None,
    ) -> str:
        self.prompts.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "timeout_seconds": timeout_seconds,
                "thinking": thinking,
                "reasoning_effort": reasoning_effort,
                "include_reasoning_content": include_reasoning_content,
            }
        )
        if self.auto_intent and "AnalyzerIntentGate" in system_prompt:
            return json.dumps(
                {
                    "analysis_type": "outline_analysis",
                    "confidence": 0.75,
                    "matched_signals": ["测试默认问题需要大纲取证"],
                    "secondary_analysis_types": [],
                    "required_evidence_plan": ["query outline roots and compact cards"],
                    "notes": "test auto intent",
                },
                ensure_ascii=False,
            )
        if not self.outputs:
            return json.dumps({"status": "ready_to_answer", "final_answer": "结论：证据不足。"}, ensure_ascii=False)
        return self.outputs.pop(0)


class SpyMemoryQueryService(NarrativeMemoryQueryService):
    def __init__(self, *, repo_root: Path) -> None:
        super().__init__(repo_root=repo_root)
        self.calls: list[str] = []

    def root_scan(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.calls.append("root_scan")
        return super().root_scan(*args, **kwargs)

    def root_map(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.calls.append("root_map")
        return super().root_map(*args, **kwargs)

    def resolve_chapter_refs(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.calls.append("resolve_chapter_refs")
        return super().resolve_chapter_refs(*args, **kwargs)

    def resolve_document_refs(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.calls.append("resolve_document_refs")
        return super().resolve_document_refs(*args, **kwargs)


def _seed_memory(repo_root: Path, *, book_id: str = "book-one") -> NovelAgentDB:
    db = NovelAgentDB(repo_root / ".indexes" / f"{book_id}.db")
    now = "2026-05-21T00:00:00Z"
    outline_path = repo_root / ".memory" / "outlines" / f"{book_id}.outline.md"
    world_path = repo_root / ".memory" / "world" / f"{book_id}.summary.md"
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text("# 故事大纲\n\n## 当前未解问题\n- 证据来源尚未揭开\n", encoding="utf-8")
    world_path.write_text("# 世界观摘要\n调查不能绕过证据链。\n", encoding="utf-8")
    with db.connect() as conn:
        db.init_schema(conn)
        AssetsRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "source_root": str(repo_root),
                "world_markdown_path": str(world_path),
                "world_summary_path": str(world_path),
                "outline_markdown_path": str(outline_path),
                "created_at": now,
                "updated_at": now,
            },
        )
        DocumentsRepo().insert_document(
            conn,
            {
                "book_id": book_id,
                "path": "doc-1",
                "content": "调查者发现证据被人刻意转移，决定暂时隐瞒线索以确认来源。",
                "document_title": "第一章",
                "document_title_index": 1,
                "character_keywords": ["调查者"],
                "content_tags": ["证据", "来源"],
                "created_at": now,
                "updated_at": now,
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "document_title_index": 1,
                "chapter_title": "第一章",
                "source_doc_start_id": 1,
                "source_doc_end_id": 1,
                "source_doc_count": 1,
                "source_total_chars": 30,
                "summary_md": "调查者发现证据线索，但来源仍然可疑。",
                "summary_short": "证据线索出现，来源未明。",
                "mentioned_characters": ["调查者"],
                "outline_update": {
                    "chapter_line": "[1] 第一章: 证据线索出现，来源未明。",
                    "outline_segment_id": "outline-segment:chapter-1:docs-1",
                    "outline_segment": "证据来源未明，调查者选择暂时隐瞒。",
                    "source_doc_ids": [1],
                    "source_doc_range": "1",
                    "source_title_indexes": [1],
                    "status": "committed",
                },
                "summary_status": "committed",
                "outline_status": "committed",
                "created_at": now,
                "updated_at": now,
            },
        )
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "canonical_name": "调查者",
                "profile_summary_md": "谨慎，重视证据链。",
                "relationships": [],
                "recent_activity": ["发现证据线索"],
                "evidence_level": "confirmed",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()
    return db


def _triage_keep(*request_ids: str) -> str:
    return json.dumps(
        {
            "kept_request_ids": list(request_ids),
            "rejected_request_ids": [],
            "notes": ["保留与当前问题直接相关的 evidence"],
        },
        ensure_ascii=False,
    )


def test_evidence_bundle_contract_statuses_and_summary_only() -> None:
    summary_bundle = EvidenceBundle(
        request_id="req-1",
        request_type="story_detail",
        query="证据来源",
        status="found",
        fact_status="confirmed",
        evidence_items=[{"summary": "证据来源未明"}],
        trace=[{"operation": "root_scan"}],
    )
    excerpt_bundle = EvidenceBundle(
        request_id="req-2",
        request_type="raw_excerpt",
        query="确认措辞",
        status="found",
        fact_status="candidate",
        excerpts=[{"doc_id": 1, "text": "有限片段"}],
        source_doc_ids=[1],
    )
    missing_bundle = EvidenceBundle(
        request_id="req-3",
        request_type="fact_check",
        query="不存在的事实",
        status="missing",
        fact_status="missing",
        missing_facets=["memory_evidence"],
    )
    conflicting_bundle = EvidenceBundle(
        request_id="req-4",
        request_type="fact_check",
        query="互相冲突的事实",
        status="found",
        fact_status="conflicting",
    )
    insufficient_bundle = EvidenceBundle(
        request_id="req-5",
        request_type="raw_excerpt",
        query="读取整本原文",
        status="blocked",
        fact_status="insufficient_context",
    )

    assert summary_bundle.to_dict()["excerpts"] == []
    assert excerpt_bundle.to_dict()["source_doc_ids"] == [1]
    assert missing_bundle.missing_facets == ["memory_evidence"]
    assert conflicting_bundle.fact_status == "conflicting"
    assert insufficient_bundle.status == "blocked"


def test_analyzer_loop_output_ignores_invalid_requests_when_ready() -> None:
    output = AnalyzerLoopOutput.from_mapping(
        {
            "status": "ready_to_answer",
            "requests": [{"type": "story_detail", "purpose": "stale malformed request"}],
            "final_answer": "结论：可以回答。",
        }
    )

    assert output.status == "ready_to_answer"
    assert output.requests == []
    assert "可以回答" in output.final_answer


def test_analyzer_budget_defaults_allow_more_loop_under_prompt_cap() -> None:
    budget = AnalyzerBudget()

    assert budget.max_rounds == 8
    assert budget.max_total_requests == 24
    assert budget.max_raw_excerpt_requests == 6
    assert budget.max_prompt_bytes == 65536
    assert budget.triage_page_bytes == 16384
    assert budget.prompt_timeout_seconds == 120
    assert budget.final_prompt_timeout_seconds == 300


def test_analyzer_intent_gate_model_routes_relationship_workflow(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    model = ScriptedAnalyzerModel(
        [
            json.dumps(
                {
                    "analysis_type": "relationship_analysis",
                    "confidence": 0.91,
                    "matched_signals": ["用户询问两名角色的感情与关系", "用户要求设计关系走向"],
                    "secondary_analysis_types": ["outline_analysis"],
                    "required_evidence_plan": [
                        "resolve participating characters",
                        "read character profiles and relationship events",
                        "find shared experiences",
                    ],
                    "notes": "关系分析应驱动取证，大纲分析作为后续结局设计补充。",
                },
                ensure_ascii=False,
            ),
            json.dumps({"status": "ready_to_answer", "final_answer": "结论：关系线需要先核对共同经历。"}, ensure_ascii=False),
        ],
        auto_intent=False,
    )
    service = AnalyzerService(repo_root=tmp_path, model_client=model)

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="分析两名主角的感情关系和后续走向。")

    assert result.status == "ok"
    assert result.seed is not None
    assert result.seed.analysis_type == "relationship_analysis"
    assert result.seed.intent_gate["confidence"] == 0.91
    assert "共同经历" in result.answer
    assert "AnalyzerIntentGate" in model.prompts[0]["system_prompt"]
    gate_payload = json.loads(model.prompts[0]["user_prompt"])
    gate_payload_text = json.dumps(gate_payload, ensure_ascii=False)
    assert "local_seed_map" not in gate_payload
    assert "root_summary" in gate_payload
    assert "character_index" not in gate_payload_text
    assert "world_concept_index" not in gate_payload_text
    assert "sources" not in gate_payload_text
    assert "analysis_type=relationship_analysis" in model.prompts[1]["system_prompt"]
    assert "RelationshipAnalyzer prompt" in model.prompts[1]["system_prompt"]
    assert "character_profile" in model.prompts[1]["system_prompt"]


def test_analyzer_prompt_stage_timeouts_are_passed_to_model(tmp_path: Path) -> None:
    model = ScriptedAnalyzerModel(
        [
            json.dumps({"status": "ready_to_answer", "final_answer": "结论：可以回答。"}, ensure_ascii=False),
            json.dumps({"kept_request_ids": ["req-1"], "rejected_request_ids": [], "notes": []}, ensure_ascii=False),
            "最终回答",
        ]
    )
    service = OutlineAnalyzerService(
        repo_root=tmp_path,
        model_client=model,
        budget=AnalyzerBudget(
            prompt_timeout_seconds=11,
            loop_prompt_timeout_seconds=7,
            triage_prompt_timeout_seconds=13,
            final_prompt_timeout_seconds=17,
        ),
    )
    db = _seed_memory(tmp_path)
    with db.connect() as conn:
        seed = service.seed_builder.build(
            conn,
            book_id="book-one",
            question="下一阶段如何回收证据？",
            conversation_history=[],
        )
        service._call_loop_model(  # noqa: SLF001 - validates model boundary contract.
            book_id="book-one",
            round_index=1,
            seed=seed,
            notebook=AnalyzerNotebook(),
            evidence_history=[],
            budget_state={"total_requests_used": 0, "raw_requests_used": 0, "exhausted": False},
        )
        service._call_single_triage_model(  # noqa: SLF001 - validates model boundary contract.
            book_id="book-one",
            round_index=1,
            bundle_index=1,
            seed=seed,
            notebook=AnalyzerNotebook(),
            request=NarrativeInquiryRequest(
                request_id="req-1",
                request_type="story_detail",
                purpose="确认证据",
                query="证据",
            ),
            candidate_bundle=EvidenceBundle(
                request_id="req-1",
                request_type="story_detail",
                query="证据",
                status="found",
            ),
            budget_state={"total_requests_used": 1, "raw_requests_used": 0, "exhausted": False},
            kept_request_ids=[],
        )
        service._call_final_answer_model(  # noqa: SLF001 - validates model boundary contract.
            book_id="book-one",
            seed=seed,
            notebook=AnalyzerNotebook(),
            evidence_history=[],
        )

    assert [prompt["timeout_seconds"] for prompt in model.prompts] == [7, 13, 17]
    assert [prompt["thinking"] for prompt in model.prompts] == ["disabled", "disabled", None]
    assert [prompt["include_reasoning_content"] for prompt in model.prompts] == [False, False, None]


def test_analyzer_prompt_budget_compacts_large_json_payload(tmp_path: Path) -> None:
    service = OutlineAnalyzerService(
        repo_root=tmp_path,
        model_client=None,
        budget=AnalyzerBudget(max_prompt_bytes=4096),
    )
    system_prompt = "system"
    user_prompt = json.dumps(
        {
            "user_question": "当前剧情合理吗？",
            "committed_evidence_digests": [
                {
                    "request_id": f"req-{index}",
                    "evidence_items": [{"summary": "重要证据" * 600}],
                    "excerpts": [{"text": "原文片段" * 600}],
                }
                for index in range(12)
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    _, compact_user_prompt = service._fit_prompt_to_budget(
        system_prompt,
        user_prompt,
        stage="loop",
        book_id="book-one",
        round_index=2,
    )

    assert len((system_prompt + compact_user_prompt).encode("utf-8")) <= 4096
    compact_payload = json.loads(compact_user_prompt)
    assert compact_payload["_prompt_budget_note"]
    assert len(compact_payload["committed_evidence_digests"]) <= 6


def test_analyzer_seed_uses_root_map_and_question_filtered_character_index(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    with db.connect() as conn:
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "canonical_name": "旁观者",
                "aliases": ["路人甲", "看客"],
                "profile_summary_md": "与当前证据线没有直接关系。",
                "recent_activity": [],
                "evidence_level": "confirmed",
                "created_at": "2026-05-21T00:00:00Z",
                "updated_at": "2026-05-21T00:00:00Z",
            },
        )
        conn.commit()

    spy_memory = SpyMemoryQueryService(repo_root=tmp_path)
    service = OutlineAnalyzerService(
        repo_root=tmp_path,
        model_client=None,
        seed_builder=None,
    )
    service.seed_builder.memory_query_service = spy_memory

    with db.connect() as conn:
        seed = service.build_context(conn, book_id="book-one", question="调查者接下来应该如何处理证据来源？")

    assert seed.chapter_index == []
    assert seed.outline_index == []
    assert seed.source_arc_index == []
    assert seed.memory_page_roots
    assert "root_map" in spy_memory.calls
    assert "root_scan" not in spy_memory.calls
    names = {item["canonical_name"] for item in seed.character_index}
    assert "调查者" in names
    assert "旁观者" not in names


def test_analyzer_prompt_discourages_overblocking_on_analysis_questions(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    with db.connect() as conn:
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "canonical_name": "核心同伴",
                "aliases": ["同伴"],
                "profile_summary_md": "贯穿多章的核心关系角色，性格坚定，常与调查者共同面对证据压力。",
                "recent_activity": ["陪同调查者确认线索"],
                "evidence_level": "explicit",
                "speaking_character_status": "confirmed_speaking",
                "mentioned_doc_ids": [1, 2, 3],
                "speaking_doc_ids": [1, 3],
                "chapter_indexes": [1, 2],
                "first_seen_doc_id": 1,
                "last_seen_doc_id": 3,
                "first_seen_title_index": 1,
                "last_seen_title_index": 2,
                "created_at": "2026-05-21T00:00:00Z",
                "updated_at": "2026-05-21T00:00:00Z",
            },
        )
        conn.commit()
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=None)

    with db.connect() as conn:
        seed = service.build_context(conn, book_id="book-one", question="请评价主角性格，并推测之后可能怎么行动。")

    loop_system, loop_user = service.build_loop_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        evidence_history=[],
        budget_state={"total_requests_used": 0, "raw_requests_used": 0},
    )
    final_system, _ = service.build_final_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        evidence_history=[],
        budget_limited=False,
    )

    for prompt in (loop_system, final_system):
        assert "评价、分析、推测" in prompt
        assert "不要因为存在多个可能解释就返回 needs_user_preference" in prompt
        assert "暂定分析" in prompt or "暂定判断" in prompt
        assert "某个对象证据不足" in prompt
        assert "不要静默只选一个" in prompt
    names = {item["canonical_name"] for item in seed.character_index}
    assert "调查者" in names
    assert "核心同伴" in names
    assert "贯穿多章的核心关系角色" in loop_user
    assert "非阻塞追问" in final_system


def test_analyzer_prompt_uses_evidence_sufficiency_for_direct_fact_depth(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=None)

    with db.connect() as conn:
        seed = service.build_context(conn, book_id="book-one", question="短信里写的具体原句是什么？")

    loop_system, _ = service.build_loop_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        evidence_history=[],
        budget_state={"total_requests_used": 0, "raw_requests_used": 0},
    )
    final_system, _ = service.build_final_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        evidence_history=[],
        budget_limited=False,
    )
    readiness_system, readiness_user = service.build_answer_readiness_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        evidence_history=[
            EvidenceBundle(
                request_id="req-001",
                request_type="chapter_summary",
                query="短信场景",
                status="found",
                fact_status="candidate",
                evidence_items=[{"summary": "本章提到角色发现短信，但未记录具体原句。"}],
                source_doc_ids=[1],
            )
        ],
        proposed_answer="暂定回答会给出短信内容。",
        budget_state={"total_requests_used": 1, "raw_requests_used": 0},
    )
    triage_system, _ = service.build_single_triage_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        request=NarrativeInquiryRequest(
            request_id="req-001",
            request_type="chapter_summary",
            query="短信场景",
            purpose="定位短信原文所在章节",
            priority="high",
        ),
        candidate_bundle=EvidenceBundle(
            request_id="req-001",
            request_type="chapter_summary",
            query="短信场景",
            status="found",
            fact_status="candidate",
            evidence_items=[{"summary": "本章提到角色发现短信，但未记录具体原句。"}],
        ),
        budget_state={"total_requests_used": 0, "raw_requests_used": 0},
        kept_request_ids=[],
    )

    assert "回答粒度" in loop_system
    assert "不能替代缺失的更直接事实证据" in loop_system
    assert "不要从第一章开始全书阅读" in loop_system
    assert "定位证据保留" in triage_system
    assert "evidence sufficiency" in triage_system
    assert "answer readiness" in readiness_system
    assert "判断依据不是题面关键词" in readiness_system
    assert "source_doc_ids" in readiness_user
    assert "超出证据的具体断言" in final_system


def test_analyzer_prompt_exposes_text_search_locator(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=None)

    with db.connect() as conn:
        seed = service.build_context(conn, book_id="book-one", question="某条短信的原句在哪里？")

    loop_system, loop_user = service.build_loop_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        evidence_history=[],
        budget_state={"total_requests_used": 0, "raw_requests_used": 0},
    )

    assert "text_search" in loop_system
    assert "grep-like" in loop_system
    assert "metadata.terms" in loop_system
    assert "allow_document_scan" in loop_system
    assert "terms 必须能共同缩小范围" in loop_system
    assert "过宽定位" in loop_system
    assert "text_search" in loop_user
    assert "match_mode" in loop_user
    assert "term_quality" in loop_user
    assert "match_offset" in loop_user
    assert "documents" in loop_user
    assert "allow_document_scan" in loop_user


def test_analyzer_prefers_narrative_scene_cards_when_available(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    scene_path = tmp_path / ".memory" / "index_cards" / "book-one.scene_cards.json"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text(
        json.dumps(
            {
                "book_id": "book-one",
                "scene_cards": [
                    {
                        "card_id": "scene-1",
                        "card_type": "narrative_scene",
                        "book_id": "book-one",
                        "summary": "调查者在公开场合选择隐瞒证据来源，形成关系压力。",
                        "source_doc_ids": ["1"],
                        "source_title_indexes": [1],
                        "source_doc_range": "1",
                        "summary_sufficiency": "sufficient",
                        "status": "committed",
                        "confidence": 0.9,
                        "payload": {
                            "scene_type": "plot_turning_point",
                            "turning_point": "调查者决定不公开来源。",
                            "outcome": "同伴暂时误解他的动机。",
                            "relationship_movements": ["信任出现裂缝"],
                            "future_consequence": "后续需要回收证据来源以修复信任。",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=None)

    with db.connect() as conn:
        seed = service.build_context(conn, book_id="book-one", question="评价主角性格，并推测之后会怎么行动。")

    loop_system, loop_user = service.build_loop_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        evidence_history=[],
        budget_state={"total_requests_used": 0, "raw_requests_used": 0},
    )
    final_system, _ = service.build_final_prompt(
        seed=seed,
        notebook=AnalyzerNotebook(),
        evidence_history=[],
        budget_limited=False,
    )
    payload = json.loads(loop_user)

    assert seed.modeling_status["narrative_scene_cards_ready"] is True
    assert any(item["source_type"] == "narrative_scene_card" for item in seed.sources)
    assert "narrative_scene_card_search" in payload["available_request_types"]
    assert payload["output_schema"]["requests"][0]["type"] == "narrative_scene_card_search"
    assert "优先使用 Narrative Index compact cards" in loop_system
    assert "场景级结构证据" in final_system


def test_analyzer_compact_mapping_preserves_scene_card_payload() -> None:
    compact = _compact_mapping(
        {
            "card_id": "scene-1",
            "card_type": "narrative_scene",
            "summary": "关键场景摘要",
            "summary_sufficiency": "sufficient",
            "payload": {
                "scene_type": "relationship_turning_point",
                "turning_point": "人物公开做出选择",
                "outcome": "关系发生变化",
                "relationship_movements": ["信任增强"],
                "future_consequence": "后续行动更主动",
            },
        },
        text_limit=120,
    )

    assert compact["card_type"] == "narrative_scene"
    assert compact["summary_sufficiency"] == "sufficient"
    assert compact["payload"]["scene_type"] == "relationship_turning_point"
    assert compact["payload"]["turning_point"] == "人物公开做出选择"
    assert compact["payload"]["relationship_movements"] == ["信任增强"]


def test_outline_analyzer_research_loop_need_more_info_to_ready(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    model = ScriptedAnalyzerModel(
        [
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "type": "story_detail",
                            "query": "证据来源的首次出现和未解状态",
                            "purpose": "判断是否适合下一阶段回收",
                            "priority": "high",
                            "expected_depth": "chapter_summary",
                        }
                    ],
                    "notebook_delta": {"uncertain_gaps": ["需要确认证据来源"]},
                },
                ensure_ascii=False,
            ),
            _triage_keep("req-001"),
            json.dumps(
                {
                    "status": "ready_to_answer",
                    "notebook_delta": {
                        "reasonable_inferences": ["适合局部回收，但不宜揭开全部真相"]
                    },
                    "final_answer": "结论：更适合先做局部回收，保留来源背后的更大问题。",
                },
                ensure_ascii=False,
            ),
        ]
    )
    spy_memory = SpyMemoryQueryService(repo_root=tmp_path)
    broker = NarrativeInquiryBroker(repo_root=tmp_path, memory_query_service=spy_memory)
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=model, inquiry_broker=broker)

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="证据线索下一步怎么回收更合理？")

    assert result.status == "ok"
    assert "局部回收" in result.answer
    assert "story_detail" in {bundle.request_type for bundle in result.evidence_bundles}
    assert result.notebook is not None
    assert any("证据来源未明" in fact for fact in result.notebook.confirmed_facts)
    assert spy_memory.calls.count("root_scan") >= 1
    assert "read_only_context" not in model.prompts[0]["user_prompt"]


def test_answer_readiness_can_request_raw_excerpt_after_locator(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    model = ScriptedAnalyzerModel(
        [
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "type": "text_search",
                            "query": "证据 原文 具体措辞",
                            "purpose": "先定位包含证据线索的候选章节或 source_doc_ids",
                            "priority": "high",
                            "expected_depth": "locator",
                            "metadata": {
                                "terms": ["证据"],
                                "match_mode": "all",
                                "scopes": ["chapter_summaries"],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            _triage_keep("req-001"),
            json.dumps(
                {
                    "status": "ready_to_answer",
                    "final_answer": "错误：未读原文也给出具体措辞。",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "id": "readiness-raw-001",
                            "type": "raw_excerpt",
                            "query": "确认候选文档中的证据原文",
                            "purpose": "当前 locator 只定位到章节，尚未覆盖用户要求的具体事实粒度",
                            "priority": "high",
                            "expected_depth": "bounded_raw_excerpt",
                            "source_doc_ids": [1],
                            "read_reason": "需要更直接事实证据确认候选文档中的具体内容",
                            "expected_confirmation": "确认原文是否写到证据被转移",
                            "affects_analysis": "决定最终回答能否给出该具体事实",
                        }
                    ],
                    "notes": ["locator evidence 不足以完整回答"],
                },
                ensure_ascii=False,
            ),
            _triage_keep("readiness-raw-001"),
            json.dumps(
                {
                    "status": "ready_to_answer",
                    "final_answer": "结论：原文片段显示，调查者发现证据被人刻意转移。",
                },
                ensure_ascii=False,
            ),
            json.dumps({"status": "ready_to_answer", "notes": ["原文 evidence 已覆盖回答粒度"]}, ensure_ascii=False),
        ]
    )
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=model)

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="证据原文具体写了什么？")

    assert result.status == "ok"
    assert result.answer == "结论：原文片段显示，调查者发现证据被人刻意转移。"
    assert {bundle.request_type for bundle in result.evidence_bundles} == {"text_search", "raw_excerpt"}
    raw_bundle = next(bundle for bundle in result.evidence_bundles if bundle.request_type == "raw_excerpt")
    assert raw_bundle.source_doc_ids == [1]
    assert any("证据被人刻意转移" in excerpt["text"] for excerpt in raw_bundle.excerpts)
    assert result.trace["readiness_checks"][0]["readiness"]["status"] == "need_more_info"
    assert result.trace["rounds"][1]["source"] == "answer_readiness"
    readiness_prompts = [prompt for prompt in model.prompts if "answer readiness 子步骤" in prompt["system_prompt"]]
    assert "判断依据不是题面关键词" in readiness_prompts[0]["system_prompt"]
    loop_payloads = [
        json.loads(prompt["user_prompt"])
        for prompt in model.prompts
        if "analyzer_seed_packet" in prompt["user_prompt"]
    ]
    assert any("readiness evidence note" in json.dumps(payload["analyzer_notebook"], ensure_ascii=False) for payload in loop_payloads[2:])


def test_analyzer_triage_rejects_evidence_before_future_prompts(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    model = ScriptedAnalyzerModel(
        [
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "type": "character_profile",
                            "name": "调查者",
                            "query": "调查者是否可靠",
                            "purpose": "判断人物弧线是否支撑下一步",
                            "priority": "high",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "kept_request_ids": [],
                    "rejected_request_ids": ["req-001"],
                    "notes": ["人物档案暂时不能改变当前问题判断"],
                },
                ensure_ascii=False,
            ),
            json.dumps({"status": "ready_to_answer", "final_answer": "结论：先保持保守判断。"}, ensure_ascii=False),
        ]
    )
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=model)

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="当前剧情合理吗？")

    assert result.status == "ok"
    assert result.evidence_bundles == []
    assert result.trace["rounds"][0]["triage"]["rejected_request_ids"] == ["req-001"]
    triage_prompts = [prompt for prompt in model.prompts if "candidate_evidence_digest" in prompt["user_prompt"]]
    followup_loop_prompts = [
        prompt
        for prompt in model.prompts
        if "committed_evidence_digests" in prompt["user_prompt"] and "candidate_evidence_digest" not in prompt["user_prompt"]
    ]
    assert "谨慎，重视证据链" in triage_prompts[0]["user_prompt"]
    assert json.loads(followup_loop_prompts[-1]["user_prompt"])["committed_evidence_digests"] == []


def test_raw_excerpt_budget_and_whole_book_block(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    broker = NarrativeInquiryBroker(repo_root=tmp_path)
    budget = AnalyzerBudget(max_raw_excerpt_requests=1, max_raw_excerpt_chars_per_request=18)

    with db.connect() as conn:
        first = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="raw-1",
                request_type="raw_excerpt",
                query="确认证据线索的具体措辞",
                purpose="摘要不足以判断措辞",
                priority="high",
                source_doc_ids=[1],
                read_reason="章节摘要不足以判断证据措辞",
                expected_confirmation="确认线索措辞和在场信息",
                affects_analysis="影响是否建议局部回收",
            ),
            budget=budget,
        )
        blocked = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="raw-all",
                request_type="raw_excerpt",
                query="读取整本原文",
                purpose="不应被允许",
                priority="high",
                read_reason="想看全部",
                expected_confirmation="全部",
                affects_analysis="全部判断",
            ),
            budget=budget,
        )
        bundles, used = broker.resolve_requests(
            conn,
            book_id="book-one",
            requests=[
                NarrativeInquiryRequest(
                    request_id="raw-2",
                    request_type="raw_excerpt",
                    query="再次确认措辞",
                    purpose="超过预算",
                    priority="high",
                    source_doc_ids=[1],
                    read_reason="章节摘要不足以判断证据措辞",
                    expected_confirmation="确认线索措辞",
                    affects_analysis="影响回收判断",
                )
            ],
            budget=budget,
            raw_requests_used=1,
        )

    assert first.status == "found"
    assert first.excerpts
    assert len(first.excerpts[0]["text"]) <= 21
    assert blocked.status == "blocked"
    assert "bounded_raw_excerpt_target" in blocked.missing_facets
    assert bundles[0].status == "budget_limited"
    assert used["raw_requests_used"] == 1


def test_analyzer_completes_raw_excerpt_read_plan_fields(tmp_path: Path) -> None:
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=None)

    [request] = service._filter_requests(
        [
            NarrativeInquiryRequest(
                request_id="raw-1",
                request_type="raw_excerpt",
                query="确认关键交易场景的原文事实",
                purpose="摘要证据互相冲突，需要以原文核验对象和代价",
                priority="high",
                source_doc_ids=[12],
            )
        ],
        budget_state={"total_requests_used": 0},
    )

    assert request.read_reason == "摘要证据互相冲突，需要以原文核验对象和代价"
    assert request.expected_confirmation == "确认关键交易场景的原文事实"
    assert request.affects_analysis == "摘要证据互相冲突，需要以原文核验对象和代价"
    assert request.metadata["read_plan_completed_by"] == "analyzer_service_schema_repair"


def test_raw_excerpt_resolver_normalizes_chapter_refs(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    broker = NarrativeInquiryBroker(repo_root=tmp_path)

    with db.connect() as conn:
        numeric_ref = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="raw-1",
                request_type="raw_excerpt",
                query="确认第一章线索原文",
                purpose="需要原文措辞",
                priority="high",
                chapter_refs=["1"],
                read_reason="摘要不足以确认原句",
                expected_confirmation="确认第一章原文片段",
                affects_analysis="影响事实回答",
            ),
            budget=AnalyzerBudget(max_raw_excerpt_chars_per_request=80),
        )
        query_ref = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="raw-2",
                request_type="raw_excerpt",
                query="在第1章中搜索证据线索原文",
                purpose="需要原文措辞",
                priority="high",
                read_reason="摘要不足以确认原句",
                expected_confirmation="确认第一章原文片段",
                affects_analysis="影响事实回答",
            ),
            budget=AnalyzerBudget(max_raw_excerpt_chars_per_request=80),
        )

    assert numeric_ref.status == "found"
    assert numeric_ref.excerpts
    assert numeric_ref.source_doc_ids == [1]
    assert query_ref.status == "found"
    assert query_ref.excerpts
    assert query_ref.source_doc_ids == [1]


def test_raw_excerpt_resolver_extracts_bounded_doc_ranges(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    broker = NarrativeInquiryBroker(repo_root=tmp_path)

    with db.connect() as conn:
        bounded = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="raw-doc-range",
                request_type="raw_excerpt",
                query="证据原文",
                purpose="在文档 1-1 范围内确认原句",
                priority="high",
                read_reason="在文档 1-1 范围内确认原句",
                expected_confirmation="确认原文",
                affects_analysis="影响事实回答",
            ),
            budget=AnalyzerBudget(max_raw_excerpt_chars_per_request=80),
        )
        broad = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="raw-broad-doc-range",
                request_type="raw_excerpt",
                query="证据原文",
                purpose="在文档 1-10 范围内确认原句",
                priority="high",
                read_reason="在文档 1-10 范围内确认原句",
                expected_confirmation="确认原文",
                affects_analysis="影响事实回答",
            ),
            budget=AnalyzerBudget(max_raw_excerpt_chars_per_request=80),
        )

    assert bounded.status == "found"
    assert bounded.source_doc_ids == [1]
    assert bounded.excerpts
    assert broad.status == "blocked"
    assert "bounded_raw_excerpt_target" in broad.missing_facets


def test_raw_excerpt_resolver_filters_bounded_docs_by_requested_terms(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    doc_ids: list[int] = []
    with db.connect() as conn:
        repo = DocumentsRepo()
        for index in range(1, 8):
            content = f"候选片段 {index} 只提供普通上下文，没有用户要确认的那句。"
            if index == 7:
                content = "关键短语就在这个靠后的片段里，前面的章节窗口不能把它截掉。"
            doc_ids.append(
                repo.insert_document(
                    conn,
                    {
                        "book_id": "book-one",
                        "path": f"doc-late-{index}",
                        "content": content,
                        "document_title": "第二章",
                        "document_title_index": 2,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            )
        conn.commit()

    broker = NarrativeInquiryBroker(repo_root=tmp_path)
    with db.connect() as conn:
        bundle = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="raw-filtered",
                request_type="raw_excerpt",
                query="关键短语",
                purpose="在已定位的章节窗口里确认关键短语原文",
                priority="high",
                source_doc_ids=doc_ids,
                read_reason="摘要只定位到章节，仍需原文确认关键短语",
                expected_confirmation="确认关键短语的原文措辞",
                affects_analysis="决定最终回答能否给出具体原句",
            ),
            budget=AnalyzerBudget(max_raw_excerpt_chars_per_request=240),
        )

    assert bundle.status == "found"
    assert doc_ids[-1] in bundle.source_doc_ids
    assert any("关键短语就在这个靠后的片段里" in excerpt["text"] for excerpt in bundle.excerpts)
    assert any(
        item.get("operation") == "raw_excerpt_doc_selection"
        and item.get("strategy") == "bounded_keyword_filter_preserve_order"
        for item in bundle.trace
    )


def test_chapter_summary_resolver_expands_verbatim_detail_terms(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    with db.connect() as conn:
        DocumentsRepo().insert_document(
            conn,
            {
                "book_id": "book-one",
                "path": "doc-2",
                "content": "角色后来发现一直存在的生日祝福短信。",
                "document_title": "第二章",
                "document_title_index": 2,
                "character_keywords": ["角色"],
                "content_tags": ["生日祝福", "短信"],
                "created_at": now,
                "updated_at": now,
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "document_title_index": 2,
                "chapter_title": "第二章",
                "source_doc_start_id": 2,
                "source_doc_end_id": 2,
                "source_doc_count": 1,
                "source_total_chars": 20,
                "summary_md": "角色发现一直存在的生日祝福短信，但摘要未记录具体歌词。",
                "summary_short": "生日祝福短信浮出水面。",
                "mentioned_characters": ["角色"],
                "outline_update": {},
                "summary_status": "committed",
                "outline_status": "committed",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()
        bundle = NarrativeInquiryBroker(repo_root=tmp_path).resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="summary-1",
                request_type="chapter_summary",
                query="生日快乐歌唱的是什么歌词",
                purpose="定位歌词原文所在章节",
                priority="high",
            ),
            budget=AnalyzerBudget(),
        )

    assert bundle.status == "found"
    assert "chapter-2" in bundle.chapter_refs


def test_character_profile_resolver_prefers_exact_alias_over_profile_mentions(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    with db.connect() as conn:
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "canonical_name": "老徐",
                "aliases": ["强哥"],
                "profile_summary_md": "负责推动关键压力线。",
                "relationships": [],
                "recent_activity": ["与主角发生正面冲突"],
                "story_events": ["在中段制造压力"],
                "evidence_level": "confirmed",
                "created_at": now,
                "updated_at": now,
            },
        )
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "canonical_name": "旁证角色",
                "aliases": [],
                "profile_summary_md": "曾在对话中提到强哥，但不是查询目标。",
                "relationships": [],
                "recent_activity": ["讨论强哥的旧事"],
                "story_events": [],
                "evidence_level": "confirmed",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()

        bundle = NarrativeInquiryBroker(repo_root=tmp_path).resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="char-strong",
                request_type="character_profile",
                name="强哥",
                query="强哥的角色状态",
                purpose="确认人物关系",
                priority="high",
            ),
            budget=AnalyzerBudget(),
        )

    assert bundle.status == "found"
    assert [item["canonical_name"] for item in bundle.evidence_items] == ["老徐"]
    assert len(json.dumps(bundle.to_dict(), ensure_ascii=False)) < 2500


def test_character_profile_resolver_selects_query_relevant_profile_items(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    with db.connect() as conn:
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "canonical_name": "核心角色",
                "aliases": [],
                "profile_summary_md": "核心角色长期卷入主线。",
                "relationships": [
                    {"target_name": "同伴", "status_summary": "早期保持距离"},
                    {"target_name": "盟友", "status_summary": "后来因救援代价形成复杂牵连"},
                ],
                "recent_activity": [
                    "整理旧线索",
                    "为盟友承担救援代价并改变关系状态",
                ],
                "story_events": [
                    {"label": "早期试探", "summary": "核心角色隐瞒计划。", "participants": ["核心角色"]},
                    {"label": "中段调查", "summary": "核心角色确认证据来源。", "participants": ["核心角色", "同伴"]},
                    {"label": "关键救援", "summary": "核心角色为盟友承担救援代价。", "participants": ["核心角色", "盟友"]},
                ],
                "evidence_level": "confirmed",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()

        bundle = NarrativeInquiryBroker(repo_root=tmp_path).resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="char-relevant",
                request_type="character_profile",
                name="核心角色",
                query="核心角色与盟友的救援代价和关系变化",
                purpose="确认关系走向是否有事实依据",
                priority="high",
            ),
            budget=AnalyzerBudget(),
        )

    assert bundle.status == "found"
    profile = bundle.evidence_items[0]
    assert "关键救援" in profile["story_events"][0]
    assert "救援代价" in profile["relationships"][0]
    assert "救援代价" in profile["recent_activity"][0]


def test_character_profile_resolver_pages_story_events_by_offset(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    with db.connect() as conn:
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "canonical_name": "核心角色",
                "aliases": [],
                "profile_summary_md": "核心角色长期卷入主线。",
                "relationships": [],
                "recent_activity": [],
                "story_events": [
                    {"label": "早期试探", "summary": "核心角色隐瞒计划。", "participants": ["核心角色"]},
                    {"label": "中段调查", "summary": "核心角色确认证据来源。", "participants": ["核心角色"]},
                    {"label": "关键救援", "summary": "核心角色为同伴承担救援代价并改变关系。", "participants": ["核心角色", "同伴"]},
                    {"label": "后续回响", "summary": "同伴开始重新理解两人的关系。", "participants": ["核心角色", "同伴"]},
                ],
                "evidence_level": "confirmed",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()

        bundle = NarrativeInquiryBroker(repo_root=tmp_path).resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="char-page",
                request_type="character_profile",
                name="核心角色",
                query="核心角色",
                purpose="分页读取人物经历",
                priority="high",
                metadata={"story_events_offset": 2, "story_events_char_budget": 99999},
            ),
            budget=AnalyzerBudget(),
        )

    assert bundle.status == "found"
    profile = bundle.evidence_items[0]
    assert profile["story_events"][0].startswith("关键救援")
    assert profile["story_events_page"]["mode"] == "offset_page"
    assert profile["story_events_page"]["offset"] == 2
    assert profile["story_events_page"]["total"] == 4
    assert profile["story_events_page"]["char_budget"] == 4096


def test_character_profile_pagination_metadata_is_not_deduped(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    with db.connect() as conn:
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "canonical_name": "核心角色",
                "aliases": [],
                "profile_summary_md": "核心角色长期卷入主线。",
                "relationships": [],
                "recent_activity": [],
                "story_events": [
                    {"label": "第一页事件", "summary": "这是第一段 experience。"},
                    {"label": "第二页事件", "summary": "这是第二段 experience。"},
                ],
                "evidence_level": "confirmed",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()

        bundles, used = NarrativeInquiryBroker(repo_root=tmp_path).resolve_requests(
            conn,
            book_id="book-one",
            requests=[
                NarrativeInquiryRequest(
                    request_id="char-page-0",
                    request_type="character_profile",
                    name="核心角色",
                    query="核心角色",
                    purpose="读取第一页",
                    priority="high",
                    metadata={"story_events_offset": 0},
                ),
                NarrativeInquiryRequest(
                    request_id="char-page-1",
                    request_type="character_profile",
                    name="核心角色",
                    query="核心角色",
                    purpose="读取第二页",
                    priority="high",
                    metadata={"story_events_offset": 1},
                ),
            ],
            budget=AnalyzerBudget(),
        )

    assert len(bundles) == 2
    assert used["total_requests_used"] == 2
    assert bundles[0].evidence_items[0]["story_events"][0].startswith("第一页事件")
    assert bundles[1].evidence_items[0]["story_events"][0].startswith("第二页事件")


def test_chapter_summary_resolver_maps_outline_segment_hits_to_chapter_summary(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    spy_memory = SpyMemoryQueryService(repo_root=tmp_path)
    broker = NarrativeInquiryBroker(repo_root=tmp_path, memory_query_service=spy_memory)

    with db.connect() as conn:
        bundle = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="chapter-from-segment",
                request_type="chapter_summary",
                query="证据来源未明时调查者如何选择",
                purpose="从大纲节点定位章节摘要",
                priority="high",
            ),
            budget=AnalyzerBudget(),
        )

    assert bundle.status == "found"
    assert bundle.chapter_refs == ["chapter-1"]
    assert any("调查者发现证据线索" in item["summary"] for item in bundle.evidence_items)
    assert "resolve_chapter_refs" in spy_memory.calls


def test_chapter_summary_resolver_scans_chapter_summaries_when_outline_omits_keyword(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    with db.connect() as conn:
        DocumentsRepo().insert_document(
            conn,
            {
                "book_id": "book-one",
                "path": "doc-2",
                "content": "核心角色为盟友承担救援代价。",
                "document_title": "第二章",
                "document_title_index": 2,
                "created_at": now,
                "updated_at": now,
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "document_title_index": 2,
                "chapter_title": "第二章",
                "source_doc_start_id": 2,
                "source_doc_end_id": 2,
                "source_doc_count": 1,
                "source_total_chars": 16,
                "summary_md": "核心角色为盟友承担救援代价，关系因此发生重大变化。",
                "summary_short": "关系发生变化。",
                "mentioned_characters": ["核心角色", "盟友"],
                "outline_update": {
                    "chapter_line": "[2] 第二章: 关系出现变化。",
                    "outline_segment_id": "outline-segment:chapter-2:docs-2",
                    "outline_segment": "核心角色和盟友的关系出现变化，但具体原因暂未写入大纲段。",
                    "source_doc_ids": [2],
                    "source_doc_range": "2",
                    "source_title_indexes": [2],
                    "status": "committed",
                },
                "summary_status": "committed",
                "outline_status": "committed",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()

        bundle = NarrativeInquiryBroker(repo_root=tmp_path).resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="chapter-direct",
                request_type="chapter_summary",
                query="救援代价",
                purpose="outline segment 没写出关键词时仍应定位章节摘要",
                priority="high",
            ),
            budget=AnalyzerBudget(),
        )

    assert bundle.status == "found"
    assert bundle.chapter_refs[0] == "chapter-2"
    assert "救援代价" in bundle.evidence_items[0]["summary"]


def test_text_search_locator_intersects_terms_across_story_artifacts(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    outline_segments_path = tmp_path / ".memory" / "outlines" / "book-one.outline_segments.json"
    outline_segments_path.parent.mkdir(parents=True, exist_ok=True)
    outline_segments_path.write_text(
        json.dumps(
            {
                "book_id": "book-one",
                "segments": [
                    {
                        "outline_segment_id": "outline-segment:chapter-2:docs-2",
                        "summary": "同伴在生日当天发来祝福短信，调查者后来发现这条消息。",
                        "chapter_line": "[2] 第二章: 生日祝福短信被发现。",
                        "source_title_indexes": [2],
                        "source_doc_ids": [2],
                        "source_doc_range": "2",
                        "status": "committed",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    scene_cards_path = tmp_path / ".memory" / "index_cards" / "book-one.scene_cards.json"
    scene_cards_path.parent.mkdir(parents=True, exist_ok=True)
    scene_cards_path.write_text(
        json.dumps(
            {
                "book_id": "book-one",
                "scene_cards": [
                    {
                        "card_id": "scene-2",
                        "card_type": "narrative_scene",
                        "summary": "调查者读到同伴留下的生日祝福短信。",
                        "source_doc_ids": [2],
                        "source_title_indexes": [2],
                        "source_doc_range": "2",
                        "query_facets": ["调查者", "同伴", "生日", "短信"],
                        "status": "committed",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with db.connect() as conn:
        DocumentsRepo().insert_document(
            conn,
            {
                "book_id": "book-one",
                "path": "doc-2",
                "content": "调查者在旧手机里发现同伴的生日祝福短信。",
                "document_title": "第二章",
                "document_title_index": 2,
                "character_keywords": ["调查者", "同伴"],
                "content_tags": ["生日", "短信"],
                "created_at": now,
                "updated_at": now,
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "document_title_index": 2,
                "chapter_title": "第二章",
                "source_doc_start_id": 2,
                "source_doc_end_id": 2,
                "source_doc_count": 1,
                "source_total_chars": 20,
                "summary_md": "调查者发现同伴留下的生日祝福短信。",
                "summary_short": "生日祝福短信被发现。",
                "mentioned_characters": ["调查者", "同伴"],
                "summary_status": "committed",
                "outline_status": "committed",
                "created_at": now,
                "updated_at": now,
            },
        )
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-one",
                "canonical_name": "同伴",
                "aliases": [],
                "profile_summary_md": "同伴曾向调查者发送生日祝福短信。",
                "story_events": [{"summary": "生日祝福短信影响二人关系。", "source_doc_ids": [2]}],
                "mentioned_doc_ids": [2],
                "chapter_indexes": [2],
                "evidence_level": "confirmed",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()

        bundle = NarrativeInquiryBroker(repo_root=tmp_path).resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="text-search-1",
                request_type="text_search",
                query="定位生日短信",
                purpose="先找候选章节",
                priority="high",
                metadata={
                    "terms": ["生日", "短信"],
                    "match_mode": "all",
                    "scopes": ["outline_segments", "chapter_summaries", "character_profiles", "index_cards"],
                },
            ),
            budget=AnalyzerBudget(max_evidence_chars_per_request=900),
        )

    assert bundle.status == "found"
    assert "chapter-2" in bundle.chapter_refs
    assert 2 in bundle.source_doc_ids
    scopes = {item["scope"] for item in bundle.evidence_items}
    assert {"outline_segment", "chapter_summary", "character_profile", "index_card"}.issubset(scopes)
    assert all(item["matched_terms"] == ["生日", "短信"] for item in bundle.evidence_items)


def test_text_search_documents_require_bounded_scope(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    broker = NarrativeInquiryBroker(repo_root=tmp_path)

    with db.connect() as conn:
        unbounded = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="text-search-docs-unbounded",
                request_type="text_search",
                query="证据 来源",
                purpose="不应默认扫全书原文",
                priority="high",
                metadata={"terms": ["证据", "来源"], "match_mode": "all", "scopes": ["documents"]},
            ),
            budget=AnalyzerBudget(),
        )
        bounded = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="text-search-docs-bounded",
                request_type="text_search",
                query="证据 来源",
                purpose="限定文档后可以词面定位原文候选",
                priority="high",
                source_doc_ids=[1],
                metadata={"terms": ["证据", "来源"], "match_mode": "all", "scopes": ["documents"]},
            ),
            budget=AnalyzerBudget(),
        )
        allowed_scan = broker.resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="text-search-docs-allowed-scan",
                request_type="text_search",
                query="证据 来源",
                purpose="模型已提出关键词，允许做一次 document-scope grep",
                priority="high",
                metadata={
                    "terms": ["证据", "来源"],
                    "match_mode": "all",
                    "scopes": ["documents"],
                    "allow_document_scan": True,
                },
            ),
            budget=AnalyzerBudget(),
        )

    assert unbounded.status == "missing"
    assert "documents_require_source_doc_ids_or_allow_document_scan" in json.dumps(unbounded.trace, ensure_ascii=False)
    assert bounded.status == "found"
    assert bounded.source_doc_ids == [1]
    assert bounded.evidence_items[0]["scope"] == "document"
    assert allowed_scan.status == "found"
    assert allowed_scan.source_doc_ids == [1]
    assert allowed_scan.evidence_items[0]["scope"] == "document"


def test_text_search_documents_support_match_offset_pagination(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    with db.connect() as conn:
        for index in range(2, 7):
            DocumentsRepo().insert_document(
                conn,
                {
                    "book_id": "book-one",
                    "path": f"doc-{index}",
                    "content": f"分页定位短语出现在第 {index} 个候选文档。",
                    "document_title": "分页章",
                    "document_title_index": index,
                    "character_keywords": [],
                    "content_tags": ["分页定位短语"],
                    "created_at": now,
                    "updated_at": now,
                },
            )
        conn.commit()

        bundle = NarrativeInquiryBroker(repo_root=tmp_path).resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="text-search-docs-page",
                request_type="text_search",
                query="分页定位短语",
                purpose="读取下一页 document grep 命中",
                priority="high",
                metadata={
                    "terms": ["分页定位短语"],
                    "match_mode": "all",
                    "scopes": ["documents"],
                    "allow_document_scan": True,
                    "max_matches_per_scope": 2,
                    "match_offset": 3,
                },
            ),
            budget=AnalyzerBudget(),
        )

    assert bundle.status == "found"
    assert bundle.source_doc_ids == [5, 6]
    assert bundle.evidence_items[0]["document_match_index"] == 3
    assert bundle.trace[-1]["document_match_offset"] == 3


def test_text_search_document_digest_keeps_bounded_candidate_page(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    now = "2026-05-21T00:00:00Z"
    with db.connect() as conn:
        for index in range(2, 12):
            DocumentsRepo().insert_document(
                conn,
                {
                    "book_id": "book-one",
                    "path": f"doc-{index}",
                    "content": f"候选片段关键词出现在第 {index} 个文档。",
                    "document_title": "候选章",
                    "document_title_index": index,
                    "character_keywords": [],
                    "content_tags": ["候选片段关键词"],
                    "created_at": now,
                    "updated_at": now,
                },
            )
        conn.commit()

        bundle = NarrativeInquiryBroker(repo_root=tmp_path).resolve_one(
            conn,
            book_id="book-one",
            request=NarrativeInquiryRequest(
                request_id="text-search-docs-default-page",
                request_type="text_search",
                query="候选片段关键词",
                purpose="保留一页候选片段",
                priority="high",
                metadata={
                    "terms": ["候选片段关键词"],
                    "match_mode": "all",
                    "scopes": ["documents"],
                    "allow_document_scan": True,
                },
            ),
            budget=AnalyzerBudget(),
        )

    digest = _compact_evidence_bundle(bundle)

    assert len(bundle.evidence_items) == 10
    assert len(digest["evidence_items"]) == 10
    assert digest["evidence_items"][0]["matched_terms"] == ["候选片段关键词"]
    assert digest["evidence_items"][0]["document_match_index"] == 0


def test_raw_excerpt_digest_keeps_excerpt_text() -> None:
    bundle = EvidenceBundle(
        request_id="raw-1",
        request_type="raw_excerpt",
        query="读取原文",
        status="found",
        fact_status="candidate",
        excerpts=[{"doc_id": 7, "text": "这是一段需要进入模型上下文的原文。"}],
    )

    digest = _compact_evidence_bundle(bundle)

    assert digest["excerpts"][0]["doc_id"] == 7
    assert "需要进入模型上下文" in digest["excerpts"][0]["text"]


def test_outline_analyzer_without_model_returns_needs_model(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=None)

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="当前剧情合理吗？")

    assert result.status == "needs_model"
    assert "需要可用模型" in result.answer
    assert result.seed is not None


def test_outline_analyzer_model_json_failure_returns_failed(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    model = ScriptedAnalyzerModel(["不是 JSON", "仍然不是 JSON"], auto_intent=False)
    service = OutlineAnalyzerService(
        repo_root=tmp_path,
        model_client=model,
        budget=AnalyzerBudget(max_json_retries=1),
    )

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="当前剧情合理吗？")

    assert result.status == "failed"
    assert "JSON" in result.answer
    assert len(model.prompts) == 2


def test_outline_analyzer_logs_prompt_lengths_for_each_model_call(tmp_path: Path, caplog: Any) -> None:
    db = _seed_memory(tmp_path)
    model = ScriptedAnalyzerModel(
        [
            json.dumps({"status": "ready_to_answer"}, ensure_ascii=False),
            json.dumps({"status": "ready_to_answer", "notes": ["当前证据足以保守回答"]}, ensure_ascii=False),
            "结论：当前只能做保守分析。",
        ]
    )
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=model)

    caplog.set_level(logging.INFO, logger="novel_agent.app.services.outline_analyzer_service")
    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="当前剧情合理吗？")

    assert result.status == "ok"
    messages = [
        record.getMessage()
        for record in caplog.records
        if "outline_analyzer.model_prompt_stats" in record.getMessage()
    ]
    assert len(messages) == 4
    assert "stage=intent_gate" in messages[0]
    assert "round=-" in messages[0]
    assert "attempt=1" in messages[0]
    assert "system_chars=" in messages[0]
    assert "user_chars=" in messages[0]
    assert "total_bytes=" in messages[0]
    assert "stage=loop" in messages[1]
    assert "round=1" in messages[1]
    assert "stage=readiness" in messages[2]
    assert "round=1" in messages[2]
    assert "stage=final" in messages[3]
    assert "round=-" in messages[3]
    assert "当前剧情合理吗" not in "\n".join(messages)


def test_outline_analyzer_records_prompt_snapshots(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    snapshots: list[dict[str, Any]] = []
    model = ScriptedAnalyzerModel(
        [
            json.dumps({"status": "ready_to_answer"}, ensure_ascii=False),
            json.dumps({"status": "ready_to_answer", "notes": ["当前证据足以保守回答"]}, ensure_ascii=False),
            "结论：当前只能做保守分析。",
        ]
    )
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=model, prompt_trace_recorder=snapshots.append)

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="当前剧情合理吗？")

    assert result.status == "ok"
    assert [item["stage"] for item in snapshots] == ["intent_gate", "loop", "readiness", "final"]
    assert all(item["system_prompt"] for item in snapshots)
    assert all(item["user_prompt"] for item in snapshots)
    assert snapshots[0]["timeout_seconds"] == 60
    assert snapshots[1]["model_kwargs"]["thinking"] == "disabled"
    assert snapshots[2]["model_kwargs"]["thinking"] == "disabled"


def test_analyzer_factual_queries_route_through_broker_and_memory_query(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    spy_memory = SpyMemoryQueryService(repo_root=tmp_path)
    broker = NarrativeInquiryBroker(repo_root=tmp_path, memory_query_service=spy_memory)
    model = ScriptedAnalyzerModel(
        [
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "type": "story_detail",
                            "query": "证据来源的事实依据",
                            "purpose": "确认事实",
                            "priority": "high",
                        },
                        {
                            "type": "raw_excerpt",
                            "query": "确认证据线索原文措辞",
                            "purpose": "摘要不足以判断措辞",
                            "priority": "high",
                            "source_doc_ids": [1],
                            "read_reason": "摘要不足以判断措辞",
                            "expected_confirmation": "确认线索措辞",
                            "affects_analysis": "影响是否建议局部回收",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            _triage_keep("req-001", "req-002"),
            json.dumps({"status": "ready_to_answer", "final_answer": "结论：事实查询已完成。"}, ensure_ascii=False),
        ]
    )
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=model, inquiry_broker=broker)

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="证据来源是否足够支撑回收？")

    assert result.status == "ok"
    assert "root_scan" in spy_memory.calls
    assert "resolve_document_refs" in spy_memory.calls
    assert all("sqlite:documents" not in source.path for source in result.sources)
    assert {bundle.request_type for bundle in result.evidence_bundles} == {"story_detail", "raw_excerpt"}
    triage_prompts = [item["user_prompt"] for item in model.prompts if "candidate_evidence_digests" in item["user_prompt"]]
    assert len(triage_prompts) == 1
    triage_payload = json.loads(triage_prompts[0])
    assert [item["request_type"] for item in triage_payload["candidate_evidence_digests"]] == ["story_detail", "raw_excerpt"]


def test_analyzer_batch_triage_falls_back_to_single_on_parse_failure(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    broker = NarrativeInquiryBroker(repo_root=tmp_path)
    model = ScriptedAnalyzerModel(
        [
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "type": "story_detail",
                            "query": "证据来源的事实依据",
                            "purpose": "确认事实",
                            "priority": "high",
                        },
                        {
                            "type": "raw_excerpt",
                            "query": "确认证据线索原文措辞",
                            "purpose": "摘要不足以判断措辞",
                            "priority": "high",
                            "source_doc_ids": [1],
                            "read_reason": "摘要不足以判断措辞",
                            "expected_confirmation": "确认线索措辞",
                            "affects_analysis": "影响最终回答",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            "not json",
            _triage_keep("req-001"),
            _triage_keep("req-002"),
            json.dumps({"status": "ready_to_answer", "final_answer": "结论：fallback 后可以回答。"}, ensure_ascii=False),
        ]
    )
    service = OutlineAnalyzerService(
        repo_root=tmp_path,
        model_client=model,
        inquiry_broker=broker,
        budget=AnalyzerBudget(max_json_retries=0),
    )

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="证据来源是否足够支撑回收？")

    assert result.status == "ok"
    triage_prompts = [item["user_prompt"] for item in model.prompts if "candidate_evidence_digest" in item["user_prompt"]]
    batch_prompts = [prompt for prompt in triage_prompts if "candidate_evidence_digests" in prompt]
    single_prompts = [prompt for prompt in triage_prompts if "candidate_evidence_digest\":" in prompt]
    assert len(batch_prompts) == 1
    assert len(single_prompts) == 2
    assert {bundle.request_type for bundle in result.evidence_bundles} == {"story_detail", "raw_excerpt"}


def test_analyzer_triage_notes_stay_in_trace_not_next_loop(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)

    class ConflictBroker:
        def resolve_requests(self, *_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
            return [
                EvidenceBundle(
                    request_id="req-001",
                    request_type="factual_event_card_search",
                    query="核验一次关键交易的对象和次数",
                    status="found",
                    fact_status="candidate",
                    evidence_items=[
                        {
                            "summary": "摘要称发生第四次交易，但其他证据暗示次数不同。",
                            "importance_facets": ["摘要派生的重要性判断"],
                            "evidence_derivation": "summary_derived_index_card",
                            "canonical_fact_status": "candidate_requires_direct_confirmation_for_conflicts",
                        }
                    ],
                )
            ], {"total_requests_used": 1, "raw_requests_used": 0}

    model = ScriptedAnalyzerModel(
        [
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "type": "factual_event_card_search",
                            "query": "核验一次关键交易的对象和次数",
                            "purpose": "定位候选事实",
                            "priority": "high",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "kept_request_ids": ["req-001"],
                    "rejected_request_ids": [],
                    "notes": ["候选摘要与既有事实在次数/对象上冲突，需要 raw_excerpt 核验。"],
                },
                ensure_ascii=False,
            ),
            json.dumps({"status": "ready_to_answer", "final_answer": "结论：需要以原文核验为准。"}, ensure_ascii=False),
        ]
    )
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=model, inquiry_broker=ConflictBroker())

    with db.connect() as conn:
        result = service.chat(conn, book_id="book-one", question="这次关键交易到底为了谁？")

    assert result.status == "ok"
    loop_prompts = [
        item["user_prompt"]
        for item in model.prompts
        if '"committed_evidence_digests"' in item["user_prompt"]
    ]
    assert len(loop_prompts) >= 2
    assert "triage evidence note" not in loop_prompts[1]
    assert "需要 raw_excerpt 核验" not in loop_prompts[1]
    assert "需要 raw_excerpt 核验" in result.trace["rounds"][0]["triage"]["notes"][0]


def test_outline_analyzer_smoke_uses_existing_memory_without_writer_side_effects(tmp_path: Path) -> None:
    db = _seed_memory(tmp_path)
    model = ScriptedAnalyzerModel(
        [
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "type": "open_threads",
                            "query": "当前未解之谜哪条最适合下一阶段回收",
                            "purpose": "定位可讨论的未解线索",
                            "priority": "high",
                        },
                        {
                            "type": "story_detail",
                            "query": "证据来源尚未揭开的历史经过和当前状态",
                            "purpose": "判断回收时机",
                            "priority": "high",
                            "expected_depth": "chapter_summary",
                        },
                    ],
                    "notebook_delta": {"uncertain_gaps": ["需要确认是否允许提前暴露幕后身份"]},
                },
                ensure_ascii=False,
            ),
            _triage_keep("req-001"),
            _triage_keep("req-002"),
            json.dumps(
                {
                    "status": "ready_to_answer",
                    "final_answer": (
                        "结论：最适合先回收“证据来源”这条未解线索，但只做局部答案。"
                        "事实依据：【故事大纲】列出证据来源尚未揭开，【章节摘要】显示证据线索已经出现。"
                        "风险：如果直接揭开幕后身份，会过早消耗悬念；需要用户确认是否接受延迟最终真相。"
                    ),
                },
                ensure_ascii=False,
            ),
        ]
    )
    service = OutlineAnalyzerService(repo_root=tmp_path, model_client=model)
    outline_path = tmp_path / ".memory" / "outlines" / "book-one.outline.md"
    world_path = tmp_path / ".memory" / "world" / "book-one.summary.md"
    before_files = {
        "outline": outline_path.read_text(encoding="utf-8"),
        "world": world_path.read_text(encoding="utf-8"),
    }

    with db.connect() as conn:
        before_counts = _table_counts(conn, "documents", "chapters", "character_profiles")
        result = service.chat(conn, book_id="book-one", question="当前未解之谜哪条最适合下一阶段回收？")
        after_counts = _table_counts(conn, "documents", "chapters", "character_profiles")

    assert result.status == "ok"
    assert "局部答案" in result.answer
    assert "证据线索出现，来源未明" not in result.answer
    assert "事实依据" in result.answer
    assert "风险" in result.answer
    assert "需要用户确认" in result.answer
    assert before_counts == after_counts
    assert outline_path.read_text(encoding="utf-8") == before_files["outline"]
    assert world_path.read_text(encoding="utf-8") == before_files["world"]
    assert not (tmp_path / "runs" / "writer").exists()


def _table_counts(conn: Any, *table_names: str) -> dict[str, int]:
    return {
        table_name: int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
        for table_name in table_names
    }
