from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from novel_agent.app.orchestrators import WriterLayeredGenerationOrchestrator
from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, StyleFeatures
from novel_agent.runs.layout import RunLayout
from novel_agent.runs.writer import RunWriter


class FakeWriterModelClient:
    """Deterministic test adapter; production no-model paths must not use this."""

    def __init__(self) -> None:
        self.settings = SimpleNamespace(dry_run=False)
        self.json_calls: list[tuple[str, str]] = []
        self.text_calls: list[tuple[str, str]] = []

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ) -> tuple[dict[str, Any] | list[Any], str]:
        _ = use_fallback_on_error
        self.json_calls.append((system_prompt, user_prompt))
        payload = fallback_factory()
        return payload, json.dumps(payload, ensure_ascii=False)

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_text: str | None = None,
    ) -> str:
        self.text_calls.append((system_prompt, user_prompt))
        if fallback_text is not None:
            return fallback_text
        return "测试正文。"


class ClimaxAnalyzerModelClient(FakeWriterModelClient):
    def __init__(self, climax_payload: dict[str, Any]) -> None:
        super().__init__()
        self.climax_payload = climax_payload

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback_factory,
        use_fallback_on_error: bool = False,
    ) -> tuple[dict[str, Any] | list[Any], str]:
        self.json_calls.append((system_prompt, user_prompt))
        if "高潮设想分析器" in system_prompt:
            return dict(self.climax_payload), json.dumps(self.climax_payload, ensure_ascii=False)
        return super().generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=fallback_factory,
            use_fallback_on_error=use_fallback_on_error,
        )


