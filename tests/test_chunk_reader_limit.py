from __future__ import annotations

from pathlib import Path

from novel_agent.app.services.chunk_reader_service import ChunkReaderService


def test_chunk_reader_respects_max_total_chars(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text("第一行\n第二行\n第三行\n第四行\n第五行\n", encoding="utf-8")

    reader = ChunkReaderService(
        target_min_chars=100,
        target_max_chars=100,
        stop_at_newline_after_limit=True,
        max_total_chars=10,
    )
    batches = reader.iter_batches([path])
    assert len(batches) == 1
    assert len(batches[0].content) <= 10


def test_chunk_reader_can_resume_from_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text("第一行\n第二行\n第三行\n第四行\n第五行\n第六行\n", encoding="utf-8")

    reader = ChunkReaderService(
        target_min_chars=6,
        target_max_chars=8,
        stop_at_newline_after_limit=True,
        max_total_chars=12,
    )
    first_batches = reader.iter_batches([path])
    assert first_batches
    resume_offset = first_batches[-1].spans[-1].end_offset

    resumed_batches = reader.iter_batches_from_checkpoint(
        [path],
        resume_source_path=path.as_posix(),
        resume_source_offset=resume_offset,
        start_batch_no=first_batches[-1].batch_no + 1,
    )

    assert resumed_batches
    assert resumed_batches[0].batch_no == first_batches[-1].batch_no + 1
    assert resumed_batches[0].spans[0].start_offset == resume_offset


def test_chunk_reader_prefers_sentence_newline_boundary(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text("第一句。\n第二句继续。\n第三句。", encoding="utf-8")

    reader = ChunkReaderService(
        target_min_chars=1,
        target_max_chars=10,
        stop_at_newline_after_limit=True,
    )
    batches = reader.iter_batches([path])

    assert batches
    assert batches[0].content == "第一句。\n"


def test_chunk_reader_falls_back_to_period_boundary_when_no_newline(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text("第一句。第二句继续。第三句。", encoding="utf-8")

    reader = ChunkReaderService(
        target_min_chars=1,
        target_max_chars=10,
        stop_at_newline_after_limit=True,
    )
    batches = reader.iter_batches([path])

    assert batches
    assert batches[0].content == "第一句。第二句继续。"
