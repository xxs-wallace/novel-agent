from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..utils.text_utils import normalize_whitespace, safe_excerpt
from .source_arc_mapping_service import SourceArcMappingService


@dataclass(frozen=True, slots=True)
class TitleIndexRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("range start must be <= end")

    @classmethod
    def from_value(cls, value: object) -> "TitleIndexRange":
        if isinstance(value, TitleIndexRange):
            return value
        if isinstance(value, str):
            parts = [part.strip() for part in value.split("-", 1)]
            if len(parts) == 2:
                return cls(start=int(parts[0]), end=int(parts[1]))
            index = int(value.strip())
            return cls(start=index, end=index)
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return cls(start=int(value[0]), end=int(value[1]))
        if isinstance(value, dict):
            start = value.get("start") or value.get("start_document_title_index")
            end = value.get("end") or value.get("end_document_title_index") or start
            return cls(start=int(start), end=int(end))
        index = int(value)
        return cls(start=index, end=index)

    def contains(self, other: "TitleIndexRange") -> bool:
        return self.start <= other.start and other.end <= self.end

    def as_text(self) -> str:
        return f"{self.start}-{self.end}"


@dataclass(slots=True)
class SummaryOutlineCommitResult:
    success: bool
    book_id: str
    evidence_window: str
    target_range: str
    committed_title_indexes: list[int] = field(default_factory=list)
    skipped_title_indexes: list[int] = field(default_factory=list)
    missing_reasons: list[str] = field(default_factory=list)


