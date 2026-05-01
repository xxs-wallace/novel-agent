from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from novel_agent.app.llm import InvalidJSONResponseError, JsonModelClient
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentRow, DocumentsRepo
from novel_agent.app.prompts.chapter_summary_prompt import build_chapter_summary_prompt
from novel_agent.app.runner.close_read_runner import CloseReadRunner, InvalidChapterSynopsisError
from novel_agent.app.schemas.config_schema import CloseReadAgentConfig
from novel_agent.app.services.chapter_assembler_service import ChapterBatch


def _insert_document(
    conn: sqlite3.Connection,
    *,
    doc_id: int,
    book_id: str,
    title_index: int,
    title: str,
    content: str,
) -> None:
    DocumentsRepo().insert_document(
        conn,
        {
            "path": f"{title_index:03d}.md",
            "scope": "novel",
            "title": title,
            "content": content,
            "mtime": 0,
            "size": len(content.encode("utf-8")),
            "content_sha256": f"sha-{doc_id}",
            "book_id": book_id,
            "source_path": f"{title_index:03d}.md",
            "source_file_name": f"{title_index:03d}.md",
            "source_start_offset": (doc_id - 1) * 1000,
            "source_end_offset": doc_id * 1000,
            "source_batch_no": 1,
            "document_title": title,
            "document_title_index": title_index,
            "inferred_chapter_no": title_index,
            "content_chars": len(content),
            "character_keywords": [],
            "content_tags": ["校园"],
            "segmentation_notes": "",
            "ingestion_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _make_document_row(
    *,
    doc_id: int,
    book_id: str,
    title_index: int,
    title: str,
    content: str,
) -> DocumentRow:
    return DocumentRow(
        doc_id=doc_id,
        book_id=book_id,
        path=f"{title_index:03d}.md",
        scope="novel",
        title=title,
        document_title=title,
        document_title_index=title_index,
        inferred_chapter_no=title_index,
        content=content,
        content_chars=len(content),
        character_keywords=[],
        content_tags=[],
        source_path=f"{title_index:03d}.md",
        source_file_name=f"{title_index:03d}.md",
        source_start_offset=(doc_id - 1) * 1000,
        source_end_offset=doc_id * 1000,
    )


def _plot_synopsis(
    plot: str,
    *,
    characters: str = "人物围绕本批次事件产生行动、情绪或关系变化。",
    info: str = "本批次保留影响后续理解的关键信息。",
    structure: str = "本批次承担剧情推进与后续铺垫功能。",
) -> str:
    return (
        "## 剧情事件链\n"
        f"- {plot}\n\n"
        "## 人物状态/关系变化\n"
        f"- {characters}\n\n"
        "## 关键信息/设定\n"
        f"- {info}\n\n"
        "## 结构功能/节奏\n"
        f"- {structure}\n"
    )


def test_close_read_runner_retries_with_smaller_batch_after_invalid_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "close_read_retry.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(
            conn,
            doc_id=1,
            book_id="close_retry_book",
            title_index=1,
            title="第一章",
            content="第一段标记。" + "路明非看着雨幕里的校园。" * 8,
        )
        _insert_document(
            conn,
            doc_id=2,
            book_id="close_retry_book",
            title_index=1,
            title="第一章",
            content="第二段标记。" + "楚子航沉默地站着。" * 8,
        )
        conn.commit()

    def fake_generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = self, system_prompt, use_fallback_on_error
        if "第一段标记" in user_prompt and "第二段标记" in user_prompt:
            raise InvalidJSONResponseError(raw_text="not-json", attempts=3)
        if "Reading Agent" in system_prompt:
            return (
                {
                    "summary_quality": "plot_synopsis",
                    "chapter_summary_md": _plot_synopsis(
                        "路明非在雨幕中的校园场景里被推入开场处境，章节先建立地点氛围，再把人物行动和悬念压缩为后续精读可承接的事件线。",
                        characters="路明非作为当前批次核心人物出现，行动状态从旁观转向进入校园。",
                        info="校园与雨幕共同提供开场背景，没有把原文句子作为梗概主体。",
                        structure="重试后的单文档批次承担开场铺垫功能。",
                    ),
                    "chapter_summary_short": "路明非进入雨幕中的校园，开场悬念被建立。",
                    "importance_score": 55,
                    "importance_reason": "开场建立人物与场景。",
                    "related_chapters": [],
                    "world_signal_score": 0,
                    "world_evidence_candidates": [],
                    "noise_documents": [],
                },
                "",
            )
        return fallback_factory(), ""

    monkeypatch.setattr(JsonModelClient, "generate_json", fake_generate_json)

    config = CloseReadAgentConfig(book_id="close_retry_book", sqlite_path=str(db_path))
    config.runtime.dry_run = True
    config.runtime.max_chapters = 1
    config.runtime.export_debug_markdown = False
    config.runtime.document_chars_budget = 20_000

    result = CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=config).run()

    assert result.processed_batches == 1

    with sqlite3.connect(db_path) as conn:
        progress_row = conn.execute(
            """
            SELECT last_completed_doc_id
            FROM reading_progress
            WHERE book_id = 'close_retry_book' AND agent_stage = 'close_reading'
            """
        ).fetchone()
        chapter_row = conn.execute(
            """
            SELECT source_doc_start_id, source_doc_end_id, source_doc_count
            FROM chapters
            WHERE book_id = 'close_retry_book' AND document_title_index = 1
            """
        ).fetchone()

    assert progress_row is not None
    assert progress_row[0] == 1
    assert chapter_row is not None
    assert chapter_row[0] == 1
    assert chapter_row[1] == 1
    assert chapter_row[2] == 1


