from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..constants import DEFAULT_MEMORY_ROOT
from ..prompts.source_arc_prompt import build_source_arc_map_prompt
from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..schemas.source_arc_schema import (
    ChapterPlotSummary,
    PlotSummaryUnit,
    SourceArc,
    SourceArcChapterRole,
    SourceArcMap,
)
from ..utils.text_utils import normalize_whitespace, safe_excerpt
from .plot_summary_unit_compression_service import PlotSummaryUnitCompressionService


ROLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("高潮", ("高潮", "决战", "大战", "爆发", "生死", "危机", "击败", "最终", "崩溃")),
    ("收束", ("收束", "结束", "告别", "回收", "尘埃落定", "余波", "后果")),
    ("设定揭示", ("世界", "规则", "设定", "能力", "组织", "血统", "禁忌", "真相", "秘密", "体系")),
    ("日常关系", ("日常", "生活", "闲聊", "对话", "内心", "情绪", "关系", "信任", "误会", "和解", "告白")),
    ("过渡缓冲", ("前往", "抵达", "离开", "准备", "转场", "过渡", "暂时", "等待", "休整")),
    ("主线推进", ("调查", "追查", "目标", "任务", "线索", "行动", "冲突", "推进", "发现", "决定")),
)


class SourceArcMappingService:
    def __init__(
        self,
        *,
        repo_root: Path,
        chapters_repo: ChaptersRepo | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
        assets_repo: AssetsRepo | None = None,
        compression_service: PlotSummaryUnitCompressionService | None = None,
        model_client: Any | None = None,
        now_factory: Any | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()
        self.assets_repo = assets_repo or AssetsRepo()
        self.model_client = model_client
        self.compression_service = compression_service or PlotSummaryUnitCompressionService(model_client=model_client)
        self.now_factory = now_factory or _utc_now

    def build_from_chapters(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        export: bool = True,
    ) -> SourceArcMap:
        summaries = self.load_chapter_plot_summaries(conn, book_id=book_id)
        character_names = self._load_character_names(conn, book_id=book_id)
        story_outline_md = self._load_story_outline(conn, book_id=book_id)
        world_summary_md = self._load_world_summary(conn, book_id=book_id)
        character_profile_summaries = self._load_character_profile_summaries(conn, book_id=book_id)
        source_arc_map = self.build(
            book_id=book_id,
            summaries=summaries,
            character_names=character_names,
            story_outline_md=story_outline_md,
            world_summary_md=world_summary_md,
            character_profile_summaries=character_profile_summaries,
        )
        if export:
            self.export(source_arc_map)
        return source_arc_map

    def build(
        self,
        *,
        book_id: str,
        summaries: Sequence[ChapterPlotSummary],
        character_names: Sequence[str] = (),
        story_outline_md: str = "",
        world_summary_md: str = "",
        character_profile_summaries: Sequence[str] = (),
    ) -> SourceArcMap:
        ordered_summaries = sorted(summaries, key=lambda item: item.document_title_index)
        compression = self.compression_service.compress_if_needed(ordered_summaries)
        role_items = self._build_role_items(
            summaries=ordered_summaries,
            units=compression.units if compression.used_compression else [],
        )
        fallback_arcs = self._group_role_items_into_arcs(
            book_id=book_id,
            role_items=role_items,
            character_names=character_names,
        )
        arcs = fallback_arcs
        if self._should_use_model():
            arcs = self._build_arcs_with_model(
                book_id=book_id,
                summaries=ordered_summaries,
                plot_summary_units=compression.units if compression.used_compression else [],
                story_outline_md=story_outline_md,
                world_summary_md=world_summary_md,
                character_profile_summaries=character_profile_summaries,
                fallback_arcs=fallback_arcs,
            )
        return SourceArcMap(
            book_id=book_id,
            generated_at=self.now_factory(),
            source_summary_count=len(ordered_summaries),
            used_compression=compression.used_compression,
            compression=compression,
            plot_summary_units=list(compression.units),
            arcs=arcs,
        )

    def export(self, source_arc_map: SourceArcMap) -> tuple[Path, Path]:
        json_path, markdown_path = self.ensure_paths(source_arc_map.book_id)
        json_path.write_text(json.dumps(source_arc_map.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(self.render_markdown(source_arc_map), encoding="utf-8")
        return json_path, markdown_path

    def ensure_paths(self, book_id: str) -> tuple[Path, Path]:
        arcs_dir = self.repo_root / DEFAULT_MEMORY_ROOT / "arcs"
        arcs_dir.mkdir(parents=True, exist_ok=True)
        return (
            arcs_dir / f"{book_id}.source_arc_map.json",
            arcs_dir / f"{book_id}.source_arc_map.md",
        )

    def load_chapter_plot_summaries(self, conn: sqlite3.Connection, *, book_id: str) -> list[ChapterPlotSummary]:
        rows = self.chapters_repo.list_by_book(conn, book_id=book_id)
        summaries: list[ChapterPlotSummary] = []
        for row in rows:
            summary_md = str(row["summary_md"] or "").strip()
            summary_short = str(row["summary_short"] or "").strip()
            if not summary_md and not summary_short:
                continue
            summaries.append(
                ChapterPlotSummary(
                    document_title_index=int(row["document_title_index"]),
                    chapter_title=str(row["chapter_title"] or ""),
                    summary_md=summary_md,
                    summary_short=summary_short,
                    importance_score=int(row["importance_score"] or 0),
                    source_doc_ids=self._source_doc_ids_from_row(row),
                    related_chapters=self._load_json_list_of_dicts(row["related_chapters_json"]),
                )
            )
        return summaries

    def load_exported(self, *, book_id: str) -> dict[str, Any] | None:
        json_path, _ = self.ensure_paths(book_id)
        if not json_path.exists():
            return None
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def render_markdown(self, source_arc_map: SourceArcMap) -> str:
        lines = [
            f"# Source Arc Map: {source_arc_map.book_id}",
            "",
            f"- generated_at: {source_arc_map.generated_at}",
            f"- source_summary_count: {source_arc_map.source_summary_count}",
            f"- used_compression: {source_arc_map.used_compression}",
        ]
        if source_arc_map.used_compression:
            lines.extend(
                [
                    f"- compression_threshold_chars: {source_arc_map.compression.threshold_chars}",
                    f"- plot_summary_units: {len(source_arc_map.plot_summary_units)}",
                ]
            )
        lines.append(f"- structural_status: {source_arc_map.structural_status}")
        for arc in source_arc_map.arcs:
            lines.extend(
                [
                    "",
                    f"## {arc.source_arc_id} {arc.source_arc_title}",
                    "",
                    f"- range: {arc.start_document_title_index}-{arc.end_document_title_index}",
                    f"- role: {arc.source_arc_role}",
                    f"- role_status: {arc.role_status}",
                    f"- evidence_window: {arc.evidence_window or f'{arc.start_document_title_index}-{arc.end_document_title_index}'}",
                    f"- target_range: {arc.target_range or f'{arc.start_document_title_index}-{arc.end_document_title_index}'}",
                    f"- transition_from_previous: {arc.transition_from_previous or 'N/A'}",
                    f"- setup_for_next: {arc.setup_for_next or 'N/A'}",
                    f"- pacing_notes: {arc.pacing_notes}",
                    "",
                    "### Core Events",
                ]
            )
            lines.extend(f"- {item}" for item in arc.core_events)
            if arc.main_character_threads:
                lines.append("")
                lines.append("### Character Threads")
                lines.extend(f"- {item}" for item in arc.main_character_threads)
            if arc.world_or_rule_reveals:
                lines.append("")
                lines.append("### World Or Rule Reveals")
                lines.extend(f"- {item}" for item in arc.world_or_rule_reveals)
            lines.append("")
            lines.append("### Chapter Role Map")
            for item in arc.chapter_role_map:
                lines.append(
                    f"- [{item.document_title_index}] {item.chapter_title} | {item.role} | {item.reason}"
                )
        return "\n".join(lines).strip() + "\n"

    def _build_role_items(
        self,
        *,
        summaries: Sequence[ChapterPlotSummary],
        units: Sequence[PlotSummaryUnit],
    ) -> list[SourceArcChapterRole]:
        if units:
            return [
                SourceArcChapterRole(
                    document_title_index=unit.start_document_title_index,
                    chapter_title=f"压缩单元 {unit.start_document_title_index}-{unit.end_document_title_index}",
                    role=self._infer_role(unit.unit_summary),
                    reason=self._role_reason(unit.unit_summary),
                    evidence_window=f"{unit.start_document_title_index}-{unit.end_document_title_index}",
                    target_range=f"{unit.start_document_title_index}-{unit.end_document_title_index}",
                    source_doc_ids=list(unit.source_doc_ids),
                )
                for unit in units
            ]
        return [
            SourceArcChapterRole(
                document_title_index=item.document_title_index,
                chapter_title=item.chapter_title,
                role=self._infer_role(self._summary_text(item)),
                reason=self._role_reason(self._summary_text(item)),
                evidence_window=f"{item.document_title_index}-{item.document_title_index}",
                target_range=f"{item.document_title_index}-{item.document_title_index}",
                source_doc_ids=list(item.source_doc_ids),
            )
            for item in summaries
        ]

    def _group_role_items_into_arcs(
        self,
        *,
        book_id: str,
        role_items: Sequence[SourceArcChapterRole],
        character_names: Sequence[str],
    ) -> list[SourceArc]:
        if not role_items:
            return []
        groups: list[list[SourceArcChapterRole]] = []
        current: list[SourceArcChapterRole] = [role_items[0]]
        for item in role_items[1:]:
            previous = current[-1]
            if item.role == previous.role:
                current.append(item)
                continue
            groups.append(current)
            current = [item]
        groups.append(current)

        arcs: list[SourceArc] = []
        for index, group in enumerate(groups, start=1):
            role = self._dominant_role(group)
            start_index = group[0].document_title_index
            end_index = group[-1].document_title_index
            source_arc_id = f"source-arc-{index:04d}"
            source_arc_title = self._arc_title(role=role, start_index=start_index, end_index=end_index)
            core_events = [self._role_event_line(item) for item in group]
            arcs.append(
                SourceArc(
                    book_id=book_id,
                    source_arc_id=source_arc_id,
                    source_arc_title=source_arc_title,
                    start_document_title_index=start_index,
                    end_document_title_index=end_index,
                    source_arc_role=role,
                    evidence_window=f"{start_index}-{end_index}",
                    target_range=f"{start_index}-{end_index}",
                    core_events=core_events,
                    main_character_threads=self._character_threads(group, character_names=character_names),
                    world_or_rule_reveals=self._world_reveals(group),
                    transition_from_previous=self._transition_from_previous(arcs[-1] if arcs else None, group),
                    setup_for_next=self._setup_for_next(group),
                    pacing_notes=self._pacing_notes(role=role, group=group),
                    chapter_role_map=list(group),
                )
            )
        return arcs

    def _build_arcs_with_model(
        self,
        *,
        book_id: str,
        summaries: Sequence[ChapterPlotSummary],
        plot_summary_units: Sequence[PlotSummaryUnit],
        story_outline_md: str,
        world_summary_md: str,
        character_profile_summaries: Sequence[str],
        fallback_arcs: Sequence[SourceArc],
    ) -> list[SourceArc]:
        fallback_payload = {
            "arcs": [arc.to_dict() for arc in fallback_arcs],
        }
        system_prompt, user_prompt = build_source_arc_map_prompt(
            book_id=book_id,
            summaries=summaries,
            plot_summary_units=plot_summary_units,
            story_outline_md=story_outline_md,
            world_summary_md=world_summary_md,
            character_profile_summaries=character_profile_summaries,
            fallback_payload=fallback_payload,
        )
        payload, _ = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: fallback_payload,
            use_fallback_on_error=True,
        )
        if not isinstance(payload, dict):
            return list(fallback_arcs)
        raw_arcs = payload.get("arcs")
        if not isinstance(raw_arcs, list):
            return list(fallback_arcs)
        fallback_by_index = {index: arc for index, arc in enumerate(fallback_arcs)}
        arcs: list[SourceArc] = []
        for index, item in enumerate(raw_arcs, start=1):
            if not isinstance(item, dict):
                continue
            fallback_arc = fallback_by_index.get(index - 1)
            parsed = self._arc_from_payload(book_id=book_id, index=index, payload=item, fallback_arc=fallback_arc)
            if parsed is not None:
                arcs.append(parsed)
        return arcs or list(fallback_arcs)

    def _arc_from_payload(
        self,
        *,
        book_id: str,
        index: int,
        payload: dict[str, Any],
        fallback_arc: SourceArc | None,
    ) -> SourceArc | None:
        start_index = self._payload_int(
            payload,
            "start_document_title_index",
            fallback_arc.start_document_title_index if fallback_arc else 0,
        )
        end_index = self._payload_int(
            payload,
            "end_document_title_index",
            fallback_arc.end_document_title_index if fallback_arc else start_index,
        )
        if start_index < 0 and fallback_arc is None:
            return None
        if end_index < start_index:
            end_index = start_index
        role = self._payload_text(payload, "source_arc_role", fallback_arc.source_arc_role if fallback_arc else "主线推进")
        chapter_role_map = self._chapter_role_map_from_payload(
            payload=payload,
            fallback_items=list(fallback_arc.chapter_role_map) if fallback_arc else [],
        )
        return SourceArc(
            book_id=book_id,
            source_arc_id=self._payload_text(payload, "source_arc_id", f"source-arc-{index:04d}"),
            source_arc_title=self._payload_text(
                payload,
                "source_arc_title",
                fallback_arc.source_arc_title if fallback_arc else self._arc_title(role=role, start_index=start_index, end_index=end_index),
            ),
            start_document_title_index=start_index,
            end_document_title_index=end_index,
            source_arc_role=role,
            role_status=self._payload_text(payload, "role_status", fallback_arc.role_status if fallback_arc else "committed"),
            evidence_window=self._payload_text(
                payload,
                "evidence_window",
                fallback_arc.evidence_window if fallback_arc else f"{start_index}-{end_index}",
            ),
            target_range=self._payload_text(
                payload,
                "target_range",
                fallback_arc.target_range if fallback_arc else f"{start_index}-{end_index}",
            ),
            core_events=self._payload_str_list(payload, "core_events", fallback_arc.core_events if fallback_arc else []),
            main_character_threads=self._payload_str_list(
                payload,
                "main_character_threads",
                fallback_arc.main_character_threads if fallback_arc else [],
            ),
            world_or_rule_reveals=self._payload_str_list(
                payload,
                "world_or_rule_reveals",
                fallback_arc.world_or_rule_reveals if fallback_arc else [],
            ),
            transition_from_previous=self._payload_text(
                payload,
                "transition_from_previous",
                fallback_arc.transition_from_previous if fallback_arc else "",
            ),
            setup_for_next=self._payload_text(payload, "setup_for_next", fallback_arc.setup_for_next if fallback_arc else ""),
            pacing_notes=self._payload_text(payload, "pacing_notes", fallback_arc.pacing_notes if fallback_arc else ""),
            chapter_role_map=chapter_role_map,
        )

    def _chapter_role_map_from_payload(
        self,
        *,
        payload: dict[str, Any],
        fallback_items: Sequence[SourceArcChapterRole],
    ) -> list[SourceArcChapterRole]:
        raw_items = payload.get("chapter_role_map")
        if not isinstance(raw_items, list):
            return list(fallback_items)
        parsed: list[SourceArcChapterRole] = []
        fallback_by_index = {index: item for index, item in enumerate(fallback_items)}
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                continue
            fallback = fallback_by_index.get(index)
            title_index = self._payload_int(
                item,
                "document_title_index",
                fallback.document_title_index if fallback else 0,
            )
            if title_index < 0 and fallback is None:
                continue
            parsed.append(
                SourceArcChapterRole(
                    document_title_index=title_index,
                    chapter_title=self._payload_text(item, "chapter_title", fallback.chapter_title if fallback else ""),
                    role=self._payload_text(item, "role", fallback.role if fallback else "主线推进"),
                    reason=self._payload_text(item, "reason", fallback.reason if fallback else ""),
                    role_status=self._payload_text(item, "role_status", fallback.role_status if fallback else "committed"),
                    evidence_window=self._payload_text(
                        item,
                        "evidence_window",
                        fallback.evidence_window if fallback else f"{title_index}-{title_index}",
                    ),
                    target_range=self._payload_text(
                        item,
                        "target_range",
                        fallback.target_range if fallback else f"{title_index}-{title_index}",
                    ),
                    source_doc_ids=self._payload_int_list(item, "source_doc_ids", fallback.source_doc_ids if fallback else []),
                    narrative_function_summary=self._payload_text(
                        item,
                        "narrative_function_summary",
                        fallback.narrative_function_summary if fallback else "",
                    ),
                    emotional_setup_notes=self._payload_str_list(
                        item,
                        "emotional_setup_notes",
                        fallback.emotional_setup_notes if fallback else [],
                    ),
                )
            )
        return parsed or list(fallback_items)

    def _dominant_role(self, group: Sequence[SourceArcChapterRole]) -> str:
        counts = Counter(item.role for item in group)
        return counts.most_common(1)[0][0]

    def _infer_role(self, text: str) -> str:
        normalized = normalize_whitespace(text)
        for role, keywords in ROLE_KEYWORDS:
            if any(keyword in normalized for keyword in keywords):
                return role
        return "主线推进"

    def _role_reason(self, text: str) -> str:
        normalized = normalize_whitespace(text)
        for role, keywords in ROLE_KEYWORDS:
            matched = [keyword for keyword in keywords if keyword in normalized][:3]
            if matched:
                return f"命中{role}线索：" + "、".join(matched)
        return "未命中特定结构词，按主线推进处理"

    def _role_event_line(self, item: SourceArcChapterRole) -> str:
        return f"[{item.document_title_index}] {item.chapter_title}: {item.reason}"

    def _arc_title(self, *, role: str, start_index: int, end_index: int) -> str:
        if start_index == end_index:
            return f"{role}单元（{start_index}）"
        return f"{role}单元（{start_index}-{end_index}）"

    def _character_threads(
        self,
        group: Sequence[SourceArcChapterRole],
        *,
        character_names: Sequence[str],
    ) -> list[str]:
        joined = " ".join(f"{item.chapter_title} {item.reason}" for item in group)
        threads: list[str] = []
        for name in character_names:
            if name and name in joined:
                threads.append(f"{name} 在 {group[0].document_title_index}-{group[-1].document_title_index} 段落中持续出现")
            if len(threads) >= 6:
                break
        if threads:
            return threads
        return ["人物线需结合章节摘要进一步确认"]

    def _world_reveals(self, group: Sequence[SourceArcChapterRole]) -> list[str]:
        reveals = [
            self._role_event_line(item)
            for item in group
            if item.role == "设定揭示" or any(keyword in item.reason for keyword in ("世界", "规则", "设定", "能力", "真相"))
        ]
        return reveals[:6]

    def _transition_from_previous(
        self,
        previous_arc: SourceArc | None,
        group: Sequence[SourceArcChapterRole],
    ) -> str:
        if previous_arc is None:
            return "源作品开篇或当前已读范围的起点"
        return f"由 {previous_arc.source_arc_role} 转入 {group[0].role}"

    def _setup_for_next(self, group: Sequence[SourceArcChapterRole]) -> str:
        last = group[-1]
        return f"[{last.document_title_index}] 后续应关注该段落留下的人物状态、未回收线索与结构转场"

    def _pacing_notes(self, *, role: str, group: Sequence[SourceArcChapterRole]) -> str:
        length = len(group)
        if role in {"日常关系", "过渡缓冲"}:
            return f"低冲突但有铺垫价值，持续 {length} 个结构单元"
        if role == "高潮":
            return f"高强度冲突或危机段，持续 {length} 个结构单元"
        if role == "设定揭示":
            return f"设定信息密度较高，持续 {length} 个结构单元"
        return f"剧情推进段，持续 {length} 个结构单元"

    def _summary_text(self, item: ChapterPlotSummary) -> str:
        return normalize_whitespace(item.summary_md or item.summary_short)

    def _payload_text(self, payload: dict[str, Any], key: str, fallback: str) -> str:
        value = payload.get(key)
        text = normalize_whitespace(str(value or ""))
        return text or fallback

    def _payload_int(self, payload: dict[str, Any], key: str, fallback: int) -> int:
        value = payload.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(fallback)

    def _payload_str_list(self, payload: dict[str, Any], key: str, fallback: Sequence[str]) -> list[str]:
        value = payload.get(key)
        if not isinstance(value, list):
            return list(fallback)
        items = [normalize_whitespace(str(item)) for item in value if normalize_whitespace(str(item))]
        return items or list(fallback)

    def _payload_int_list(self, payload: dict[str, Any], key: str, fallback: Sequence[int]) -> list[int]:
        value = payload.get(key)
        if not isinstance(value, list):
            return list(fallback)
        items: list[int] = []
        for item in value:
            try:
                items.append(int(item))
            except (TypeError, ValueError):
                continue
        return items or list(fallback)

    def _should_use_model(self) -> bool:
        if self.model_client is None:
            return False
        settings = getattr(self.model_client, "settings", None)
        return not bool(getattr(settings, "dry_run", False))

    def _load_story_outline(self, conn: sqlite3.Connection, *, book_id: str) -> str:
        row = self.assets_repo.get(conn, book_id=book_id)
        if row is None:
            return ""
        return self._read_text_path(str(row["outline_markdown_path"] or ""))

    def _load_world_summary(self, conn: sqlite3.Connection, *, book_id: str) -> str:
        row = self.assets_repo.get(conn, book_id=book_id)
        if row is None:
            return ""
        return self._read_text_path(str(row["world_summary_path"] or ""))

    def _load_character_profile_summaries(self, conn: sqlite3.Connection, *, book_id: str) -> list[str]:
        rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        summaries: list[str] = []
        for row in rows:
            name = str(row["canonical_name"] or "").strip()
            summary = normalize_whitespace(str(row["profile_summary_md"] or ""))
            if summary:
                summaries.append(f"{name}: {summary}" if name else summary)
            elif name:
                summaries.append(name)
        return summaries[:24]

    def _read_text_path(self, raw_path: str) -> str:
        if not raw_path:
            return ""
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.repo_root / path
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _source_doc_ids_from_row(self, row: sqlite3.Row) -> list[int]:
        start = int(row["source_doc_start_id"] or 0)
        end = int(row["source_doc_end_id"] or 0)
        if start <= 0 or end <= 0:
            return []
        if end < start:
            return [start]
        if end - start > 512:
            return [start, end]
        return list(range(start, end + 1))

    def _load_json_list_of_dicts(self, raw_value: object) -> list[dict[str, Any]]:
        if not raw_value:
            return []
        try:
            value = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    def _load_character_names(self, conn: sqlite3.Connection, *, book_id: str) -> list[str]:
        rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        return [str(row["canonical_name"] or "").strip() for row in rows if str(row["canonical_name"] or "").strip()]


def select_source_arc_context(
    payload: dict[str, Any],
    *,
    document_title_index: int | None,
    max_chars: int,
) -> list[dict[str, Any]]:
    arcs = payload.get("arcs")
    if not isinstance(arcs, list) or max_chars <= 0:
        return []
    candidates = [arc for arc in arcs if isinstance(arc, dict)]
    if document_title_index is not None:
        containing = [
            arc
            for arc in candidates
            if int(arc.get("start_document_title_index") or 0)
            <= document_title_index
            <= int(arc.get("end_document_title_index") or 0)
        ]
        if containing:
            index = candidates.index(containing[0])
            candidates = candidates[max(0, index - 1) : index + 2]
    selected: list[dict[str, Any]] = []
    used_chars = 0
    for arc in candidates:
        item = _compact_arc_context(arc)
        item_chars = len(json.dumps(item, ensure_ascii=False))
        if selected and used_chars + item_chars > max_chars:
            break
        if not selected and item_chars > max_chars:
            item["core_events"] = [safe_excerpt("；".join(item.get("core_events", [])), limit=max(80, max_chars // 2))]
            item_chars = len(json.dumps(item, ensure_ascii=False))
        selected.append(item)
        used_chars += item_chars
    return selected


def _compact_arc_context(arc: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_arc_id": str(arc.get("source_arc_id") or ""),
        "source_arc_title": str(arc.get("source_arc_title") or ""),
        "start_document_title_index": int(arc.get("start_document_title_index") or 0),
        "end_document_title_index": int(arc.get("end_document_title_index") or 0),
        "source_arc_role": str(arc.get("source_arc_role") or ""),
        "status": str(arc.get("role_status") or arc.get("structural_status") or "committed"),
        "evidence_window": str(arc.get("evidence_window") or ""),
        "target_range": str(arc.get("target_range") or ""),
        "core_events": [safe_excerpt(str(item), limit=160) for item in _list_items(arc.get("core_events"))[:4]],
        "transition_from_previous": safe_excerpt(str(arc.get("transition_from_previous") or ""), limit=160),
        "setup_for_next": safe_excerpt(str(arc.get("setup_for_next") or ""), limit=160),
        "pacing_notes": safe_excerpt(str(arc.get("pacing_notes") or ""), limit=160),
    }


def _list_items(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
