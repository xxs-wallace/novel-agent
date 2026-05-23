from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from novel_agent.app.repos.assets_repo import AssetsRepo
from novel_agent.app.repos.chapters_repo import ChaptersRepo
from novel_agent.app.repos.character_profiles_repo import CharacterProfilesRepo
from novel_agent.app.repos.db import NovelAgentDB
from novel_agent.app.repos.documents_repo import DocumentsRepo
from novel_agent.app.schemas.narrative_inquiry_schema import AnalyzerBudget
from novel_agent.app.services.outline_analyzer_benchmark_service import (
    DEFAULT_ANALYZER_BENCHMARK_TIMEOUT_SECONDS,
    AnalyzerBenchmarkConfig,
    OutlineAnalyzerBenchmarkService,
    build_default_longzu_120kb_config,
)


class ScriptedBenchmarkModel:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, str]] = []

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if not self.outputs:
            raise AssertionError("scripted benchmark model has no more outputs")
        return self.outputs.pop(0)


def _seed_memory(repo_root: Path, *, book_id: str = "bench-book") -> Path:
    db_path = repo_root / ".indexes" / f"{book_id}.db"
    db = NovelAgentDB(db_path)
    now = "2026-05-21T00:00:00Z"
    outline_path = repo_root / ".memory" / "outlines" / f"{book_id}.outline.md"
    world_path = repo_root / ".memory" / "world" / f"{book_id}.summary.md"
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text("# 故事大纲\n\n## 当前问题\n- 甲和乙正在追查秘密。\n", encoding="utf-8")
    world_path.write_text("# 世界观摘要\n调查需要证据，秘密不能无代价揭开。\n", encoding="utf-8")
    with db.connect() as conn:
        db.init_schema(conn)
        AssetsRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "source_root": str(repo_root),
                "world_markdown_path": str(world_path),
                "world_summary_path": str(world_path),
                "outline_markdown_path": str(outline_path),
                "created_at": now,
                "updated_at": now,
            },
        )
        DocumentsRepo().insert_document(
            conn,
            {
                "book_id": book_id,
                "path": "doc-1",
                "content": "甲和乙在雨夜发现秘密线索。",
                "document_title": "第一章",
                "document_title_index": 1,
                "character_keywords": ["甲", "乙"],
                "content_tags": ["秘密"],
                "created_at": now,
                "updated_at": now,
            },
        )
        ChaptersRepo().upsert(
            conn,
            {
                "book_id": book_id,
                "document_title_index": 1,
                "chapter_title": "第一章",
                "source_doc_start_id": 1,
                "source_doc_end_id": 1,
                "source_doc_count": 1,
                "source_total_chars": 14,
                "summary_md": "甲和乙发现秘密线索，但真相尚未揭开。",
                "summary_short": "甲乙发现秘密线索。",
                "mentioned_characters": ["甲", "乙"],
                "outline_update": {
                    "timeline_events": [
                        {
                            "event_id": "event-secret",
                            "label": "秘密线索出现",
                            "summary": "甲和乙发现秘密线索。",
                            "participants": ["甲", "乙"],
                            "source_doc_ids": [1],
                            "source_doc_range": "1",
                        }
                    ]
                },
                "summary_status": "committed",
                "outline_status": "committed",
                "created_at": now,
                "updated_at": now,
            },
        )
        for name, profile in (("甲", "谨慎，重视证据。"), ("乙", "敏感，行动更直接。")):
            CharacterProfilesRepo().upsert(
                conn,
                {
                    "book_id": book_id,
                    "canonical_name": name,
                    "profile_summary_md": profile,
                    "relationships": [],
                    "recent_activity": ["追查秘密线索"],
                    "evidence_level": "confirmed",
                    "created_at": now,
                    "updated_at": now,
                },
            )
        conn.commit()
    return db_path


