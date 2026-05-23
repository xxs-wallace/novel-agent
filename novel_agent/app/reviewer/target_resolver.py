from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..schemas.reviewer_schema import EVIDENCE_SOURCE_TYPES, ResolvedReviewTarget, ReviewRequest, ReviewTarget


class ReviewTargetResolver:
    def __init__(self, *, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path.cwd()

    def resolve(self, request: ReviewRequest, *, conn: sqlite3.Connection | None = None) -> ResolvedReviewTarget:
        target = request.target
        pieces: list[str] = []
        source_refs = self._normalize_source_refs(target.source_refs, target_id=target.target_id)
        artifact_refs: list[dict[str, Any]] = []
        document_refs: list[dict[str, Any]] = []

        if target.text:
            pieces.append(target.text)
            source_refs.append({"source_type": "target_text", "source_id": target.target_id, "label": "inline target text"})

        if target.document_ids:
            if conn is None:
                raise ValueError("conn is required to resolve ReviewTarget.document_ids")
            document_texts, refs = self._resolve_documents(conn, book_id=request.book_id, document_ids=target.document_ids)
            pieces.extend(document_texts)
            document_refs.extend(refs)
            source_refs.extend(
                {
                    "source_type": "target_text",
                    "source_id": target.target_id,
                    "label": f"document:{ref.get('label', ref['document_id'])}",
                    "location": {"document_id": ref["document_id"]},
                }
                for ref in refs
            )

        if target.artifact_path:
            artifact_text, artifact_ref = self._resolve_artifact(target)
            pieces.append(artifact_text)
            artifact_refs.append(artifact_ref)
            source_refs.append(
                {
                    "source_type": "writer_artifact",
                    "source_id": target.artifact_id or target.artifact_path,
                    "label": artifact_ref["path"],
                }
            )

        resolved_text = "\n\n".join(piece for piece in pieces if piece.strip()).strip()
        if not resolved_text:
            raise ValueError("ReviewTarget resolved to empty text")

        original_chars = len(resolved_text)
        truncation = {
            "truncated": False,
            "strategy": "",
            "original_chars": original_chars,
            "resolved_chars": original_chars,
        }
        max_chars = request.budget.max_target_chars
        if len(resolved_text) > max_chars:
            resolved_text = resolved_text[:max_chars].rstrip()
            truncation = {
                "truncated": True,
                "strategy": f"prefix_chars:{max_chars}",
                "original_chars": original_chars,
                "resolved_chars": len(resolved_text),
            }

        return ResolvedReviewTarget(
            target_id=target.target_id,
            target_type=target.target_type,
            resolved_text=resolved_text,
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            document_refs=document_refs,
            truncation=truncation,
        )

    def _resolve_documents(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        document_ids: list[str],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        clean_ids: list[int] = []
        for item in document_ids:
            try:
                doc_id = int(item)
            except (TypeError, ValueError):
                continue
            if doc_id > 0 and doc_id not in clean_ids:
                clean_ids.append(doc_id)
        if not clean_ids:
            return [], []
        placeholders = ",".join("?" for _ in clean_ids)
        rows = conn.execute(
            f"""
            SELECT doc_id, content, document_title, document_title_index, source_path, source_start_offset, source_end_offset
            FROM documents
            WHERE book_id = ? AND doc_id IN ({placeholders})
            ORDER BY doc_id
            """,
            (book_id, *clean_ids),
        ).fetchall()
        texts: list[str] = []
        refs: list[dict[str, Any]] = []
        for row in rows:
            text = str(row["content"] or "").strip()
            if text:
                texts.append(text)
            refs.append(
                {
                    "document_id": str(row["doc_id"]),
                    "label": str(row["document_title"] or row["document_title_index"] or row["doc_id"]),
                    "source_path": str(row["source_path"] or ""),
                    "source_start_offset": int(row["source_start_offset"] or 0),
                    "source_end_offset": int(row["source_end_offset"] or 0),
                }
            )
        return texts, refs

    def _resolve_artifact(self, target: ReviewTarget) -> tuple[str, dict[str, Any]]:
        path = Path(target.artifact_path)
        resolved_path = path if path.is_absolute() else self.repo_root / path
        if not resolved_path.exists():
            raise FileNotFoundError(f"ReviewTarget artifact_path does not exist: {resolved_path}")
        text = resolved_path.read_text(encoding="utf-8").strip()
        return text, {"artifact_id": target.artifact_id, "path": str(resolved_path), "kind": target.target_type}

    def _normalize_source_refs(self, refs: list[dict[str, Any]], *, target_id: str) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for ref in refs:
            item = dict(ref)
            source_type = str(item.get("source_type") or "").strip()
            if source_type == "document":
                document_id = str(item.get("source_id") or item.get("document_id") or "").strip()
                item["source_type"] = "target_text"
                item["source_id"] = target_id
                item.setdefault("label", f"document:{document_id}" if document_id else "document")
                if document_id:
                    item["location"] = {**dict(item.get("location") or {}), "document_id": document_id}
                normalized.append(item)
                continue
            if source_type in EVIDENCE_SOURCE_TYPES:
                normalized.append(item)
        return normalized
