from __future__ import annotations

from pathlib import Path

from novel_agent.app.constants import DEFAULT_CLOSE_READING_STAGE
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentRow
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.reading_progress_repo import ReadingProgressRepo
from novel_agent.app.runner.close_read_runner import CloseReadRunner
from novel_agent.app.schemas.config_schema import CloseReadAgentConfig, CloseReadRuntimeConfig
from novel_agent.app.services.chapter_assembler_service import ChapterAssemblerService, ChapterBatch
from novel_agent.app.services.memory_candidate_service import MemoryCandidateService


def _close_read_runner(tmp_path: Path) -> CloseReadRunner:
    return CloseReadRunner(
        repo_root=tmp_path,
        db_path=tmp_path / "novel.db",
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(dry_run=True),
        ),
    )


def _plot_synopsis_md() -> str:
    return "\n".join(
        [
            "## 剧情事件链",
            "林澈进入旧仓库寻找线索，发现铁柜背后藏着失踪录音带，调查线因此获得新证据。",
            "## 人物状态/关系变化",
            "林澈从被动追查转为掌握关键证据，并准备把录音带交给同伴核验。",
            "## 关键信息/设定",
            "录音带被藏在旧仓库铁柜背后，是旧案调查的重要物证。",
            "## 结构功能/节奏",
            "本章完成线索发现，并为后续对峙和证据核验铺垫。",
        ]
    )


def _chapter_batch(*, title_index: int = 1, doc_id: int = 1, content: str = "林澈继续调查旧案。") -> ChapterBatch:
    return ChapterBatch(
        document_title_index=title_index,
        chapter_title=f"第{title_index}章",
        documents=[
            DocumentRow(
                doc_id=doc_id,
                book_id="book",
                path="source.txt",
                scope="chapter",
                title=f"第{title_index}章",
                document_title=f"第{title_index}章",
                document_title_index=title_index,
                inferred_chapter_no=title_index,
                content=content,
                content_chars=len(content),
                character_keywords=[],
                content_tags=[],
                source_path="source.txt",
                source_file_name="source.txt",
                source_start_offset=0,
                source_end_offset=len(content),
            )
        ],
        chapter_doc_count=1,
        chapter_total_chars=len(content),
    )


def test_chapter_summary_accepts_valid_chapter_summary_alias(tmp_path: Path) -> None:
    runner = _close_read_runner(tmp_path)
    batch = _chapter_batch(content="林澈继续调查旧案。" * 20)
    payload = {
        "summary_quality": "plot_synopsis",
        "chapter_summary": _plot_synopsis_md(),
        "chapter_summary_short": "林澈在旧仓库发现失踪录音带。",
        "importance_score": 70,
        "importance_reason": "关键证据出现。",
        "related_chapters": [],
    }

    normalized = runner._normalize_chapter_summary_schema_aliases(payload)  # noqa: SLF001
    runner._validate_summary_payload(batch=batch, payload=payload)  # noqa: SLF001

    assert normalized["chapter_summary_md"] == payload["chapter_summary"]


def test_multi_chapter_summary_accepts_nested_chapter_summary_alias(tmp_path: Path) -> None:
    runner = _close_read_runner(tmp_path)
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="多章",
        documents=[
            _chapter_batch(title_index=1, doc_id=1, content="林澈调查旧案。" * 20).documents[0],
            _chapter_batch(title_index=2, doc_id=2, content="顾迟追踪证据。" * 20).documents[0],
        ],
    )
    payload = {
        "summary_quality": "plot_synopsis",
        "chapter_summaries": [
            {
                "document_title_index": 1,
                "chapter_title": "第1章",
                "summary_quality": "plot_synopsis",
                "chapter_summary": _plot_synopsis_md(),
                "chapter_summary_short": "林澈在旧仓库发现失踪录音带。",
                "importance_score": 70,
                "importance_reason": "关键证据出现。",
                "related_chapters": [],
            },
            {
                "document_title_index": 2,
                "chapter_title": "第2章",
                "summary_quality": "plot_synopsis",
                "chapter_summary": _plot_synopsis_md(),
                "chapter_summary_short": "顾迟追踪证据。",
                "importance_score": 60,
                "importance_reason": "调查线推进。",
                "related_chapters": [],
            },
        ],
    }

    normalized_items = runner._normalize_model_chapter_summaries(  # noqa: SLF001
        batch=batch,
        raw_summaries=payload["chapter_summaries"],
    )
    runner._validate_summary_payload(batch=batch, payload=payload)  # noqa: SLF001

    assert all(item["chapter_summary_md"] for item in normalized_items)


