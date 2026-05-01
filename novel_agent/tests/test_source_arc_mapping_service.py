from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.schemas.orchestration_schema import MemoryAssemblyBudget, MemoryAssemblyInput
from novel_agent.app.schemas.source_arc_schema import ChapterPlotSummary
from novel_agent.app.services.context_assembly_service import ContextAssemblyService
from novel_agent.app.services.outline_service import OutlineService
from novel_agent.app.services.plot_summary_unit_compression_service import PlotSummaryUnitCompressionService
from novel_agent.app.services.source_arc_mapping_service import SourceArcMappingService
from novel_agent.app.services.world_state_service import WorldStateService


class _SequenceModelClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
        self.calls.append((str(kwargs["system_prompt"]), str(kwargs["user_prompt"])))
        if not self.responses:
            fallback_factory = kwargs["fallback_factory"]
            payload = fallback_factory()
            return payload, "{}"
        payload = self.responses.pop(0)
        return payload, "{}"


def test_plot_summary_compression_uses_overlapped_windows() -> None:
    summaries = [_summary(index, "主线推进，人物继续调查旧案。") for index in range(14)]
    service = PlotSummaryUnitCompressionService(threshold_chars=1, window_size=8, overlap_size=2)

    result = service.compress_if_needed(summaries)

    assert result.used_compression is True
    assert [unit.source_title_indexes for unit in result.units] == [
        list(range(0, 8)),
        list(range(6, 14)),
    ]
    assert result.units[0].overlap_title_indexes == []
    assert result.units[1].overlap_title_indexes == [6, 7]
    assert result.stride == 6


def test_plot_summary_compression_skips_when_under_threshold() -> None:
    summaries = [_summary(index, "短梗概。") for index in range(3)]
    service = PlotSummaryUnitCompressionService(threshold_chars=10_000)

    result = service.compress_if_needed(summaries)

    assert result.used_compression is False
    assert result.units == []


def test_source_arc_mapping_under_threshold_sends_all_summaries_to_model() -> None:
    model_client = _SequenceModelClient(
        [
            {
                "arcs": [
                    {
                        "source_arc_id": "source-arc-0001",
                        "source_arc_title": "日常铺垫到旧案线索",
                        "start_document_title_index": 1,
                        "end_document_title_index": 2,
                        "source_arc_role": "日常关系",
                        "core_events": ["前半段建立日常关系，随后引出旧案调查。"],
                        "main_character_threads": ["主角从生活状态进入调查状态。"],
                        "world_or_rule_reveals": [],
                        "transition_from_previous": "开篇日常进入主线线索",
                        "setup_for_next": "旧案调查继续推进",
                        "pacing_notes": "2 个 chapter 中先铺垫关系，再转入线索。",
                        "chapter_role_map": [
                            {
                                "document_title_index": 1,
                                "chapter_title": "第1章",
                                "role": "日常关系",
                                "reason": "建立生活状态与关系基线。",
                            },
                            {
                                "document_title_index": 2,
                                "chapter_title": "第2章",
                                "role": "主线推进",
                                "reason": "旧案线索推动剧情进入调查。",
                            },
                        ],
                    }
                ]
            }
        ]
    )
    service = SourceArcMappingService(
        repo_root=Path("."),
        model_client=model_client,  # type: ignore[arg-type]
        now_factory=lambda: "now",
    )

    result = service.build(
        book_id="book",
        summaries=[
            _summary(1, "主角在日常生活中和朋友闲聊，关系出现细微变化。"),
            _summary(2, "调查旧案时发现新的组织规则和能力设定。"),
        ],
    )

    assert result.used_compression is False
    assert len(model_client.calls) == 1
    assert "input_type" in model_client.calls[0][1]
    assert "chapter_summaries" in model_client.calls[0][1]
    assert result.arcs[0].source_arc_title == "日常铺垫到旧案线索"
    assert result.arcs[0].pacing_notes == "2 个 chapter 中先铺垫关系，再转入线索。"


