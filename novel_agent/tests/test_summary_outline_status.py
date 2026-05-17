from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.runner.close_read_runner import CloseReadRunner
from novel_agent.app.schemas.orchestration_schema import ContinuationIntent, ExtractedCharacterMentions, MemoryAssemblyBudget, MemoryAssemblyInput
from novel_agent.app.services.chapter_assembler_service import ChapterBatch
from novel_agent.app.services.character_mention_service import CharacterMentionService
from novel_agent.app.services.character_profile_service import CharacterProfileService
from novel_agent.app.services.context_assembly_service import ContextAssemblyService
from novel_agent.app.services.chapter_event_list_service import ChapterEventListService
from novel_agent.app.services.chapter_event_summary_service import ChapterEventSummaryService
from novel_agent.app.services.outline_event_summary_service import OutlineEventSummaryService
from novel_agent.app.services.outline_research_service import OutlineSeedPacketBuilder
from novel_agent.app.services.outline_service import OutlineService
from novel_agent.app.services.source_arc_mapping_service import SourceArcMappingService
from novel_agent.app.services.summary_outline_commit_service import SummaryOutlineCommitService
from novel_agent.app.services.world_state_service import WorldStateService


def test_chapters_repo_status_fields_default_and_preserve_committed(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "memory.db")
    repo = ChaptersRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        repo.upsert(conn, _chapter_payload(book_id="book", index=1, summary="provisional summary"))
        row = repo.get(conn, book_id="book", document_title_index=1)
        assert row is not None
        assert row["summary_status"] == "provisional"
        assert row["outline_status"] == "provisional"

        repo.upsert(
            conn,
            {
                **_chapter_payload(book_id="book", index=1, summary="committed summary"),
                "summary_status": "committed",
                "summary_evidence_window": "1-3",
                "summary_target_range": "1-1",
                "outline_update": {"chapter_line": "[1] committed line", "timeline_events": []},
                "outline_status": "committed",
                "outline_evidence_window": "1-3",
                "outline_target_range": "1-1",
            },
        )
        repo.upsert(conn, _chapter_payload(book_id="book", index=1, summary="new provisional summary"))
        row = repo.get(conn, book_id="book", document_title_index=1)

    assert row is not None
    assert "committed summary" in row["summary_md"]
    assert "new provisional summary" not in row["summary_md"]
    assert row["summary_status"] == "committed"
    assert row["summary_evidence_window"] == "1-3"
    assert json.loads(row["outline_update_json"])["chapter_line"] == "[1] committed line"
    assert row["outline_status"] == "committed"


