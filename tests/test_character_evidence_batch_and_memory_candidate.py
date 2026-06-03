from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from novel_agent.app.llm import JsonModelClient
from novel_agent.app.prompts.character_evidence_prompt import build_character_evidence_prompt
from novel_agent.app.repos.character_evidence_log_repo import CharacterEvidenceLogRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentRow
from novel_agent.app.runner.close_read_runner import CloseReadRunner
from novel_agent.app.schemas.config_schema import CloseReadAgentConfig
from novel_agent.app.schemas.orchestration_schema import MemoryAssemblyBudget, MemoryAssemblyInput
from novel_agent.app.services.character_evidence_batch_assembler_service import CharacterEvidenceBatchAssemblerService
from novel_agent.app.services.character_profile_service import CharacterProfileService
from novel_agent.app.services.context_assembly_service import ContextAssemblyService
from novel_agent.app.services.memory_candidate_service import MemoryCandidateService


def _doc(*, doc_id: int, title_index: int, title: str, content: str) -> DocumentRow:
    return DocumentRow(
        doc_id=doc_id,
        book_id="book-1",
        path=f"{doc_id}.md",
        scope="novel",
        title=title,
        document_title=title,
        document_title_index=title_index,
        inferred_chapter_no=title_index,
        content=content,
        content_chars=len(content),
        character_keywords=[],
        content_tags=[],
        source_path=f"{doc_id}.md",
        source_file_name=f"{doc_id}.md",
        source_start_offset=0,
        source_end_offset=len(content),
    )