def _seed_assets(conn, *, book_id: str, repo_root: Path) -> None:
    world_summary_path = repo_root / "memory" / "worlds" / f"{book_id}.world_summary.md"
    outline_path = repo_root / "memory" / "outlines" / f"{book_id}.outline.md"
    world_summary_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    world_summary_path.write_text(
        "# 世界观概要\n\n## 能力体系\n\n- 现有体系不能无代价突破。\n",
        encoding="utf-8",
    )
    outline_path.write_text(
        "# 故事大纲\n\n## 主线概览\n- 旧案调查仍未结束。\n\n## 当前未解问题\n- 更高层黑手未现身。\n",
        encoding="utf-8",
    )
    AssetsRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "source_root": str(repo_root),
            "world_markdown_path": "",
            "world_summary_path": str(world_summary_path),
            "outline_markdown_path": str(outline_path),
            "toc_markdown": "",
            "toc_source_path": "",
            "debug_export_path": "",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _seed_document(conn, *, book_id: str) -> None:
    DocumentsRepo().insert_document(
        conn,
        {
            "book_id": book_id,
            "path": "docs/chapter-10.md",
            "scope": "docs",
            "title": "第十章 雨夜",
            "document_title": "第十章 雨夜",
            "document_title_index": 10,
            "inferred_chapter_no": 10,
            "content": "沈青在雨夜继续追查旧案，仍然需要援军接应。",
            "content_chars": 24,
            "character_keywords": ["沈青"],
            "content_tags": ["雨夜", "调查"],
            "source_path": "docs/chapter-10.md",
            "source_file_name": "chapter-10.md",
            "source_start_offset": 0,
            "source_end_offset": 24,
            "ingestion_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _seed_profile(conn, *, book_id: str, canonical_name: str) -> None:
    CharacterProfilesRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "canonical_name": canonical_name,
            "aliases": [],
            "profile_summary_md": f"# {canonical_name}\n\n- 已建档人物。\n",
            "personality": [],
            "occupations": [],
            "age_timeline": [],
            "abilities": [],
            "recent_activity": [],
            "relationships": [],
            "chapter_indexes": [10],
            "first_seen_doc_id": 1,
            "last_seen_doc_id": 1,
            "first_seen_title_index": 10,
            "last_seen_title_index": 10,
            "importance_score": 8,
            "profile_version": 1,
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _seed_fragment_card(conn) -> None:
    FragmentCardsRepo().upsert_cards(
        conn,
        [
            FragmentCard(
                fragment_id="frag-1",
                doc_id="1",
                document_title="第十章 雨夜",
                document_title_index="10",
                cluster_id=None,
                is_cluster_representative=False,
                source_path="docs/chapter-10.md",
                source_offsets=(0, 24),
                source_excerpt="沈青在雨夜继续追查旧案。",
                content_summary="追查旧案的承接桥段。",
                narrative_function=["承接推进"],
                narrative_function_text="承接旧案调查并抬高压力。",
                emotion_tags=["紧张"],
                emotion_mechanism_text="通过持续追踪与外部压迫制造紧张。",
                character_temperament=["克制"],
                character_relation_text="关系仍处在谨慎合作阶段。",
                relationship_state=["谨慎合作"],
                style_features=StyleFeatures(
                    sentence_rhythm="短句偏多",
                    dialogue_density="低",
                    interiority_density="中",
                    imagery_density="低",
                ),
                style_profile_text="克制推进，低对白。",
                transferability_score=0.7,
                context_dependency_level="medium",
            )
        ],
    )


def _seed_knowledge_docs(repo_root: Path) -> None:
    docs_dir = repo_root / "novel_agent" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "story_structure_knowledge_base.md").write_text(
        "故事圆环适合承上启下，批次内宜控制单章主功能。",
        encoding="utf-8",
    )
    (docs_dir / "relationship_arc_knowledge_base.md").write_text(
        "关系推进应先共同危机，再公开站队，最后才进入有限信任。",
        encoding="utf-8",
    )


def _build_orchestrator(tmp_path: Path) -> tuple[NovelAgentDB, WriterLayeredGenerationOrchestrator]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _seed_knowledge_docs(repo_root)
    db = NovelAgentDB(tmp_path / "writer_layers.db")
    run_writer = RunWriter(layout=RunLayout(base_dir=tmp_path / "runs"))
    orchestrator = WriterLayeredGenerationOrchestrator(
        repo_root=repo_root,
        run_writer=run_writer,
        model_client=FakeWriterModelClient(),  # type: ignore[arg-type]
    )
    return db, orchestrator


def test_check_modeling_status_blocks_when_modeling_is_incomplete(tmp_path: Path) -> None:
    db, orchestrator = _build_orchestrator(tmp_path)

    with db.connect() as conn:
        db.init_schema(conn)
        status = orchestrator.check_modeling_status(conn, book_id="book-incomplete")

    assert status.ready_for_continuation is False
    assert "documents.not_indexed" in status.missing_modeling_steps
    assert "memory.character_profiles" in status.missing_modeling_steps
    assert "creative_kb.fragment_cards" not in status.missing_modeling_steps


def test_check_modeling_status_treats_creative_kb_as_advisory(tmp_path: Path) -> None:
    db, orchestrator = _build_orchestrator(tmp_path)
    book_id = "book-no-kb"

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        _seed_profile(conn, book_id=book_id, canonical_name="沈青")
        conn.commit()

        status = orchestrator.check_modeling_status(conn, book_id=book_id)

    checks = {item.name: item for item in status.checks}
    assert status.ready_for_continuation is True
    assert checks["creative_kb"].ready is False
    assert "creative_kb.fragment_cards" not in status.missing_modeling_steps


def test_check_modeling_status_reports_optional_structure_artifacts_without_blocking(tmp_path: Path) -> None:
    db, orchestrator = _build_orchestrator(tmp_path)
    book_id = "book-optional"

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        _seed_profile(conn, book_id=book_id, canonical_name="沈青")
        _seed_fragment_card(conn)
        conn.commit()

        missing_optional_status = orchestrator.check_modeling_status(conn, book_id=book_id)

    missing_checks = {item.name: item for item in missing_optional_status.checks}
    assert missing_optional_status.ready_for_continuation is True
    assert missing_checks["source_arc_map"].ready is False
    assert missing_checks["narrative_structure_patterns"].ready is False
    assert "memory.source_arc_map" not in missing_optional_status.missing_modeling_steps
    assert "creative_kb.narrative_structure_patterns" not in missing_optional_status.missing_modeling_steps

    source_arc_path = orchestrator.repo_root / ".memory" / "arcs" / f"{book_id}.source_arc_map.json"
    pattern_path = (
        orchestrator.repo_root
        / ".memory"
        / "structure_patterns"
        / f"{book_id}.narrative_structure_patterns.json"
    )
    source_arc_path.parent.mkdir(parents=True, exist_ok=True)
    pattern_path.parent.mkdir(parents=True, exist_ok=True)
    source_arc_path.write_text('{"arcs": [{"source_arc_id": "source-arc-001"}]}', encoding="utf-8")
    pattern_path.write_text('{"patterns": [{"pattern_id": "pattern-001"}]}', encoding="utf-8")

    with db.connect() as conn:
        db.init_schema(conn)
        ready_optional_status = orchestrator.check_modeling_status(conn, book_id=book_id)

    ready_checks = {item.name: item for item in ready_optional_status.checks}
    source_types = {item.type for item in ready_optional_status.sources}
    assert ready_optional_status.ready_for_continuation is True
    assert ready_checks["source_arc_map"].ready is True
    assert ready_checks["narrative_structure_patterns"].ready is True
    assert "source_arc_map" in source_types
    assert "narrative_structure_pattern" in source_types


def test_prepare_freeze_a_preserves_story_scale_and_climax_inputs(tmp_path: Path) -> None:
    db, orchestrator = _build_orchestrator(tmp_path)
    book_id = "book-scale"

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        _seed_profile(conn, book_id=book_id, canonical_name="沈青")
        _seed_fragment_card(conn)
        conn.commit()

        bundle = orchestrator.prepare_freeze_a(
            conn,
            run_id="run-scale",
            book_id=book_id,
            intent_payload={
                "major_characters": ["沈青"],
                "desired_actions": ["追查旧案线索"],
                "story_scale": {
                    "target_chapter_count": 4,
                    "target_total_chars": 20000,
                    "default_chapter_target_chars": 5000,
                    "pacing_profile": "后段爆发",
                    "length_distribution_notes": "第四章展开",
                },
                "climax_plan": {
                    "conflict_climax": "公开暴露新证据",
                    "emotional_climax": "沈青必须决定是否信任顾迟",
                    "target_chapter_index": 4,
                    "must_foreshadow": ["新证据来源"],
                    "must_not_resolve_before": ["反派身份"],
                    "payoff_expectation": "证明旧案仍有隐情",
                },
            },
        )

    intent = bundle["continuation_intent"]
    plan = bundle["book_continuation_plan"]
    assert intent["story_scale"]["target_total_chars"] == 20000
    assert intent["climax_plan"]["conflict_climax"] == "公开暴露新证据"
    assert plan["target_chapter_count"] == 4
    assert plan["target_total_chars"] == 20000
    assert plan["default_chapter_target_chars"] == 5000
    assert plan["climax_plan"]["must_not_resolve_before"] == ["反派身份"]
    assert len(plan["chapter_outline_slots"]) == 4
    assert plan["chapter_outline_slots"][3]["payoff_targets"] == ["证明旧案仍有隐情"]


def test_build_continuation_intent_analyzes_climax_from_user_prompt(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_writer = RunWriter(layout=RunLayout(base_dir=tmp_path / "runs"))
    model_client = ClimaxAnalyzerModelClient(
        {
            "analysis_status": "extracted",
            "conflict_climax": "第二章让旧案证人当面翻供",
            "emotional_climax": "主角决定是否继续信任同伴",
            "target_chapter_index": 2,
            "must_foreshadow": ["证词前后矛盾"],
            "must_not_resolve_before": ["幕后主使身份"],
            "payoff_expectation": "把调查推入下一阶段",
        }
    )
    orchestrator = WriterLayeredGenerationOrchestrator(
        repo_root=repo_root,
        run_writer=run_writer,
        model_client=model_client,  # type: ignore[arg-type]
    )

    intent = orchestrator.build_continuation_intent(
        {
            "desired_actions": ["写两章调查推进，第二章安排证人翻供作为重点转折。"],
            "story_scale": {"target_chapter_count": 2, "default_chapter_target_chars": 3000},
        }
    )

    assert intent.climax_plan["conflict_climax"] == "第二章让旧案证人当面翻供"
    assert intent.climax_plan["target_chapter_index"] == 2
    assert intent.climax_plan["must_foreshadow"] == ["证词前后矛盾"]
    assert any("高潮设想分析器" in call[0] for call in model_client.json_calls)


def test_build_continuation_intent_keeps_no_climax_transition_choice(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_writer = RunWriter(layout=RunLayout(base_dir=tmp_path / "runs"))
    model_client = ClimaxAnalyzerModelClient(
        {
            "analysis_status": "no_climax",
            "climax_mode": "none",
            "no_climax": True,
            "climax_notes": "用户说明本批次只是过渡剧情。",
        }
    )
    orchestrator = WriterLayeredGenerationOrchestrator(
        repo_root=repo_root,
        run_writer=run_writer,
        model_client=model_client,  # type: ignore[arg-type]
    )

    intent = orchestrator.build_continuation_intent(
        {
            "desired_actions": ["没有高潮部分，本批次章节为过渡剧情，只整理线索和人物关系。"],
            "story_scale": {"target_chapter_count": 3, "default_chapter_target_chars": 3000},
        }
    )
    slots = orchestrator._fallback_chapter_outline_slots(
        count=3,
        default_chars=3000,
        highlights=[],
        climax_plan=intent.climax_plan,
    )

    assert intent.climax_plan["no_climax"] is True
    assert intent.climax_plan["climax_mode"] == "none"
    assert all("高潮" not in slot["plot_function"] for slot in slots)


def test_writer_layered_generation_pipeline_supports_review_and_freeze_chain(tmp_path: Path) -> None:
    db, orchestrator = _build_orchestrator(tmp_path)
    book_id = "book-1"

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        _seed_assets(conn, book_id=book_id, repo_root=orchestrator.repo_root)
        _seed_document(conn, book_id=book_id)
        _seed_profile(conn, book_id=book_id, canonical_name="沈青")
        _seed_fragment_card(conn)
        conn.commit()

        freeze_a_bundle = orchestrator.prepare_freeze_a(
            conn,
            run_id="run-1",
            book_id=book_id,
                intent_payload={
                    "major_characters": ["沈青", "顾迟"],
                    "desired_actions": ["安排援军接应并继续追查旧案"],
                    "avoidances": ["不要突然告白"],
                    "preferred_outcome": "阶段性脱险但留下更深疑点",
                    "notes": "需要一个新的反派压力位。",
                    "climax_plan": {
                        "conflict_climax": "援军接应时暴露更高层黑手的压力",
                        "emotional_climax": "沈青决定暂时信任顾迟",
                        "target_chapter_index": 2,
                    },
                },
            character_seed_payloads=[
                {
                    "seed_id": "seed-1",
                    "display_name_hint": "顾迟",
                    "faction": "友方",
                    "core_concept": "外冷内热的情报中间人",
                    "must_keep": ["冷静", "克制"],
                    "must_avoid": ["喧宾夺主"],
                    "relationship_entry": {
                        "target_character": "沈青",
                        "initial_state": "互相试探",
                        "allowed_target_state_in_this_batch": "有限合作",
                    },
                    "world_constraints": ["不得拥有超出现有体系的能力"],
                }
            ],
        )

    requirement_report = freeze_a_bundle["character_requirement_report"]
    assert requirement_report["named_existing_characters"][0]["resolved_to"] == "沈青"
    assert requirement_report["named_new_characters"][0]["name"] == "顾迟"
    assert any(item["slot_type"] == "行动支援位" for item in requirement_report["unfilled_role_slots"])
    assert any(item["slot_type"] == "反派压力位" for item in requirement_report["unfilled_role_slots"])

    freeze_a_paths = orchestrator.confirm_freeze_a(run_id="run-1")
    assert Path(freeze_a_paths["freeze.json"]).exists()

    with db.connect() as conn:
        batch_result = orchestrator.prepare_batch_plan(
            conn,
            run_id="run-1",
            book_id=book_id,
            target_chapter_count=2,
        )
    assert batch_result["review_checkpoint"]["status"] == "needs_review"

    batch_plan_path = Path(orchestrator.run_writer.layout.run_dir("run-1") / "batch_plan.json")
    batch_plan_doc = json.loads(batch_plan_path.read_text(encoding="utf-8"))
    assert batch_plan_doc["data"]["chapters"] == ["chapter-11", "chapter-12"]
    assert "scope_start" not in batch_plan_doc["data"]
    assert "scope_end" not in batch_plan_doc["data"]
    assert "后端已冻结的当前批次章节列表" in orchestrator.model_client.json_calls[-1][1]
    batch_plan_doc["data"]["batch_goal"] = "用户修改后的批次目标"
    batch_plan_path.write_text(json.dumps(batch_plan_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    freeze_b_paths = orchestrator.confirm_batch_plan(run_id="run-1")
    assert Path(freeze_b_paths["freeze.json"]).exists()

    freeze_b_payload = orchestrator._load_frozen_artifact("run-1", "freeze_b", "batch_plan.json")
    assert freeze_b_payload["batch_goal"] == "用户修改后的批次目标"

    chapter_result = orchestrator.prepare_chapter_package(
        run_id="run-1",
        book_id=book_id,
        chapter_count=2,
    )
    assert chapter_result["review_checkpoint"]["status"] == "needs_review"

    chapter_package_path = Path(orchestrator.run_writer.layout.run_dir("run-1") / "chapter_package.json")
    chapter_package_doc = json.loads(chapter_package_path.read_text(encoding="utf-8"))
    chapter_package_doc["data"]["chapters"][0]["title"] = "用户修改后的章节标题"
    chapter_package_path.write_text(json.dumps(chapter_package_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    freeze_c_paths = orchestrator.confirm_chapter_package(run_id="run-1")
    assert Path(freeze_c_paths["freeze.json"]).exists()

    freeze_c_payload = orchestrator._load_frozen_artifact("run-1", "freeze_c", "chapter_package.json")
    assert freeze_c_payload["chapters"][0]["title"] == "用户修改后的章节标题"


def test_prepare_freeze_a_raises_when_modeling_not_ready(tmp_path: Path) -> None:
    db, orchestrator = _build_orchestrator(tmp_path)

    with db.connect() as conn:
        db.init_schema(conn)
        with pytest.raises(ValueError, match="建模状态未满足续写要求"):
            orchestrator.prepare_freeze_a(
                conn,
                run_id="run-blocked",
                book_id="book-blocked",
                intent_payload={"desired_actions": ["继续写"]},
            )