def test_character_reduce_inputs_group_same_character_in_doc_order() -> None:
    service = MemoryCandidateService()
    reduce_inputs = service.build_character_reduce_inputs(
        prompt_input={
            "book_id": "book",
            "character_profiles": [{"canonical_name": "林澈", "aliases": ["小林"], "profile_summary_md": "旧档案"}],
        },
        summary_payload={"chapter_summary_short": "林澈连续经历两次事件。"},
        evidence_payload={
            "character_evidence_batches": [
                {
                    "character_evidence_batch_id": "book:character-evidence:2",
                    "doc_ids": [2],
                    "document_title_indexes": [1],
                    "characters": [
                        {
                            "canonical_name": "林澈",
                            "aliases": [],
                            "is_speaking_character": False,
                            "personhood_evidence": "被称呼并行动。",
                            "activity_or_state_evidence": "后续进入营地。",
                            "relationship_evidence": "",
                            "candidate_type": "character",
                            "confidence": 0.8,
                        }
                    ],
                },
                {
                    "character_evidence_batch_id": "book:character-evidence:1",
                    "doc_ids": [1],
                    "document_title_indexes": [1],
                    "characters": [
                        {
                            "canonical_name": "林澈",
                            "aliases": [],
                            "is_speaking_character": True,
                            "speaking_evidence": "有明确回应。",
                            "personhood_evidence": "发言并被称呼。",
                            "activity_or_state_evidence": "先收到邀请。",
                            "relationship_evidence": "",
                            "candidate_type": "character",
                            "confidence": 0.9,
                        },
                        {
                            "canonical_name": "广场",
                            "personhood_evidence": "",
                            "candidate_type": "scene",
                            "confidence": 0.2,
                        },
                    ],
                },
            ]
        },
        current_outline_segment={
            "outline_segment_id": "outline-segment:chapter-1:docs-1-2",
            "outline_segment": "林澈先收到邀请，随后进入营地。",
            "chapter_line": "[1] 第一章: 林澈进入营地。",
            "source_doc_ids": [1, 2],
            "source_doc_range": "1-2",
            "source_title_indexes": [1],
        },
    )

    assert [item["canonical_name"] for item in reduce_inputs] == ["林澈"]
    evidence = reduce_inputs[0]["ordered_character_evidence"]
    assert [item["source_doc_ids"] for item in evidence] == [[1], [2]]
    assert reduce_inputs[0]["existing_profile"]["profile_summary_md"] == "旧档案"
    assert reduce_inputs[0]["current_outline_segment"]["outline_segment_id"] == "outline-segment:chapter-1:docs-1-2"
    assert reduce_inputs[0]["reduce_policy"]["key_experiences_must_be_target_character_scoped"] is True