def _insert_document(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    title_index: int,
    title: str,
    content: str,
) -> None:
    from novel_agent.app.repos.documents_repo import DocumentsRepo

    DocumentsRepo().insert_document(
        conn,
        {
            "path": f"{title_index:03d}.md",
            "scope": "novel",
            "title": title,
            "content": content,
            "mtime": 0,
            "size": len(content.encode("utf-8")),
            "content_sha256": f"sha-{title_index}-{len(content)}",
            "book_id": book_id,
            "source_path": f"{title_index:03d}.md",
            "source_file_name": f"{title_index:03d}.md",
            "source_start_offset": 0,
            "source_end_offset": len(content),
            "source_batch_no": 1,
            "document_title": title,
            "document_title_index": title_index,
            "inferred_chapter_no": title_index,
            "content_chars": len(content),
            "character_keywords": [],
            "content_tags": [],
            "segmentation_notes": "",
            "ingestion_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _chapter_summary_md(plot: str) -> str:
    return (
        "## 剧情事件链\n"
        f"- {plot}\n\n"
        "## 人物状态/关系变化\n"
        "- 路明非明确回应并进入学院，人物行动与关系变化被保留。\n\n"
        "## 关键信息/设定\n"
        "- 学院入口和同行关系成为后续记忆更新依据。\n\n"
        "## 结构功能/节奏\n"
        "- 本章承担入场推进与关系铺垫功能。\n"
    )


def test_character_evidence_batch_joins_consecutive_documents_without_chapter_binding() -> None:
    documents = [
        _doc(doc_id=1, title_index=1, title="第一章", content="路明非走进校园。"),
        _doc(doc_id=2, title_index=1, title="第一章", content="诺诺问他要不要加入。"),
        _doc(doc_id=3, title_index=2, title="第二章", content="楚子航沉默地点头。"),
    ]

    batch = CharacterEvidenceBatchAssemblerService(document_chars_budget=200).build_batch(
        book_id="book-1",
        documents=documents,
        existing_context_summary="已有世界观概要",
        local_character_hints={1: ["路明非"], 2: ["诺诺"], 3: ["楚子航"]},
        existing_character_roster=[
            {"canonical_name": "路明非", "aliases": ["明非"], "last_seen_doc_id": 1},
        ],
    )

    assert batch.character_evidence_batch_id == "book-1:character-evidence:1-3"
    assert batch.doc_ids == [1, 2, 3]
    assert batch.document_title_indexes == [1, 2]
    assert "[DOC doc_id=1 title_index=1 title=第一章]" in batch.batch_text
    assert "[DOC doc_id=3 title_index=2 title=第二章]" in batch.batch_text
    assert "local_character_hints" not in batch.documents[1]
    assert batch.existing_character_roster == [
        {"canonical_name": "路明非", "aliases": ["明非"], "last_seen_doc_id": 1},
    ]


def test_character_evidence_prompt_is_batch_level_and_excludes_offsets() -> None:
    batch = CharacterEvidenceBatchAssemblerService(document_chars_budget=200).build_batch(
        book_id="book-1",
        documents=[_doc(doc_id=1, title_index=1, title="第一章", content="路明非说他会去。")],
    )

    system_prompt, user_prompt = build_character_evidence_prompt({"character_evidence_batch": batch.to_dict()})

    assert "character_evidence_batch_id" in user_prompt
    assert "personhood_evidence" in user_prompt
    assert "activity_or_state_evidence" in user_prompt
    assert "relationship_evidence" in user_prompt
    assert "local_character_hints" not in user_prompt
    assert "existing_character_roster" in user_prompt
    assert "document_character_mentions" in system_prompt
    assert "不要逐 doc_id 返回人物列表" in system_prompt
    assert "mention_offsets" in system_prompt


def test_character_evidence_prompt_requests_character_id_mapping() -> None:
    batch = CharacterEvidenceBatchAssemblerService(document_chars_budget=200).build_batch(
        book_id="book-1",
        documents=[_doc(doc_id=1, title_index=1, title="第一章", content="明非说他会去。")],
        existing_character_roster=[
            {"character_id": "42", "canonical_name": "路明非", "aliases": ["明非"]},
        ],
    )

    system_prompt, user_prompt = build_character_evidence_prompt({"character_evidence_batch": batch.to_dict()})

    assert "character_id 必须使用 roster 中的 character_id" in system_prompt
    assert '"character_id": "42"' in user_prompt
    assert '"character_id": "123"' in user_prompt
    assert "resolution_status" in user_prompt


def test_memory_candidate_filters_low_confidence_and_keeps_character_facts() -> None:
    service = MemoryCandidateService()
    evidence_payload = {
        "character_evidence_batch_id": "book-1:character-evidence:1-2",
        "characters": [
            {
                "canonical_name": "路明非",
                "aliases": ["路明非同学"],
                "is_speaking_character": True,
                "speaking_evidence": "有明确说话归因。",
                "personhood_evidence": "被称呼并发言。",
                "activity_or_state_evidence": "路明非决定进入学院。",
                "relationship_evidence": "与诺诺直接对话。",
                "candidate_type": "character",
                "confidence": 0.88,
                "uncertainty_reason": "",
            },
            {
                "canonical_name": "张开",
                "aliases": [],
                "is_speaking_character": False,
                "speaking_evidence": "",
                "personhood_evidence": "",
                "activity_or_state_evidence": "",
                "relationship_evidence": "",
                "candidate_type": "non_person",
                "confidence": 0.2,
                "uncertainty_reason": "像动作短语。",
            },
        ],
    }

    output = service.build_fallback_output(
        chapter_title="第一章",
        document_title_index=1,
        summary_payload={"chapter_summary_short": "路明非进入学院。"},
        evidence_payload=evidence_payload,
    )

    assert [item["canonical_name"] for item in output["character_updates"]] == ["路明非"]
    assert output["character_updates"][0]["recent_activity"] == "路明非决定进入学院。"
    assert output["character_updates"][0]["is_speaking_character"] is True


def test_character_reduce_inputs_prefer_character_id_and_existing_profile_by_id() -> None:
    service = MemoryCandidateService()
    reduce_inputs = service.build_character_reduce_inputs(
        prompt_input={
            "book_id": "book-1",
            "character_profiles": [
                {"character_id": "7", "canonical_name": "旧名", "aliases": ["阿衡"], "profile_summary_md": "旧档案"}
            ],
        },
        summary_payload={
            "chapter_summary_md": "这段完整章节摘要不应进入 character reduce 输入。",
            "chapter_summary_short": "短摘要唯一文本不应在已有 outline segment 时进入上下文。",
        },
        current_outline_segment={
            "outline_segment_id": "outline-segment:chapter-4:docs-7-8",
            "outline_segment": "阿衡在当前剧情段重新出现并留下线索。",
            "source_doc_range": "7-8",
            "source_doc_ids": [7, 8],
            "compression_notes": "这段内部说明不需要进入人物归并。",
        },
        evidence_payload={
            "characters": [
                {
                    "character_id": "7",
                    "canonical_name": "周衡",
                    "aliases": ["阿衡"],
                    "personhood_evidence": "阿衡被称呼并行动。",
                    "activity_or_state_evidence": "阿衡重新进入场景。",
                    "candidate_type": "character",
                    "confidence": 0.9,
                },
                {
                    "character_id": "7",
                    "canonical_name": "阿衡",
                    "personhood_evidence": "阿衡继续行动。",
                    "activity_or_state_evidence": "阿衡留下线索。",
                    "candidate_type": "character",
                    "confidence": 0.88,
                },
            ]
        },
    )

    assert len(reduce_inputs) == 1
    assert reduce_inputs[0]["character_id"] == "7"
    assert reduce_inputs[0]["existing_profile"]["canonical_name"] == "旧名"
    assert reduce_inputs[0]["existing_profile"]["profile_brief_status"] == "missing"
    assert [item["canonical_name"] for item in reduce_inputs[0]["ordered_character_evidence"]] == ["周衡", "阿衡"]


def test_character_reduce_inputs_use_profile_brief_when_available() -> None:
    service = MemoryCandidateService()
    reduce_inputs = service.build_character_reduce_inputs(
        prompt_input={
            "book_id": "book-1",
            "character_profiles": [
                {
                    "character_id": "7",
                    "canonical_name": "旧名",
                    "aliases": ["阿衡"],
                    "profile_summary_md": "这段旧 Markdown 不应进入 reduce。",
                    "profile_brief": {
                        "identity": {"character_id": "7", "canonical_name": "旧名", "aliases": ["阿衡"]},
                        "current_state": "持久化人物简档。",
                        "source_refs": [{"outline_segment_id": "outline-segment:chapter-1:docs-1", "source_doc_ids": [1]}],
                        "compacted_until": {"doc_id": 1, "outline_segment_id": "outline-segment:chapter-1:docs-1"},
                    },
                    "profile_brief_status": "ready",
                }
            ],
        },
        summary_payload={
            "chapter_summary_md": "这段完整章节摘要不应进入 character reduce 输入。",
            "chapter_summary_short": "短摘要唯一文本不应在已有 outline segment 时进入上下文。",
        },
        current_outline_segment={
            "outline_segment_id": "outline-segment:chapter-4:docs-7-8",
            "outline_segment": "阿衡在当前剧情段重新出现并留下线索。",
            "source_doc_range": "7-8",
            "source_doc_ids": [7, 8],
            "compression_notes": "这段内部说明不需要进入人物归并。",
        },
        evidence_payload={
            "characters": [
                {
                    "character_id": "7",
                    "canonical_name": "周衡",
                    "aliases": ["阿衡"],
                    "personhood_evidence": "阿衡被称呼并行动。",
                    "activity_or_state_evidence": "阿衡重新进入场景。",
                    "candidate_type": "character",
                    "confidence": 0.9,
                }
            ]
        },
    )

    existing_profile = reduce_inputs[0]["existing_profile"]
    assert "profile_summary_md" not in existing_profile
    assert existing_profile["profile_brief"]["current_state"] == "持久化人物简档。"
    assert "source_refs" not in existing_profile["profile_brief"]
    assert "compacted_until" not in existing_profile["profile_brief"]
    assert "chapter_summary_md" not in reduce_inputs[0]["chapter_summary"]
    assert "完整章节摘要" not in json.dumps(reduce_inputs[0], ensure_ascii=False)
    assert "短摘要唯一文本" not in reduce_inputs[0]["chapter_context_text"]
    assert "outline-segment:chapter-4:docs-7-8" in reduce_inputs[0]["chapter_context_text"]
    assert "compression_notes" not in reduce_inputs[0]["current_outline_segment"]


def test_character_reduce_context_falls_back_to_short_summary_without_outline_segment() -> None:
    service = MemoryCandidateService()
    reduce_inputs = service.build_character_reduce_inputs(
        prompt_input={"book_id": "book-1", "character_profiles": []},
        summary_payload={"chapter_summary_short": "只有短摘要可用。"},
        current_outline_segment={"outline_segment_id": "outline-segment:chapter-4:docs-7-8"},
        evidence_payload={
            "characters": [
                {
                    "character_id": "7",
                    "canonical_name": "周衡",
                    "personhood_evidence": "周衡被称呼并行动。",
                    "activity_or_state_evidence": "周衡重新进入场景。",
                    "candidate_type": "character",
                    "confidence": 0.9,
                }
            ]
        },
    )

    assert reduce_inputs[0]["chapter_context_text"] == "短摘要：只有短摘要可用。"


def test_character_reduce_context_prefers_multi_chapter_outline_segments_and_falls_back_per_item() -> None:
    service = MemoryCandidateService()

    context_text = service._character_reduce_chapter_context_text(  # noqa: SLF001
        summary_short="顶层短摘要不应在当前 segment 可用时重复。",
        current_outline_segment={
            "outline_segment_id": "outline-segment:chapter-1:docs-1-2",
            "outline_segment": "第一章 outline segment。",
            "source_doc_range": "1-2",
        },
        chapter_summaries=service._compact_chapter_summaries(  # noqa: SLF001
            [
                {
                    "document_title_index": 2,
                    "chapter_title": "第二章",
                    "chapter_summary_short": "第二章短摘要不应出现。",
                    "outline_segment_id": "outline-segment:chapter-2:docs-3-4",
                    "outline_segment": "第二章 outline segment。",
                    "source_doc_range": "3-4",
                },
                {
                    "document_title_index": 3,
                    "chapter_title": "第三章",
                    "chapter_summary_short": "第三章缺 segment，使用短摘要。",
                },
            ]
        ),
    )

    assert "第一章 outline segment" in context_text
    assert "第二章 outline segment" in context_text
    assert "第三章缺 segment，使用短摘要。" in context_text
    assert "顶层短摘要不应" not in context_text
    assert "第二章短摘要不应出现" not in context_text


def test_character_reduce_inputs_carry_profile_update_detail_gate() -> None:
    service = MemoryCandidateService()
    reduce_inputs = service.build_character_reduce_inputs(
        prompt_input={
            "book_id": "book-1",
            "character_profiles": [
                {
                    "character_id": "7",
                    "canonical_name": "周衡",
                    "aliases": [],
                    "profile_brief": {"identity": {"character_id": "7", "canonical_name": "周衡"}},
                    "profile_brief_status": "ready",
                    "character_update_gate": {
                        "detail_level": "index_only",
                        "reason": "low_frequency_or_background_role",
                        "current_doc_frequency": 0.25,
                    },
                }
            ],
        },
        summary_payload={"chapter_summary_short": "周衡在远处短暂出现。"},
        evidence_payload={
            "character_evidence_batches": [
                {
                    "doc_ids": [11],
                    "document_title_indexes": [4],
                    "characters": [
                        {
                            "character_id": "7",
                            "canonical_name": "周衡",
                            "personhood_evidence": "周衡被提及。",
                            "activity_or_state_evidence": "",
                            "candidate_type": "character",
                            "confidence": 0.8,
                        }
                    ],
                }
            ]
        },
    )

    assert reduce_inputs[0]["reduce_policy"]["detail_level"] == "index_only"
    assert reduce_inputs[0]["profile_update_gate"]["reason"] == "low_frequency_or_background_role"


def test_memory_candidate_prompt_input_uses_batch_level_evidence() -> None:
    service = MemoryCandidateService()

    prompt_input = service.build_prompt_input(
        prompt_input={
            "book_id": "book-1",
            "current_title_index": 1,
            "chapter_title": "第一章",
            "story_outline_md": "大纲",
            "world_summary_md": "世界观",
            "character_profiles": [],
        },
        summary_payload={"chapter_summary_short": "路明非进入学院。"},
        evidence_payload={
            "character_evidence_batch_id": "book-1:character-evidence:1-2",
            "characters": [{"canonical_name": "路明非", "candidate_type": "character", "confidence": 0.9}],
        },
    )

    assert "character_evidence_batches" in prompt_input
    assert prompt_input["character_evidence_batches"][0]["character_evidence_batch_id"] == (
        "book-1:character-evidence:1-2"
    )
    assert "candidate_policy" in prompt_input
    assert "character_evidence" not in prompt_input


def test_character_profile_service_consumes_lightweight_character_evidence(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "profile_lightweight.db")
    service = CharacterProfileService(profiles_repo=CharacterProfilesRepo())

    with db.connect() as conn:
        db.init_schema(conn)
        service.merge_updates(
            conn,
            book_id="book-17",
            chapter_index=4,
            doc_ids=[40],
            updates=[
                {
                    "canonical_name": "路明非",
                    "aliases": [],
                    "is_speaking_character": True,
                    "speaking_evidence": "路明非有明确回应。",
                    "personhood_evidence_summary": "被称呼并发言，执行具体行动。",
                    "activity_or_state_evidence": "路明非决定进入学院。",
                    "relationship_evidence": "与楚子航 直接对话并建立信任。",
                    "evidence_level": "explicit",
                }
            ],
        )
        conn.commit()
        row = CharacterProfilesRepo().get(conn, book_id="book-17", canonical_name="路明非")

    assert row is not None
    assert row["speaking_character_status"] == "confirmed_speaking"
    assert row["personhood_evidence_summary"] == "被称呼并发言，执行具体行动。"
    assert row["evidence_level"] == "explicit"
    assert json.loads(row["recent_activity_json"])[0]["value"] == "路明非决定进入学院。"
    assert json.loads(row["relationships_json"]) == []
    assert "发言状态：confirmed_speaking" in row["profile_summary_md"]
    assert "人物性证据：被称呼并发言，执行具体行动。" in row["profile_summary_md"]


def test_character_evidence_log_buffers_pending_evidence_until_compacted(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "character_evidence_log.db")
    repo = CharacterEvidenceLogRepo()

    with db.connect() as conn:
        db.init_schema(conn)
        inserted = repo.append_many(
            conn,
            book_id="book-17",
            evidence_items=[
                {
                    "character_id": "9",
                    "canonical_name": "路明非",
                    "candidate_type": "character",
                    "confidence": 0.9,
                    "activity_or_state_evidence": "路明非决定进入学院。",
                    "source_doc_ids": [40],
                    "source_title_indexes": [4],
                }
            ],
            outline_segment={
                "outline_segment_id": "outline-segment:chapter-4:docs-40-40",
                "outline_segment": "路明非决定进入学院。",
                "source_doc_ids": [40],
                "source_title_indexes": [4],
                "source_doc_range": "40-40",
            },
            updated_at="now",
        )
        groups = repo.pending_groups(conn, book_id="book-17")

        assert inserted == 1
        assert len(groups) == 1
        assert groups[0]["character_id"] == "9"
        assert groups[0]["canonical_name"] == "路明非"
        assert groups[0]["outline_segment_ids"] == ["outline-segment:chapter-4:docs-40-40"]
        assert groups[0]["evidence_items"][0]["evidence_id"].startswith("char-evidence:")
        assert groups[0]["evidence_items"][0]["outline_segment"] == "路明非决定进入学院。"

        repo.mark_compacted(conn, evidence_ids=groups[0]["evidence_ids"], updated_at="later")
        assert repo.pending_groups(conn, book_id="book-17") == []


def test_character_profile_service_persists_character_reduce_profile_brief(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "profile_brief_from_reduce.db")
    service = CharacterProfileService(profiles_repo=CharacterProfilesRepo())

    profile_brief = {
        "identity": {"character_id": "1", "canonical_name": "路明非", "aliases": []},
        "current_state": "已决定进入学院。",
        "stable_traits": [],
        "abilities_or_limits": [],
        "relationship_digest": [],
        "open_questions": [],
        "latest_major_change": {"summary": "决定进入学院。", "source_refs": []},
        "source_refs": [{"outline_segment_id": "outline-segment:chapter-4:docs-40-40", "source_doc_ids": [40]}],
        "compacted_until": {"doc_id": 40, "outline_segment_id": "outline-segment:chapter-4:docs-40-40"},
    }

    with db.connect() as conn:
        db.init_schema(conn)
        service.merge_updates(
            conn,
            book_id="book-17",
            chapter_index=4,
            doc_ids=[40],
            updates=[
                {
                    "canonical_name": "路明非",
                    "aliases": [],
                    "recent_activity": "路明非决定进入学院。",
                    "relationships": [],
                    "profile_brief": profile_brief,
                    "profile_brief_status": "ready",
                }
            ],
        )
        conn.commit()
        row = CharacterProfilesRepo().get(conn, book_id="book-17", canonical_name="路明非")

    assert row is not None
    assert json.loads(row["profile_brief_json"]) == profile_brief
    assert row["profile_brief_status"] == "ready"
    assert row["brief_compacted_until_doc_id"] == 40
    assert row["brief_compacted_until_segment_id"] == "outline-segment:chapter-4:docs-40-40"


def test_context_assembly_exposes_profile_state_without_raw_character_evidence(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "context_lightweight.db")
    with db.connect() as conn:
        db.init_schema(conn)
        CharacterProfilesRepo().upsert(
            conn,
            {
                "book_id": "book-18",
                "canonical_name": "路明非",
                "aliases": [],
                "profile_summary_md": "# 路明非\n\n- 发言状态：confirmed_speaking\n- 人物性证据：被称呼并发言。\n",
                "speaking_character_status": "confirmed_speaking",
                "personhood_evidence_summary": "被称呼并发言。",
                "evidence_level": "explicit",
                "personality": [],
                "occupations": [],
                "age_timeline": [],
                "abilities": [],
                "recent_activity": [{"value": "决定进入学院。"}],
                "relationships": [],
                "chapter_indexes": [1],
                "first_seen_doc_id": 1,
                "last_seen_doc_id": 1,
                "first_seen_title_index": 1,
                "last_seen_title_index": 1,
                "importance_score": 50,
                "profile_version": 1,
                "created_at": "now",
                "updated_at": "now",
            },
        )
        conn.commit()

        payload = ContextAssemblyService.build_default(repo_root=tmp_path).assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book-18",
                document_title_index="1",
                related_character_names=["路明非"],
                token_budget=MemoryAssemblyBudget(
                    chapter_context_chars=0,
                    world_summary_chars=0,
                    character_profiles_chars=800,
                    story_outline_chars=0,
                ),
            ),
        ).to_dict()

    profile = payload["character_profiles"][0]
    assert profile["speaking_character_status"] == "confirmed_speaking"
    assert profile["personhood_evidence_summary"] == "被称呼并发言。"
    assert profile["recent_activity_summary"] == "决定进入学院。"
    assert "character_evidence_batch_id" not in json.dumps(payload, ensure_ascii=False)
    assert "speaking_offsets" not in json.dumps(payload, ensure_ascii=False)
    assert "document_character_mentions" not in json.dumps(payload, ensure_ascii=False)


