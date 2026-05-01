from __future__ import annotations

from pathlib import Path

from novel_agent.app.run_close_read import main as close_read_main
from novel_agent.app.run_segment_book import main as segment_main


def test_cli_segment_and_close_read(tmp_path: Path) -> None:
    source_root = Path(__file__).parent / "fixtures" / "novel_agent" / "longzu_5kb"
    db_path = tmp_path / "cli.db"
    debug_md = tmp_path / "debug.md"

    segment_exit = segment_main(
        [
            "--repo-root",
            str(tmp_path),
            "--db",
            str(db_path),
            "--book-id",
            "cli_book",
            "--source-root",
            str(source_root),
            "--max-read-chars",
            "5120",
            "--preferred-document-chars-min",
            "800",
            "--thinking",
            "enabled",
            "--reasoning-effort",
            "high",
            "--dry-run",
        ]
    )
    assert segment_exit == 0

    close_exit = close_read_main(
        [
            "--repo-root",
            str(tmp_path),
            "--db",
            str(db_path),
            "--book-id",
            "cli_book",
            "--dry-run",
            "--max-chapters",
            "1",
            "--debug-markdown-path",
            str(debug_md),
            "--thinking",
            "enabled",
            "--reasoning-effort",
            "high",
        ]
    )
    assert close_exit == 0
    assert debug_md.exists()
