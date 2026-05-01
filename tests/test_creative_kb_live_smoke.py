from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from novel_agent.app.repos.creative_kb_storage import init_creative_kb_schema
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.repos.fragment_cards_repo import FragmentCardsRepo
from novel_agent.app.repos.fragment_clusters_repo import FragmentClustersRepo
from novel_agent.app.runner.segmentation_runner import SegmentationRunner
from novel_agent.app.schemas.config_schema import SegmentationAgentConfig, SegmentationBookConfig
from novel_agent.app.schemas.creative_kb_schema import FragmentCard, FragmentCluster, SceneBrief, StyleFeatures
from novel_agent.app.services.coarse_retrieval_service import CoarseRetrievalService
from novel_agent.app.services.rerank_service import RerankService

COUPLE_TXT_PATH = Path("couple.txt")
DEEPSEEK_API_FILE = Path("~/deepseek.api")


def _require_live_smoke_enabled() -> None:
    if os.getenv("RUN_DEEPSEEK_CREATIVE_KB_SMOKE") != "1":
        pytest.skip("Set RUN_DEEPSEEK_CREATIVE_KB_SMOKE=1 to enable the creative KB DeepSeek smoke test.")
    if not COUPLE_TXT_PATH.exists():
        pytest.skip(f"Missing smoke input file: {COUPLE_TXT_PATH}")
    if not DEEPSEEK_API_FILE.exists():
        pytest.skip(f"Missing DeepSeek API key file: {DEEPSEEK_API_FILE}")


