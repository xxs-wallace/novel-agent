from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from novel_agent.app.llm import InvalidJSONResponseError, JsonModelClient
from novel_agent.app.prompts.chapter_summary_prompt import build_chapter_summary_prompt
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentRow, DocumentsRepo
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


def test_close_read_runner_augments_partial_character_updates_from_source_verified_names(tmp_path: Path) -> None:
    config = CloseReadAgentConfig(book_id="book-augment", sqlite_path=str(tmp_path / "augment.db"))
    runner = CloseReadRunner(repo_root=tmp_path, db_path=tmp_path / "augment.db", config=config)

    updates = runner._augment_character_updates_from_source_verified_names(
        raw_character_updates=[
            {
                "canonical_name": "路明非",
                "aliases": [],
                "recent_activity": "路明非回应邀请。",
                "relationships": [],
            }
        ],
        source_verified_names=["路明非", "诺诺"],
        summary_short="路明非和诺诺完成对话。",
    )

    assert [item["canonical_name"] for item in updates] == ["路明非", "诺诺"]
    assert updates[1]["recent_activity"] == "路明非和诺诺完成对话。"
    assert updates[1]["evidence_level"] == "inferred"


def test_character_evidence_agent_reruns_with_full_roster_on_request(tmp_path: Path) -> None:
    config = CloseReadAgentConfig(book_id="book-roster-loop", sqlite_path=str(tmp_path / "roster_loop.db"))
    runner = CloseReadRunner(repo_root=tmp_path, db_path=tmp_path / "roster_loop.db", config=config)
    doc = _make_document_row(
        doc_id=1,
        book_id="book-roster-loop",
        title_index=1,
        title="第一章",
        content="远期人物重新出现并开口说话。",
    )
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="第一章",
        documents=[doc],
        chapter_doc_count=1,
        chapter_total_chars=doc.content_chars,
    )

    class _RosterLoopModel:
        def __init__(self) -> None:
            self.scopes: list[str] = []

        def generate_json(self, *, system_prompt, user_prompt, fallback_factory, use_fallback_on_error=False):  # type: ignore[no-untyped-def]
            _ = system_prompt, fallback_factory, use_fallback_on_error
            payload = json.loads(str(user_prompt).split("输入数据如下：\n", 1)[1])
            batch_payload = payload["character_evidence_batch"]
            self.scopes.append(batch_payload["character_roster_scope"])
            if batch_payload["character_roster_scope"] == "recent_32":
                assert len(batch_payload["existing_character_roster"]) == 1
                return (
                    {
                        "doc_id": 1,
                        "document_title_index": 1,
                        "request_full_roster": True,
                        "request_full_roster_reason": "正文出现不在最近名册中的疑似旧人物。",
                        "characters": [],
                    },
                    "",
                )
            assert len(batch_payload["existing_character_roster"]) == 2
            return (
                {
                    "doc_id": 1,
                    "document_title_index": 1,
                    "request_full_roster": False,
                    "request_full_roster_reason": "",
                    "characters": [
                        {
                            "canonical_name": "远期人物",
                            "aliases": [],
                            "is_speaking_character": True,
                            "speaking_evidence": "远期人物开口说话。",
                            "personhood_evidence": "在完整名册中确认该人物。",
                            "activity_or_state_evidence": "重新出现。",
                            "relationship_evidence": "",
                            "source_doc_ids": [1],
                            "source_title_indexes": [1],
                            "candidate_type": "character",
                            "confidence": 0.9,
                            "uncertainty_reason": "",
                        }
                    ],
                },
                "",
            )

    model = _RosterLoopModel()
    payload = runner._generate_character_evidence_payload(  # noqa: SLF001
        model_client=model,  # type: ignore[arg-type]
        batch=batch,
        prompt_input={
            "book_id": "book-roster-loop",
            "world_summary_md": "",
            "story_outline_md": "",
            "existing_character_roster": [{"canonical_name": "最近人物"}],
            "full_existing_character_roster": [{"canonical_name": "最近人物"}, {"canonical_name": "远期人物"}],
        },
    )

    assert model.scopes == ["recent_32", "full"]
    assert payload["characters"][0]["canonical_name"] == "远期人物"


