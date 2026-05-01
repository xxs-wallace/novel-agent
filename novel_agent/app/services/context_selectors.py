from __future__ import annotations

import json
import sqlite3


def rank_chapter_rows(
    rows: list[sqlite3.Row],
    *,
    current_title_index: str | None,
) -> list[sqlite3.Row]:
    usable_rows = [row for row in rows if _chapter_summary_text(row).strip()]
    if not usable_rows:
        return []

    if current_title_index is None:
        return sorted(
            usable_rows,
            key=lambda row: (
                -int(row["importance_score"] or 0),
                -int(row["document_title_index"]),
            ),
        )

    current_index = int(current_title_index)
    bounded_rows = [
        row for row in usable_rows if int(row["document_title_index"]) <= current_index
    ]
    return sorted(
        bounded_rows,
        key=lambda row: (
            abs(current_index - int(row["document_title_index"])),
            -int(row["document_title_index"]),
            -int(row["importance_score"] or 0),
        ),
    )


def chapter_summary_text(row: sqlite3.Row) -> str:
    return _chapter_summary_text(row).strip()


def infer_character_names(
    rows: list[sqlite3.Row],
    *,
    prioritized_names: list[str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for name in prioritized_names:
        normalized = str(name).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)

    for row in rows:
        for raw_name in _load_json_list(row["mentioned_characters_json"]):
            normalized = str(raw_name).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)

    return ordered


def rank_character_rows(
    rows: list[sqlite3.Row],
    *,
    prioritized_names: list[str],
) -> list[sqlite3.Row]:
    priority_order = {
        str(name).strip(): index
        for index, name in enumerate(prioritized_names)
        if str(name).strip()
    }
    return sorted(
        rows,
        key=lambda row: (
            0 if str(row["canonical_name"]) in priority_order else 1,
            priority_order.get(str(row["canonical_name"]), 10_000),
            -int(row["importance_score"] or 0),
            -int(row["last_seen_title_index"] or 0),
            str(row["canonical_name"]),
        ),
    )


def _chapter_summary_text(row: sqlite3.Row) -> str:
    return str(row["summary_md"] or row["summary_short"] or "")


def _load_json_list(raw_value: object) -> list[object]:
    if not raw_value:
        return []
    try:
        value = json.loads(str(raw_value))
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []
