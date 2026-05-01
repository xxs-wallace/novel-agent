from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from novel_agent.app.llm import InvalidJSONResponseError, JsonModelClient, ModelSettings
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.reading_progress_repo import ReadingProgressRepo
from novel_agent.app.services.chunk_reader_service import ChunkFileSpan, TextBatch
from novel_agent.app.services.document_ingest_service import DocumentIngestService


def build_service() -> DocumentIngestService:
    return DocumentIngestService(
        model_client=JsonModelClient(
            ModelSettings(
                model_type="OpenAIModel",
                model_name="deepseek-chat",
                dry_run=True,
            )
        ),
        documents_repo=DocumentsRepo(),
        progress_repo=ReadingProgressRepo(),
        preferred_document_chars_min=4096,
        preferred_document_chars_max=20480,
    )


def test_postprocess_documents_keeps_keywords_empty_and_merges_tiny_tail() -> None:
    service = build_service()
    docs = [
        {
            "document_local_id": 1,
            "document_title": "第一幕 卡塞尔之门 (Part 1/2)",
            "document_title_index": 6,
            "content": "路明非站在雨里。路明非看见楚子航，楚子航没有说话。",
            "content_chars": 0,
            "character_keywords": [],
            "content_tags": [],
        },
        {
            "document_local_id": 2,
            "document_title": "第一幕 卡塞尔之门 (Part 2/2)",
            "document_title_index": 6,
            "content": "完。",
            "content_chars": 0,
            "character_keywords": [],
            "content_tags": [],
        },
    ]

    processed = service._postprocess_documents(docs)
    assert len(processed) == 1
    assert processed[0]["character_keywords"] == []
    assert "雨天" in processed[0]["content_tags"]
    assert len(processed[0]["content_tags"]) <= 4
    assert "完。" in processed[0]["content"]


def test_postprocess_documents_skips_front_matter() -> None:
    service = build_service()
    docs = [
        {
            "document_local_id": 1,
            "document_title": "版权信息",
            "document_title_index": 1,
            "content": "本书版权为浙江出版集团数字传媒有限公司所有，ISBN 123456。",
            "content_chars": 0,
            "character_keywords": [],
            "content_tags": [],
        }
    ]

    processed = service._postprocess_documents(docs)
    assert processed == []


def test_infer_content_tags_prefers_distinct_high_value_groups() -> None:
    service = build_service()

    ancient_tags = service._infer_content_tags(
        title="序章 白帝城",
        content="所谓弃族的命运。黑暗中火光燃烧，城市在哭号，白帝城像一场盛大的献祭。",
    )
    assert "遗迹古城" in ancient_tags
    assert "开场铺垫" in ancient_tags
    assert len(ancient_tags) <= 4

    school_tags = service._infer_content_tags(
        title="第一幕 卡塞尔之门",
        content="路明非是高中生，在学院前等录取通知。他切到QQ，看着成绩和高考倒计时发呆。",
    )
    assert "校园" in school_tags
    assert "学习考试" in school_tags
    assert len(school_tags) <= 4


def test_build_batch_segments_splits_text_into_byte_bounded_segments(tmp_path: Path) -> None:
    service = build_service()
    text = ("路明非，楚子航，" * 40) + "\n" + ("卡塞尔学院！" * 40)
    batch = TextBatch(
        batch_no=1,
        chars=len(text),
        spans=[
            ChunkFileSpan(
                source_path=(tmp_path / "segments.md").as_posix(),
                source_file_name="segments.md",
                start_offset=0,
                end_offset=len(text),
                text=text,
            )
        ],
    )

    segments = service._build_batch_segments(batch)

    assert len(segments) >= 2
    assert segments[0].segment_id == 1
    assert segments[-1].end_index == len(text)
    assert all(1 <= segment.segment_id <= len(segments) for segment in segments)
    assert all(100 <= segment.byte_length <= 1000 for segment in segments)
    assert "".join(segment.text for segment in segments) == text