def _judge_pass_payload() -> str:
    return json.dumps(
        {
            "same_core_conclusion": 4,
            "character_reading_accuracy": 4,
            "worldview_theme_coverage": 4,
            "style_tone_sensitivity": 4,
            "key_evidence_coverage": 3,
            "canon_consistency": 4,
            "hallucination_or_overclaim_penalty": 0,
            "notes": ["Analyzer 与完整原文 baseline 的核心判断接近。"],
        },
        ensure_ascii=False,
    )


def test_outline_analyzer_benchmark_writes_artifacts_and_records_prompt_stats(tmp_path: Path) -> None:
    db_path = _seed_memory(tmp_path)
    source_path = tmp_path / "source.txt"
    source_path.write_text("甲  和\n乙 在雨夜发现秘密线索。", encoding="utf-8")
    model = ScriptedBenchmarkModel(
        [
            "baseline：甲谨慎，乙直接。",
            json.dumps(
                {
                    "status": "need_more_info",
                    "requests": [
                        {
                            "type": "story_detail",
                            "query": "甲和乙发现秘密线索的经过",
                            "purpose": "支撑人物行动推测",
                            "priority": "high",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps({"kept_request_ids": ["req-001"], "rejected_request_ids": []}, ensure_ascii=False),
            json.dumps({"status": "ready_to_answer"}, ensure_ascii=False),
            "Analyzer：甲会继续求证，乙可能主动推进冲突。",
            _judge_pass_payload(),
        ]
    )
    config = AnalyzerBenchmarkConfig(
        source_path=source_path,
        db_path=db_path,
        book_id="bench-book",
        artifact_dir=tmp_path / "runs" / "outline_analyzer",
        run_id="bench-run",
        prompt_set={
            "protagonist_character_and_next_actions": "评价男主角和女主角的人物性格，推测他们之后会采取什么样的行动，或者发生什么样的故事。"
        },
        analyzer_budget=AnalyzerBudget(max_rounds=2),
    )

    result = OutlineAnalyzerBenchmarkService(repo_root=tmp_path, model_client=model).run(config)

    assert result.status == "pass"
    run_dir = result.artifact_dir / "protagonist_character_and_next_actions"
    assert (run_dir / "baseline" / "request_prompt_stats.json").exists()
    assert (run_dir / "analyzer" / "prompt_stats.json").exists()
    assert (run_dir / "judge" / "comparison_report.json").exists()
    baseline_payload = model.calls[0]["user_prompt"]
    assert "甲和乙在雨夜发现秘密线索。" in baseline_payload
    assert "甲  和" not in baseline_payload
    prompt_stats = json.loads((run_dir / "analyzer" / "prompt_stats.json").read_text(encoding="utf-8"))
    assert [item["stage"] for item in prompt_stats["calls"]] == ["loop", "triage", "loop", "final"]
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["prompts"][0]["quality_pass"] is True


def test_default_longzu_120kb_config_uses_large_prompt_timeout() -> None:
    repo_root = Path.cwd()
    config = build_default_longzu_120kb_config(repo_root=repo_root, prompt_ids=["worldview_story_theme"])

    assert config.source_path == repo_root / "novel_agent" / "tests" / "longzu_120kb.txt"
    assert config.source_path.exists()
    assert config.prompt_ids == ["worldview_story_theme"]
    assert config.model_config.timeout_seconds == DEFAULT_ANALYZER_BENCHMARK_TIMEOUT_SECONDS
    assert config.model_config.timeout_seconds >= 600


def test_outline_analyzer_benchmark_reuses_cached_baseline(tmp_path: Path) -> None:
    db_path = _seed_memory(tmp_path)
    source_path = tmp_path / "source.txt"
    source_path.write_text("甲和乙发现秘密线索。", encoding="utf-8")
    prompt_set = {
        "worldview_story_theme": "概括描述一下本作的世界观是怎样的，这本书讲述了一个什么样的故事，并推测主题。"
    }
    model = ScriptedBenchmarkModel(
        [
            "baseline：完整原文分析。",
            json.dumps({"status": "ready_to_answer"}, ensure_ascii=False),
            "Analyzer：第一次分析。",
            _judge_pass_payload(),
            json.dumps({"status": "ready_to_answer"}, ensure_ascii=False),
            "Analyzer：第二次分析。",
            _judge_pass_payload(),
        ]
    )
    service = OutlineAnalyzerBenchmarkService(repo_root=tmp_path, model_client=model)
    first = AnalyzerBenchmarkConfig(
        source_path=source_path,
        db_path=db_path,
        book_id="bench-book",
        artifact_dir=tmp_path / "runs" / "outline_analyzer",
        run_id="first",
        prompt_set=prompt_set,
    )
    second = AnalyzerBenchmarkConfig(
        source_path=source_path,
        db_path=db_path,
        book_id="bench-book",
        artifact_dir=tmp_path / "runs" / "outline_analyzer",
        run_id="second",
        prompt_set=prompt_set,
    )

    first_result = service.run(first)
    second_result = service.run(second)

    assert first_result.prompt_results[0].baseline_prompt_stats["cache_hit"] is False
    assert second_result.prompt_results[0].baseline_prompt_stats["cache_hit"] is True
    baseline_calls = [
        call for call in model.calls if "full_source_text_without_whitespace" in call["user_prompt"]
    ]
    assert len(baseline_calls) == 1


def test_outline_analyzer_benchmark_can_shape_check_existing_longzu_120kb_memory(tmp_path: Path) -> None:
    repo_root = Path.cwd()
    source_path = repo_root / "novel_agent" / "tests" / "longzu_120kb.txt"
    db_path = repo_root / ".indexes" / "longzu-120kb-web-real-20260518b.db"
    if not db_path.exists():
        pytest.skip("local longzu 120kb close-read sqlite is not available")
    model = ScriptedBenchmarkModel(
        [
            "baseline：这是完整原文分析。",
            json.dumps({"status": "ready_to_answer"}, ensure_ascii=False),
            "Analyzer：这是基于 Memory 的分析。",
            _judge_pass_payload(),
        ]
    )
    config = AnalyzerBenchmarkConfig(
        source_path=source_path,
        db_path=db_path,
        book_id="longzu-120kb-web-real-20260518b",
        artifact_dir=tmp_path / "outline_analyzer",
        run_id="longzu-shape",
        prompt_ids=["worldview_story_theme"],
    )

    result = OutlineAnalyzerBenchmarkService(repo_root=repo_root, model_client=model).run(config)

    assert result.status == "pass"
    baseline_stats = result.prompt_results[0].baseline_prompt_stats
    assert int(baseline_stats["prompt_bytes"]) > 100_000
    analyzer_stats = result.prompt_results[0].analyzer_prompt_stats
    assert int(analyzer_stats["max_single_prompt_chars"]) < int(baseline_stats["prompt_chars"])


@pytest.mark.slow
@pytest.mark.timeout(1800)
def test_real_llm_outline_analyzer_benchmark_is_explicitly_gated(tmp_path: Path) -> None:
    if os.getenv("RUN_REAL_LLM_OUTLINE_ANALYZER_BENCHMARK") != "1":
        pytest.skip("set RUN_REAL_LLM_OUTLINE_ANALYZER_BENCHMARK=1 to run the real LLM Analyzer benchmark")
    assert os.getenv("DEEPSEEK_API_KEY"), "DEEPSEEK_API_KEY is required for the gated Analyzer benchmark"
    repo_root = Path.cwd()
    config = build_default_longzu_120kb_config(
        repo_root=repo_root,
        artifact_dir=tmp_path / "outline_analyzer",
        prompt_ids=["worldview_story_theme"],
    )

    result = OutlineAnalyzerBenchmarkService(repo_root=repo_root).run(config)

    assert result.prompt_results
    assert result.summary_path.exists()
    assert result.status in {"pass", "needs_review"}
