from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Mapping


class CharacterEvidenceLogRepo:
    """Stores uncompressed character evidence until Character Reduce absorbs it."""

    def append_many(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        evidence_items: list[Mapping[str, Any]],
        outline_segment: Mapping[str, Any],
        updated_at: str,
    ) -> int:
        count = 0
        outline_segment_id = str(outline_segment.get("outline_segment_id") or "").strip()
        source_doc_range = str(outline_segment.get("source_doc_range") or "").strip()
        for item in evidence_items:
            canonical_name = str(item.get("canonical_name") or "").strip()
            if not canonical_name:
                continue
            evidence = dict(item)
            if outline_segment_id:
                evidence.setdefault("outline_segment_id", outline_segment_id)
            if source_doc_range:
                evidence.setdefault("source_doc_range", source_doc_range)
            if outline_segment.get("outline_segment"):
                evidence.setdefault("outline_segment", str(outline_segment.get("outline_segment") or "").strip())
            source_doc_ids = self._int_list(evidence.get("source_doc_ids") or outline_segment.get("source_doc_ids"))
            source_title_indexes = self._int_list(
                evidence.get("source_title_indexes") or outline_segment.get("source_title_indexes")
            )
            evidence_id = self._evidence_id(
                book_id=book_id,
                canonical_name=canonical_name,
                character_id=str(evidence.get("character_id") or "").strip(),
                evidence=evidence,
                outline_segment_id=outline_segment_id,
                source_doc_ids=source_doc_ids,
            )
            evidence.setdefault("evidence_id", evidence_id)
            evidence_json = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO character_evidence_log(
                    evidence_id, book_id, character_id, canonical_name, status, evidence_json,
                    outline_segment_id, source_doc_ids_json, source_title_indexes_json,
                    source_doc_range, evidence_chars, has_major_change, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    book_id,
                    str(evidence.get("character_id") or "").strip(),
                    canonical_name,
                    evidence_json,
                    outline_segment_id,
                    json.dumps(source_doc_ids, ensure_ascii=False),
                    json.dumps(source_title_indexes, ensure_ascii=False),
                    source_doc_range,
                    len(evidence_json),
                    1 if self._has_major_change(evidence) else 0,
                    updated_at,
                    updated_at,
                ),
            )
            count += max(0, int(cur.rowcount or 0))
        return count

    def pending_groups(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT * FROM character_evidence_log
            WHERE book_id = ? AND status = 'pending'
            ORDER BY canonical_name, evidence_id
            """,
            (book_id,),
        ).fetchall()
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row["character_id"] or "").strip() or f"name:{row['canonical_name']}"
            group = groups.setdefault(
                key,
                {
                    "character_id": str(row["character_id"] or "").strip(),
                    "canonical_name": str(row["canonical_name"] or "").strip(),
                    "evidence_ids": [],
                    "evidence_items": [],
                    "evidence_chars": 0,
                    "has_major_change": False,
                    "source_doc_ids": set(),
                    "source_title_indexes": set(),
                    "outline_segment_ids": set(),
                },
            )
            group["evidence_ids"].append(str(row["evidence_id"]))
            evidence = self._json_dict(row["evidence_json"])
            if evidence:
                group["evidence_items"].append(evidence)
            group["evidence_chars"] += int(row["evidence_chars"] or 0)
            group["has_major_change"] = bool(group["has_major_change"] or int(row["has_major_change"] or 0))
            group["source_doc_ids"].update(self._json_int_list(row["source_doc_ids_json"]))
            group["source_title_indexes"].update(self._json_int_list(row["source_title_indexes_json"]))
            if str(row["outline_segment_id"] or "").strip():
                group["outline_segment_ids"].add(str(row["outline_segment_id"]).strip())
        result = []
        for group in groups.values():
            result.append(
                {
                    **group,
                    "source_doc_ids": sorted(group["source_doc_ids"]),
                    "source_title_indexes": sorted(group["source_title_indexes"]),
                    "outline_segment_ids": sorted(group["outline_segment_ids"]),
                }
            )
        return result

    def mark_compacted(
        self,
        conn: sqlite3.Connection,
        *,
        evidence_ids: list[str],
        updated_at: str,
    ) -> None:
        ids = [str(item).strip() for item in evidence_ids if str(item).strip()]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE character_evidence_log SET status = 'compacted', updated_at = ? WHERE evidence_id IN ({placeholders})",
            [updated_at, *ids],
        )

    @staticmethod
    def _evidence_id(
        *,
        book_id: str,
        canonical_name: str,
        character_id: str,
        evidence: Mapping[str, Any],
        outline_segment_id: str,
        source_doc_ids: list[int],
    ) -> str:
        payload = json.dumps(
            {
                "book_id": book_id,
                "character_id": character_id,
                "canonical_name": canonical_name,
                "outline_segment_id": outline_segment_id,
                "source_doc_ids": source_doc_ids,
                "evidence": evidence,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
        return f"char-evidence:{digest}"

    @staticmethod
    def _has_major_change(evidence: Mapping[str, Any]) -> bool:
        for key in ("has_major_change", "major_change", "profile_brief_major_change"):
            if bool(evidence.get(key)):
                return True
        compact_signal = evidence.get("profile_brief_compact") or evidence.get("brief_compact")
        return isinstance(compact_signal, Mapping) and bool(compact_signal.get("needed"))

    @staticmethod
    def _int_list(value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for item in value:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in result:
                result.append(number)
        return result

    @classmethod
    def _json_int_list(cls, value: object) -> list[int]:
        try:
            payload = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
        return cls._int_list(payload)

    @staticmethod
    def _json_dict(value: object) -> dict[str, Any]:
        try:
            payload = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}