def test_build_batch_segments_keeps_markdown_headings_as_hard_boundaries(tmp_path: Path) -> None:
    service = build_service()
    text = (
        "前置说明，" * 20
        + "\n## 开篇\n"
        + "路明非等了十八年，门终于开了。" * 8
        + "\n## 序章 白帝城\n"
        + "所谓弃族的命运，就是要穿越荒原。" * 8
    )
    batch = TextBatch(
        batch_no=1,
        chars=len(text),
        spans=[
            ChunkFileSpan(
                source_path=(tmp_path / "headings.md").as_posix(),
                source_file_name="headings.md",
                start_offset=0,
                end_offset=len(text),
                text=text,
            )
        ],
    )

    segments = service._build_batch_segments(batch)

    assert any(segment.text.startswith("## 开篇") for segment in segments)
    assert any(segment.text.startswith("## 序章 白帝城") for segment in segments)
    assert "".join(segment.text for segment in segments) == text


class CaptureModelClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.prompts: list[str] = []
        self.settings = SimpleNamespace(dry_run=False)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = system_prompt, fallback_factory, use_fallback_on_error
        self.prompts.append(user_prompt)
        return self.payload, ""


class RetryThenFallbackModelClient:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(dry_run=False)
        self.prompts: list[str] = []
        self.failed_once = False

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = system_prompt, use_fallback_on_error
        self.prompts.append(user_prompt)
        if not self.failed_once and "第一部分标记" in user_prompt and "第二部分标记" in user_prompt:
            self.failed_once = True
            raise InvalidJSONResponseError(raw_text="not-json", attempts=3)
        return fallback_factory(), ""


class EmptyDocumentsModelClient:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(dry_run=False)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ):
        _ = system_prompt, user_prompt, fallback_factory, use_fallback_on_error
        return {"documents": []}, ""


def test_ingest_batches_includes_resume_context_and_trims_overlap(tmp_path: Path) -> None:
    db_path = tmp_path / "resume_context.db"
    db = NovelAgentDB(db_path)
    model_client = CaptureModelClient(
        {
            "document_title_index_start": 2,
            "documents": [
                {
                    "document_local_id": 1,
                    "document_title": "第一幕 卡塞尔之门",
                    "document_title_index": 2,
                    "inferred_chapter_no": 2,
                    "segment_ids": [1],
                    "character_keywords": [],
                    "content_tags": ["校园"],
                    "segmentation_reason": "resume_test",
                    "continuity_hint": "承接上文",
                }
            ],
            "batch_summary": {"chapter_count": 1, "document_count": 1, "new_characters": []},
        }
    )
    service = DocumentIngestService(
        model_client=model_client,  # type: ignore[arg-type]
        documents_repo=DocumentsRepo(),
        progress_repo=ReadingProgressRepo(),
        preferred_document_chars_min=800,
        preferred_document_chars_max=1600,
    )
    batch = TextBatch(
        batch_no=2,
        chars=12,
        spans=[
            ChunkFileSpan(
                source_path=(tmp_path / "sample.md").as_posix(),
                source_file_name="sample.md",
                start_offset=100,
                end_offset=112,
                text="这里是新的段落开头。",
            )
        ],
    )
    previous_content = "这是上一条document的结尾部分，用来测试断点续传时的上下文重叠裁剪。"

    with db.connect() as conn:
        db.init_schema(conn)
        result = service.ingest_batches(
            conn=conn,
            repo_root=tmp_path,
            book_id="resume_book",
            batches=[batch],
            run_id="resume-run",
            reset_book=False,
            initial_title_index=2,
            continued_title="第一幕 卡塞尔之门",
            continued_title_index=1,
            continued_document_content=previous_content,
        )
        inserted = conn.execute(
            "SELECT content, document_title_index FROM documents WHERE book_id = 'resume_book' ORDER BY doc_id"
        ).fetchall()

    assert result.inserted_documents == 1
    assert model_client.prompts
    assert "续传衔接上下文" in model_client.prompts[0]
    assert '"segment_ids": [' in model_client.prompts[0]
    assert previous_content in model_client.prompts[0]
    assert inserted[0]["content"] == "这里是新的段落开头。"
    assert inserted[0]["document_title_index"] == 1


