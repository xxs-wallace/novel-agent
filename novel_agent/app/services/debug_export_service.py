from __future__ import annotations

import json
from pathlib import Path


class DebugExportService:
    def export(self, conn, *, book_id: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        docs = conn.execute(
            "SELECT doc_id, document_title_index, document_title, source_path, source_start_offset, source_end_offset, content_chars, character_keywords_json, content_tags_csv, content FROM documents WHERE book_id = ? ORDER BY doc_id",
            (book_id,),
        ).fetchall()
        chapters = conn.execute(
            "SELECT document_title_index, chapter_title, importance_score, summary_short, summary_md, source_doc_start_id, source_doc_end_id, source_total_chars FROM chapters WHERE book_id = ? ORDER BY document_title_index",
            (book_id,),
        ).fetchall()
        profiles = conn.execute(
            "SELECT canonical_name, chapter_indexes_json, profile_summary_md FROM character_profiles WHERE book_id = ? ORDER BY canonical_name",
            (book_id,),
        ).fetchall()
        progress = conn.execute(
            "SELECT * FROM reading_progress WHERE book_id = ? ORDER BY agent_stage",
            (book_id,),
        ).fetchall()
        assets = conn.execute(
            "SELECT * FROM book_assets WHERE book_id = ?",
            (book_id,),
        ).fetchall()

        lines = [f"# SQLite Debug Export: {book_id}", ""]
        lines.append("## Documents")
        for row in docs:
            keywords = ", ".join(json.loads(row["character_keywords_json"] or "[]"))
            content_tags = str(row["content_tags_csv"] or "")
            lines.append(
                f"- doc_id={row['doc_id']} | title_index={row['document_title_index']} | title={row['document_title']} | chars={row['content_chars']} | offsets={row['source_start_offset']}-{row['source_end_offset']} | path={row['source_path']} | characters={keywords} | tags={content_tags}"
            )
            lines.append("")
            lines.append("```text")
            lines.append(str(row["content"]).rstrip())
            lines.append("```")
        lines.append("")
        lines.append("## Chapters")
        for row in chapters:
            lines.append(
                f"- title_index={row['document_title_index']} | title={row['chapter_title']} | importance={row['importance_score']} | doc_range={row['source_doc_start_id']}-{row['source_doc_end_id']} | source_chars={row['source_total_chars']} | short={row['summary_short'] or ''}"
            )
            lines.append("")
            lines.append(str(row["summary_md"]).strip())
        lines.append("")
        lines.append("## Character Profiles")
        for row in profiles:
            chapter_indexes = ", ".join(str(x) for x in json.loads(row["chapter_indexes_json"] or "[]"))
            lines.append(f"- {row['canonical_name']} | chapters={chapter_indexes}")
            lines.append("")
            lines.append(str(row["profile_summary_md"]).strip())
        lines.append("")
        lines.append("## Reading Progress")
        for row in progress:
            lines.append(
                f"- stage={row['agent_stage']} | last_doc={row['last_completed_doc_id']} | last_title={row['last_completed_title_index']} | checkpoint={row['checkpoint_token'] or ''}"
            )
        lines.append("")
        lines.append("## Book Assets")
        for row in assets:
            lines.append(f"- book_id={row['book_id']} | source_root={row['source_root']} | debug_export_path={row['debug_export_path'] or ''}")
            toc_markdown = str(row["toc_markdown"] or "").strip()
            if toc_markdown:
                lines.append("")
                lines.append(f"Toc Source: {row['toc_source_path'] or ''}")
                lines.append("")
                lines.append("```text")
                lines.append(toc_markdown)
                lines.append("```")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(self._row_to_jsonable_dict(row), ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")
        lines.append("## Raw SQLite Rows")
        for table_name in ["documents", "chapters", "character_profiles", "reading_progress", "book_assets"]:
            rows = conn.execute(
                f"SELECT * FROM {table_name} WHERE book_id = ? ORDER BY 1",
                (book_id,),
            ).fetchall()
            lines.append(f"### {table_name}")
            for row in rows:
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(self._row_to_jsonable_dict(row), ensure_ascii=False, indent=2))
                lines.append("```")
        output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return output_path

    def _row_to_jsonable_dict(self, row: sqlite3.Row) -> dict[str, object]:
        return {key: row[key] for key in row.keys()}