def _write_input_book(tmp_path: Path) -> Path:
    source_root = tmp_path / "book_source"
    source_root.mkdir()
    target = source_root / "couple.txt"
    target.write_text(COUPLE_TXT_PATH.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return source_root


def _build_fragment_card(*, fragment_id: str, doc_row, cluster_id: str | None, is_rep: bool, rank: int) -> FragmentCard:
    source_excerpt = doc_row.content[:400].strip()
    content_summary = f"creative-smoke-{rank} relationship beat from segmented real document"
    return FragmentCard(
        fragment_id=fragment_id,
        doc_id=str(doc_row.doc_id),
        document_title=doc_row.document_title,
        document_title_index=str(doc_row.document_title_index),
        cluster_id=cluster_id,
        is_cluster_representative=is_rep,
        source_path=doc_row.source_path or doc_row.path,
        source_offsets=(doc_row.source_start_offset, doc_row.source_end_offset),
        source_excerpt=source_excerpt,
        content_summary=content_summary,
        narrative_function=["关系推进", "承接推进"] if rank == 1 else ["情绪沉浸", "承接推进"],
        narrative_function_text=(
            "creative-smoke relationship progression with restrained emotional carry-over"
            if rank == 1
            else "creative-smoke emotional settling after relational tension"
        ),
        scene_space_tags=["现实", "日常"],
        event_tags=["关系互动", "情绪波动"],
        emotion_tags=["克制", "暧昧"] if rank == 1 else ["克制", "低落"],
        emotion_mechanism_text=(
            "creative-smoke restrained emotion expressed through hesitation and subtext"
        ),
        expression_mode_tags=["心理活动", "对白"],
        preferred_tags=["关系", "对话"] if rank == 1 else ["关系", "情绪"],
        pov_mode="近距离第三人称",
        character_focus=[],
        character_temperament=["敏感", "克制"] if rank == 1 else ["克制"],
        character_relation_text="creative-smoke unresolved relationship tension remains active",
        relationship_state=["未和解", "暧昧"] if rank == 1 else ["未和解"],
        continuity_phase="承接阶段",
        style_features=StyleFeatures(
            sentence_rhythm="短句偏多",
            dialogue_density="中",
            interiority_density="中",
            imagery_density="低",
        ),
        style_profile_text="creative-smoke short sentences with restrained dialogue and subtext",
        transferability_score=0.86 if rank == 1 else 0.72,
        context_dependency_level="low" if rank == 1 else "medium",
    )


@pytest.mark.timeout(360)
def test_creative_kb_live_smoke_with_real_segmentation(tmp_path: Path) -> None:
    _require_live_smoke_enabled()

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source_root = _write_input_book(tmp_path)
    db_path = tmp_path / "creative_kb_live.db"
    book_id = "creative-kb-live-smoke"

    config = SegmentationAgentConfig(book=SegmentationBookConfig(book_id=book_id, source_root=source_root.as_posix()))
    config.model.model_type = "OpenAIModel"
    config.model.model_name = "deepseek-chat"
    config.model.base_url = "https://api.deepseek.com"
    config.model.api_key_file = DEEPSEEK_API_FILE.as_posix()
    config.model.api_key_env = "DEEPSEEK_API_KEY"
    config.model.timeout_seconds = 180
    config.runtime.dry_run = False
    config.runtime.resume_from_checkpoint = False
    config.read_strategy.target_chunk_chars_min = 4000
    config.read_strategy.target_chunk_chars_max = 8000
    config.read_strategy.preferred_document_chars_min = 1200
    config.read_strategy.preferred_document_chars_max = 4000

    result = SegmentationRunner(repo_root=repo_root, db_path=db_path, config=config).run()
    assert result.inserted_documents >= 1

    db = NovelAgentDB(db_path)
    docs_repo = DocumentsRepo()
    cards_repo = FragmentCardsRepo()
    clusters_repo = FragmentClustersRepo()

    with db.connect() as conn:
        init_creative_kb_schema(conn)
        documents = docs_repo.fetch_after_doc_id(conn, book_id=book_id)
        assert documents

        primary_doc = documents[0]
        secondary_doc = documents[1] if len(documents) > 1 else documents[0]

        primary_card = _build_fragment_card(
            fragment_id="creative-smoke-frag-1",
            doc_row=primary_doc,
            cluster_id="creative-cluster-a",
            is_rep=True,
            rank=1,
        )
        secondary_card = _build_fragment_card(
            fragment_id="creative-smoke-frag-2",
            doc_row=secondary_doc,
            cluster_id="creative-cluster-b",
            is_rep=True,
            rank=2,
        )
        cards_repo.upsert_cards(conn, [primary_card, secondary_card])
        clusters_repo.upsert_clusters(
            conn,
            [
                FragmentCluster(
                    cluster_id="creative-cluster-a",
                    cluster_theme="creative smoke relationship progression",
                    representative_fragment_id=primary_card.fragment_id,
                    member_count=1,
                    dedup_reason="single representative",
                ),
                FragmentCluster(
                    cluster_id="creative-cluster-b",
                    cluster_theme="creative smoke emotional afterglow",
                    representative_fragment_id=secondary_card.fragment_id,
                    member_count=1,
                    dedup_reason="single representative",
                ),
            ],
        )
        conn.commit()

        fts_hits = cards_repo.search_fts(conn, query_text="creative smoke relationship", representatives_only=True)
        fts_hit_ids = [item.fragment_id for item in fts_hits]
        assert primary_card.fragment_id in fts_hit_ids

        scene_brief = SceneBrief(
            scene_objective="为关系未明的两人寻找一段克制推进的参考桥段",
            emotional_goal="保持克制但允许关系微妙推进",
            conflict_goal="承接上一段张力，不直接化解",
            narrative_function=["关系推进", "承接推进"],
            emotion_mode=["克制", "暧昧"],
            character_temperament=["敏感", "克制"],
            relationship_state=["未和解", "暧昧"],
            style_need=["short sentences", "subtext", "restrained dialogue"],
            must_avoid=["直接告白", "突然和解"],
            preferred_tags=["关系", "对话"],
        )

        coarse = CoarseRetrievalService(candidate_limit=12).retrieve(
            scene_brief=scene_brief,
            fragment_cards=[primary_card, secondary_card],
            fragment_clusters=clusters_repo.list_by_cluster_ids(
                conn,
                cluster_ids=["creative-cluster-a", "creative-cluster-b"],
            ),
            fts_fragment_ids=fts_hit_ids,
        )
        assert primary_card.fragment_id in coarse.candidate_fragment_ids

        candidates = cards_repo.list_by_fragment_ids(conn, fragment_ids=coarse.candidate_fragment_ids)
        rerank = RerankService(top_n=2).rerank(
            scene_brief=scene_brief,
            candidates=candidates,
            anchor_context=primary_doc.content[:300],
            recent_window_summary=primary_doc.content[:500],
        )

    assert rerank.selected_fragment_ids
    assert primary_card.fragment_id in rerank.selected_fragment_ids
    assert rerank.selection_notes == "rule_based_placeholder_rerank"