def test_close_read_runner_persists_multi_chapter_batch_without_schema_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "close_read_multi.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(
            conn,
            doc_id=1,
            book_id="multi_chapter_book",
            title_index=1,
            title="第一章",
            content="第一章标记。" + "路明非进入校园。" * 6,
        )
        _insert_document(
            conn,
            doc_id=2,
            book_id="multi_chapter_book",
            title_index=2,
            title="第二章",
            content="第二章标记。" + "楚子航提到龙族。" * 6,
        )
        conn.commit()

    long_summary = "剧情推进充分，人物关系和设定变化被清晰保留。" * 20

    def fake_generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = self, system_prompt, user_prompt, fallback_factory, use_fallback_on_error
        return (
            {
                "chapter_summary_md": long_summary,
                "chapter_summary_short": "两章连续推进。",
                "importance_score": 70,
                "importance_reason": "连续推进主线。",
                "related_chapters": [],
                "document_character_mentions": [
                    {
                        "doc_id": 1,
                        "character_keywords": ["路明非"],
                        "speaking_character_keywords": ["路明非"],
                        "character_evidence": {"路明非": ["路明非进入校园"]},
                        "speaking_evidence": {"路明非": ["路明非进入校园"]},
                    },
                    {
                        "doc_id": 2,
                        "character_keywords": ["楚子航"],
                        "speaking_character_keywords": ["楚子航"],
                        "character_evidence": {"楚子航": ["楚子航提到龙族"]},
                        "speaking_evidence": {"楚子航": ["楚子航提到龙族"]},
                    },
                ],
                "world_update": {"should_update": False, "changes": []},
                "character_updates": [],
                "outline_update": {"chapter_line": "[1-2] 连续推进。", "timeline_events": []},
                "chapter_summaries": [
                    {
                        "document_title_index": 1,
                        "chapter_title": "第一章",
                        "chapter_summary_md": "路明非进入校园，第一章建立场景。" * 12,
                        "chapter_summary_short": "路明非进入校园。",
                        "importance_score": 60,
                        "importance_reason": "建立场景。",
                        "related_chapters": [],
                        "world_update": {"should_update": False, "changes": []},
                        "outline_update": {"chapter_line": "[1] 第一章: 路明非进入校园。", "timeline_events": []},
                    },
                    {
                        "document_title_index": 2,
                        "chapter_title": "第二章",
                        "chapter_summary_md": "楚子航提到龙族，第二章推进设定。" * 12,
                        "chapter_summary_short": "楚子航提到龙族。",
                        "importance_score": 65,
                        "importance_reason": "推进设定。",
                        "related_chapters": [],
                        "world_update": {"should_update": False, "changes": []},
                        "outline_update": {"chapter_line": "[2] 第二章: 楚子航提到龙族。", "timeline_events": []},
                    },
                ],
            },
            "",
        )

    monkeypatch.setattr(JsonModelClient, "generate_json", fake_generate_json)

    config = CloseReadAgentConfig(book_id="multi_chapter_book", sqlite_path=str(db_path))
    config.runtime.dry_run = True
    config.runtime.max_chapters = 1
    config.runtime.export_debug_markdown = False
    config.runtime.document_chars_budget = 20_000

    result = CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=config).run()

    assert result.processed_batches == 1
    assert result.batch_metrics[0]["doc_count"] == 2
    assert result.batch_metrics[0]["document_title_indexes"] == [1, 2]

    with sqlite3.connect(db_path) as conn:
        chapter_rows = conn.execute(
            """
            SELECT document_title_index, source_doc_start_id, source_doc_end_id, source_doc_count, summary_short
            FROM chapters
            WHERE book_id = 'multi_chapter_book'
            ORDER BY document_title_index
            """
        ).fetchall()
        progress_row = conn.execute(
            """
            SELECT last_completed_doc_id, last_completed_title_index
            FROM reading_progress
            WHERE book_id = 'multi_chapter_book' AND agent_stage = 'close_reading'
            """
        ).fetchone()
        profile_rows = conn.execute(
            """
            SELECT canonical_name, mentioned_doc_ids_json, speaking_doc_ids_json, profile_summary_md
            FROM character_profiles
            WHERE book_id = 'multi_chapter_book'
            ORDER BY canonical_name
            """
        ).fetchall()

    assert [(row[0], row[1], row[2], row[3]) for row in chapter_rows] == [(1, 1, 1, 1), (2, 2, 2, 1)]
    assert "路明非" in chapter_rows[0][4]
    assert "楚子航" in chapter_rows[1][4]
    assert progress_row == (2, 2)
    assert [(row[0], row[1], row[2]) for row in profile_rows] == [
        ("楚子航", "[2]", "[2]"),
        ("路明非", "[1]", "[1]"),
    ]
    assert "发言 documents" in profile_rows[0][3]


