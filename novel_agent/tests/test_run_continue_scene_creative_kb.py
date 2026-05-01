from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.fragment_clusters_repo import FragmentClustersRepo
from novel_agent.app.run_continue_scene import (
    _augment_prompt_with_creative_kb,
    _maybe_run_creative_kb_retrieval,
)
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, FragmentCluster, StyleFeatures
from novel_agent.runs import RunLayout, RunWriter


def _card() -> FragmentCard:
    return FragmentCard(
        fragment_id="frag-1",
        doc_id="doc-1",
        document_title="第十章",
        document_title_index="10",
        cluster_id="cluster-1",
        is_cluster_representative=True,
        source_path="/tmp/source.md",
        source_offsets=(0, 64),
        source_excerpt="她在雨里停顿了一下，没有把告别说满。",
        content_summary="雨夜里的克制型告别停顿。",
        narrative_function=["收束", "情绪沉浸"],
        narrative_function_text="通过停顿收束关系张力。",
        scene_space_tags=["雨夜"],
        event_tags=["告别"],
        emotion_tags=["克制", "悲伤"],
        emotion_mechanism_text="通过停顿和动作压住悲伤。",
        expression_mode_tags=["动作描写"],
        preferred_tags=["雨天", "告别"],
        pov_mode="近距离第三人称",
        character_focus=["林清"],
        character_temperament=["克制"],
        character_relation_text="处在未和解的离别边缘。",
        relationship_state=["未和解"],
        continuity_phase="冲突后收束",
        style_features=StyleFeatures(
            sentence_rhythm="短句偏多",
            dialogue_density="低",
            interiority_density="高",
            imagery_density="中",
        ),
        style_profile_text="短句、低对白、高内心密度。",
        transferability_score=0.9,
        context_dependency_level="low",
    )


def _seed_chapter(conn, *, book_id: str, chapter_index: int = 10) -> None:
    ChaptersRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "document_title_index": chapter_index,
            "chapter_title": f"第{chapter_index}章 雨中对话",
            "source_doc_start_id": 1,
            "source_doc_end_id": 1,
            "source_doc_count": 1,
            "source_total_chars": 24,
            "summary_intermediate": ["两人停在雨里，关系进入收束前的短暂停顿。"],
            "summary_md": "两人停在雨里，关系进入收束前的短暂停顿。",
            "summary_short": "雨中停顿",
            "importance_score": 8,
            "importance_reason": "当前关系转折前的关键章节。",
            "related_chapters": [],
            "mentioned_characters": ["林清"],
            "world_update": {},
            "outline_update": {},
            "close_read_run_id": "seed",
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _seed_character_profile(conn, *, book_id: str, canonical_name: str = "林清") -> None:
    CharacterProfilesRepo().upsert(
        conn,
        {
            "book_id": book_id,
            "canonical_name": canonical_name,
            "aliases": ["小清"],
            "profile_summary_md": "情绪克制，遇到重大情感冲突时会先压住表达。",
            "personality": ["克制"],
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
            "importance_score": 9,
            "profile_version": 1,
            "created_at": "now",
            "updated_at": "now",
        },
    )


def _seed_book_assets(conn, *, book_id: str, repo_root: Path) -> None:
    world_summary_path = repo_root / "memory" / "worlds" / f"{book_id}.world_summary.md"
    outline_path = repo_root / "memory" / "outlines" / f"{book_id}.outline.md"
    world_summary_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    world_summary_path.write_text("故事发生在现代都市，没有超自然设定。", encoding="utf-8")
    outline_path.write_text("主线推进到误解后的对峙与关系收束阶段。", encoding="utf-8")
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