def test_memory_candidates_keep_model_supported_short_names_and_roles() -> None:
    service = MemoryCandidateService()
    evidence_payload = {
        "characters": [
            {
                "canonical_name": "静",
                "aliases": [],
                "is_speaking_character": True,
                "speaking_evidence": "静说今晚继续调查。",
                "personhood_evidence": "静被明确当作行动者。",
                "activity_or_state_evidence": "静继续调查旧案。",
                "relationship_evidence": "静与丈夫存在冲突。",
                "candidate_type": "character",
                "confidence": 0.9,
            },
            {
                "canonical_name": "小锋",
                "aliases": [],
                "is_speaking_character": False,
                "personhood_evidence": "小锋在门口等待。",
                "activity_or_state_evidence": "小锋负责看守门口。",
                "relationship_evidence": "",
                "candidate_type": "character",
                "confidence": 0.72,
            },
            {
                "canonical_name": "丈夫",
                "aliases": [],
                "is_speaking_character": False,
                "personhood_evidence": "丈夫是家庭关系中的行动者。",
                "activity_or_state_evidence": "丈夫拿走录音带。",
                "relationship_evidence": "丈夫与静存在隐瞒。",
                "candidate_type": "character",
                "confidence": 0.81,
            },
            {
                "canonical_name": "身体",
                "aliases": [],
                "personhood_evidence": "身体只是物理状态。",
                "activity_or_state_evidence": "",
                "relationship_evidence": "",
                "candidate_type": "object",
                "confidence": 0.9,
            },
        ]
    }

    updates = service.build_character_updates(summary_short="静重新调查旧案。", evidence_payload=evidence_payload)
    reduce_inputs = service.build_character_reduce_inputs(
        prompt_input={"book_id": "book", "character_profiles": []},
        summary_payload={"chapter_summary_short": "静重新调查旧案。"},
        evidence_payload=evidence_payload,
    )

    assert {item["canonical_name"] for item in updates} == {"静", "小锋", "丈夫"}
    assert {item["canonical_name"] for item in reduce_inputs} == {"静", "小锋", "丈夫"}


def test_document_mentions_keep_model_supported_short_names(tmp_path: Path) -> None:
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=tmp_path / "novel.db",
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(dry_run=True),
        ),
    )
    content = "静说今晚继续调查，小锋说他会守在门口。丈夫先生把录音带藏了起来。"
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="第一章",
        documents=[
            DocumentRow(
                doc_id=1,
                book_id="book",
                path="source.txt",
                scope="chapter",
                title="第一章",
                document_title="第一章",
                document_title_index=1,
                inferred_chapter_no=1,
                content=content,
                content_chars=len(content),
                character_keywords=[],
                content_tags=[],
                source_path="source.txt",
                source_file_name="source.txt",
                source_start_offset=0,
                source_end_offset=len(content),
            )
        ],
        chapter_doc_count=1,
        chapter_total_chars=len(content),
    )

    mentions = runner._document_mentions_from_character_evidence(  # noqa: SLF001
        batch=batch,
        evidence_payload={
            "characters": [
                {
                    "canonical_name": "静",
                    "is_speaking_character": True,
                    "speaking_evidence": "静说今晚继续调查。",
                    "personhood_evidence": "静说今晚继续调查。",
                    "activity_or_state_evidence": "静继续调查旧案。",
                    "candidate_type": "character",
                    "confidence": 0.9,
                },
                {
                    "canonical_name": "小锋",
                    "is_speaking_character": True,
                    "speaking_evidence": "小锋说他会守在门口。",
                    "personhood_evidence": "小锋说他会守在门口。",
                    "activity_or_state_evidence": "小锋守在门口。",
                    "candidate_type": "character",
                    "confidence": 0.78,
                },
                {
                    "canonical_name": "丈夫",
                    "is_speaking_character": False,
                    "personhood_evidence": "丈夫先生把录音带藏了起来。",
                    "activity_or_state_evidence": "丈夫先生把录音带藏了起来。",
                    "relationship_evidence": "丈夫与静有隐瞒。",
                    "candidate_type": "character",
                    "confidence": 0.8,
                },
            ]
        },
    )
    normalized_mentions = runner._normalize_document_character_mentions(  # noqa: SLF001
        batch=batch,
        payload={"document_character_mentions": mentions},
    )

    assert normalized_mentions[1] == ["静", "小锋", "丈夫"]