def test_close_read_runner_resumes_split_chapter_and_merges_intermediate_summaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "close_read_resume.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(
            conn,
            doc_id=1,
            book_id="resume_split_book",
            title_index=1,
            title="第一章",
            content="第一批标记。" + "路明非在雨夜里踏入校门。" * 10,
        )
        _insert_document(
            conn,
            doc_id=2,
            book_id="resume_split_book",
            title_index=1,
            title="第一章",
            content="第二批标记。" + "楚子航说明龙族相关真相。" * 10,
        )
        conn.commit()

    def fake_generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = self, system_prompt, fallback_factory, use_fallback_on_error
        if "第一批标记" in user_prompt:
            return (
                {
                    "chapter_summary_md": "路明非在雨夜进入校园，异常氛围持续堆积。",
                    "chapter_summary_short": "路明非进入校园。",
                    "importance_score": 55,
                    "importance_reason": "开场建立悬念。",
                    "related_chapters": [{"document_title_index": 2, "score": 60, "reason": "后续承接"}],
                    "document_character_mentions": [
                        {
                            "doc_id": 1,
                            "character_keywords": ["路明非"],
                            "character_evidence": {"路明非": ["路明非在雨夜里踏入校门"]},
                        }
                    ],
                    "world_update": {"should_update": False, "changes": []},
                    "character_updates": [],
                    "outline_update": {"chapter_line": "[1] 第一章: 路明非进入校园。", "timeline_events": []},
                },
                "",
            )
        return (
            {
                "chapter_summary_md": "楚子航补充说明龙族真相，章节核心冲突被正式点明。",
                "chapter_summary_short": "楚子航揭示真相。",
                "importance_score": 88,
                "importance_reason": "关键设定曝光。",
                "related_chapters": [{"document_title_index": 3, "score": 80, "reason": "主线推进"}],
                "document_character_mentions": [
                    {
                        "doc_id": 2,
                        "character_keywords": ["楚子航"],
                        "character_evidence": {"楚子航": ["楚子航说明龙族相关真相"]},
                    }
                ],
                "world_update": {"should_update": True, "changes": [{"section": "能力体系", "summary": "龙族真相被直接提及", "evidence": "龙族"}]},
                "character_updates": [],
                "outline_update": {"chapter_line": "[1] 第一章: 楚子航揭示龙族真相。", "timeline_events": []},
            },
            "",
        )

    monkeypatch.setattr(JsonModelClient, "generate_json", fake_generate_json)

    config = CloseReadAgentConfig(book_id="resume_split_book", sqlite_path=str(db_path))
    config.runtime.dry_run = True
    config.runtime.max_chapters = 1
    config.runtime.export_debug_markdown = False
    config.runtime.document_chars_budget = 160

    first_result = CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=config).run()
    assert first_result.processed_batches == 1

    with sqlite3.connect(db_path) as conn:
        first_row = conn.execute(
            """
            SELECT summary_intermediate_json, summary_md, summary_short, source_doc_count, source_total_chars
            FROM chapters
            WHERE book_id = 'resume_split_book' AND document_title_index = 1
            """
        ).fetchone()
        first_progress = conn.execute(
            """
            SELECT last_completed_doc_id, checkpoint_token
            FROM reading_progress
            WHERE book_id = 'resume_split_book' AND agent_stage = 'close_reading'
            """
        ).fetchone()

    assert first_row is not None
    assert first_row[1] == ""
    assert "## 摘要元信息" in json.loads(first_row[0])[0]
    assert first_row[3] == 1
    assert first_progress is not None
    assert first_progress[0] == 1
    assert first_progress[1] == "1:1"

    second_result = CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=config).run()
    assert second_result.processed_batches == 1

    with sqlite3.connect(db_path) as conn:
        final_row = conn.execute(
            """
            SELECT summary_intermediate_json, summary_md, summary_short, source_doc_count, source_total_chars,
                   importance_score, related_chapters_json, mentioned_characters_json
            FROM chapters
            WHERE book_id = 'resume_split_book' AND document_title_index = 1
            """
        ).fetchone()
        final_progress = conn.execute(
            """
            SELECT last_completed_doc_id, checkpoint_token
            FROM reading_progress
            WHERE book_id = 'resume_split_book' AND agent_stage = 'close_reading'
            """
        ).fetchone()

    assert final_row is not None
    assert final_row[0] == "[]"
    assert "## 摘要元信息" in final_row[1]
    assert "## 剧情推进" in final_row[1]
    assert "## 人物状态/关系变化" in final_row[1]
    assert "## 关键信息/设定" in final_row[1]
    assert "汇总批次数：2" in final_row[1]
    assert final_row[2]
    assert final_row[3] == 2
    assert final_row[4] > 200
    assert final_row[5] == 88
    assert "路明非" in final_row[7]
    assert "楚子航" in final_row[7]
    assert "document_title_index" in final_row[6]
    assert final_progress is not None
    assert final_progress[0] == 2
    assert final_progress[1] == "1:2"