def test_maybe_run_creative_kb_retrieval_writes_run_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "novel.db"
    runs_dir = tmp_path / "runs"
    writer = RunWriter(layout=RunLayout(base_dir=runs_dir))
    run_id = "run-1"
    db = NovelAgentDB(db_path)
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(conn, [_card()])
        clusters_repo.upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="cluster-1",
                    cluster_theme="雨夜告别停顿",
                    representative_fragment_id="frag-1",
                    member_count=1,
                    dedup_reason="singleton",
                )
            ],
        )
        conn.commit()

    scene_plan_path = tmp_path / "scene_plan.json"
    scene_plan_path.write_text(
        json.dumps(
            {
                "goal": "续写一段克制型离别前停顿",
                "emotional_goal": "压住悲伤",
                "conflict_goal": "保持表面平静",
                "current_relationship_state": ["未和解"],
                "forbidden": ["突然表白"],
                "style_reference_query": {
                    "narrative_function": ["收束", "情绪沉浸"],
                    "emotion_mode": ["克制", "悲伤"],
                    "character_temperament": ["克制"],
                    "style_need": ["短句", "低对白"],
                },
                "retrieval_hints": {
                    "preferred_tags": ["雨天", "告别"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        creative_kb_db=str(db_path),
        anchor_context="上一段写到她握紧伞柄。",
        recent_window_summary="当前处于误解后的短暂对峙，需要一段收束前的停顿。",
        goal="续写一段克制型离别前停顿",
        book_id=None,
        document_title_index=None,
        previous_generated_segment="她想开口，却又停住。",
        character_hit=["林清"],
        related_character_name=[],
        timeline_hit=["第十章"],
        lore_hit=["雨夜"],
        scene_plan_json=str(scene_plan_path),
        include_coarse_result=False,
    )

    payload = _maybe_run_creative_kb_retrieval(args=args, run_id=run_id, writer=writer)

    assert payload is not None
    assert payload["rerank_result"]["selected_fragment_ids"] == ["frag-1"]
    assert (runs_dir / run_id / "scene_brief.json").exists()
    assert (runs_dir / run_id / "retrieval_bundle.json").exists()
    assert (runs_dir / run_id / "writer_input_bundle.json").exists()
    retrieval_bundle = json.loads((runs_dir / run_id / "retrieval_bundle.json").read_text(encoding="utf-8"))
    assert retrieval_bundle["data"]["rerank_result"]["selected_fragment_ids"] == ["frag-1"]
    writer_input_bundle = json.loads((runs_dir / run_id / "writer_input_bundle.json").read_text(encoding="utf-8"))
    assert writer_input_bundle["data"]["scene_brief"]["scene_objective"] == "续写一段克制型离别前停顿"
    assert writer_input_bundle["data"]["reference_fragments"][0]["fragment_id"] == "frag-1"


def test_augment_prompt_with_creative_kb_includes_reference_material() -> None:
    prompt = "继续写这一段。"
    payload = {
        "rerank_result": {
            "selected_fragment_ids": ["frag-1"],
        },
        "writer_input_bundle": {
            "scene_brief": {
                "scene_objective": "寻找一段克制型离别参考",
                "emotional_goal": "压住悲伤",
                "conflict_goal": "保持表面平静",
                "narrative_function": ["收束"],
                "emotion_mode": ["克制"],
                "style_need": ["短句"],
            },
            "reference_fragments": [
                {
                    "fragment_id": "frag-1",
                    "source_excerpt": "她在雨里停顿了一下，没有把告别说满。",
                    "content_summary": "雨夜里的克制型告别停顿。",
                    "style_profile_text": "短句、低对白、高内心密度。",
                }
            ],
            "context_payload": {
                "chapter_context": [
                    {
                        "document_title_index": "10",
                        "chapter_title": "第十章 雨中对话",
                        "summary_md": "两人停在雨里，关系进入收束前的短暂停顿。",
                        "importance_score": 8,
                    }
                ],
                "world_summary_md": "故事发生在现代都市，没有超自然设定。",
                "character_profiles": [
                    {
                        "canonical_name": "林清",
                        "profile_summary_md": "情绪克制，遇到重大情感冲突时会先压住表达。",
                        "aliases": ["小清"],
                        "importance_score": 9,
                    }
                ],
                "story_outline_md": "主线推进到误解后的对峙与关系收束阶段。",
                "missing_context": [],
            },
        },
    }

    augmented = _augment_prompt_with_creative_kb(prompt, payload)

    assert "Creative KB Retrieval Context:" in augmented
    assert "selected_fragment_ids: frag-1" in augmented
    assert "excerpt: 她在雨里停顿了一下，没有把告别说满。" in augmented
    assert "第十章 雨中对话" in augmented
    assert "world_summary_md: 故事发生在现代都市，没有超自然设定。" in augmented
    assert "主线推进到误解后的对峙与关系收束阶段。" in augmented
    assert augmented.endswith("User Task:\n继续写这一段。")


def test_maybe_run_creative_kb_retrieval_end_to_end_with_memory_context(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "novel.db"
    runs_dir = tmp_path / "runs"
    writer = RunWriter(layout=RunLayout(base_dir=runs_dir))
    run_id = "run-e2e"
    db = NovelAgentDB(db_path)
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    book_id = "book-1"
    monkeypatch.chdir(tmp_path)

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(conn, [_card()])
        clusters_repo.upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="cluster-1",
                    cluster_theme="雨夜告别停顿",
                    representative_fragment_id="frag-1",
                    member_count=1,
                    dedup_reason="singleton",
                )
            ],
        )
        _seed_chapter(conn, book_id=book_id)
        _seed_character_profile(conn, book_id=book_id)
        _seed_book_assets(conn, book_id=book_id, repo_root=tmp_path)
        conn.commit()

    scene_plan_path = tmp_path / "scene_plan.json"
    scene_plan_path.write_text(
        json.dumps(
            {
                "goal": "续写一段克制型离别前停顿",
                "emotional_goal": "压住悲伤",
                "conflict_goal": "保持表面平静",
                "current_relationship_state": ["未和解"],
                "forbidden": ["突然表白"],
                "style_reference_query": {
                    "narrative_function": ["收束", "情绪沉浸"],
                    "emotion_mode": ["克制", "悲伤"],
                    "character_temperament": ["克制"],
                    "style_need": ["短句", "低对白"],
                },
                "retrieval_hints": {
                    "preferred_tags": ["雨天", "告别"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        creative_kb_db=str(db_path),
        anchor_context="上一段写到她握紧伞柄。",
        recent_window_summary="当前处于误解后的短暂对峙，需要一段收束前的停顿。",
        goal="续写一段克制型离别前停顿",
        book_id=book_id,
        document_title_index="10",
        previous_generated_segment="她想开口，却又停住。",
        character_hit=["林清"],
        related_character_name=["林清"],
        timeline_hit=["第十章"],
        lore_hit=["雨夜"],
        scene_plan_json=str(scene_plan_path),
        include_coarse_result=False,
    )

    payload = _maybe_run_creative_kb_retrieval(args=args, run_id=run_id, writer=writer)

    assert payload is not None
    bundle = payload["writer_input_bundle"]
    assert bundle["reference_fragments"][0]["fragment_id"] == "frag-1"
    assert bundle["context_payload"]["chapter_context"][0]["chapter_title"] == "第10章 雨中对话"
    assert bundle["context_payload"]["world_summary_md"] == "故事发生在现代都市，没有超自然设定。"
    assert bundle["context_payload"]["character_profiles"][0]["canonical_name"] == "林清"
    assert bundle["context_payload"]["story_outline_md"] == "主线推进到误解后的对峙与关系收束阶段。"
    assert bundle["context_payload"]["missing_context"] == []


def test_maybe_run_creative_kb_retrieval_degrades_when_memory_assets_missing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "novel.db"
    runs_dir = tmp_path / "runs"
    writer = RunWriter(layout=RunLayout(base_dir=runs_dir))
    run_id = "run-missing-memory"
    db = NovelAgentDB(db_path)
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()
    book_id = "book-missing"
    monkeypatch.chdir(tmp_path)

    with db.connect() as conn:
        db.init_schema(conn)
        init_creative_kb_schema(conn)
        cards_repo.upsert_cards(conn, [_card()])
        clusters_repo.upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="cluster-1",
                    cluster_theme="雨夜告别停顿",
                    representative_fragment_id="frag-1",
                    member_count=1,
                    dedup_reason="singleton",
                )
            ],
        )
        _seed_chapter(conn, book_id=book_id)
        conn.commit()

    scene_plan_path = tmp_path / "scene_plan.json"
    scene_plan_path.write_text(
        json.dumps(
            {
                "goal": "续写一段克制型离别前停顿",
                "emotional_goal": "压住悲伤",
                "conflict_goal": "保持表面平静",
                "current_relationship_state": ["未和解"],
                "forbidden": ["突然表白"],
                "style_reference_query": {
                    "narrative_function": ["收束", "情绪沉浸"],
                    "emotion_mode": ["克制", "悲伤"],
                    "character_temperament": ["克制"],
                    "style_need": ["短句", "低对白"],
                },
                "retrieval_hints": {
                    "preferred_tags": ["雨天", "告别"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        creative_kb_db=str(db_path),
        anchor_context="上一段写到她握紧伞柄。",
        recent_window_summary="当前处于误解后的短暂对峙，需要一段收束前的停顿。",
        goal="续写一段克制型离别前停顿",
        book_id=book_id,
        document_title_index="10",
        previous_generated_segment="她想开口，却又停住。",
        character_hit=["林清"],
        related_character_name=["林清"],
        timeline_hit=["第十章"],
        lore_hit=["雨夜"],
        scene_plan_json=str(scene_plan_path),
        include_coarse_result=False,
    )

    payload = _maybe_run_creative_kb_retrieval(args=args, run_id=run_id, writer=writer)

    assert payload is not None
    bundle = payload["writer_input_bundle"]
    assert bundle["reference_fragments"][0]["fragment_id"] == "frag-1"
    missing_context = bundle["context_payload"]["missing_context"]
    assert "book_assets.missing" in missing_context
    assert "character_profiles.none_found" in missing_context
    assert bundle["context_payload"]["world_summary_md"]
    assert bundle["context_payload"]["story_outline_md"]
    assert (runs_dir / run_id / "writer_input_bundle.json").exists()