def test_document_mentions_use_source_doc_ids_and_alias_evidence(tmp_path: Path) -> None:
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=tmp_path / "novel.db",
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(dry_run=True),
        ),
    )
    documents = [
        DocumentRow(
            doc_id=1,
            book_id="book",
            path="source.txt",
            scope="chapter",
            title="第一章",
            document_title="第一章",
            document_title_index=1,
            inferred_chapter_no=1,
            content="门外传来脚步声，房间里暂时无人说话。",
            content_chars=len("门外传来脚步声，房间里暂时无人说话。"),
            character_keywords=[],
            content_tags=[],
            source_path="source.txt",
            source_file_name="source.txt",
            source_start_offset=0,
            source_end_offset=20,
        ),
        DocumentRow(
            doc_id=2,
            book_id="book",
            path="source.txt",
            scope="chapter",
            title="第一章",
            document_title="第一章",
            document_title_index=1,
            inferred_chapter_no=1,
            content="Danny说今晚继续调查，老板点头回应。",
            content_chars=len("Danny说今晚继续调查，老板点头回应。"),
            character_keywords=[],
            content_tags=[],
            source_path="source.txt",
            source_file_name="source.txt",
            source_start_offset=20,
            source_end_offset=50,
        ),
    ]
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="第一章",
        documents=documents,
        chapter_doc_count=2,
        chapter_total_chars=sum(doc.content_chars for doc in documents),
    )

    mentions = runner._document_mentions_from_character_evidence(  # noqa: SLF001
        batch=batch,
        evidence_payload={
            "character_evidence_batches": [
                {
                    "doc_ids": [2],
                    "document_title_indexes": [1],
                    "characters": [
                        {
                            "canonical_name": "丹尼",
                            "aliases": ["Danny"],
                            "is_speaking_character": True,
                            "speaking_evidence": "Danny说今晚继续调查",
                            "personhood_evidence": "Danny说今晚继续调查",
                            "activity_or_state_evidence": "Danny继续调查",
                            "candidate_type": "character",
                            "confidence": 0.9,
                            "source_doc_ids": [2],
                        }
                    ],
                }
            ]
        },
    )
    normalized_mentions = runner._normalize_document_character_mentions(  # noqa: SLF001
        batch=batch,
        payload={"document_character_mentions": mentions},
    )
    normalized_speakers = runner._normalize_document_speaking_mentions(  # noqa: SLF001
        batch=batch,
        payload={"document_character_mentions": mentions},
    )

    assert normalized_mentions[1] == []
    assert normalized_mentions[2] == ["丹尼"]
    assert normalized_speakers[2] == ["丹尼"]


def test_document_mentions_trust_source_doc_ids_for_summarized_evidence(tmp_path: Path) -> None:
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=tmp_path / "novel.db",
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(dry_run=True),
        ),
    )
    content = "门外传来脚步声，房间里暂时无人说话。"
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="第一章",
        documents=[
            DocumentRow(
                doc_id=1,
                book_id="book",
                path="source.txt",
                scope="chapter",
                title="第一章",
                document_title="第一章",
                document_title_index=1,
                inferred_chapter_no=1,
                content=content,
                content_chars=len(content),
                character_keywords=[],
                content_tags=[],
                source_path="source.txt",
                source_file_name="source.txt",
                source_start_offset=0,
                source_end_offset=len(content),
            )
        ],
        chapter_doc_count=1,
        chapter_total_chars=len(content),
    )

    mentions = runner._document_mentions_from_character_evidence(  # noqa: SLF001
        batch=batch,
        evidence_payload={
            "character_evidence_batches": [
                {
                    "doc_ids": [1],
                    "document_title_indexes": [1],
                    "characters": [
                        {
                            "canonical_name": "林澈",
                            "is_speaking_character": False,
                            "personhood_evidence": "林澈在这一段被作为行动者追踪。",
                            "activity_or_state_evidence": "林澈注意到门外脚步声。",
                            "candidate_type": "character",
                            "confidence": 0.9,
                        }
                    ],
                }
            ]
        },
    )
    normalized_mentions = runner._normalize_document_character_mentions(  # noqa: SLF001
        batch=batch,
        payload={"document_character_mentions": mentions},
    )

    assert normalized_mentions[1] == ["林澈"]