def test_source_arc_mapping_over_threshold_model_compresses_windows_before_arc_mapping() -> None:
    model_client = _SequenceModelClient(
        [
            {
                "unit_summary": "模型压缩单元 1：日常关系铺垫后引出调查。",
                "continuity_hooks": ["调查线索延续。"],
                "boundary_events": ["start[0]: 日常开始", "end[7]: 线索出现"],
                "major_character_state_changes": ["主角决定调查。"],
                "relationship_movements": ["同伴信任增强。"],
                "world_or_rule_reveals": ["组织规则被提及。"],
                "uncertainty_notes": [],
            },
            {
                "unit_summary": "模型压缩单元 2：冲突升级并暴露组织规则。",
                "continuity_hooks": ["冲突进入下一阶段。"],
                "boundary_events": ["start[6]: 线索承接", "end[13]: 冲突爆发"],
                "major_character_state_changes": ["主角被迫选择立场。"],
                "relationship_movements": ["同伴关系出现分歧。"],
                "world_or_rule_reveals": ["能力规则被确认。"],
                "uncertainty_notes": [],
            },
            {
                "arcs": [
                    {
                        "source_arc_id": "source-arc-0001",
                        "source_arc_title": "铺垫到冲突升级",
                        "start_document_title_index": 0,
                        "end_document_title_index": 12,
                        "source_arc_role": "冲突升级",
                        "core_events": ["两个压缩单元展示从日常铺垫到冲突爆发。"],
                        "main_character_threads": ["主角从调查者转为冲突参与者。"],
                        "world_or_rule_reveals": ["组织规则和能力规则逐步明确。"],
                        "transition_from_previous": "当前已读范围起点",
                        "setup_for_next": "冲突后果待处理",
                        "pacing_notes": "约 14 个 chapter，经 2 个压缩单元表现铺垫和冲突升级。",
                        "chapter_role_map": [
                            {
                                "document_title_index": 0,
                                "chapter_title": "压缩单元 0-7",
                                "role": "日常关系",
                                "reason": "关系铺垫后引出调查。",
                            },
                            {
                                "document_title_index": 6,
                                "chapter_title": "压缩单元 6-13",
                                "role": "冲突升级",
                                "reason": "承接重叠线索并推进冲突。",
                            },
                        ],
                    }
                ]
            },
        ]
    )
    summaries = [_summary(index, "日常铺垫后，人物继续调查旧案并发现组织规则。") for index in range(14)]
    service = SourceArcMappingService(
        repo_root=Path("."),
        model_client=model_client,  # type: ignore[arg-type]
        compression_service=PlotSummaryUnitCompressionService(
            threshold_chars=1,
            window_size=8,
            overlap_size=2,
            model_client=model_client,  # type: ignore[arg-type]
        ),
        now_factory=lambda: "now",
    )

    result = service.build(book_id="book", summaries=summaries)

    assert result.used_compression is True
    assert [unit.unit_summary for unit in result.plot_summary_units] == [
        "模型压缩单元 1：日常关系铺垫后引出调查。",
        "模型压缩单元 2：冲突升级并暴露组织规则。",
    ]
    assert len(model_client.calls) == 3
    assert "剧情梗概压缩 Agent" in model_client.calls[0][0]
    assert "剧情梗概压缩 Agent" in model_client.calls[1][0]
    assert "Source Arc Mapping Agent" in model_client.calls[2][0]
    assert "plot_summary_units" in model_client.calls[2][1]
    assert result.arcs[0].source_arc_role == "冲突升级"


def test_source_arc_mapping_smoke_compresses_over_8kb_and_exports(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "novel.db")
    book_id = "book-source-arc"
    with db.connect() as conn:
        db.init_schema(conn)
        for index in range(14):
            repeated_summary = "日常对话之后，人物决定继续调查旧案，并发现新的能力规则与组织秘密。" * 18
            _insert_chapter(conn, book_id=book_id, index=index, summary=repeated_summary)
        conn.commit()

        service = SourceArcMappingService(
            repo_root=tmp_path,
            compression_service=PlotSummaryUnitCompressionService(threshold_chars=8 * 1024),
            now_factory=lambda: "2026-05-05T00:00:00+00:00",
        )
        source_arc_map = service.build_from_chapters(conn, book_id=book_id)

    json_path, markdown_path = service.ensure_paths(book_id)
    assert source_arc_map.used_compression is True
    assert len(source_arc_map.plot_summary_units) == 2
    assert source_arc_map.plot_summary_units[1].overlap_title_indexes == [6, 7]
    assert source_arc_map.arcs
    assert json_path.exists()
    assert markdown_path.exists()
    assert "source-arc-0001" in markdown_path.read_text(encoding="utf-8")


def test_context_assembly_includes_exported_source_arc_context(tmp_path: Path) -> None:
    db = NovelAgentDB(tmp_path / "novel.db")
    book_id = "book-context-arc"
    with db.connect() as conn:
        db.init_schema(conn)
        world_path, world_summary_path = WorldStateService(repo_root=tmp_path).ensure_paths(book_id)
        outline_path = OutlineService(repo_root=tmp_path).ensure_path(book_id)
        AssetsRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "source_root": str(tmp_path),
                "world_markdown_path": str(world_path),
                "world_summary_path": str(world_summary_path),
                "outline_markdown_path": str(outline_path),
                "created_at": "now",
                "updated_at": "now",
            },
        )
        for index in range(1, 9):
            summary = "人物日常对话和关系铺垫。" if index < 4 else "世界规则与能力体系被进一步揭示。"
            _insert_chapter(conn, book_id=book_id, index=index, summary=summary)
        source_arc_service = SourceArcMappingService(
            repo_root=tmp_path,
            now_factory=lambda: "2026-05-05T00:00:00+00:00",
        )
        source_arc_service.build_from_chapters(conn, book_id=book_id)
        conn.commit()

        payload = ContextAssemblyService.build_default(repo_root=tmp_path).assemble(
            conn,
            assembly_input=MemoryAssemblyInput(
                book_id=book_id,
                document_title_index="6",
                token_budget=MemoryAssemblyBudget(source_arc_context_chars=2_000),
            ),
        )

    assert payload.source_arc_context
    assert any(item.start_document_title_index <= 6 <= item.end_document_title_index for item in payload.source_arc_context)
    assert payload.to_dict()["source_arc_context"][0]["source_arc_id"].startswith("source-arc-")


def _summary(index: int, text: str) -> ChapterPlotSummary:
    return ChapterPlotSummary(
        document_title_index=index,
        chapter_title=f"第{index}章",
        summary_md=text,
        source_doc_ids=[index],
    )


def _insert_chapter(conn, *, book_id: str, index: int, summary: str) -> None:  # type: ignore[no-untyped-def]
    ChaptersRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "document_title_index": index,
            "chapter_title": f"第{index}章",
            "source_doc_start_id": index,
            "source_doc_end_id": index,
            "source_doc_count": 1,
            "source_total_chars": len(summary),
            "summary_intermediate": [],
            "summary_md": summary,
            "summary_short": summary[:80],
            "importance_score": 5,
            "importance_reason": "",
            "related_chapters": [],
            "mentioned_characters": [],
            "world_update": {},
            "outline_update": {},
            "close_read_run_id": "test",
            "created_at": "now",
            "updated_at": "now",
        },
    )