def test_ingest_batches_retries_with_split_batches_after_invalid_json(tmp_path: Path) -> None:
    db_path = tmp_path / "retry_split.db"
    db = NovelAgentDB(db_path)
    model_client = RetryThenFallbackModelClient()
    service = DocumentIngestService(
        model_client=model_client,  # type: ignore[arg-type]
        documents_repo=DocumentsRepo(),
        progress_repo=ReadingProgressRepo(),
        preferred_document_chars_min=800,
        preferred_document_chars_max=1600,
    )
    left_text = "第一部分标记。" + "路明非看着雨幕里的校园。" * 8
    right_text = "第二部分标记。" + "楚子航沉默地站着。" * 8
    full_text = f"{left_text}\n{right_text}"
    batch = TextBatch(
        batch_no=1,
        chars=len(full_text),
        spans=[
            ChunkFileSpan(
                source_path=(tmp_path / "sample.md").as_posix(),
                source_file_name="sample.md",
                start_offset=0,
                end_offset=len(full_text),
                text=full_text,
            )
        ],
    )

    with db.connect() as conn:
        db.init_schema(conn)
        result = service.ingest_batches(
            conn=conn,
            repo_root=tmp_path,
            book_id="retry_book",
            batches=[batch],
            run_id="retry-run",
            reset_book=False,
        )
        inserted = conn.execute(
            "SELECT content, source_batch_no FROM documents WHERE book_id = 'retry_book' ORDER BY doc_id"
        ).fetchall()

    assert result.inserted_documents == 2
    assert result.batch_count == 2
    assert len(model_client.prompts) == 3
    assert [row["source_batch_no"] for row in inserted] == [1, 2]
    assert [row["content"] for row in inserted] == [left_text, right_text]


def test_safe_fallback_preserves_opening_heading_after_invalid_json(tmp_path: Path) -> None:
    db_path = tmp_path / "fallback_opening.db"
    db = NovelAgentDB(db_path)
    service = DocumentIngestService(
        model_client=EmptyDocumentsModelClient(),  # type: ignore[arg-type]
        documents_repo=DocumentsRepo(),
        progress_repo=ReadingProgressRepo(),
        preferred_document_chars_min=800,
        preferred_document_chars_max=1600,
    )
    text = (
        "# longzu\n\n- Source: `/tmp/longzu.pdf`\n- Pages: 10\n\n"
        "## 目录（来自 PDF 书签）\n- [开篇](#开篇)\n- [序章 白帝城](#序章-白帝城)\n\n"
        "## 开篇\n\n在你最孤单最无望的时候，有一扇门会在你身边打开。\n"
        "谨以此书献给所有有梦想的衰小孩！\n\n"
        "## 序章 白帝城\n\n所谓弃族的命运，就是要穿越荒原，再次竖起战旗。\n"
    )
    batch = TextBatch(
        batch_no=1,
        chars=len(text),
        spans=[
            ChunkFileSpan(
                source_path=(tmp_path / "longzu.md").as_posix(),
                source_file_name="longzu.md",
                start_offset=0,
                end_offset=len(text),
                text=text,
            )
        ],
    )

    with db.connect() as conn:
        db.init_schema(conn)
        result = service.ingest_batches(
            conn=conn,
            repo_root=tmp_path,
            book_id="fallback_opening",
            batches=[batch],
            run_id="fallback-opening-run",
            reset_book=True,
        )
        rows = conn.execute(
            "SELECT doc_id, document_title, source_start_offset, content FROM documents WHERE book_id = 'fallback_opening' ORDER BY doc_id"
        ).fetchall()

    assert result.inserted_documents >= 2
    assert rows[0]["document_title"] == "开篇"
    assert rows[0]["source_start_offset"] == text.index("## 开篇")
    assert "谨以此书献给所有有梦想的衰小孩" in rows[0]["content"]