def test_old_chapter_rows_gain_provisional_status_defaults(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "legacy.db")
    with sqlite3.connect(str(db.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE chapters (
                chapter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                document_title_index INTEGER NOT NULL,
                chapter_title TEXT NOT NULL,
                source_doc_start_id INTEGER NOT NULL,
                source_doc_end_id INTEGER NOT NULL,
                source_doc_count INTEGER NOT NULL,
                source_total_chars INTEGER NOT NULL,
                summary_intermediate_json TEXT NOT NULL DEFAULT '[]',
                summary_md TEXT NOT NULL DEFAULT '',
                summary_short TEXT,
                importance_score INTEGER NOT NULL DEFAULT 0,
                importance_reason TEXT,
                related_chapters_json TEXT NOT NULL DEFAULT '[]',
                mentioned_characters_json TEXT NOT NULL DEFAULT '[]',
                world_update_json TEXT NOT NULL DEFAULT '{}',
                outline_update_json TEXT NOT NULL DEFAULT '{}',
                close_read_run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(book_id, document_title_index)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO chapters(
                book_id, document_title_index, chapter_title, source_doc_start_id,
                source_doc_end_id, source_doc_count, source_total_chars,
                summary_md, summary_short, created_at, updated_at
            ) VALUES ('book', 1, '第一章', 1, 1, 1, 100, '旧摘要', '旧短摘要', 'now', 'now')
            """
        )
        db.init_schema(conn)
        row = ChaptersRepo().get(conn, book_id="book", document_title_index=1)

    assert row is not None
    assert row["summary_status"] == "provisional"
    assert row["outline_status"] == "provisional"


def test_close_read_outline_events_record_source_doc_range() -> None:
    runner = object.__new__(CloseReadRunner)
    runner.character_mention_service = CharacterMentionService()
    batch = SimpleNamespace(
        document_title_index=12,
        chapter_title="第12章 交易",
        documents=[
            SimpleNamespace(doc_id=48, document_title_index=12),
            SimpleNamespace(doc_id=49, document_title_index=12),
        ],
    )

    outline_update = runner._enrich_outline_update_with_sources(
        batch=batch,
        outline_update={
            "chapter_line": "[12] 第12章: 芬格尔兜售考题。",
            "timeline_events": [
                {
                    "label": "芬格尔兜售考题",
                    "participants": ["路明非", "芬格尔"],
                    "summary": "芬格尔利用时间压力促成交易。",
                }
            ],
        },
        summary_short="芬格尔向路明非兜售考题。",
    )
    fallback_outline_update = runner._enrich_outline_update_with_sources(
        batch=batch,
        outline_update={"timeline_events": [{"label": "交易发生", "summary": "考题交易被推进。"}]},
        summary_short="芬格尔向路明非兜售考题。",
        fallback_participants=["路明非", "楚子航"],
    )

    event = outline_update["timeline_events"][0]
    assert event["event_id"].startswith("chapter-12:event-01")
    assert event["source_doc_ids"] == [48, 49]
    assert event["source_doc_range"] == "48-49"
    assert event["event_id"].endswith("docs-48-49")
    assert outline_update["event_summary"] == "芬格尔利用时间压力促成交易。"
    assert fallback_outline_update["timeline_events"][0]["participants"] == ["路明非", "楚子航"]


def test_close_read_outline_event_summary_uses_full_plot_chain_without_excerpt() -> None:
    runner = object.__new__(CloseReadRunner)
    runner.character_mention_service = CharacterMentionService()
    batch = SimpleNamespace(
        document_title_index=3,
        chapter_title="第三章",
        documents=[
            SimpleNamespace(doc_id=10, document_title_index=3),
            SimpleNamespace(doc_id=11, document_title_index=3),
        ],
    )
    summary_md = "\n".join(
        [
            "## 摘要元信息",
            "- 章节索引：3",
            "## 剧情事件链",
            "- 调查员接到新线索，重新梳理前一晚的行动顺序。",
            "- 同伴补充关键证词，使队伍确认事件并非偶然。",
            "- " + "后续行动持续推进，新的证据逐步连接到同一个核心冲突。" * 6,
            "## 人物状态/关系变化",
            "- 队伍内部从迟疑转为协作。",
            "## 关键信息/设定",
            "- 证据链需要继续核验。",
            "## 结构功能/节奏",
            "- 本章把线索从分散状态推进为可追踪链条。",
        ]
    )

    event_summary = runner._flatten_summary_event_chain(summary_md)  # noqa: SLF001
    outline_update = runner._enrich_outline_update_with_sources(  # noqa: SLF001
        batch=batch,
        outline_update={},
        summary_short="调查员接到新线索...",
        event_summary=event_summary,
    )

    assert len(event_summary) > 120
    assert event_summary.endswith("核心冲突。")
    assert "- " not in event_summary
    assert outline_update["event_summary"] == event_summary
    assert outline_update["timeline_events"][0]["summary"] == event_summary


def test_chapter_event_summary_service_uses_summary_md_compression_prompt() -> None:
    class _EventSummaryModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = fallback_factory, use_fallback_on_error
            assert "Chapter Event Summary Agent" in system_prompt
            assert "summary_md" in user_prompt
            assert "chapter_event_list" in user_prompt
            return (
                {
                    "event_summary": (
                        "调查员接到线索后重新串联前夜行动，同伴补充证词让队伍确认事件并非偶然，"
                        "后续证据把分散线索指向同一核心冲突。"
                    ),
                    "compression_notes": "保留起因、协作、转折和结果。",
                },
                "",
            )

    summary_md = "\n".join(
        [
            "## 剧情事件链",
            "- 起点：调查员接到新线索，重新梳理前一晚的行动顺序。",
            "- 触发：同伴补充关键证词，使队伍确认事件并非偶然。",
            "- 行动/冲突：" + "后续行动持续推进，新的证据逐步连接到同一个核心冲突。" * 5,
            "## 人物状态/关系变化",
            "- 队伍内部从迟疑转为协作。",
            "## 关键信息/设定",
            "- 证据链需要继续核验。",
            "## 结构功能/节奏",
            "- 本章把线索从分散状态推进为可追踪链条。",
        ]
    )

    event_summary = ChapterEventSummaryService(model_client=_EventSummaryModel()).summarize(
        book_id="book",
        document_title_index=3,
        chapter_title="第三章",
        summary_md=summary_md,
        chapter_summary_short="调查员接到新线索。",
        source_doc_range="10-11",
        chapter_event_list=[{"label": "线索串联", "summary": "调查员接到线索并串联前夜行动。"}],
    )

    assert event_summary.startswith("调查员接到线索后")
    assert "后续证据" in event_summary
    assert not event_summary.endswith("...")


def test_chapter_event_list_service_uses_summary_md_prompt_and_returns_events() -> None:
    class _EventListModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = fallback_factory, use_fallback_on_error
            assert "Chapter Event List Agent" in system_prompt
            assert "summary_md" in user_prompt
            assert "existing_timeline_events" in user_prompt
            return (
                {
                    "chapter_line": "[3] 第三章: 调查线索被重新串联。",
                    "timeline_events": [
                        {
                            "label": "线索重启",
                            "participants": ["调查员"],
                            "summary": "调查员接到新线索后重新梳理前夜行动顺序。",
                        },
                        {
                            "label": "证词确认",
                            "participants": ["同伴"],
                            "summary": "同伴补充关键证词，使队伍确认事件并非偶然。",
                        },
                    ],
                },
                "",
            )

    outline_update = ChapterEventListService(model_client=_EventListModel()).build_outline_update(
        book_id="book",
        document_title_index=3,
        chapter_title="第三章",
        summary_md="## 剧情事件链\n- 起点：调查员接到新线索。\n- 触发：同伴补充关键证词。",
        chapter_summary_short="调查线索被重新串联。",
        source_doc_range="10-11",
    )

    assert outline_update["chapter_line"] == "[3] 第三章: 调查线索被重新串联。"
    assert [event["label"] for event in outline_update["timeline_events"]] == ["线索重启", "证词确认"]
    assert outline_update["timeline_events"][0]["participants"] == ["调查员"]


def test_chapter_event_list_requires_model_client() -> None:
    with pytest.raises(RuntimeError, match="ChapterEventListService requires an available model_client"):
        ChapterEventListService(model_client=None).build_outline_update(
            book_id="book",
            document_title_index=3,
            chapter_title="第三章",
            summary_md=(
                "## 剧情事件链\n"
                "- 起点：调查员接到新线索，重新梳理前一晚的行动顺序。\n"
                "- 触发：同伴补充关键证词，使队伍确认事件并非偶然。"
            ),
            chapter_summary_short="调查线索被重新串联。",
        )


def test_close_read_generates_event_list_then_event_summary_from_summary_md() -> None:
    calls: list[str] = []

    class _EventModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = fallback_factory, use_fallback_on_error
            if "Chapter Event List Agent" in system_prompt:
                calls.append("event_list")
                assert "summary_md" in user_prompt
                return (
                    {
                        "chapter_line": "[3] 第三章: 调查线索被重新串联。",
                        "timeline_events": [
                            {
                                "label": "线索重启",
                                "participants": ["调查员"],
                                "summary": "调查员接到新线索后重新梳理前夜行动顺序。",
                            },
                            {
                                "label": "证词确认",
                                "participants": ["同伴"],
                                "summary": "同伴补充关键证词，使队伍确认事件并非偶然。",
                            },
                        ],
                    },
                    "",
                )
            if "Chapter Event Summary Agent" in system_prompt:
                calls.append("event_summary")
                assert "chapter_event_list" in user_prompt
                assert "线索重启" in user_prompt
                return (
                    {
                        "event_summary": "调查员接到新线索后重启前夜行动梳理，同伴证词进一步确认事件并非偶然。",
                        "compression_notes": "由事件列表压缩。",
                    },
                    "",
                )
            raise AssertionError(system_prompt)

    runner = object.__new__(CloseReadRunner)
    runner.config = SimpleNamespace(book_id="book")
    runner._emit_progress = lambda event: None  # noqa: SLF001
    batch = SimpleNamespace(
        document_title_index=3,
        chapter_title="第三章",
        title_indexes=[3],
        documents=[
            SimpleNamespace(doc_id=10, document_title_index=3),
            SimpleNamespace(doc_id=11, document_title_index=3),
        ],
        total_chars=2000,
    )
    summary_md = "## 剧情事件链\n- 起点：调查员接到新线索。\n- 触发：同伴补充关键证词。"

    outline_update = runner._generate_chapter_event_list(  # noqa: SLF001
        model_client=_EventModel(),
        batch=batch,
        summary_md=summary_md,
        summary_short="调查线索被重新串联。",
        outline_update={},
    )
    event_summary = runner._generate_chapter_event_summary(  # noqa: SLF001
        model_client=_EventModel(),
        batch=batch,
        summary_md=summary_md,
        summary_short="调查线索被重新串联。",
        outline_update=outline_update,
    )

    assert calls == ["event_list", "event_summary"]
    assert [event["label"] for event in outline_update["timeline_events"]] == ["线索重启", "证词确认"]
    assert event_summary.startswith("调查员接到新线索后")


def test_chapter_event_summary_requires_model_client() -> None:
    summary_md = "\n".join(
        [
            "## 剧情事件链",
            "- 起点：调查员接到新线索，重新梳理前一晚的行动顺序。",
            "- 触发：同伴补充关键证词，使队伍确认事件并非偶然。",
            "- 行动/冲突：" + "后续行动持续推进，新的证据逐步连接到同一个核心冲突。" * 5,
            "- 后续铺垫：队伍决定分头追踪证人与幕后联系人。",
            "## 人物状态/关系变化",
            "- 队伍内部从迟疑转为协作。",
        ]
    )

    with pytest.raises(RuntimeError, match="ChapterEventSummaryService requires an available model_client"):
        ChapterEventSummaryService(model_client=None).summarize(
            book_id="book",
            document_title_index=3,
            chapter_title="第三章",
            summary_md=summary_md,
            chapter_summary_short="调查员接到新线索...",
        )


def test_outline_service_keeps_split_batch_events_with_same_label(tmp_path: Path) -> None:
    service = OutlineService(repo_root=tmp_path)

    service.apply_update(
        book_id="book",
        chapter_line="[8] （八）: 长章节推进。",
        timeline_events=[
            {
                "label": "（八）剧情进展",
                "participants": ["强哥"],
                "summary": "前一批剧情推进。",
                "event_id": "chapter-8:event-01",
                "source_doc_ids": [67, 68, 69, 70],
                "source_doc_range": "67-70",
            }
        ],
    )
    outline_path = service.apply_update(
        book_id="book",
        chapter_line="[8] （八）: 长章节推进到后段。",
        timeline_events=[
            {
                "label": "（八）剧情进展",
                "participants": ["强哥"],
                "summary": "后一批剧情推进。",
                "event_id": "chapter-8:event-01",
                "source_doc_ids": [98, 99, 100, 101, 102],
                "source_doc_range": "98-102",
            }
        ],
    )

    outline_md = outline_path.read_text(encoding="utf-8")
    assert outline_md.count("（八）剧情进展") == 2
    assert "documents：67-70" in outline_md
    assert "documents：98-102" in outline_md


def test_close_read_merges_split_outline_updates_by_doc_range() -> None:
    runner = object.__new__(CloseReadRunner)

    merged = runner._merge_outline_updates(  # noqa: SLF001
        existing={
            "chapter_line": "[8] 旧章节线",
            "source_doc_ids": [67, 68, 69, 70],
            "source_title_indexes": [8],
            "timeline_events": [
                {
                    "label": "（八）剧情进展",
                    "participants": ["强哥"],
                    "summary": "前一批剧情推进。",
                    "event_id": "chapter-8:event-01",
                    "source_doc_ids": [67, 68, 69, 70],
                    "source_doc_range": "67-70",
                }
            ],
        },
        current={
            "chapter_line": "[8] 新章节线",
            "source_doc_ids": [98, 99, 100, 101, 102],
            "source_title_indexes": [8],
            "timeline_events": [
                {
                    "label": "（八）剧情进展",
                    "participants": ["强哥"],
                    "summary": "后一批剧情推进。",
                    "event_id": "chapter-8:event-01",
                    "source_doc_ids": [98, 99, 100, 101, 102],
                    "source_doc_range": "98-102",
                }
            ],
        },
    )

    assert merged["chapter_line"] == "[8] 新章节线"
    assert len(merged["timeline_events"]) == 2
    assert [event["source_doc_range"] for event in merged["timeline_events"]] == ["67-70", "98-102"]
    assert merged["source_doc_range"] == "67-102"


def test_complete_outline_merge_prefers_current_full_event_summary() -> None:
    runner = object.__new__(CloseReadRunner)
    full_event_summary = (
        "完整章节事件链从初始线索、调查推进、人物协作到冲突确认连续展开。"
        + "后续证据持续补足，使这一章的事件摘要不再依赖 timeline event 的短句。" * 4
    )

    merged = runner._merge_outline_updates(  # noqa: SLF001
        existing={
            "event_summary": "前一批拆分摘要。",
            "source_doc_ids": [1, 2],
            "source_title_indexes": [3],
            "timeline_events": [
                {
                    "label": "前批事件",
                    "summary": "前批短句。",
                    "source_doc_ids": [1, 2],
                    "source_doc_range": "1-2",
                }
            ],
        },
        current={
            "event_summary": full_event_summary,
            "source_doc_ids": [3, 4],
            "source_title_indexes": [3],
            "timeline_events": [
                {
                    "label": "后批事件",
                    "summary": "后批短句。",
                    "source_doc_ids": [3, 4],
                    "source_doc_range": "3-4",
                }
            ],
        },
        prefer_current_event_summary=True,
    )

    assert merged["event_summary"] == full_event_summary


def test_merged_chapter_summary_preserves_late_split_batches() -> None:
    runner = object.__new__(CloseReadRunner)
    batch = SimpleNamespace(
        document_title_index=8,
        is_split_batch=True,
        batch_label="拆批-93-97",
        batch_doc_count=5,
        total_chars=16000,
        chapter_doc_count=94,
    )
    summaries = [
        "\n".join(
            [
                "## 剧情事件链",
                f"- 第{index}批剧情：" + "甲" * 900,
                "## 人物状态/关系变化",
                f"- 第{index}批人物变化。",
                "## 关键信息/设定",
                f"- 第{index}批设定。",
                "## 结构功能/节奏",
                f"- 第{index}批结构功能。",
            ]
        )
        for index in range(1, 8)
    ]
    summaries.append(
        "\n".join(
            [
                "## 剧情事件链",
                "- 终局标记：最后一批剧情不能被头部截断吞掉。",
                "## 人物状态/关系变化",
                "- 最后一批人物关系落点。",
                "## 关键信息/设定",
                "- 最后一批设定回收。",
                "## 结构功能/节奏",
                "- 最后一批结构收束。",
            ]
        )
    )

    merged = runner._merge_intermediate_summaries(  # noqa: SLF001
        summaries=summaries,
        batch=batch,
        source_total_chars=335544,
    )

    assert "终局标记" in merged
    assert "章节总文档数：94" in merged
    assert len(merged) > 6000


def test_close_read_source_stats_are_derived_from_document_rows(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "source-stats.db")
    documents_repo = DocumentsRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        for index, content in enumerate(["甲" * 10, "乙" * 20, "丙" * 30], start=1):
            documents_repo.insert_document(
                conn,
                {
                    "path": f"doc-{index}.txt",
                    "scope": "chapter",
                    "title": "第八章",
                    "content": content,
                    "mtime": 0,
                    "size": len(content),
                    "content_sha256": f"sha-{index}",
                    "book_id": "book",
                    "source_path": "book.txt",
                    "source_file_name": "book.txt",
                    "source_start_offset": index * 100,
                    "source_end_offset": index * 100 + len(content),
                    "source_batch_no": index,
                    "document_title": "第八章",
                    "document_title_index": 8,
                    "inferred_chapter_no": 8,
                    "content_chars": len(content),
                    "character_keywords": [],
                    "content_tags": [],
                    "segmentation_notes": "",
                    "ingestion_run_id": "seed",
                    "created_at": "now",
                    "updated_at": "now",
                },
            )
        docs = documents_repo.fetch_by_title_index(conn, book_id="book", document_title_index=8)
        partial_batch = ChapterBatch(
            document_title_index=8,
            chapter_title="第八章",
            documents=[docs[1]],
            is_complete_chapter=False,
            chapter_doc_count=3,
            chapter_total_chars=60,
            batch_doc_start_index=2,
        )
        complete_batch = ChapterBatch(
            document_title_index=8,
            chapter_title="第八章",
            documents=[docs[2]],
            is_complete_chapter=True,
            chapter_doc_count=3,
            chapter_total_chars=60,
            batch_doc_start_index=3,
        )
        runner = object.__new__(CloseReadRunner)
        runner.config = SimpleNamespace(book_id="book")

        partial_stats = runner._processed_chapter_source_stats(  # noqa: SLF001
            conn=conn,
            documents_repo=documents_repo,
            batch=partial_batch,
        )
        complete_stats = runner._processed_chapter_source_stats(  # noqa: SLF001
            conn=conn,
            documents_repo=documents_repo,
            batch=complete_batch,
        )

    assert partial_stats == (1, 2, 2, 30)
    assert complete_stats == (1, 3, 3, 60)


def test_close_read_seeds_existing_summary_when_resuming_mid_chapter() -> None:
    runner = object.__new__(CloseReadRunner)
    batch = SimpleNamespace(
        documents=[
            SimpleNamespace(doc_id=20),
            SimpleNamespace(doc_id=21),
        ],
    )

    should_seed = runner._should_seed_existing_summary_intermediate(  # noqa: SLF001
        existing={
            "source_doc_start_id": 8,
            "source_doc_end_id": 19,
            "summary_md": "## 剧情事件链\n- 前半章摘要。",
        },
        batch=batch,
        summary_intermediate=[],
    )
    should_not_seed_completed = runner._should_seed_existing_summary_intermediate(  # noqa: SLF001
        existing={
            "source_doc_start_id": 8,
            "source_doc_end_id": 102,
            "summary_md": "## 剧情事件链\n- 已完整摘要。",
        },
        batch=batch,
        summary_intermediate=[],
    )

    assert should_seed is True
    assert should_not_seed_completed is False


def test_character_profile_story_events_are_person_scoped_and_indexed(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "profile-events.db")
    with db.connect() as conn:
        db.init_schema(conn)
        CharacterProfileService(profiles_repo=CharacterProfilesRepo()).merge_updates(
            conn,
            book_id="book",
            chapter_index=12,
            doc_ids=[48, 49],
            updates=[
                {
                    "canonical_name": "芬格尔",
                    "aliases": [],
                    "occupations": ["卡塞尔学院师兄"],
                    "relationships": [],
                }
            ],
            mentioned_doc_ids_by_name={"芬格尔": [48, 49]},
            speaking_doc_ids_by_name={"芬格尔": [48]},
            story_events_by_name={
                "芬格尔": [
                    {
                        "event_id": "chapter-12:event-01-fingel-sells-exam",
                        "label": "芬格尔兜售考题",
                        "summary": "芬格尔利用信息差向路明非兜售3E考试答案。",
                        "source_chapter_indexes": [12],
                        "source_doc_ids": [48, 49],
                        "source_doc_range": "48-49",
                        "participants": ["路明非", "芬格尔"],
                    }
                ]
            },
        )
        row = CharacterProfilesRepo().get(conn, book_id="book", canonical_name="芬格尔")

    assert row is not None
    story_events = json.loads(row["story_events_json"])
    assert story_events[0]["event_id"] == "chapter-12:event-01-fingel-sells-exam"
    assert story_events[0]["source_doc_ids"] == [48, 49]
    assert "## 基本属性/能力" in row["profile_summary_md"]
    assert "## 剧情时间线" in row["profile_summary_md"]
    assert "documents：48-49" in row["profile_summary_md"]


def test_outline_service_renders_timeline_event_source_indexes(tmp_path: Path) -> None:
    outline_path = OutlineService(repo_root=tmp_path).apply_update(
        book_id="book",
        chapter_line="[12] 第12章: 芬格尔兜售考题。",
        timeline_events=[
            {
                "event_id": "chapter-12:event-01-fingel-sells-exam",
                "label": "芬格尔兜售考题",
                "participants": ["路明非", "芬格尔"],
                "summary": "芬格尔利用信息差促成交易。",
                "source_doc_ids": [48, 49],
                "source_doc_range": "48-49",
            }
        ],
    )

    outline_md = outline_path.read_text(encoding="utf-8")
    assert "事件：chapter-12:event-01-fingel-sells-exam" in outline_md
    assert "documents：48-49" in outline_md


def test_outline_event_summary_compresses_prefix_and_keeps_unrelated_tail(tmp_path: Path) -> None:
    class _OutlineEventSummaryModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = system_prompt, user_prompt, fallback_factory, use_fallback_on_error
            return (
                {
                    "should_compress": True,
                    "summary_title": "事件1-7调查线推进",
                    "event_summary": "事件1至事件7连续推动同一条调查线。",
                    "tail_uncompressed_event_indexes": [8, 9],
                    "reason": "前七个事件属于同一调查线，末尾两个事件保留为近期上下文。",
                },
                "",
            )

    db = NovelAgentDB(tmp_path / "event-summary.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(conn, tmp_path, "book")
        for index in range(1, 10):
            payload = _chapter_payload(book_id="book", index=index, summary=f"事件{index}推进")
            payload["outline_update"] = {
                "chapter_line": f"[{index}] 第{index}章: 事件{index}推进",
                "timeline_events": [
                    {
                        "event_id": f"chapter-{index}:event-01",
                        "label": f"事件{index}",
                        "summary": f"事件{index}推动同一条调查线。",
                        "document_title_index": index,
                        "source_doc_ids": [index],
                        "source_doc_range": str(index),
                        "participants": ["沈青"],
                    }
                ],
            }
            ChaptersRepo().upsert(conn, payload)
        conn.commit()

        state = OutlineEventSummaryService(
            repo_root=tmp_path,
            model_client=_OutlineEventSummaryModel(),  # type: ignore[arg-type]
            min_uncompressed_events=4,
            fallback_tail_events=2,
        ).refresh(conn, book_id="book")
        packet = OutlineSeedPacketBuilder(repo_root=tmp_path).build(
            conn,
            book_id="book",
            intent=ContinuationIntent(desired_actions=["继续调查"]),
            mentions=ExtractedCharacterMentions(),
            resolutions=[],
        )

    assert state["segments"][0]["event_ids"] == [f"chapter-{index}:event-01" for index in range(1, 8)]
    assert state["pending_event_ids"] == ["chapter-8:event-01", "chapter-9:event-01"]
    assert state["segments"][0]["source_doc_range"] == "1-7"
    assert any(item.get("summary_level") == "event_group" for item in packet.historical_story_overview)
    assert packet.sources[-1].type == "event_summaries"


def test_summary_outline_commit_window_marks_target_range_committed(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "commit.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(conn, tmp_path, "book")
        for index in range(10, 21):
            summary = "日常关系铺垫。" if index < 14 else "调查线索推进并暴露新真相。"
            ChaptersRepo().upsert(conn, _chapter_payload(book_id="book", index=index, summary=summary))
        source_arc_payload = {
            "arcs": [
                {
                    "source_arc_id": "source-arc-001",
                    "start_document_title_index": 10,
                    "end_document_title_index": 20,
                    "source_arc_role": "主线推进",
                    "pacing_notes": "中速推进，后段信息密度上升。",
                    "chapter_role_map": [
                        {
                            "document_title_index": index,
                            "chapter_title": f"第{index}章",
                            "role": "设定揭示" if index in {16, 17} else "主线推进",
                            "reason": "窗口复核后确认结构功能。",
                        }
                        for index in range(10, 21)
                    ],
                }
            ]
        }

        result = SummaryOutlineCommitService(repo_root=tmp_path, now_factory=lambda: "now").commit_window(
            conn,
            book_id="book",
            evidence_window=(10, 20),
            target_range=(14, 18),
            source_arc_payload=source_arc_payload,
        )
        rows = [ChaptersRepo().get(conn, book_id="book", document_title_index=index) for index in range(14, 19)]

    assert result.success
    assert result.committed_title_indexes == [14, 15, 16, 17, 18]
    assert all(row is not None and row["summary_status"] == "committed" for row in rows)
    assert all(row is not None and row["summary_evidence_window"] == "10-20" for row in rows)
    assert all(row is not None and row["summary_target_range"] == "14-18" for row in rows)
    assert "状态：committed" in str(rows[0]["summary_md"])
    outline_update = json.loads(rows[2]["outline_update_json"])
    assert outline_update["chapter_line"] != "[16] 第16章: 调查线索推进并暴露新真相。"
    assert "篇章功能=设定揭示" in outline_update["chapter_line"]


def test_context_assembly_marks_mixed_status_and_falls_back_to_provisional(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "context.db")
    repo = ChaptersRepo()
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(conn, tmp_path, "book")
        repo.upsert(conn, _chapter_payload(book_id="book", index=1, summary="第一章暂定摘要"))
        repo.upsert(
            conn,
            {
                **_chapter_payload(book_id="book", index=2, summary="第二章定稿摘要"),
                "summary_status": "committed",
                "summary_evidence_window": "1-3",
                "summary_target_range": "2-2",
                "outline_update": {"chapter_line": "[2] 第2章: 第二章定稿大纲", "timeline_events": []},
                "outline_status": "committed",
                "outline_evidence_window": "1-3",
                "outline_target_range": "2-2",
            },
        )

        payload = ContextAssemblyService.build_default(repo_root=tmp_path).assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book",
                document_title_index="2",
                token_budget=MemoryAssemblyBudget(chapter_context_chars=2000, story_outline_chars=2000),
            ),
        )

    assert payload.memory_status["chapter_context"] == "mixed"
    assert payload.memory_status["story_outline"] == "mixed"
    assert {item.summary_status for item in payload.chapter_context} == {"provisional", "committed"}
    assert "status=provisional" in payload.story_outline_md
    assert "status=committed" in payload.story_outline_md


def test_source_arc_map_committed_structure_enters_context_and_can_reverse_commit(tmp_path: Path) -> None:
    class _SourceArcModel:
        settings = SimpleNamespace(dry_run=False)

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = system_prompt, user_prompt, fallback_factory, use_fallback_on_error
            return (
                {
                    "arcs": [
                        {
                            "source_arc_id": "source-arc-0001",
                            "source_arc_title": "关系铺垫到规则揭示",
                            "start_document_title_index": 1,
                            "end_document_title_index": 4,
                            "source_arc_role": "主线推进",
                            "core_events": ["前半段关系铺垫，后半段世界规则被进一步揭示。"],
                            "main_character_threads": [],
                            "world_or_rule_reveals": ["世界规则与能力体系被进一步揭示。"],
                            "transition_from_previous": "当前已读范围起点",
                            "setup_for_next": "后续继续处理规则影响。",
                            "pacing_notes": "四个 chapter 从日常铺垫转入规则揭示。",
                            "chapter_role_map": [
                                {
                                    "document_title_index": 1,
                                    "chapter_title": "第1章",
                                    "role": "日常关系",
                                    "reason": "人物日常对话和关系铺垫。",
                                },
                                {
                                    "document_title_index": 2,
                                    "chapter_title": "第2章",
                                    "role": "日常关系",
                                    "reason": "人物日常对话和关系铺垫。",
                                },
                                {
                                    "document_title_index": 3,
                                    "chapter_title": "第3章",
                                    "role": "设定揭示",
                                    "reason": "世界规则与能力体系被进一步揭示。",
                                },
                                {
                                    "document_title_index": 4,
                                    "chapter_title": "第4章",
                                    "role": "设定揭示",
                                    "reason": "世界规则与能力体系被进一步揭示。",
                                },
                            ],
                        }
                    ]
                },
                "",
            )

    db = NovelAgentDB(tmp_path / "source_arc.db")
    with db.connect() as conn:
        db.init_schema(conn)
        _seed_assets(conn, tmp_path, "book")
        for index in range(1, 5):
            summary = "世界规则与能力体系被进一步揭示。" if index >= 3 else "人物日常对话和关系铺垫。"
            ChaptersRepo().upsert(conn, _chapter_payload(book_id="book", index=index, summary=summary))
        source_arc_service = SourceArcMappingService(
            repo_root=tmp_path,
            model_client=_SourceArcModel(),  # type: ignore[arg-type]
            now_factory=lambda: "now",
        )
        source_arc_map = source_arc_service.build_from_chapters(conn, book_id="book")

        commit_result = SummaryOutlineCommitService(repo_root=tmp_path, now_factory=lambda: "now").commit_from_source_arc_map(
            conn,
            book_id="book",
            source_arc_payload=source_arc_map.to_dict(),
        )
        row = ChaptersRepo().get(conn, book_id="book", document_title_index=3)
        payload = ContextAssemblyService.build_default(repo_root=tmp_path).assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id="book",
                document_title_index="3",
                token_budget=MemoryAssemblyBudget(source_arc_context_chars=2000),
            ),
        )

    assert commit_result.success
    assert row is not None
    assert row["summary_status"] == "committed"
    assert payload.source_arc_context
    assert payload.source_arc_context[0].status == "committed"
    assert payload.memory_status["source_arc_context"] == "committed"


def _seed_assets(conn, repo_root: Path, book_id: str) -> None:
    world_path, world_summary_path = WorldStateService(repo_root=repo_root).ensure_paths(book_id)
    world_summary_path.write_text("世界观概要：现代都市。", encoding="utf-8")
    outline_path = OutlineService(repo_root=repo_root).ensure_path(book_id)
    AssetsRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "source_root": str(repo_root),
            "world_markdown_path": str(world_path),
            "world_summary_path": str(world_summary_path),
            "outline_markdown_path": str(outline_path),
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _chapter_payload(*, book_id: str, index: int, summary: str) -> dict[str, object]:
    return {
        "book_id": book_id,
        "document_title_index": index,
        "chapter_title": f"第{index}章",
        "source_doc_start_id": index,
        "source_doc_end_id": index,
        "source_doc_count": 1,
        "source_total_chars": 100,
        "summary_intermediate": [],
        "summary_md": (
            "## 剧情事件链\n"
            f"- {summary}\n\n"
            "## 人物状态/关系变化\n"
            "- 人物关系继续推进。\n\n"
            "## 关键信息/设定\n"
            "- 关键信息继续积累。\n\n"
            "## 结构功能/节奏\n"
            "- 即时 close-read 暂定判断。\n"
        ),
        "summary_short": summary,
        "importance_score": 60,
        "importance_reason": "seed",
        "related_chapters": [],
        "mentioned_characters": ["林清"],
        "world_update": {},
        "outline_update": {"chapter_line": f"[{index}] 第{index}章: {summary}", "timeline_events": []},
        "close_read_run_id": "seed",
        "created_at": "now",
        "updated_at": "now",
    }