def test_global_memory_input_excludes_documents_and_fallback_uses_world_candidates() -> None:
    service = MemoryCandidateService()
    global_input = service.build_global_memory_input(
        prompt_input={
            "book_id": "book",
            "documents": [{"doc_id": 1, "content": "原文不应进入 global memory"}],
            "world_summary_md": "旧世界观",
        },
        summary_payload={
            "chapter_summary_short": "本章揭示契约规则。",
            "world_signal_score": 80,
            "world_evidence_candidates": [
                {
                    "section": "能力体系",
                    "summary": "法术会受到契约约束。",
                    "evidence_hint": "法术与契约同段出现。",
                    "source_doc_ids": [1],
                    "confidence": 0.8,
                }
            ],
        },
        world_evidence_payload={},
    )

    assert "documents" not in global_input
    assert global_input["global_memory_policy"]["do_not_read_full_documents"] is True
    fallback = service.build_global_memory_fallback_output(
        summary_payload=global_input["chapter_summary"],
        world_evidence_payload=global_input["world_evidence"],
    )
    assert fallback["world_update"]["should_update"] is True
    assert fallback["world_update"]["changes"][0]["section"] == "能力体系"


def test_world_evidence_trigger_uses_hybrid_threshold(tmp_path: Path) -> None:
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=tmp_path / "novel.db",
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(
                dry_run=True,
                world_evidence_signal_threshold=70,
            ),
        ),
    )

    assert runner._should_run_world_evidence(  # noqa: SLF001
        batch=_FakeBatch("普通剧情推进，没有设定词。"),
        summary_payload={"world_signal_score": 20, "world_evidence_candidates": []},
    ) is False
    assert runner._should_run_world_evidence(  # noqa: SLF001
        batch=_FakeBatch("普通剧情推进。"),
        summary_payload={"world_signal_score": 75, "world_evidence_candidates": []},
    ) is True
    assert runner._should_run_world_evidence(  # noqa: SLF001
        batch=_FakeBatch("普通剧情推进。"),
        summary_payload={
            "world_signal_score": 20,
            "world_evidence_candidates": [{"section": "能力体系", "summary": "疑似规则", "confidence": 0.4}],
        },
    ) is True


def test_close_read_normalizes_model_low_signal_front_matter_summary(tmp_path: Path) -> None:
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=tmp_path / "novel.db",
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(dry_run=True),
        ),
    )
    content = "目录 第一幕 第二幕 献词 题记 在你最孤单最无望的时候，有一扇门会打开。"
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="第二幕 黄金瞳 Golden Eyes",
        documents=[
            DocumentRow(
                doc_id=1,
                book_id="book",
                path="source.txt",
                scope="chapter",
                title="第二幕 黄金瞳 Golden Eyes",
                document_title="第二幕 黄金瞳 Golden Eyes",
                document_title_index=1,
                inferred_chapter_no=1,
                content=content,
                content_chars=len(content),
                character_keywords=[],
                content_tags=[],
                source_path="source.txt",
                source_file_name="source.txt",
                source_start_offset=0,
                source_end_offset=len(content),
            )
        ],
        chapter_doc_count=1,
        chapter_total_chars=len(content),
    )

    summary = runner._normalize_chapter_summary(  # noqa: SLF001
        summary_md="本章节内容为全书目录和献词题记。无具体剧情事件、人物行动或情节推进。",
        batch=batch,
        source_total_chars=len(content),
    )

    assert "## 剧情事件链" in summary
    assert "无具体剧情事件" in summary
    assert "## 结构功能/节奏" in summary
    assert "低信号前置文本" in summary