class SummaryOutlineCommitService:
    """Finalize chapter summaries and outline fragments using a wider evidence window.

    Conflict policy:
    - Window commits are authoritative for chapter summary/outline rows.
    - SourceArcMap is committed structural evidence, but reverse updates never overwrite an
      existing committed row unless a caller explicitly enables overwrite.
    """

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        chapters_repo: ChaptersRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        assets_repo: AssetsRepo | None = None,
        now_factory: Any | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.assets_repo = assets_repo or AssetsRepo()
        self.now_factory = now_factory or _utc_now

    def commit_window(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        evidence_window: object,
        target_range: object,
        source_arc_payload: dict[str, Any] | None = None,
        overwrite_committed: bool = False,
    ) -> SummaryOutlineCommitResult:
        evidence = TitleIndexRange.from_value(evidence_window)
        target = TitleIndexRange.from_value(target_range)
        result = SummaryOutlineCommitResult(
            success=False,
            book_id=book_id,
            evidence_window=evidence.as_text(),
            target_range=target.as_text(),
        )
        if not evidence.contains(target):
            result.missing_reasons.append("target_range.outside_evidence_window")
            return result

        rows = self.chapters_repo.list_by_book(conn, book_id=book_id)
        evidence_rows = [row for row in rows if evidence.start <= int(row["document_title_index"]) <= evidence.end]
        target_rows = [row for row in rows if target.start <= int(row["document_title_index"]) <= target.end]
        if not evidence_rows:
            result.missing_reasons.append("evidence_window.empty")
            return result
        if not target_rows:
            result.missing_reasons.append("target_range.empty")
            return result

        source_arc_payload = source_arc_payload or self._load_source_arc_payload(book_id=book_id)
        source_arc_index = self._source_arc_index(source_arc_payload)
        character_context = self._character_context(conn, book_id=book_id, target=target)
        world_context = self._world_context(conn, book_id=book_id)
        evidence_digest = self._evidence_digest(evidence_rows=evidence_rows, character_context=character_context, world_context=world_context)

        for row in target_rows:
            title_index = int(row["document_title_index"])
            if not overwrite_committed and self._row_status(row, "summary_status") == "committed":
                result.skipped_title_indexes.append(title_index)
                continue
            role_context = source_arc_index.get(title_index, {})
            summary_md = self._committed_summary(row=row, evidence_digest=evidence_digest, role_context=role_context)
            summary_short = self._committed_short(row=row, role_context=role_context)
            outline_update = self._committed_outline_update(row=row, role_context=role_context, summary_short=summary_short)
            changed = self.chapters_repo.mark_committed(
                conn,
                book_id=book_id,
                document_title_index=title_index,
                summary_md=summary_md,
                summary_short=summary_short,
                outline_update=outline_update,
                evidence_window=evidence.as_text(),
                target_range=target.as_text(),
                updated_at=self.now_factory(),
                overwrite_committed=overwrite_committed,
            )
            if changed:
                result.committed_title_indexes.append(title_index)
            else:
                result.skipped_title_indexes.append(title_index)

        result.success = bool(result.committed_title_indexes or result.skipped_title_indexes)
        return result

    def commit_from_source_arc_map(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        source_arc_payload: dict[str, Any] | None = None,
        overwrite_committed: bool = False,
    ) -> SummaryOutlineCommitResult:
        payload = source_arc_payload or self._load_source_arc_payload(book_id=book_id)
        if not payload:
            return SummaryOutlineCommitResult(
                success=False,
                book_id=book_id,
                evidence_window="",
                target_range="",
                missing_reasons=["source_arc_map.missing"],
            )
        arcs = payload.get("arcs")
        if not isinstance(arcs, list) or not arcs:
            return SummaryOutlineCommitResult(
                success=False,
                book_id=book_id,
                evidence_window="",
                target_range="",
                missing_reasons=["source_arc_map.empty"],
            )
        aggregate = SummaryOutlineCommitResult(success=True, book_id=book_id, evidence_window="", target_range="")
        for arc in arcs:
            if not isinstance(arc, dict):
                continue
            try:
                arc_range = TitleIndexRange.from_value(
                    {
                        "start_document_title_index": arc.get("start_document_title_index"),
                        "end_document_title_index": arc.get("end_document_title_index"),
                    }
                )
            except (TypeError, ValueError):
                continue
            role_items = arc.get("chapter_role_map")
            target_indexes = [
                int(item.get("document_title_index"))
                for item in role_items
                if isinstance(item, dict) and _safe_int(item.get("document_title_index")) is not None
            ] if isinstance(role_items, list) else list(range(arc_range.start, arc_range.end + 1))
            for title_index in target_indexes:
                partial = self.commit_window(
                    conn,
                    book_id=book_id,
                    evidence_window=arc_range,
                    target_range=TitleIndexRange(title_index, title_index),
                    source_arc_payload=payload,
                    overwrite_committed=overwrite_committed,
                )
                aggregate.committed_title_indexes.extend(partial.committed_title_indexes)
                aggregate.skipped_title_indexes.extend(partial.skipped_title_indexes)
                aggregate.missing_reasons.extend(partial.missing_reasons)
        aggregate.evidence_window = "source_arc_map"
        aggregate.target_range = "source_arc_map"
        aggregate.success = bool(aggregate.committed_title_indexes or aggregate.skipped_title_indexes)
        if not aggregate.success and not aggregate.missing_reasons:
            aggregate.missing_reasons.append("source_arc_map.no_matching_chapters")
        return aggregate

    def _committed_summary(self, *, row: sqlite3.Row, evidence_digest: str, role_context: dict[str, str]) -> str:
        summary_md = str(row["summary_md"] or row["summary_short"] or "").strip()
        sections = _parse_summary_sections(summary_md)
        if not sections:
            sections["剧情事件链"] = [safe_excerpt(summary_md, 360) or "本章事件需结合上下文继续补全。"]
        sections["结构功能/节奏"] = self._structure_lines(row=row, role_context=role_context, evidence_digest=evidence_digest)
        return _render_summary_sections(sections)

    def _committed_short(self, *, row: sqlite3.Row, role_context: dict[str, str]) -> str:
        base = normalize_whitespace(str(row["summary_short"] or row["summary_md"] or ""))
        role = role_context.get("role") or self._infer_role(base)
        short = safe_excerpt(base, 96) if base else f"{row['chapter_title']} 的剧情位置完成复核。"
        return f"{short}（结构定稿：{role}）"

    def _committed_outline_update(self, *, row: sqlite3.Row, role_context: dict[str, str], summary_short: str) -> dict[str, Any]:
        title_index = int(row["document_title_index"])
        role = role_context.get("role") or self._infer_role(summary_short)
        pacing = role_context.get("pacing_notes") or self._pacing_for_role(role)
        characters = self._load_json_list(row["mentioned_characters_json"])[:8]
        return {
            "chapter_line": f"[{title_index}] {row['chapter_title']}: {summary_short}；篇章功能={role}；节奏={pacing}",
            "timeline_events": [
                {
                    "label": f"{row['chapter_title']}结构定稿",
                    "participants": characters,
                    "summary": f"{summary_short}；{role}；{pacing}",
                }
            ],
            "commit_source": "window_recompute",
        }

    def _structure_lines(self, *, row: sqlite3.Row, role_context: dict[str, str], evidence_digest: str) -> list[str]:
        role = role_context.get("role") or self._infer_role(f"{row['summary_md']} {evidence_digest}")
        reason = role_context.get("reason") or "基于 evidence_window 内章节梗概、人物档案和世界观概要重新判断。"
        pacing = role_context.get("pacing_notes") or self._pacing_for_role(role)
        source_arc_id = role_context.get("source_arc_id")
        lines = [
            f"- 状态：committed。该结构判断已结合后续窗口复核，不再视为即时 close-read 暂定结论。",
            f"- 篇章功能：{role}。",
            f"- 节奏判断：{pacing}。",
            f"- 判断依据：{reason}",
        ]
        if source_arc_id:
            lines.append(f"- SourceArcMap 辅助证据：{source_arc_id}。窗口定稿与 SourceArcMap 冲突时，已写入的窗口定稿优先。")
        return lines

    def _source_arc_index(self, payload: dict[str, Any] | None) -> dict[int, dict[str, str]]:
        if not payload:
            return {}
        index: dict[int, dict[str, str]] = {}
        arcs = payload.get("arcs")
        if not isinstance(arcs, list):
            return index
        for arc in arcs:
            if not isinstance(arc, dict):
                continue
            role_map = arc.get("chapter_role_map")
            if isinstance(role_map, list):
                for item in role_map:
                    if not isinstance(item, dict) or _safe_int(item.get("document_title_index")) is None:
                        continue
                    title_index = int(item["document_title_index"])
                    index[title_index] = {
                        "source_arc_id": str(arc.get("source_arc_id") or ""),
                        "role": normalize_whitespace(str(item.get("role") or arc.get("source_arc_role") or "")),
                        "reason": normalize_whitespace(str(item.get("reason") or "")),
                        "pacing_notes": normalize_whitespace(str(arc.get("pacing_notes") or "")),
                    }
                continue
            start = _safe_int(arc.get("start_document_title_index"))
            end = _safe_int(arc.get("end_document_title_index"))
            if start is None or end is None:
                continue
            for title_index in range(start, end + 1):
                index[title_index] = {
                    "source_arc_id": str(arc.get("source_arc_id") or ""),
                    "role": normalize_whitespace(str(arc.get("source_arc_role") or "")),
                    "reason": "SourceArcMap arc-level role applies to this chapter range.",
                    "pacing_notes": normalize_whitespace(str(arc.get("pacing_notes") or "")),
                }
        return index

    def _evidence_digest(
        self,
        *,
        evidence_rows: list[sqlite3.Row],
        character_context: str,
        world_context: str,
    ) -> str:
        summaries = [
            f"[{row['document_title_index']}] {row['chapter_title']}: {safe_excerpt(str(row['summary_short'] or row['summary_md'] or ''), 120)}"
            for row in evidence_rows
        ]
        return normalize_whitespace(" ".join([*summaries, character_context, world_context]))

    def _character_context(self, conn: sqlite3.Connection, *, book_id: str, target: TitleIndexRange) -> str:
        rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        selected: list[str] = []
        for row in rows:
            indexes = self._load_json_list(row["chapter_indexes_json"])
            if any(_safe_int(item) is not None and target.start <= int(item) <= target.end for item in indexes):
                selected.append(f"{row['canonical_name']}: {safe_excerpt(str(row['profile_summary_md'] or ''), 160)}")
        return " ".join(selected[:12])

    def _world_context(self, conn: sqlite3.Connection, *, book_id: str) -> str:
        if self.repo_root is None:
            return ""
        row = self.assets_repo.get(conn, book_id=book_id)
        if row is None:
            return ""
        raw_path = str(row["world_summary_path"] or "")
        if not raw_path:
            return ""
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.repo_root / path
        if not path.exists():
            return ""
        return safe_excerpt(path.read_text(encoding="utf-8", errors="replace"), 800)

    def _load_source_arc_payload(self, *, book_id: str) -> dict[str, Any] | None:
        if self.repo_root is None:
            return None
        return SourceArcMappingService(repo_root=self.repo_root).load_exported(book_id=book_id)

    def _infer_role(self, text: str) -> str:
        normalized = normalize_whitespace(text)
        if any(keyword in normalized for keyword in ("高潮", "决战", "危机", "爆发")):
            return "高潮"
        if any(keyword in normalized for keyword in ("收束", "告别", "余波", "结束")):
            return "收束"
        if any(keyword in normalized for keyword in ("设定", "规则", "世界", "能力", "真相")):
            return "设定揭示"
        if any(keyword in normalized for keyword in ("日常", "关系", "闲聊", "情绪", "和解")):
            return "日常关系"
        if any(keyword in normalized for keyword in ("前往", "抵达", "准备", "等待", "过渡")):
            return "过渡缓冲"
        return "主线推进"

    def _pacing_for_role(self, role: str) -> str:
        if role in {"日常关系", "过渡缓冲"}:
            return "低冲突、重铺垫，承接人物状态与后续转场。"
        if role == "高潮":
            return "高冲突密度，承担阶段性爆发或危机推进。"
        if role == "设定揭示":
            return "信息密度较高，优先服务规则、真相或世界观确认。"
        if role == "收束":
            return "回收前序事件并整理后续状态。"
        return "稳定推进主线，兼顾行动结果和下一步压力。"

    def _row_status(self, row: sqlite3.Row, column: str) -> str:
        try:
            value = row[column]
        except (IndexError, KeyError):
            return "provisional"
        text = str(value or "provisional").strip()
        return text if text in {"provisional", "committed"} else "provisional"

    def _load_json_list(self, raw_value: object) -> list[Any]:
        if not raw_value:
            return []
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return []
        return list(value) if isinstance(value, list) else []


def _parse_summary_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current and line:
            sections.setdefault(current, []).append(line)
    return sections


def _render_summary_sections(sections: dict[str, list[str]]) -> str:
    preferred_order = ("剧情事件链", "人物状态/关系变化", "关键信息/设定", "结构功能/节奏")
    ordered_names = [name for name in preferred_order if name in sections]
    ordered_names.extend(name for name in sections if name not in ordered_names)
    lines: list[str] = []
    for name in ordered_names:
        body = [line for line in sections.get(name, []) if str(line).strip()]
        if not body:
            continue
        lines.extend([f"## {name}", *body, ""])
    return "\n".join(lines).strip() + "\n"


def _safe_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