def test_close_read_runner_accepts_batch_level_character_evidence_and_filters_low_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "runner_batch_evidence.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(
            conn,
            book_id="book-19",
            title_index=1,
            title="第一章",
            content="路明非说：“我会去。”他与诺诺一起进入学院。张开地图铺在桌上。",
        )
        conn.commit()

    long_summary = _chapter_summary_md("路明非明确回应并进入学院，随后与诺诺同行，张开地图造成的伪人物候选被过滤。")

    def fake_generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = self, use_fallback_on_error
        if "Character Evidence Agent" in system_prompt:
            assert "character_evidence_batch_id" in user_prompt
            assert "mention_offsets" in system_prompt
            return (
                {
                    "character_evidence_batch_id": "book-19:character-evidence:1",
                    "characters": [
                        {
                            "canonical_name": "路明非",
                            "aliases": [],
                            "is_speaking_character": True,
                            "speaking_evidence": "有明确说话归因。",
                            "personhood_evidence": "被姓名指称并发言。",
                            "activity_or_state_evidence": "路明非回应后进入学院。",
                            "relationship_evidence": "与诺诺 一起进入学院。",
                            "candidate_type": "character",
                            "confidence": 0.9,
                            "uncertainty_reason": "",
                        },
                        {
                            "canonical_name": "张开",
                            "aliases": [],
                            "is_speaking_character": False,
                            "speaking_evidence": "",
                            "personhood_evidence": "",
                            "activity_or_state_evidence": "",
                            "relationship_evidence": "",
                            "candidate_type": "non_person",
                            "confidence": 0.2,
                            "uncertainty_reason": "动作词。",
                        },
                    ],
                },
                "",
            )
        if "Memory Update Candidate Agent" in system_prompt:
            return fallback_factory(), ""
        if "Character Reduce Agent" in system_prompt:
            return fallback_factory(), ""
        if "Chapter Outline Segment Agent" in system_prompt:
            return fallback_factory(), ""
        if "Character Identity Resolution Agent" in system_prompt:
            return fallback_factory(), ""
        if "Outline Root Summary Agent" in system_prompt:
            return fallback_factory(), ""
        return (
            {
                "chapter_summary_md": long_summary,
                "chapter_summary_short": "路明非回应后进入学院。",
                "importance_score": 70,
                "importance_reason": "人物行动明确。",
                "related_chapters": [],
            },
            "",
        )

    monkeypatch.setattr(JsonModelClient, "generate_json", fake_generate_json)

    config = CloseReadAgentConfig(book_id="book-19", sqlite_path=str(db_path))
    config.runtime.dry_run = True
    config.runtime.max_chapters = 1
    config.runtime.export_debug_markdown = False
    config.runtime.document_chars_budget = 20_000

    result = CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=config).run()

    assert result.processed_batches == 1
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        profile_rows = conn.execute(
            "SELECT canonical_name, speaking_character_status, personhood_evidence_summary, recent_activity_json "
            "FROM character_profiles WHERE book_id = 'book-19' ORDER BY canonical_name"
        ).fetchall()
        doc_keywords = conn.execute(
            "SELECT character_keywords_json FROM documents WHERE book_id = 'book-19'"
        ).fetchone()[0]

    assert [row["canonical_name"] for row in profile_rows] == ["路明非"]
    assert profile_rows[0]["speaking_character_status"] == "confirmed_speaking"
    assert profile_rows[0]["personhood_evidence_summary"] == "被姓名指称并发言。"
    assert "路明非回应后进入学院" in profile_rows[0]["recent_activity_json"]
    assert "路明非" in doc_keywords
    assert "张开" not in doc_keywords