def test_close_read_ignores_stray_chapter_summaries_for_single_chapter_batch(tmp_path: Path) -> None:
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=tmp_path / "novel.db",
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(dry_run=True),
        ),
    )
    content = "林澈推开旧仓库的门，发现失踪的录音带藏在铁柜背后。"
    batch = ChapterBatch(
        document_title_index=8,
        chapter_title="第八章",
        documents=[
            DocumentRow(
                doc_id=56,
                book_id="book",
                path="source.txt",
                scope="chapter",
                title="第八章",
                document_title="第八章",
                document_title_index=8,
                inferred_chapter_no=8,
                content=content,
                content_chars=len(content),
                character_keywords=[],
                content_tags=[],
                source_path="source.txt",
                source_file_name="source.txt",
                source_start_offset=0,
                source_end_offset=len(content),
            )
        ],
        chapter_doc_count=1,
        chapter_total_chars=len(content),
    )
    summary_md = "\n".join(
        [
            "## 剧情事件链",
            "林澈进入旧仓库寻找线索，发现铁柜背后藏着失踪录音带，调查线因此获得新证据。",
            "## 人物状态/关系变化",
            "林澈从被动追查转为掌握关键证据。",
            "## 关键信息/设定",
            "录音带被藏在旧仓库铁柜背后。",
            "## 结构功能/节奏",
            "本章完成线索发现，并为后续对峙铺垫。",
        ]
    )

    payload = runner._compose_close_read_payload(  # noqa: SLF001
        batch=batch,
        summary_payload={
            "summary_quality": "plot_synopsis",
            "chapter_summary_md": summary_md,
            "chapter_summary_short": "林澈在旧仓库发现失踪录音带。",
            "importance_score": 70,
            "importance_reason": "关键证据出现。",
            "related_chapters": [],
            "chapter_summaries": [
                {
                    "document_title_index": 999,
                    "chapter_title": "模型误填章节",
                    "chapter_summary_md": "这一项不属于当前 batch。",
                }
            ],
        },
        evidence_payload={},
        character_reduce_payload={},
        global_memory_payload={},
    )

    assert "chapter_summaries" not in payload
    assert payload["chapter_summary_md"] == summary_md


def test_chapter_assembler_can_prefetch_multiple_close_read_batches(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "novel.db")
    documents_repo = DocumentsRepo()
    progress_repo = ReadingProgressRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        for index in range(1, 4):
            _insert_document(
                conn,
                book_id="book",
                title_index=index,
                content=f"第{index}章内容，沈青继续调查。",
                offset=index * 100,
            )
        conn.commit()

        assembler = ChapterAssemblerService(
            documents_repo=documents_repo,
            progress_repo=progress_repo,
            document_chars_budget=18,
            progress_stage=DEFAULT_CLOSE_READING_STAGE,
        )
        batches = assembler.load_next_batches(conn, book_id="book", limit=2)

    assert len(batches) == 2
    assert [batch.documents[0].document_title_index for batch in batches] == [1, 2]
    assert [batch.documents[0].doc_id for batch in batches] == [1, 2]


def test_chapter_assembler_does_not_merge_adjacent_chapters_into_one_batch(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "novel.db")
    documents_repo = DocumentsRepo()
    progress_repo = ReadingProgressRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        for index in range(1, 4):
            _insert_document(
                conn,
                book_id="book",
                title_index=index,
                content=f"第{index}章内容，沈青继续调查。",
                offset=index * 100,
            )
        conn.commit()

        assembler = ChapterAssemblerService(
            documents_repo=documents_repo,
            progress_repo=progress_repo,
            document_chars_budget=100_000,
            progress_stage=DEFAULT_CLOSE_READING_STAGE,
        )
        batch = assembler.load_next_batch(conn, book_id="book")
        batches = assembler.load_next_batches(conn, book_id="book", limit=3)

    assert batch is not None
    assert batch.title_indexes == [1]
    assert batch.is_multi_chapter is False
    assert [item.title_indexes for item in batches] == [[1], [2], [3]]