def test_close_read_runner_fills_missing_multi_chapter_summary_item_in_non_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "close_read_partial_multi.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(
            conn,
            doc_id=1,
            book_id="partial_multi_book",
            title_index=1,
            title="第一章",
            content="第一章标记。" + "路明非进入学院并作出回应。" * 12,
        )
        _insert_document(
            conn,
            doc_id=2,
            book_id="partial_multi_book",
            title_index=2,
            title="第二章",
            content="第二章标记。" + "楚子航说明龙族相关真相。" * 12,
        )
        conn.commit()

    long_summary = "路明非进入学院，章节保留了行动、关系和设定变化。" * 20

    def fake_generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = self, user_prompt, fallback_factory, use_fallback_on_error
        if "Reading Agent" in system_prompt:
            return (
                {
                    "chapter_summary_md": long_summary,
                    "chapter_summary_short": "两章连续推进。",
                    "importance_score": 70,
                    "importance_reason": "连续推进主线。",
                    "related_chapters": [],
                    "chapter_summaries": [
                        {
                            "document_title_index": 1,
                            "chapter_title": "第一章",
                            "chapter_summary_md": "路明非进入学院并作出回应，第一章完成入场。" * 12,
                            "chapter_summary_short": "路明非进入学院。",
                            "importance_score": 60,
                            "importance_reason": "人物入场。",
                            "related_chapters": [],
                        }
                    ],
                },
                "",
            )
        if "Character Evidence Agent" in system_prompt:
            return {"character_evidence_batch_id": "partial_multi_book:character-evidence:1-2", "characters": []}, ""
        return {"character_updates": [], "world_update": {"should_update": False, "changes": []}, "outline_update": {"chapter_line": "[1-2] 连续推进。", "timeline_events": []}}, ""

    monkeypatch.setattr(JsonModelClient, "generate_json", fake_generate_json)
    monkeypatch.setattr(JsonModelClient, "generate_text", lambda self, **kwargs: kwargs["fallback_text"])

    config = CloseReadAgentConfig(book_id="partial_multi_book", sqlite_path=str(db_path))
    config.runtime.dry_run = False
    config.runtime.max_chapters = 1
    config.runtime.export_debug_markdown = False
    config.runtime.document_chars_budget = 20_000

    result = CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=config).run()

    assert result.processed_batches == 1
    with sqlite3.connect(db_path) as conn:
        chapter_rows = conn.execute(
            """
            SELECT document_title_index, summary_short
            FROM chapters
            WHERE book_id = 'partial_multi_book'
            ORDER BY document_title_index
            """
        ).fetchall()

    assert [row[0] for row in chapter_rows] == [1, 2]
    assert "路明非" in chapter_rows[0][1]
    assert "楚子航" in chapter_rows[1][1]


