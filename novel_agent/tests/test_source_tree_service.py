from __future__ import annotations

from pathlib import Path

from novel_agent.app.services.source_tree_service import SourceTreeService


def test_single_file_analysis_uses_explicit_file_order_without_model(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("第一章\n正文", encoding="utf-8")

    analysis = SourceTreeService(model_client=None).analyze(source_path, book_id="book-1")

    assert analysis.strategy_type == "single_file"
    assert len(analysis.books) == 1
    assert analysis.books[0].selected_paths == [source_path.as_posix()]
    assert analysis.books[0].read_order[0].path == source_path.as_posix()
