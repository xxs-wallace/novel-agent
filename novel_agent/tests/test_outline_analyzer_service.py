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
from novel_agent.app.services.outline_analyzer_service import OutlineAnalyzerService, _compact_mapping


class ScriptedAnalyzerModel:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[dict[str, str]] = []

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
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
    assert "谨慎，重视证据链" in model.prompts[1]["user_prompt"]
    assert json.loads(model.prompts[2]["user_prompt"])["committed_evidence_digests"] == []


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
    model = ScriptedAnalyzerModel(["不是 JSON", "仍然不是 JSON"])
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
    assert len(messages) == 2
    assert "stage=loop" in messages[0]
    assert "round=1" in messages[0]
    assert "attempt=1" in messages[0]
    assert "system_chars=" in messages[0]
    assert "user_chars=" in messages[0]
    assert "total_bytes=" in messages[0]
    assert "stage=final" in messages[1]
    assert "round=-" in messages[1]
    assert "当前剧情合理吗" not in "\n".join(messages)


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
            _triage_keep("req-001"),
            _triage_keep("req-002"),
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
    triage_prompts = [item["user_prompt"] for item in model.prompts if "candidate_evidence_digest" in item["user_prompt"]]
    assert len(triage_prompts) == 2
    assert all("candidate_evidence_digests" not in prompt for prompt in triage_prompts)
    assert "story_detail" in triage_prompts[0]
    assert "raw_excerpt" in triage_prompts[1]


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