def test_payload_for_title_index_uses_summary_fallback_when_chapter_summaries_item_is_missing(
    tmp_path: Path,
) -> None:
    config = CloseReadAgentConfig(book_id="helper_book", sqlite_path=str(tmp_path / "helper.db"))
    config.runtime.dry_run = False
    runner = CloseReadRunner(repo_root=tmp_path, db_path=tmp_path / "helper.db", config=config)
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="第一章",
        documents=[
            _make_document_row(
                doc_id=1,
                book_id="helper_book",
                title_index=1,
                title="第一章",
                content="路明非进入学院。" * 20,
            ),
            _make_document_row(
                doc_id=2,
                book_id="helper_book",
                title_index=2,
                title="第二章",
                content="楚子航说明龙族真相。" * 20,
            ),
        ],
    )
    sub_batch = batch.as_single_title_batch(2)

    payload = runner._payload_for_title_index(
        sub_batch=sub_batch,
        payload={
            "chapter_summaries": [{"document_title_index": 1, "chapter_summary_short": "第一章摘要。"}],
            "document_character_mentions": [],
            "character_updates": [],
            "world_update": {"should_update": False, "changes": []},
            "outline_update": {"chapter_line": "", "timeline_events": []},
        },
        chapter_payload=None,
    )

    assert "楚子航" in payload["chapter_summary_short"]
    assert payload["document_character_mentions"] == []
    assert payload["character_updates"] == []