def test_close_read_coverage_audit_adds_model_detected_missing_character(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "coverage_audit.db"
    db = NovelAgentDB(db_path)
    with db.connect() as conn:
        db.init_schema(conn)
        _insert_document(
            conn,
            doc_id=1,
            book_id="coverage-book",
            title_index=1,
            title="第一章",
            content="林初推门进来。周衡站起身说：“我等你很久了。”周衡随后带她去旧剧院。",
        )
        conn.commit()

    calls: list[str] = []

    def fake_generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = self, user_prompt, use_fallback_on_error
        if "Character Evidence Coverage Agent" in system_prompt:
            calls.append("coverage")
            return (
                {
                    "coverage_gap_found": True,
                    "coverage_notes": "第一轮人物证据漏掉了一个有明确发言和行动的人物。",
                    "characters": [
                        {
                            "canonical_name": "周衡",
                            "aliases": [],
                            "is_speaking_character": True,
                            "speaking_evidence": "周衡站起身说他等了很久。",
                            "personhood_evidence": "周衡被姓名指称并明确发言。",
                            "activity_or_state_evidence": "周衡与林初会面并带她前往旧剧院。",
                            "relationship_evidence": "周衡与林初发生直接对话和同行。",
                            "source_doc_ids": [1],
                            "source_title_indexes": [1],
                            "candidate_type": "character",
                            "confidence": 0.93,
                            "uncertainty_reason": "",
                        }
                    ],
                },
                "",
            )
        if "Character Evidence Agent" in system_prompt:
            calls.append("evidence")
            return (
                {
                    "doc_id": 1,
                    "document_title_index": 1,
                    "request_full_roster": False,
                    "request_full_roster_reason": "",
                    "characters": [
                        {
                            "canonical_name": "林初",
                            "aliases": [],
                            "is_speaking_character": False,
                            "speaking_evidence": "",
                            "personhood_evidence": "林初被姓名指称并进入场景。",
                            "activity_or_state_evidence": "林初推门进来。",
                            "relationship_evidence": "林初与周衡会面。",
                            "source_doc_ids": [1],
                            "source_title_indexes": [1],
                            "candidate_type": "character",
                            "confidence": 0.9,
                            "uncertainty_reason": "",
                        }
                    ],
                },
                "",
            )
        if "Chapter Event List Agent" in system_prompt:
            return (
                {
                    "chapter_line": "[1] 第一章: 林初与周衡会面。",
                    "timeline_events": [
                        {
                            "label": "会面",
                            "participants": ["林初", "周衡"],
                            "summary": "林初进入场景后与周衡会面，周衡带她前往旧剧院。",
                        }
                    ],
                },
                "",
            )
        if "Chapter Event Summary Agent" in system_prompt:
            return {"event_summary": "林初与周衡会面，周衡随后带她去旧剧院。", "compression_notes": ""}, ""
        if (
            "Character Reduce Agent" in system_prompt
            or "Global Memory Agent" in system_prompt
            or "Character Identity Resolution Agent" in system_prompt
            or "Character Canonical Name Agent" in system_prompt
        ):
            return fallback_factory(), ""
        return (
            {
                "summary_quality": "plot_synopsis",
                "chapter_summary_md": _plot_synopsis(
                    "林初进入场景，与周衡会面；周衡明确发言并带她前往旧剧院。",
                    characters="林初进入场景；周衡从等待者转为行动者，并与林初建立直接互动。",
                ),
                "chapter_summary_short": "林初与周衡会面，周衡带她去旧剧院。",
                "importance_score": 70,
                "importance_reason": "新人物行动和关系明确。",
                "related_chapters": [],
                "world_signal_score": 0,
                "world_evidence_candidates": [],
            },
            "",
        )

    monkeypatch.setattr(JsonModelClient, "generate_json", fake_generate_json)

    config = CloseReadAgentConfig(book_id="coverage-book", sqlite_path=str(db_path))
    config.runtime.dry_run = True
    config.runtime.max_chapters = 1
    config.runtime.export_debug_markdown = False

    result = CloseReadRunner(repo_root=tmp_path, db_path=db_path, config=config).run()

    assert result.processed_batches == 1
    assert calls[:2] == ["evidence", "coverage"]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        profile_names = [
            row["canonical_name"]
            for row in conn.execute(
                "SELECT canonical_name FROM character_profiles WHERE book_id = ? ORDER BY canonical_name",
                ("coverage-book",),
            ).fetchall()
        ]
        doc_keywords = conn.execute(
            "SELECT character_keywords_json FROM documents WHERE book_id = ?",
            ("coverage-book",),
        ).fetchone()[0]

    assert profile_names == ["周衡", "林初"]
    assert "周衡" in doc_keywords
    assert "林初" in doc_keywords


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
                        "路明非在雨幕中的校园场景里被推入开场处境，章节先建立地点氛围，再把人物行动和悬念压缩为后续阅读可承接的事件线。",
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
            content="第一章标记。" + "路明非说自己进入校园。" * 6,
        )
        _insert_document(
            conn,
            doc_id=2,
            book_id="multi_chapter_book",
            title_index=2,
            title="第二章",
            content="第二章标记。" + "楚子航说出龙族线索。" * 6,
        )
        conn.commit()

    long_summary = _plot_synopsis(
        "路明非进入校园之后，第二章继续以楚子航提到龙族为线索推进设定，两章合在一起形成从入场到设定揭示的连续事件链。",
        characters="路明非完成入场，楚子航承担设定提示，人物信息分别落在各自章节。",
        info="校园场景与龙族线索被压缩为后续记忆需要保留的关键信息。",
        structure="多章批次承担连续推进与设定揭示功能。",
    )

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
            if "路明非" in user_prompt:
                return (
                    {
                        "doc_id": 1,
                        "document_title_index": 1,
                        "characters": [
                            {
                                "canonical_name": "路明非",
                                "aliases": [],
                                "is_speaking_character": True,
                                "speaking_evidence": "文本中有路明非相关行动与回应线索。",
                                "personhood_evidence": "路明非被姓名称呼并执行进入校园的行动。",
                                "activity_or_state_evidence": "路明非进入校园。",
                                "relationship_evidence": "",
                                "source_doc_ids": [1],
                                "source_title_indexes": [1],
                                "candidate_type": "character",
                                "confidence": 0.9,
                                "uncertainty_reason": "",
                            }
                        ],
                    },
                    "",
                )
            return (
                {
                    "doc_id": 2,
                    "document_title_index": 2,
                    "characters": [
                        {
                            "canonical_name": "楚子航",
                            "aliases": [],
                            "is_speaking_character": True,
                            "speaking_evidence": "文本中有楚子航提到龙族的说明线索。",
                            "personhood_evidence": "楚子航被姓名称呼并执行说明行为。",
                            "activity_or_state_evidence": "楚子航提到龙族。",
                            "relationship_evidence": "",
                            "source_doc_ids": [2],
                            "source_title_indexes": [2],
                            "candidate_type": "character",
                            "confidence": 0.9,
                            "uncertainty_reason": "",
                        }
                    ],
                },
                "",
            )
        if "Reading Agent" not in system_prompt:
            return fallback_factory(), ""
        return (
            {
                "summary_quality": "plot_synopsis",
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
                        "summary_quality": "plot_synopsis",
                        "chapter_summary_md": _plot_synopsis(
                            "路明非进入校园，第一章把人物入场、校园背景和后续事件的起点压缩为清晰的开场事件链。",
                            characters="路明非从外部进入校园场景，成为本章记忆主体。",
                            info="校园场景作为后续剧情发生地点被建立。",
                            structure="第一章承担人物入场和场景铺垫功能。",
                        ),
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
                        "summary_quality": "plot_synopsis",
                        "chapter_summary_md": _plot_synopsis(
                            "楚子航提到龙族，第二章把新设定线索从背景中推到台前，使本批次从校园入场转向主线规则提示。",
                            characters="楚子航以说明者身份出现，推动路明非后续理解世界规则。",
                            info="龙族线索成为本章需要保存的设定信息。",
                            structure="第二章承担设定揭示与主线推进功能。",
                        ),
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
    assert result.batch_metrics[0]["doc_count"] == 1
    assert result.batch_metrics[0]["document_title_indexes"] == [1]

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

    assert [(row[0], row[1], row[2], row[3]) for row in chapter_rows] == [(1, 1, 1, 1)]
    assert "路明非" in chapter_rows[0][4]
    assert progress_row == (1, 1)
    assert [(row[0], row[1], row[2]) for row in profile_rows] == [("路明非", "[1]", "[1]")]
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
        _ = self, use_fallback_on_error
        if "Character Evidence Agent" in system_prompt:
            if "路明非" in user_prompt:
                return (
                    {
                        "doc_id": 1,
                        "document_title_index": 1,
                        "characters": [
                            {
                                "canonical_name": "路明非",
                                "aliases": [],
                                "is_speaking_character": False,
                                "speaking_evidence": "",
                                "personhood_evidence": "路明非被姓名称呼并执行进入校门的行动。",
                                "activity_or_state_evidence": "路明非在雨夜里踏入校门。",
                                "relationship_evidence": "",
                                "source_doc_ids": [1],
                                "source_title_indexes": [1],
                                "candidate_type": "character",
                                "confidence": 0.9,
                                "uncertainty_reason": "",
                            }
                        ],
                    },
                    "",
                )
            return (
                {
                    "doc_id": 2,
                    "document_title_index": 1,
                    "characters": [
                        {
                            "canonical_name": "楚子航",
                            "aliases": [],
                            "is_speaking_character": False,
                            "speaking_evidence": "",
                            "personhood_evidence": "楚子航被姓名称呼并执行说明行为。",
                            "activity_or_state_evidence": "楚子航说明龙族相关真相。",
                            "relationship_evidence": "",
                            "source_doc_ids": [2],
                            "source_title_indexes": [1],
                            "candidate_type": "character",
                            "confidence": 0.9,
                            "uncertainty_reason": "",
                        }
                    ],
                },
                "",
            )
        if "Reading Agent" not in system_prompt:
            return fallback_factory(), ""
        if "第一批标记" in user_prompt:
            return (
                {
                    "summary_quality": "plot_synopsis",
                    "chapter_summary_md": _plot_synopsis(
                        "路明非在雨夜进入校园，第一批次把人物入场、环境压力和后续悬念整理为章节开端。",
                        characters="路明非从外部进入校门，行动状态被推进到主场景内。",
                        info="雨夜校园提供本章前半段的地点与氛围信息。",
                        structure="拆批前半段承担开场铺垫与悬念累积功能。",
                    ),
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
                "summary_quality": "plot_synopsis",
                "chapter_summary_md": _plot_synopsis(
                    "楚子航补充说明龙族真相，第二批次把前半段悬念转化为明确设定揭示，章节核心冲突被正式点明。",
                    characters="楚子航成为说明关键信息的人物，路明非此前的入场获得新的意义。",
                    info="龙族真相被纳入长期记忆中的关键设定候选。",
                    structure="拆批后半段承担设定揭示和冲突点明功能。",
                ),
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
    final_intermediate = json.loads(final_row[0])
    assert len(final_intermediate) == 2
    assert "路明非在雨夜进入校园" in final_intermediate[0]
    assert "楚子航补充说明龙族真相" in final_intermediate[1]
    assert "## 摘要元信息" in final_row[1]
    assert "## 剧情事件链" in final_row[1]
    assert "## 人物状态/关系变化" in final_row[1]
    assert "## 关键信息/设定" in final_row[1]
    assert "汇总批次数：2" in final_row[1]
    assert final_row[2]
    assert final_row[3] == 2
    assert final_row[4] > 200
    assert final_row[5] == 88
    assert isinstance(json.loads(final_row[7]), list)
    assert "document_title_index" in final_row[6]
    assert final_progress is not None
    assert final_progress[0] == 2
    assert final_progress[1] == "1:2"


def test_close_read_runner_persists_complete_multi_chapter_synopses_in_non_dry_run(
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

    long_summary = _plot_synopsis(
        "路明非进入学院并作出回应，随后楚子航说明龙族相关真相，多章批次形成从人物入场到设定揭示的压缩剧情链。",
        characters="路明非完成入场回应，楚子航承担设定说明，两人的行动分别服务于连续推进。",
        info="学院场景和龙族真相是本批次需要保留的关键信息。",
        structure="多章批次承担人物入场、主线设定揭示和后续铺垫功能。",
    )

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
                    "summary_quality": "plot_synopsis",
                    "chapter_summary_md": long_summary,
                    "chapter_summary_short": "两章连续推进。",
                    "importance_score": 70,
                    "importance_reason": "连续推进主线。",
                    "related_chapters": [],
                    "chapter_summaries": [
                        {
                            "document_title_index": 1,
                            "chapter_title": "第一章",
                            "summary_quality": "plot_synopsis",
                            "chapter_summary_md": _plot_synopsis(
                                "路明非进入学院并作出回应，第一章完成人物入场、处境确认和后续事件的起点搭建。",
                                characters="路明非从进入学院转向作出回应，行动状态更明确。",
                                info="学院作为当前剧情场景被建立。",
                                structure="第一章承担人物入场和场景铺垫功能。",
                            ),
                            "chapter_summary_short": "路明非进入学院。",
                            "importance_score": 60,
                            "importance_reason": "人物入场。",
                            "related_chapters": [],
                        },
                        {
                            "document_title_index": 2,
                            "chapter_title": "第二章",
                            "summary_quality": "plot_synopsis",
                            "chapter_summary_md": _plot_synopsis(
                                "楚子航说明龙族相关真相，第二章将前序场景推进到关键设定揭示，使后续主线拥有明确方向。",
                                characters="楚子航以说明者身份推动信息显露，路明非面对的世界规则被重新定义。",
                                info="龙族真相是本章需要进入长期记忆的核心设定。",
                                structure="第二章承担设定揭示和主线推进功能。",
                            ),
                            "chapter_summary_short": "楚子航说明龙族真相。",
                            "importance_score": 75,
                            "importance_reason": "设定揭示。",
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

    assert [row[0] for row in chapter_rows] == [1]
    assert "路明非" in chapter_rows[0][1]


def test_payload_for_title_index_rejects_missing_chapter_synopsis_item(
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

    with pytest.raises(InvalidChapterSynopsisError, match="Missing chapter summary payload"):
        runner._payload_for_title_index(
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


def test_payload_for_title_index_accepts_single_chapter_top_level_summary_with_extra_chapter_summaries(
    tmp_path: Path,
) -> None:
    config = CloseReadAgentConfig(book_id="helper_book", sqlite_path=str(tmp_path / "helper.db"))
    config.runtime.dry_run = False
    runner = CloseReadRunner(repo_root=tmp_path, db_path=tmp_path / "helper.db", config=config)
    sub_batch = ChapterBatch(
        document_title_index=1,
        chapter_title="第一章",
        documents=[
            _make_document_row(
                doc_id=1,
                book_id="helper_book",
                title_index=1,
                title="第一章",
                content="路明非进入学院。" * 80,
            )
        ],
    )
    summary_md = _plot_synopsis(
        "路明非进入学院，第一章把人物入场、学院场景和后续事件的起点压缩为清晰的开场事件链。",
        characters="路明非从日常环境进入学院场景，成为本章记忆主体。",
        info="学院场景作为后续剧情发生地点被建立。",
        structure="第一章承担人物入场和场景铺垫功能。",
    )

    payload = runner._payload_for_title_index(
        sub_batch=sub_batch,
        payload={
            "summary_quality": "plot_synopsis",
            "chapter_summary_md": summary_md,
            "chapter_summary_short": "路明非进入学院。",
            "importance_score": 70,
            "importance_reason": "建立场景。",
            "related_chapters": [],
            "chapter_summaries": [
                {
                    "document_title_index": 1,
                    "chapter_title": "第一章",
                    "chapter_summary_md": summary_md,
                    "chapter_summary_short": "路明非进入学院。",
                }
            ],
            "document_character_mentions": [],
            "character_updates": [],
            "world_update": {"should_update": False, "changes": []},
            "outline_update": {"chapter_line": "", "timeline_events": []},
        },
        chapter_payload=None,
    )

    assert payload["chapter_summary_md"] == summary_md
    assert "chapter_summaries" not in payload


def test_chapter_summary_prompt_requires_plot_synopsis_not_document_prefix() -> None:
    system_prompt, user_prompt = build_chapter_summary_prompt(
        {
            "book_id": "prompt_book",
            "current_title_index": 1,
            "chapter_title": "扉页",
            "source_total_chars": 120,
            "summary_target_chars_min": 160,
            "documents": [
                {
                    "doc_id": 1,
                    "document_title_index": 1,
                    "content": "作者信息：某某。版权所有。",
                }
            ],
        }
    )

    combined_prompt = system_prompt + user_prompt
    assert "剧情梗概" in combined_prompt
    assert "document 开头/结尾" in combined_prompt
    assert "即使是关键信息/设定" in combined_prompt
    assert "作者信息" in combined_prompt
    assert "扉页" in combined_prompt
    assert "low_signal_needs_review" in combined_prompt


def test_close_read_runner_accepts_low_signal_noise_summary(tmp_path: Path) -> None:
    config = CloseReadAgentConfig(book_id="noise_book", sqlite_path=str(tmp_path / "noise.db"))
    runner = CloseReadRunner(repo_root=tmp_path, db_path=tmp_path / "noise.db", config=config)
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="扉页",
        documents=[
            _make_document_row(
                doc_id=1,
                book_id="noise_book",
                title_index=1,
                title="扉页",
                content="作者信息、目录和献词，没有具体剧情事件。" * 6,
            )
        ],
    )

    runner._validate_single_plot_synopsis(
        batch=batch,
        payload={
            "summary_quality": "low_signal_needs_review",
            "chapter_summary_md": "本段主要是目录、献词和结构信息，没有可概括的人物行动或剧情推进。",
            "chapter_summary_short": "目录和献词，无实质剧情。",
            "importance_score": 5,
            "importance_reason": "仅提供结构背景。",
            "related_chapters": [],
            "noise_documents": [{"doc_id": 1, "document_title_index": 1, "reason": "无具体剧情"}],
        },
    )


def test_close_read_runner_rejects_source_prefix_as_chapter_synopsis(tmp_path: Path) -> None:
    config = CloseReadAgentConfig(book_id="prefix_book", sqlite_path=str(tmp_path / "prefix.db"))
    runner = CloseReadRunner(repo_root=tmp_path, db_path=tmp_path / "prefix.db", config=config)
    source_prefix = "路明非推开学院大门后沿着湿漉漉的石阶向前走去，雨水顺着他的额发落下。"
    batch = ChapterBatch(
        document_title_index=1,
        chapter_title="第一章",
        documents=[
            _make_document_row(
                doc_id=1,
                book_id="prefix_book",
                title_index=1,
                title="第一章",
                content=source_prefix + "他意识到真正的考验才刚刚开始。" * 8,
            )
        ],
    )
    copied_prefix_payload = {
        "summary_quality": "plot_synopsis",
        "chapter_summary_md": _plot_synopsis(
            f"{source_prefix} 这一段被错误地直接当作剧情梗概使用。",
            characters="路明非进入学院后状态发生变化。",
            info="学院场景被建立。",
            structure="本章承担开场铺垫功能。",
        ),
        "chapter_summary_short": "路明非进入学院。",
        "importance_score": 60,
        "importance_reason": "开场建立场景。",
        "related_chapters": [],
    }

    with pytest.raises(InvalidChapterSynopsisError, match="copy source text"):
        runner._validate_single_plot_synopsis(batch=batch, payload=copied_prefix_payload)