def test_close_read_character_evidence_runs_once_per_document_in_batch(tmp_path: Path) -> None:
    db_path = tmp_path / "novel.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        for index, name in enumerate(["沈青", "顾迟", "林晚"], start=1):
            _insert_document(
                conn,
                book_id="book",
                title_index=1,
                content=f"{name}说今晚继续调查，其他人点头回应。",
                offset=index * 100,
            )
        conn.commit()

    events: list[dict[str, object]] = []
    runner = CloseReadRunner(
        repo_root=tmp_path,
        db_path=db_path,
        config=CloseReadAgentConfig(
            book_id="book",
            runtime=CloseReadRuntimeConfig(
                dry_run=True,
                export_debug_markdown=False,
                max_chapters=1,
                document_chars_budget=1_000,
                close_read_extraction_window_count=1,
                close_read_extraction_max_workers=4,
            ),
        ),
        progress_callback=events.append,
    )

    def fake_summary_payload(*, model_client, batch, prompt_input):  # noqa: ANN001, ARG001
        runner._emit_progress(  # noqa: SLF001
            {
                "stage": "close_reading",
                "agent": "chapter_summary",
                "event": "prompt_start",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
            }
        )
        runner._emit_progress(  # noqa: SLF001
            {
                "stage": "close_reading",
                "agent": "chapter_summary",
                "event": "prompt_end",
                "document_title_indexes": batch.title_indexes,
                "doc_count": len(batch.documents),
                "total_chars": batch.total_chars,
                "duration_seconds": 0.0,
            }
        )
        return {
            "summary_quality": "plot_synopsis",
            "chapter_summary_md": "\n".join(
                [
                    "## 剧情事件链",
                    "沈青、顾迟和林晚继续调查旧案，三人各自确认下一步行动。",
                    "## 人物状态/关系变化",
                    "三人的协作关系继续推进。",
                    "## 关键信息/设定",
                    "旧案仍是本章调查核心。",
                    "## 结构功能/节奏",
                    "本章承担继续推进调查线的功能。",
                ]
            ),
            "chapter_summary_short": "三人继续调查旧案。",
            "importance_score": 50,
            "importance_reason": "人物行动清晰。",
            "related_chapters": [],
            "world_signal_score": 0,
            "world_evidence_candidates": [],
        }

    runner._generate_chapter_summary_payload = fake_summary_payload  # type: ignore[method-assign]  # noqa: SLF001
    result = runner.run()

    evidence_starts = [
        event
        for event in events
        if event.get("agent") == "character_evidence" and event.get("event") == "prompt_start"
    ]
    summary_starts = [
        event
        for event in events
        if event.get("agent") == "chapter_summary" and event.get("event") == "prompt_start"
    ]
    assert result.processed_batches == 1
    assert len(summary_starts) == 1
    assert summary_starts[0]["doc_count"] == 3
    assert len(evidence_starts) == 3
    assert {event["doc_count"] for event in evidence_starts} == {1}


class _FakeDoc:
    doc_id = 1
    document_title_index = 1
    document_title = "第一章"

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeBatch:
    title_indexes = [1]

    def __init__(self, content: str) -> None:
        self.documents = [_FakeDoc(content)]


def _insert_document(conn, *, book_id: str, title_index: int, content: str, offset: int) -> int:
    return DocumentsRepo().insert_document(
        conn,
        {
            "book_id": book_id,
            "path": f"docs/chapter-{title_index}.md",
            "scope": "docs",
            "title": f"第{title_index}章",
            "document_title": f"第{title_index}章",
            "document_title_index": title_index,
            "inferred_chapter_no": title_index,
            "content": content,
            "content_chars": len(content),
            "character_keywords": [],
            "content_tags": [],
            "source_path": "docs/book.md",
            "source_file_name": "book.md",
            "source_start_offset": offset,
            "source_end_offset": offset + len(content),
            "ingestion_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )
