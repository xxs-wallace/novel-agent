from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...schemas import RunConfig
from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.creative_kb_storage import init_creative_kb_schema
from ..repos.db import NovelAgentDB
from ..repos.documents_repo import DocumentsRepo
from ..runner import SingleSampleSmokeRunResult, SingleSampleSmokeRunner
from .continuation_generation_service import ContinuationGenerationService
from .smoke_sample_service import SmokeSampleService
from .smoke_reviewer_service import SmokeReviewerService
from ..utils.text_utils import split_sentences


LONGZU_32KB_FIXTURE = Path("novel_agent/tests/longzu_32kb.txt")
LONGZU_96KB_FIXTURE = Path("novel_agent/tests/longzu_96kb.txt")
LONGZU_120KB_FIXTURE = Path("novel_agent/tests/longzu_120kb.txt")
MODELING_CACHE_SCHEMA_VERSION = 1
SEGMENT_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
CHAPTER_HEADING_PATTERN = re.compile(r"^\s*(第[一二三四五六七八九十百千万\d]+[章节幕卷回部]|chapter\b)", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, limit: int = 120) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _normalize_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = _normalize_text(value)
        return [text] if text else []
    if isinstance(value, list | tuple | set):
        normalized: list[str] = []
        for item in value:
            if isinstance(item, dict):
                for key in ("summary", "text", "name", "canonical_name", "current_state", "target_shift"):
                    text = _normalize_text(item.get(key))
                    if text:
                        normalized.append(text)
                        break
                continue
            text = _normalize_text(item)
            if text:
                normalized.append(text)
        return [item for item in dict.fromkeys(normalized) if item]
    return []


@dataclass(frozen=True, slots=True)
class SmokeBenchmarkSampleBuildResult:
    sample_path: Path
    db_path: Path
    output_dir: Path
    source_path: Path
    anchor_context: str
    recent_window: list[str]
    reference_truth: str


class SmokeBenchmarkSampleService:
    """Builds canonical smoke samples consumed by SingleSampleSmokeRunner."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root.expanduser().resolve() if repo_root is not None else Path.cwd().resolve()

    def default_longzu_source_path(self) -> Path:
        return (self.repo_root / LONGZU_32KB_FIXTURE).resolve()

    def default_longzu_96kb_source_path(self) -> Path:
        return (self.repo_root / LONGZU_96KB_FIXTURE).resolve()

    def default_longzu_120kb_source_path(self) -> Path:
        return (self.repo_root / LONGZU_120KB_FIXTURE).resolve()

    def load_existing_sample(self, sample_path: Path):
        return SmokeSampleService(repo_root=self.repo_root).load(sample_path)

    def build_longzu_32kb_sample(
        self,
        *,
        source_path: Path | None = None,
        output_dir: Path | None = None,
        recent_window_size: int = 3,
        prefix_count: int = 8,
        target_length_chars: int = 600,
    ) -> SmokeBenchmarkSampleBuildResult:
        resolved_source_path = (source_path or self.default_longzu_source_path()).expanduser().resolve()
        if not resolved_source_path.exists():
            raise FileNotFoundError(
                f"longzu smoke fixture not found: {resolved_source_path}. "
                "请确认 novel_agent/tests/longzu_32kb.txt 存在，或使用 --source 指定可读文本。"
            )
        text = resolved_source_path.read_text(encoding="utf-8")
        segments = self._split_story_segments(text)
        if len(segments) <= prefix_count:
            raise ValueError(
                f"source only has {len(segments)} usable story segments; "
                "need enough prefix segments plus one reference truth segment"
            )

        normalized_prefix_count = max(1, min(int(prefix_count), len(segments) - 1))
        prefix_segments = segments[:normalized_prefix_count]
        reference_truth = segments[normalized_prefix_count]
        recent_window = prefix_segments[-max(1, int(recent_window_size)) :]
        anchor_context = "\n\n".join(prefix_segments[-min(2, len(prefix_segments)) :]).strip()

        resolved_output_dir = (output_dir or self.repo_root / "runs" / "benchmarks" / "longzu_32kb").expanduser()
        if not resolved_output_dir.is_absolute():
            resolved_output_dir = (self.repo_root / resolved_output_dir).resolve()
        resolved_output_dir.mkdir(parents=True, exist_ok=True)

        sample_path = resolved_output_dir / "sample.json"
        db_path = resolved_output_dir / "longzu_smoke.db"
        anchor_path = resolved_output_dir / "anchor_context.md"
        reference_path = resolved_output_dir / "reference_truth.md"
        outline_path = resolved_output_dir / "outline.md"
        world_path = resolved_output_dir / "world.md"
        world_summary_path = resolved_output_dir / "world_summary.md"
        recent_paths = [
            resolved_output_dir / f"recent_window_{index}.md"
            for index in range(1, len(recent_window) + 1)
        ]

        anchor_path.write_text(anchor_context + "\n", encoding="utf-8")
        reference_path.write_text(reference_truth + "\n", encoding="utf-8")
        for path, segment in zip(recent_paths, recent_window, strict=True):
            path.write_text(segment + "\n", encoding="utf-8")
        outline_text = self._derive_authorized_outline(prefix_segments=prefix_segments)
        outline_path.write_text(outline_text + "\n", encoding="utf-8")
        world_path.write_text("", encoding="utf-8")
        world_summary_path.write_text("", encoding="utf-8")

        sample_payload = self._build_sample_payload(
            anchor_path=anchor_path,
            recent_paths=recent_paths,
            reference_path=reference_path,
            prefix_count=normalized_prefix_count,
            target_length_chars=target_length_chars,
        )
        sample_path.write_text(json.dumps(sample_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._build_source_db(
            db_path=db_path,
            source_path=resolved_source_path,
            source_root=resolved_output_dir,
            prefix_segments=prefix_segments,
            outline_path=outline_path,
            world_path=world_path,
            world_summary_path=world_summary_path,
        )
        return SmokeBenchmarkSampleBuildResult(
            sample_path=sample_path,
            db_path=db_path,
            output_dir=resolved_output_dir,
            source_path=resolved_source_path,
            anchor_context=anchor_context,
            recent_window=recent_window,
            reference_truth=reference_truth,
        )

    def _split_story_segments(self, text: str) -> list[str]:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        raw_lines = normalized.splitlines()
        start_index = 0
        for index, line in enumerate(raw_lines):
            if CHAPTER_HEADING_PATTERN.search(line):
                start_index = index + 1
                break
        candidate_text = "\n".join(raw_lines[start_index:])
        segments = self._clean_segments(SEGMENT_SPLIT_PATTERN.split(candidate_text))
        if len(segments) < 10:
            segments = self._clean_segments(candidate_text.splitlines())
        return [
            segment
            for segment in segments
            if len(segment) >= 20 and any(token in segment for token in ("。", "？", "！", "；", "，", "“", "”"))
        ]

    def _clean_segments(self, values: list[str]) -> list[str]:
        return [segment for segment in (_normalize_text(value) for value in values) if segment]

    def _derive_authorized_outline(self, *, prefix_segments: list[str]) -> str:
        recent = prefix_segments[-min(5, len(prefix_segments)) :]
        lines = ["# MVP Smoke Authorized Plan", "", "## Prefix Recap"]
        lines.extend(f"- {_safe_excerpt(segment)}" for segment in recent)
        lines.extend(
            [
                "",
                "## Current Unit Plan",
                "- 承接最近剧情窗口，延续当前人物行动与情绪压力。",
                "- 推进下一小段正文，保持逻辑通顺，不一次性解决全部悬念。",
            ]
        )
        return "\n".join(lines).strip()

    def _build_sample_payload(
        self,
        *,
        anchor_path: Path,
        recent_paths: list[Path],
        reference_path: Path,
        prefix_count: int,
        target_length_chars: int,
    ) -> dict[str, object]:
        current_unit_plan = {
            "target_chapter_id": f"segment-{prefix_count + 1}",
            "target_segment_id": "longzu-smoke-target",
            "chapter_goal": "承接最近剧情窗口，延续当前人物行动与情绪压力，推进下一小段正文。",
            "emotional_goal": "承接上一段情绪并保持克制。",
            "conflict_goal": "推进当前局面但避免冲突被一次性解决。",
            "outline_excerpt": "根据前缀摘要续写下一小段，保持剧情连续和内部逻辑通顺。",
            "source_paths": ["outline_markdown_path"],
        }
        scene_brief_seed = {
            "scene_objective": current_unit_plan["chapter_goal"],
            "emotional_goal": current_unit_plan["emotional_goal"],
            "conflict_goal": current_unit_plan["conflict_goal"],
            "narrative_function": ["承接推进"],
            "emotion_mode": ["克制表达"],
            "character_temperament": [],
            "relationship_state": [],
            "style_need": ["中短句"],
            "must_avoid": ["避免设定冲突"],
            "preferred_tags": [],
        }
        return {
            "sample_id": "longzu-32kb-smoke",
            "book_id": "longzu-32kb-smoke",
            "target_chapter_id": f"segment-{prefix_count + 1}",
            "target_segment_id": "longzu-smoke-target",
            "mode": "chapter_authorized",
            "anchor_context_path": anchor_path.name,
            "recent_window_refs": [path.name for path in recent_paths],
            "documents_cutoff": {"max_document_title_index": str(prefix_count)},
            "allowed_outline_scope": {
                "chapter_range": ["MVP Smoke Authorized Plan", "Current Unit Plan"],
                "allow_future_outline": True,
            },
            "reference_truth_path": reference_path.name,
            "metadata": {
                "target_length_chars": int(target_length_chars),
                "window_size": len(recent_paths),
                "current_unit_plan": current_unit_plan,
                "scene_plan_seed": {
                    "goal": current_unit_plan["chapter_goal"],
                    "emotional_goal": current_unit_plan["emotional_goal"],
                    "conflict_goal": current_unit_plan["conflict_goal"],
                    "current_relationship_state": [],
                    "forbidden": ["避免设定冲突"],
                    "avoidance_items": [],
                    "style_reference_query": {
                        "narrative_function": ["承接推进"],
                        "emotion_mode": ["克制表达"],
                        "character_temperament": [],
                        "style_need": ["中短句"],
                    },
                    "retrieval_hints": {"preferred_tags": []},
                },
                "scene_brief_seed": scene_brief_seed,
            },
        }

    def _build_source_db(
        self,
        *,
        db_path: Path,
        source_path: Path,
        source_root: Path,
        prefix_segments: list[str],
        outline_path: Path,
        world_path: Path,
        world_summary_path: Path,
    ) -> None:
        if db_path.exists():
            db_path.unlink()
        db = NovelAgentDB(db_path)
        documents_repo = DocumentsRepo()
        chapters_repo = ChaptersRepo()
        assets_repo = AssetsRepo()
        with db.connect() as conn:
            db.init_schema(conn)
            init_creative_kb_schema(conn)
            doc_ids: list[int] = []
            offset = 0
            for index, segment in enumerate(prefix_segments, start=1):
                doc_id = documents_repo.insert_document(
                    conn,
                    {
                        "book_id": "longzu-32kb-smoke",
                        "path": str(source_path),
                        "scope": "chapter",
                        "title": f"prefix segment {index}",
                        "content": segment,
                        "source_path": str(source_path),
                        "source_file_name": source_path.name,
                        "source_start_offset": offset,
                        "source_end_offset": offset + len(segment),
                        "document_title": f"Prefix Segment {index}",
                        "document_title_index": index,
                        "inferred_chapter_no": index,
                        "content_chars": len(segment),
                        "character_keywords": [],
                        "content_tags": [],
                        "created_at": _utc_now(),
                        "updated_at": _utc_now(),
                    },
                )
                doc_ids.append(doc_id)
                chapters_repo.upsert(
                    conn,
                    {
                        "book_id": "longzu-32kb-smoke",
                        "document_title_index": index,
                        "chapter_title": f"Prefix Segment {index}",
                        "source_doc_start_id": doc_id,
                        "source_doc_end_id": doc_id,
                        "source_doc_count": 1,
                        "source_total_chars": len(segment),
                        "summary_intermediate": [_safe_excerpt(segment, 160)],
                        "summary_md": _safe_excerpt(segment, 220),
                        "summary_short": _safe_excerpt(segment, 80),
                        "importance_score": 5,
                        "importance_reason": "prefix smoke segment",
                        "related_chapters": [],
                        "mentioned_characters": [],
                        "world_update": {},
                        "outline_update": {},
                        "close_read_run_id": "smoke-benchmark-builder",
                        "created_at": _utc_now(),
                        "updated_at": _utc_now(),
                    },
                )
                offset += len(segment)
            assets_repo.upsert(
                conn,
                {
                    "book_id": "longzu-32kb-smoke",
                    "source_root": str(source_root),
                    "world_markdown_path": str(world_path),
                    "world_summary_path": str(world_summary_path),
                    "outline_markdown_path": str(outline_path),
                    "toc_markdown": "",
                    "toc_source_path": "",
                    "debug_export_path": "",
                    "created_at": _utc_now(),
                    "updated_at": _utc_now(),
                },
            )
            conn.commit()


class SmokeBenchmarkRunService:
    """Facade that invokes the canonical SingleSampleSmokeRunner."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root.expanduser().resolve() if repo_root is not None else Path.cwd().resolve()
        self.sample_service = SmokeBenchmarkSampleService(repo_root=self.repo_root)

    def run_longzu_32kb(
        self,
        *,
        runs_dir: Path | None = None,
        generation_config: RunConfig | None = None,
        use_real_model: bool = False,
    ) -> SingleSampleSmokeRunResult:
        self._require_real_model(generation_config=generation_config, use_real_model=use_real_model)
        build_result = self.sample_service.build_longzu_32kb_sample()
        return self.run_existing_sample(
            sample_path=build_result.sample_path,
            db_path=build_result.db_path,
            runs_dir=runs_dir or self.repo_root / "runs" / "benchmarks",
            generation_config=generation_config,
            use_real_model=use_real_model,
        )

    def run_from_source(
        self,
        *,
        source_path: Path,
        runs_dir: Path | None = None,
        generation_config: RunConfig | None = None,
        use_real_model: bool = False,
    ) -> SingleSampleSmokeRunResult:
        self._require_real_model(generation_config=generation_config, use_real_model=use_real_model)
        output_dir = self.repo_root / "runs" / "benchmarks" / f"source_{uuid.uuid4().hex[:8]}"
        build_result = self.sample_service.build_longzu_32kb_sample(
            source_path=source_path,
            output_dir=output_dir,
        )
        return self.run_existing_sample(
            sample_path=build_result.sample_path,
            db_path=build_result.db_path,
            runs_dir=runs_dir or self.repo_root / "runs" / "benchmarks",
            generation_config=generation_config,
            use_real_model=use_real_model,
        )

    def run_existing_sample(
        self,
        *,
        sample_path: Path,
        db_path: Path,
        runs_dir: Path | None = None,
        generation_config: RunConfig | None = None,
        use_real_model: bool = False,
    ) -> SingleSampleSmokeRunResult:
        self._require_real_model(generation_config=generation_config, use_real_model=use_real_model)
        if not Path(sample_path).expanduser().exists():
            raise FileNotFoundError(f"smoke sample file not found: {sample_path}")
        if not Path(db_path).expanduser().exists():
            raise FileNotFoundError(f"smoke source db not found: {db_path}")
        from .continuation_generation_service import ContinuationGenerationService

        reviewer_service = (
            SmokeReviewerService(
                generation_service=ContinuationGenerationService(),
                generation_config=generation_config,
            )
            if use_real_model and generation_config is not None
            else None
        )
        runner = SingleSampleSmokeRunner(
            source_db_path=db_path,
            runs_dir=runs_dir or self.repo_root / "runs" / "benchmarks",
            repo_root=self.repo_root,
            generation_service=ContinuationGenerationService(),
            generation_config=generation_config,
            reviewer_service=reviewer_service,
        )
        return runner.run(sample_path=sample_path)

    def _require_real_model(self, *, generation_config: RunConfig | None, use_real_model: bool) -> None:
        if not use_real_model or generation_config is None:
            raise ValueError("MVP smoke benchmark requires a real LLM config; pass use_real_model=True")


class SmokeBenchmarkSummaryPresenter:
    def to_json_summary(self, result: SingleSampleSmokeRunResult) -> dict[str, object]:
        reviewer_report = getattr(result, "reviewer_report", None)
        payload: dict[str, object] = {
            "run_id": result.run_id,
            "sample_id": result.sample.config.sample_id,
            "mode": result.sample.config.mode,
            "run_dir": result.run_dir,
            "selected_fragment_ids": list(result.retrieval_result.rerank_result.selected_fragment_ids),
            "generated_chars": len(result.generated_text),
            "reference_truth_chars": len(result.sample.reference_truth.text),
            "decision": result.compare_report.decision,
            "weighted_score": result.compare_report.weighted_score,
        }
        if reviewer_report is not None:
            payload.update(
                {
                    "reviewer_decision": reviewer_report.decision,
                    "reviewer_score": reviewer_report.score,
                    "reviewer_summary": reviewer_report.summary,
                }
            )
        return payload

    def render_cli_summary(self, result: SingleSampleSmokeRunResult) -> str:
        reviewer_report = getattr(result, "reviewer_report", None)
        if reviewer_report is None:
            reviewer_line = "Reviewer：未启用"
        else:
            reviewer_line = (
                f"Reviewer：{reviewer_report.summary} "
                f"({reviewer_report.decision}, {reviewer_report.score:.2f})"
            )
        return "\n".join(
            [
                reviewer_line,
                f"run_id：{result.run_id}",
                f"产物目录：{result.run_dir}",
                f"生成字数：{len(result.generated_text)}",
                f"reference truth 字数：{len(result.sample.reference_truth.text)}",
                f"smoke compare：{result.compare_report.decision} / {result.compare_report.weighted_score:.2f}",
            ]
        )

    def payload_for_cli(self, result: SingleSampleSmokeRunResult) -> dict[str, Any]:
        payload = self.to_json_summary(result)
        payload["summary_text"] = self.render_cli_summary(result)
        return payload


@dataclass(frozen=True, slots=True)
class AgenticSmokeBenchmarkResult:
    run_id: str
    run_dir: str
    book_id: str
    source_path: str
    prefix_source_path: str
    db_path: str
    writer_run_dir: str
    draft_path: str
    reference_truth_path: str
    generated_synopsis_path: str
    reference_synopsis_path: str
    synopsis_reviewer_report_path: str
    expansion_prompt_path: str
    expansion_reviewer_report_path: str
    reviewer_report_path: str
    summary_path: str
    generated_chars: int
    reference_truth_chars: int
    synopsis_decision: str
    synopsis_score: float
    synopsis_summary: str
    expansion_decision: str
    expansion_score: float
    expansion_summary: str
    reviewer_decision: str
    reviewer_score: float
    reviewer_summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "book_id": self.book_id,
            "source_path": self.source_path,
            "prefix_source_path": self.prefix_source_path,
            "db_path": self.db_path,
            "writer_run_dir": self.writer_run_dir,
            "draft_path": self.draft_path,
            "reference_truth_path": self.reference_truth_path,
            "generated_synopsis_path": self.generated_synopsis_path,
            "reference_synopsis_path": self.reference_synopsis_path,
            "synopsis_reviewer_report_path": self.synopsis_reviewer_report_path,
            "expansion_prompt_path": self.expansion_prompt_path,
            "expansion_reviewer_report_path": self.expansion_reviewer_report_path,
            "reviewer_report_path": self.reviewer_report_path,
            "summary_path": self.summary_path,
            "generated_chars": self.generated_chars,
            "reference_truth_chars": self.reference_truth_chars,
            "synopsis_decision": self.synopsis_decision,
            "synopsis_score": self.synopsis_score,
            "synopsis_summary": self.synopsis_summary,
            "expansion_decision": self.expansion_decision,
            "expansion_score": self.expansion_score,
            "expansion_summary": self.expansion_summary,
            "reviewer_decision": self.reviewer_decision,
            "reviewer_score": self.reviewer_score,
            "reviewer_summary": self.reviewer_summary,
        }


@dataclass(frozen=True, slots=True)
class AgenticModelingArtifacts:
    book_id: str
    db_path: Path
    pipeline_result: dict[str, object]
    reference_context: dict[str, object]
    reference_synopsis: dict[str, object]
    story_context: dict[str, object]
    story_outline: dict[str, object]
    writer_planning_input: dict[str, object]
    prefix_source_path: Path
    reference_truth_path: Path
    reference_synopsis_path: Path
    story_outline_path: Path
    writer_planning_input_path: Path
    cache_dir: Path | None = None
    cache_hit: bool = False


class AgenticSmokeBenchmarkService:
    """Runs the real rough-read/close-read/Writer path on a held-out single sample."""

    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.sample_service = SmokeBenchmarkSampleService(repo_root=self.repo_root)

    def run_longzu_32kb(
        self,
        *,
        api_key: str,
        source_path: Path | None = None,
        runs_dir: Path | None = None,
        prefix_count: int = 1,
        prefix_min_chars: int = 4_000,
        recent_window_size: int = 3,
        reference_min_chars: int = 2_700,
        benchmark_cache_dir: Path | None = None,
        reuse_modeling_cache: bool = False,
        rebuild_modeling_cache: bool = False,
        clear_modeling_cache: bool = False,
        max_read_kb: int = 64,
        max_close_batches: int = 12,
        segment_step_kb: int = 32,
        close_step_batches: int = 1,
    ) -> AgenticSmokeBenchmarkResult:
        return self.run_from_source(
            source_path=source_path or self.sample_service.default_longzu_source_path(),
            api_key=api_key,
            runs_dir=runs_dir,
            prefix_count=prefix_count,
            prefix_min_chars=prefix_min_chars,
            recent_window_size=recent_window_size,
            reference_min_chars=reference_min_chars,
            benchmark_cache_dir=benchmark_cache_dir,
            reuse_modeling_cache=reuse_modeling_cache,
            rebuild_modeling_cache=rebuild_modeling_cache,
            clear_modeling_cache=clear_modeling_cache,
            max_read_kb=max_read_kb,
            max_close_batches=max_close_batches,
            segment_step_kb=segment_step_kb,
            close_step_batches=close_step_batches,
        )

    def run_from_source(
        self,
        *,
        source_path: Path,
        api_key: str,
        runs_dir: Path | None = None,
        prefix_count: int = 1,
        prefix_min_chars: int = 4_000,
        recent_window_size: int = 3,
        reference_min_chars: int = 2_700,
        benchmark_cache_dir: Path | None = None,
        reuse_modeling_cache: bool = False,
        rebuild_modeling_cache: bool = False,
        clear_modeling_cache: bool = False,
        max_read_kb: int = 64,
        max_close_batches: int = 12,
        segment_step_kb: int = 32,
        close_step_batches: int = 1,
    ) -> AgenticSmokeBenchmarkResult:
        from .. import run_interactive

        resolved_source = source_path.expanduser().resolve()
        if not resolved_source.exists():
            raise FileNotFoundError(f"benchmark source not found: {resolved_source}")
        if not api_key.strip():
            raise ValueError("api_key is required for real agentic smoke benchmark")

        run_id = uuid.uuid4().hex
        root = (runs_dir or self.repo_root / "runs" / "benchmarks").expanduser().resolve()
        run_dir = root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        source_text = resolved_source.read_text(encoding="utf-8")
        prefix_text, _recent_segments, reference_truth, _prefix_segments = self._prepare_agentic_windows(
            source_text=source_text,
            minimum_prefix_chars=prefix_min_chars,
            minimum_prefix_chunks=prefix_count,
            recent_window_size=recent_window_size,
            reference_min_chars=reference_min_chars,
        )
        prefix_source_path = run_dir / "source_prefix.txt"
        reference_truth_path = run_dir / "reference_truth.txt"
        prefix_source_path.write_text(prefix_text.rstrip() + "\n", encoding="utf-8")
        reference_truth_path.write_text(reference_truth + "\n", encoding="utf-8")

        cache_params = {
            "prefix_count": int(prefix_count),
            "prefix_min_chars": int(prefix_min_chars),
            "recent_window_size": int(recent_window_size),
            "reference_min_chars": int(reference_min_chars),
            "max_read_kb": int(max_read_kb),
            "max_close_batches": int(max_close_batches),
            "segment_step_kb": int(segment_step_kb),
            "close_step_batches": int(close_step_batches),
        }
        cache_root = self._default_modeling_cache_root(runs_dir=root) if (
            benchmark_cache_dir is None and (reuse_modeling_cache or rebuild_modeling_cache or clear_modeling_cache)
        ) else benchmark_cache_dir
        cache_key = self._build_modeling_cache_key(
            source_path=resolved_source,
            source_text=source_text,
            prefix_text=prefix_text,
            reference_truth=reference_truth,
            params=cache_params,
        )
        cache_dir = self._resolve_modeling_cache_dir(cache_root=cache_root, cache_key=cache_key)
        book_slug = self._source_slug(resolved_source)
        book_id = f"{book_slug}-agentic-cache-{cache_key[:8]}" if cache_dir is not None else (
            f"{book_slug}-agentic-{run_id[:8]}"
        )
        db_path = self.repo_root / ".indexes" / f"{book_id}.db"

        if clear_modeling_cache and cache_dir is not None and cache_dir.exists():
            shutil.rmtree(cache_dir)

        modeling_artifacts: AgenticModelingArtifacts | None = None
        if cache_dir is not None and reuse_modeling_cache and not rebuild_modeling_cache:
            modeling_artifacts = self._load_modeling_cache(
                cache_dir=cache_dir,
                run_dir=run_dir,
                db_path=db_path,
                prefix_source_path=prefix_source_path,
                reference_truth_path=reference_truth_path,
            )

        if modeling_artifacts is None:
            if db_path.exists():
                db_path.unlink()
            pipeline_result = run_interactive._run_pipeline(  # noqa: SLF001
                repo_root=self.repo_root,
                book_id=book_id,
                source_path=prefix_source_path,
                db_path=db_path,
                debug_path=run_dir / "debug.md",
                api_key=api_key,
                run_mode="fresh",
                max_read_kb=max_read_kb,
                max_close_batches=max_close_batches,
                segment_step_kb=segment_step_kb,
                close_step_batches=close_step_batches,
                build_creative_kb=True,
                thinking="disabled",
                reasoning_effort=None,
                include_reasoning_content=False,
            )
            (run_dir / "pipeline_result.json").write_text(
                json.dumps(pipeline_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            reference_close_read = self._run_reference_close_read(
                run_interactive=run_interactive,
                run_dir=run_dir,
                book_id=f"{book_id}-reference",
                reference_truth=reference_truth,
                api_key=api_key,
                max_read_kb=max_read_kb,
                max_close_batches=max_close_batches,
                segment_step_kb=segment_step_kb,
                close_step_batches=close_step_batches,
            )
            (run_dir / "reference_close_read_result.json").write_text(
                json.dumps(reference_close_read["pipeline_result"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "reference_close_read_context.json").write_text(
                json.dumps(reference_close_read, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            reference_synopsis = self._build_reference_synopsis_from_close_read(
                reference_context=reference_close_read,
                source_chars=len(reference_truth.strip()),
            )
            reference_synopsis_prompt_path = run_dir / "reference_story_synopsis_prompt.json"
            reference_synopsis_prompt_path.write_text(
                json.dumps(
                    {
                        "source": "close_read_artifacts",
                        "note": (
                            "No standalone benchmark prompt was used. "
                            "reference_story_synopsis was assembled from close-read chapter summaries."
                        ),
                        "reference_close_read_result_path": str(run_dir / "reference_close_read_result.json"),
                        "reference_close_read_db_path": str(reference_close_read["db_path"]),
                        "summary_source": reference_close_read["reference_chapter_summaries"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            reference_synopsis_path = run_dir / "reference_story_synopsis.json"
            reference_synopsis_path.write_text(
                json.dumps(reference_synopsis, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            story_context = self._load_story_context(db_path=db_path, book_id=book_id)
            (run_dir / "story_context.json").write_text(
                json.dumps(story_context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            story_outline = self._build_story_outline_from_close_read(
                story_context=story_context,
                reference_context=reference_close_read,
                target_chars=int(reference_synopsis.get("source_chars") or len(reference_truth.strip())),
            )
            (run_dir / "story_outline_prompt.json").write_text(
                json.dumps(
                    {
                        "source": "close_read_artifacts",
                        "note": (
                            "No standalone benchmark prompt was used. "
                            "benchmark_story_outline was assembled from close-read story outline and chapter summaries."
                        ),
                        "reference_close_read_result_path": str(run_dir / "reference_close_read_result.json"),
                        "reference_story_outline_md": reference_close_read.get("story_outline_md", ""),
                        "reference_chapter_summaries": reference_close_read["reference_chapter_summaries"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            story_outline_path = run_dir / "benchmark_story_outline.json"
            story_outline_path.write_text(json.dumps(story_outline, ensure_ascii=False, indent=2), encoding="utf-8")
            writer_planning_input = self._build_benchmark_writer_planning_input(
                story_outline=story_outline,
                story_context=story_context,
                target_chars=len(reference_truth.strip()),
            )
            writer_planning_input_path = run_dir / "writer_planning_input.json"
            writer_planning_input_path.write_text(
                json.dumps(writer_planning_input, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            modeling_artifacts = AgenticModelingArtifacts(
                book_id=book_id,
                db_path=db_path,
                pipeline_result=pipeline_result,
                reference_context=reference_close_read,
                reference_synopsis=reference_synopsis,
                story_context=story_context,
                story_outline=story_outline,
                writer_planning_input=writer_planning_input,
                prefix_source_path=prefix_source_path,
                reference_truth_path=reference_truth_path,
                reference_synopsis_path=reference_synopsis_path,
                story_outline_path=story_outline_path,
                writer_planning_input_path=writer_planning_input_path,
                cache_dir=cache_dir,
                cache_hit=False,
            )
            if cache_dir is not None:
                self._store_modeling_cache(
                    cache_dir=cache_dir,
                    artifacts=modeling_artifacts,
                    manifest={
                        "schema_version": MODELING_CACHE_SCHEMA_VERSION,
                        "cache_key": cache_key,
                        "book_id": book_id,
                        "source_path": str(resolved_source),
                        "source_sha256": self._sha256_text(source_text),
                        "prefix_sha256": self._sha256_text(prefix_text),
                        "reference_truth_sha256": self._sha256_text(reference_truth),
                        "params": cache_params,
                        "created_at": _utc_now(),
                    },
                )

        book_id = modeling_artifacts.book_id
        db_path = modeling_artifacts.db_path
        reference_synopsis = modeling_artifacts.reference_synopsis
        story_context = modeling_artifacts.story_context
        story_outline = modeling_artifacts.story_outline
        writer_planning_input = modeling_artifacts.writer_planning_input
        reference_synopsis_path = modeling_artifacts.reference_synopsis_path
        story_outline_path = modeling_artifacts.story_outline_path
        writer_planning_input_path = modeling_artifacts.writer_planning_input_path

        writer_db_path = run_interactive.resolve_writer_memory_db_path(
            repo_root=self.repo_root,
            book_id=book_id,
            reset=True,
        )
        db, workflow = run_interactive.build_writer_workflow(
            repo_root=self.repo_root,
            db_path=writer_db_path,
            runs_dir=run_dir / "writer_runs",
            dry_run=False,
            api_key=api_key,
            thinking="disabled",
            reasoning_effort=None,
            include_reasoning_content=False,
        )
        with db.connect() as conn:
            db.init_schema(conn)
            init_creative_kb_schema(conn)
            writer_result = run_interactive.run_writer_guided_flow(
                workflow=workflow,
                conn=conn,
                run_id=run_id,
                book_id=book_id,
                product_mode="auto_novel",
                intent_payload=dict(writer_planning_input["intent_payload"]),
                user_world_notes=str(writer_planning_input["user_world_notes"]),
                target_chapter_count=1,
                chapter_count=1,
                default_target_chars=len(reference_truth.strip()),
                allow_incomplete_modeling=False,
                confirm_review=lambda _stage, _artifact_path: True,
                accept_chapter_review=lambda _artifact_path: "accepted",
                execute_chapter=False,
            )
            conn.commit()
        (run_dir / "writer_result.json").write_text(
            json.dumps(run_interactive.redact_writer_result_for_terminal(writer_result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        writer_run_dir = run_dir / "writer_runs" / run_id
        execution_input_path = writer_run_dir / "chapter_execution_input.json"
        if not execution_input_path.exists():
            raise FileNotFoundError(f"writer synopsis input not found after benchmark run: {execution_input_path}")
        execution_data = self._unwrap_run_data(json.loads(execution_input_path.read_text(encoding="utf-8")))
        legacy_writer_synopsis = {
            "stage": "legacy_writer_chapter_brief",
            "source": "writer.chapter_brief",
            "chapter_title": execution_data.get("chapter_title"),
            "chapter_brief": dict(execution_data.get("chapter_brief") or {}),
            "length_budget": dict(execution_data.get("length_budget") or {}),
        }
        (run_dir / "legacy_writer_chapter_brief.json").write_text(
            json.dumps(legacy_writer_synopsis, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        reviewer_config = RunConfig(
            prompt=None,
            model_type="OpenAIModel",
            model_id=run_interactive.DEFAULT_WRITER_MODEL_NAME,
            provider=None,
            api_base="https://api.deepseek.com",
            api_key=api_key,
            thinking="disabled",
            reasoning_effort=None,
            save_reasoning=False,
            action_type="tool_calling",
            tools=[],
            imports=[],
            verbosity_level=1,
            dry_run=False,
        )
        generation_service = ContinuationGenerationService()

        generated_synopsis_prompt = {
            "source": "writer_artifacts",
            "note": (
                "No standalone benchmark synopsis-generation prompt was used. "
                "generated_story_synopsis is a normalized view of Writer chapter planning artifacts."
            ),
            "writer_run_dir": str(writer_run_dir),
            "writer_chapter_package_path": str(writer_run_dir / "chapter_package.json"),
            "writer_chapter_brief_path": str(writer_run_dir / "chapter_brief.json"),
            "writer_execution_input_path": str(execution_input_path),
            "writer_planning_input_path": str(writer_planning_input_path),
            "close_read_story_outline_path": str(story_outline_path),
        }
        (run_dir / "generated_story_synopsis_prompt.json").write_text(
            json.dumps(generated_synopsis_prompt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        generated_synopsis = self._build_writer_generated_synopsis(
            execution_data=execution_data,
            writer_run_dir=writer_run_dir,
            fallback_target_chars=0,
        )
        writer_generated_synopsis_path = run_dir / "writer_generated_story_synopsis.json"
        writer_generated_synopsis_path.write_text(
            json.dumps(generated_synopsis, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        generated_synopsis_path = run_dir / "generated_story_synopsis.json"
        generated_synopsis_path.write_text(json.dumps(generated_synopsis, ensure_ascii=False, indent=2), encoding="utf-8")

        synopsis_review_prompt = self._build_synopsis_review_prompt(
            story_outline=story_outline,
            recent_story_synopses=story_context["recent_story_synopses"],
            character_docs=story_context["character_docs"],
            generated_synopsis=generated_synopsis,
            reference_synopsis=reference_synopsis,
        )
        (run_dir / "synopsis_reviewer_prompt.json").write_text(
            json.dumps(synopsis_review_prompt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        synopsis_report = self._generate_json_with_model(
            generation_service=generation_service,
            generation_config=reviewer_config,
            prompt_payload=synopsis_review_prompt,
        )
        synopsis_reviewer_report_path = run_dir / "synopsis_reviewer_report.json"
        synopsis_reviewer_report_path.write_text(
            json.dumps(synopsis_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        expansion_dir = run_dir / "expansion"
        expansion_dir.mkdir(parents=True, exist_ok=True)
        expansion_execution_input = self._build_reference_synopsis_execution_input(
            base_execution_data=execution_data,
            reference_synopsis=reference_synopsis,
            story_outline=story_outline,
            story_context=story_context,
            target_chars=len(reference_truth.strip()),
        )
        expansion_execution_input_path = expansion_dir / "writer_execution_input.json"
        expansion_execution_input_path.write_text(
            json.dumps(expansion_execution_input, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        draft_prompt = workflow.executor.build_draft_prompt(expansion_execution_input)
        generated_text = workflow.executor.generate_draft_from_execution_input(expansion_execution_input).strip()
        draft_path = expansion_dir / "draft.md"
        draft_path.write_text(generated_text + "\n", encoding="utf-8")
        expansion_prompt = {
            "source": "writer_execution_interface",
            "note": (
                "No standalone benchmark expansion prompt was used. "
                "The benchmark builds a Writer execution input from close-read reference_story_synopsis "
                "and calls RestrictedWriterExecutor.generate_draft_from_execution_input."
            ),
            "planning_writer_run_dir": str(writer_run_dir),
            "planning_writer_execution_input_path": str(execution_input_path),
            "writer_execution_input_path": str(expansion_execution_input_path),
            "reference_story_synopsis_path": str(reference_synopsis_path),
            "benchmark_draft_path": str(draft_path),
            "length_budget": dict(expansion_execution_input.get("length_budget") or {}),
            "generation_prompt": draft_prompt,
        }
        expansion_prompt_path = expansion_dir / "prompt.json"
        expansion_prompt_path.write_text(json.dumps(expansion_prompt, ensure_ascii=False, indent=2), encoding="utf-8")

        expansion_review_prompt = self._build_expansion_review_prompt(
            reference_synopsis=reference_synopsis,
            reference_truth=reference_truth,
            generated_text=generated_text,
        )
        (run_dir / "expansion_reviewer_prompt.json").write_text(
            json.dumps(expansion_review_prompt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        expansion_report = self._generate_json_with_model(
            generation_service=generation_service,
            generation_config=reviewer_config,
            prompt_payload=expansion_review_prompt,
        )
        expansion_reviewer_report_path = run_dir / "expansion_reviewer_report.json"
        expansion_reviewer_report_path.write_text(
            json.dumps(expansion_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        reviewer_report_path = run_dir / "reviewer_report.json"
        combined_reviewer_report = {
            "decision": self._combined_decision(synopsis_report, expansion_report),
            "score": self._combined_score(synopsis_report, expansion_report),
            "summary": (
                f"梗概层：{self._report_summary(synopsis_report)} "
                f"扩写层：{self._report_summary(expansion_report)}"
            ).strip(),
            "layers": {
                "synopsis": {
                    "decision": self._report_decision(synopsis_report),
                    "score": self._report_score(synopsis_report),
                    "summary": self._report_summary(synopsis_report),
                },
                "expansion": {
                    "decision": self._report_decision(expansion_report),
                    "score": self._report_score(expansion_report),
                    "summary": self._report_summary(expansion_report),
                },
            },
            "synopsis_report": synopsis_report,
            "expansion_report": expansion_report,
            "generated_chars": len(generated_text.strip()),
            "reference_truth_chars": len(reference_truth.strip()),
        }
        reviewer_report_path.write_text(
            json.dumps(combined_reviewer_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary_path = run_dir / "summary.json"
        result = AgenticSmokeBenchmarkResult(
            run_id=run_id,
            run_dir=str(run_dir),
            book_id=book_id,
            source_path=str(resolved_source),
            prefix_source_path=str(prefix_source_path),
            db_path=str(db_path),
            writer_run_dir=str(writer_run_dir),
            draft_path=str(draft_path),
            reference_truth_path=str(reference_truth_path),
            generated_synopsis_path=str(generated_synopsis_path),
            reference_synopsis_path=str(reference_synopsis_path),
            synopsis_reviewer_report_path=str(synopsis_reviewer_report_path),
            expansion_prompt_path=str(expansion_prompt_path),
            expansion_reviewer_report_path=str(expansion_reviewer_report_path),
            reviewer_report_path=str(reviewer_report_path),
            summary_path=str(summary_path),
            generated_chars=len(generated_text.strip()),
            reference_truth_chars=len(reference_truth.strip()),
            synopsis_decision=self._report_decision(synopsis_report),
            synopsis_score=self._report_score(synopsis_report),
            synopsis_summary=self._report_summary(synopsis_report),
            expansion_decision=self._report_decision(expansion_report),
            expansion_score=self._report_score(expansion_report),
            expansion_summary=self._report_summary(expansion_report),
            reviewer_decision=str(combined_reviewer_report["decision"]),
            reviewer_score=float(combined_reviewer_report["score"]),
            reviewer_summary=str(combined_reviewer_report["summary"]),
        )
        summary_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _default_modeling_cache_root(self, *, runs_dir: Path) -> Path:
        return runs_dir / "_modeling_cache"

    def _resolve_modeling_cache_dir(self, *, cache_root: Path | None, cache_key: str) -> Path | None:
        if cache_root is None:
            return None
        root = cache_root.expanduser()
        if not root.is_absolute():
            root = (self.repo_root / root).resolve()
        return root / cache_key

    def _build_modeling_cache_key(
        self,
        *,
        source_path: Path,
        source_text: str,
        prefix_text: str,
        reference_truth: str,
        params: dict[str, object],
    ) -> str:
        payload = {
            "schema_version": MODELING_CACHE_SCHEMA_VERSION,
            "source_name": source_path.name,
            "source_sha256": self._sha256_text(source_text),
            "prefix_sha256": self._sha256_text(prefix_text),
            "reference_truth_sha256": self._sha256_text(reference_truth),
            "params": params,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _sha256_text(self, text: str) -> str:
        return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()

    def _source_slug(self, source_path: Path) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", source_path.stem).strip("-").lower()
        return slug[:48] or "source"

    def _load_modeling_cache(
        self,
        *,
        cache_dir: Path,
        run_dir: Path,
        db_path: Path,
        prefix_source_path: Path,
        reference_truth_path: Path,
    ) -> AgenticModelingArtifacts | None:
        manifest_path = cache_dir / "manifest.json"
        db_cache_path = cache_dir / "prefix.db"
        required_files = [
            manifest_path,
            db_cache_path,
            cache_dir / "pipeline_result.json",
            cache_dir / "reference_close_read_result.json",
            cache_dir / "reference_close_read_context.json",
            cache_dir / "reference_story_synopsis.json",
            cache_dir / "story_context.json",
            cache_dir / "benchmark_story_outline.json",
            cache_dir / "writer_planning_input.json",
        ]
        if not all(path.exists() for path in required_files):
            return None

        manifest = self._read_json_object(manifest_path)
        if int(manifest.get("schema_version") or 0) != MODELING_CACHE_SCHEMA_VERSION:
            return None
        book_id = _normalize_text(manifest.get("book_id"))
        if not book_id:
            return None

        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_cache_path, db_path)
        self._restore_cached_memory_files(cache_dir=cache_dir, manifest=manifest)

        for name in (
            "pipeline_result.json",
            "reference_close_read_result.json",
            "reference_close_read_context.json",
            "reference_story_synopsis_prompt.json",
            "reference_story_synopsis.json",
            "story_context.json",
            "story_outline_prompt.json",
            "benchmark_story_outline.json",
            "writer_planning_input.json",
        ):
            source = cache_dir / name
            if source.exists():
                shutil.copy2(source, run_dir / name)
        reference_cache_dir = cache_dir / "reference_close_read"
        if reference_cache_dir.exists():
            shutil.copytree(reference_cache_dir, run_dir / "reference_close_read", dirs_exist_ok=True)

        pipeline_result = self._read_json_object(run_dir / "pipeline_result.json")
        reference_context = self._read_json_object(run_dir / "reference_close_read_context.json")
        reference_context.update(
            {
                "db_path": str(run_dir / "reference_close_read" / "reference.db"),
                "source_path": str(run_dir / "reference_close_read" / "source.txt"),
                "debug_path": str(run_dir / "reference_close_read" / "debug.md"),
            }
        )
        (run_dir / "reference_close_read_context.json").write_text(
            json.dumps(reference_context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        reference_synopsis_path = run_dir / "reference_story_synopsis.json"
        story_outline_path = run_dir / "benchmark_story_outline.json"
        writer_planning_input_path = run_dir / "writer_planning_input.json"
        return AgenticModelingArtifacts(
            book_id=book_id,
            db_path=db_path,
            pipeline_result=pipeline_result,
            reference_context=reference_context,
            reference_synopsis=self._read_json_object(reference_synopsis_path),
            story_context=self._read_json_object(run_dir / "story_context.json"),
            story_outline=self._read_json_object(story_outline_path),
            writer_planning_input=self._read_json_object(writer_planning_input_path),
            prefix_source_path=prefix_source_path,
            reference_truth_path=reference_truth_path,
            reference_synopsis_path=reference_synopsis_path,
            story_outline_path=story_outline_path,
            writer_planning_input_path=writer_planning_input_path,
            cache_dir=cache_dir,
            cache_hit=True,
        )

    def _store_modeling_cache(
        self,
        *,
        cache_dir: Path,
        artifacts: AgenticModelingArtifacts,
        manifest: dict[str, object],
    ) -> None:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifacts.db_path, cache_dir / "prefix.db")
        run_dir = artifacts.reference_truth_path.parent
        for name in (
            "source_prefix.txt",
            "reference_truth.txt",
            "pipeline_result.json",
            "reference_close_read_result.json",
            "reference_close_read_context.json",
            "reference_story_synopsis_prompt.json",
            "reference_story_synopsis.json",
            "story_context.json",
            "story_outline_prompt.json",
            "benchmark_story_outline.json",
            "writer_planning_input.json",
        ):
            source = run_dir / name
            if source.exists():
                shutil.copy2(source, cache_dir / name)
        reference_dir = run_dir / "reference_close_read"
        if reference_dir.exists():
            shutil.copytree(reference_dir, cache_dir / "reference_close_read")

        manifest_payload = dict(manifest)
        manifest_payload["memory_files"] = self._snapshot_modeling_memory_files(
            cache_dir=cache_dir,
            db_path=artifacts.db_path,
            book_id=artifacts.book_id,
        )
        (cache_dir / "manifest.json").write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _snapshot_modeling_memory_files(self, *, cache_dir: Path, db_path: Path, book_id: str) -> list[dict[str, str]]:
        memory_files: list[dict[str, str]] = []
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT world_markdown_path, world_summary_path, outline_markdown_path, debug_export_path
                FROM book_assets
                WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return memory_files
        memory_dir = cache_dir / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        for field in ("world_markdown_path", "world_summary_path", "outline_markdown_path", "debug_export_path"):
            source = Path(str(row[field] or "")).expanduser()
            if not source.exists() or not source.is_file():
                continue
            cache_name = f"{field}{source.suffix or '.md'}"
            cache_path = memory_dir / cache_name
            shutil.copy2(source, cache_path)
            memory_files.append(
                {
                    "cache_path": str(Path("memory") / cache_name),
                    "restore_path": str(source),
                }
            )
        return memory_files

    def _restore_cached_memory_files(self, *, cache_dir: Path, manifest: dict[str, object]) -> None:
        for item in manifest.get("memory_files", []):
            if not isinstance(item, dict):
                continue
            cache_path = cache_dir / _normalize_text(item.get("cache_path"))
            restore_path_text = _normalize_text(item.get("restore_path"))
            if not cache_path.exists() or not restore_path_text:
                continue
            restore_path = Path(restore_path_text).expanduser()
            if not restore_path.is_absolute():
                restore_path = (self.repo_root / restore_path).resolve()
            restore_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cache_path, restore_path)

    def _read_json_object(self, path: Path) -> dict[str, object]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"expected JSON object in {path}")
        return {str(key): value for key, value in payload.items()}

    def _run_reference_close_read(
        self,
        *,
        run_interactive: Any,
        run_dir: Path,
        book_id: str,
        reference_truth: str,
        api_key: str,
        max_read_kb: int = 64,
        max_close_batches: int = 12,
        segment_step_kb: int = 32,
        close_step_batches: int = 1,
    ) -> dict[str, object]:
        reference_dir = run_dir / "reference_close_read"
        reference_dir.mkdir(parents=True, exist_ok=True)
        reference_source_path = reference_dir / "source.txt"
        reference_source_path.write_text(reference_truth.strip() + "\n", encoding="utf-8")
        reference_db_path = reference_dir / "reference.db"
        if reference_db_path.exists():
            reference_db_path.unlink()
        pipeline_result = run_interactive._run_pipeline(  # noqa: SLF001
            repo_root=self.repo_root,
            book_id=book_id,
            source_path=reference_source_path,
            db_path=reference_db_path,
            debug_path=reference_dir / "debug.md",
            api_key=api_key,
            run_mode="fresh",
            max_read_kb=max_read_kb,
            max_close_batches=max_close_batches,
            segment_step_kb=segment_step_kb,
            close_step_batches=close_step_batches,
            build_creative_kb=False,
            thinking="disabled",
            reasoning_effort=None,
            include_reasoning_content=False,
        )
        context = self._load_reference_close_read_context(db_path=reference_db_path, book_id=book_id)
        return {
            **context,
            "book_id": book_id,
            "db_path": str(reference_db_path),
            "source_path": str(reference_source_path),
            "debug_path": str(reference_dir / "debug.md"),
            "pipeline_result": pipeline_result,
        }

    def _load_reference_close_read_context(self, *, db_path: Path, book_id: str) -> dict[str, object]:
        chapter_summaries: list[dict[str, object]] = []
        character_docs: list[dict[str, object]] = []
        story_outline_md = ""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            asset_row = conn.execute(
                """
                SELECT outline_markdown_path
                FROM book_assets
                WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()
            if asset_row is not None:
                story_outline_md = self._read_optional_text_path(asset_row["outline_markdown_path"])
            for row in conn.execute(
                """
                SELECT document_title_index, chapter_title, summary_short, summary_md, source_total_chars
                FROM chapters
                WHERE book_id = ?
                ORDER BY document_title_index
                """,
                (book_id,),
            ).fetchall():
                chapter_summaries.append(
                    {
                        "document_title_index": row["document_title_index"],
                        "chapter_title": row["chapter_title"],
                        "summary_short": row["summary_short"],
                        "summary_md": row["summary_md"],
                        "source_total_chars": row["source_total_chars"],
                    }
                )
            for row in conn.execute(
                """
                SELECT canonical_name, aliases_json, profile_summary_md, chapter_indexes_json
                FROM character_profiles
                WHERE book_id = ?
                ORDER BY canonical_name
                """,
                (book_id,),
            ).fetchall():
                character_docs.append(
                    {
                        "canonical_name": row["canonical_name"],
                        "aliases": self._safe_json_list(row["aliases_json"]),
                        "profile_summary_md": row["profile_summary_md"],
                        "chapter_indexes": self._safe_json_list(row["chapter_indexes_json"]),
                    }
                )
        finally:
            conn.close()
        return {
            "reference_chapter_summaries": chapter_summaries,
            "reference_character_docs": character_docs,
            "story_outline_md": story_outline_md,
        }

    def _build_reference_synopsis_from_close_read(
        self,
        *,
        reference_context: dict[str, object],
        source_chars: int,
    ) -> dict[str, object]:
        summaries = [
            item for item in reference_context.get("reference_chapter_summaries", [])
            if isinstance(item, dict)
        ]
        combined_parts = [
            _normalize_text(item.get("summary_md")) or _normalize_text(item.get("summary_short"))
            for item in summaries
        ]
        combined_synopsis = "\n\n".join(part for part in combined_parts if part).strip()
        document_synopses = [
            {
                "order": index,
                "document_title_index": item.get("document_title_index"),
                "chapter_title": item.get("chapter_title"),
                "source_chars": item.get("source_total_chars"),
                "summary": _normalize_text(item.get("summary_md")) or _normalize_text(item.get("summary_short")),
            }
            for index, item in enumerate(summaries, start=1)
            if _normalize_text(item.get("summary_md")) or _normalize_text(item.get("summary_short"))
        ]
        plot_beats = self._plot_beats_from_chapter_summaries(summaries)
        tone_and_style = "\n".join(
            section
            for section in (
                self._extract_markdown_section(_normalize_text(item.get("summary_md")), "结构功能/节奏")
                for item in summaries
            )
            if section
        ).strip()
        return {
            "source": "close_read_chapter_summary",
            "source_chars": int(source_chars),
            "combined_synopsis": combined_synopsis,
            "document_synopses": document_synopses,
            "plot_beats": plot_beats,
            "tone_and_style": tone_and_style,
            "must_preserve": plot_beats,
            "must_avoid": ["不得新增 close-read 梗概未覆盖的大剧情。"],
        }

    def _build_story_outline_from_close_read(
        self,
        *,
        story_context: dict[str, object],
        reference_context: dict[str, object],
        target_chars: int,
    ) -> dict[str, object]:
        reference_summaries = [
            item for item in reference_context.get("reference_chapter_summaries", [])
            if isinstance(item, dict)
        ]
        recent_summaries = [
            item for item in story_context.get("recent_story_synopses", [])
            if isinstance(item, dict)
        ]
        timeline: list[dict[str, object]] = []
        for order, item in enumerate(recent_summaries[-3:], start=1):
            summary = _normalize_text(item.get("summary_short")) or _safe_excerpt(item.get("summary_md"), 180)
            if summary:
                timeline.append({"order": order, "scope": "past", "summary": summary})
        character_names = self._character_names_from_context(story_context)
        story_outline_md = _normalize_text(reference_context.get("story_outline_md"))
        target_summary = self._target_outline_node_from_story_outline(story_outline_md) or self._target_outline_summary(
            reference_summaries
        )
        timeline.append(
            {
                "order": len(timeline) + 1,
                "scope": "target",
                "summary": target_summary,
                "target_chars": int(target_chars),
            }
        )
        return {
            "outline_id": "close-read-gold-outline",
            "source": "close_read_story_outline",
            "current_position": self._current_position_from_recent(recent_summaries),
            "story_outline_md": story_outline_md,
            "timeline": timeline,
            "usable_character_names": character_names,
            "next_outline_node": target_summary,
        }

    def _build_benchmark_writer_planning_input(
        self,
        *,
        story_outline: dict[str, object],
        story_context: dict[str, object],
        target_chars: int,
    ) -> dict[str, object]:
        next_outline_node = _normalize_text(story_outline.get("next_outline_node"))
        recent_synopses = [
            item for item in story_context.get("recent_story_synopses", [])
            if isinstance(item, dict)
        ]
        character_docs = [
            item for item in story_context.get("character_docs", [])
            if isinstance(item, dict)
        ]
        recent_briefs = [
            _normalize_text(item.get("summary_short")) or _safe_excerpt(item.get("summary_md"), 180)
            for item in recent_synopses[-3:]
        ]
        recent_briefs = [item for item in recent_briefs if item]
        character_names = _normalize_string_list(story_outline.get("usable_character_names"))
        if not character_names:
            character_names = [
                _normalize_text(item.get("canonical_name"))
                for item in character_docs
                if _normalize_text(item.get("canonical_name"))
            ]
        benchmark_context = {
            "benchmark_layer": "synopsis",
            "input_policy": (
                "Use only gold upper-layer planning inputs assembled from close-read artifacts: "
                "benchmark_story_outline, prefix recent_story_synopses, and prefix character_docs. "
                "Do not use reference_story_synopsis or reference_truth text for Writer planning."
            ),
            "target_outline_node": next_outline_node,
            "target_chars": int(target_chars),
            "story_outline": story_outline,
            "recent_story_synopses": recent_synopses[-3:],
            "character_docs": character_docs,
        }
        desired_actions = [
            "这是 benchmark Synopsis 层测试：只生成下一段/下一章的 Writer ChapterBrief，不自由另起新线。",
            f"目标故事大纲节点：{next_outline_node}",
            f"目标正文长度约 {int(target_chars)} 个中文字符；ChapterBrief 的剧情边界必须匹配该长度。",
            "ChapterBrief 必须承接 recent_story_synopses，并优先使用 character_docs 中已经出现的人物。",
        ]
        if recent_briefs:
            desired_actions.append("最近故事梗概：" + " / ".join(recent_briefs))
        avoidances = [
            "不得把 Creative KB、世界观摘要或结构知识库中的抽象模式替换为新的剧情目标。",
            "不得新增目标故事大纲节点之外的大型超自然事件、梦境线、机构远程监测或神秘物件。",
            "不得使用 reference_story_synopsis、reference_truth 原文或 Reviewer 对照信息生成 ChapterBrief。",
        ]
        intent_payload = {
            "allow_character_cast": False,
            "major_characters": character_names[:12],
            "desired_actions": desired_actions,
            "avoidances": avoidances,
            "preferred_outcome": next_outline_node,
            "notes": json.dumps(benchmark_context, ensure_ascii=False, indent=2),
        }
        user_world_notes = (
            "本次 Writer planning 用于 benchmark Synopsis 层，不是自由扩展世界观。"
            "如世界观摘要或 Creative KB 暗示更宏大的设定，只可作为背景约束；"
            "ChapterBrief 必须以 benchmark_story_outline.next_outline_node 为唯一剧情目标。"
        )
        return {
            "source": "close_read_gold_upper_inputs",
            "intent_payload": intent_payload,
            "user_world_notes": user_world_notes,
            "benchmark_context": benchmark_context,
            "forbidden_generation_inputs": [
                "reference_truth text",
                "reference_story_synopsis",
                "Reviewer reports",
            ],
        }

    def _build_reference_synopsis_execution_input(
        self,
        *,
        base_execution_data: dict[str, object],
        reference_synopsis: dict[str, object],
        story_outline: dict[str, object],
        story_context: dict[str, object],
        target_chars: int,
    ) -> dict[str, object]:
        execution_input = deepcopy(base_execution_data)
        chapter_id = _normalize_text(execution_input.get("chapter_id")) or "benchmark-expansion"
        chapter_title = (
            _normalize_text(story_outline.get("next_outline_node"))
            or _normalize_text(execution_input.get("chapter_title"))
            or "close-read 梗概扩写"
        )
        source_chars = int(reference_synopsis.get("source_chars") or target_chars or 0)
        target_length = int(target_chars or source_chars or 1800)
        plot_beats = _normalize_string_list(reference_synopsis.get("plot_beats"))
        must_preserve = _normalize_string_list(reference_synopsis.get("must_preserve")) or plot_beats
        combined_synopsis = _normalize_text(reference_synopsis.get("combined_synopsis"))
        document_synopses = [
            item for item in reference_synopsis.get("document_synopses", [])
            if isinstance(item, dict)
        ]
        tone_and_style = _normalize_text(reference_synopsis.get("tone_and_style"))
        chapter_brief = {
            "chapter_id": chapter_id,
            "title": chapter_title,
            "goal": _safe_excerpt(combined_synopsis, limit=360) or chapter_title,
            "chapter_role": "benchmark expansion from close-read synopsis",
            "plot_function": _normalize_text(story_outline.get("next_outline_node")) or chapter_title,
            "emotional_goal": tone_and_style,
            "conflict_goal": _safe_excerpt("; ".join(plot_beats[:2]), limit=240),
            "relationship_targets": [],
            "must_include": must_preserve,
            "forbidden": _normalize_string_list(reference_synopsis.get("must_avoid")),
            "structure_hint": {
                "theory": "close-read event chain",
                "beats": plot_beats,
                "document_synopses": document_synopses,
            },
            "ending_hook": plot_beats[-1] if plot_beats else "",
            "target_word_count": target_length,
            "combined_synopsis": combined_synopsis,
            "reference_document_synopses": document_synopses,
            "sources": [
                {
                    "type": "reference_story_synopsis",
                    "evidence_level": "close_read_summary",
                    "note": "Expansion benchmark input; no reference truth text is included.",
                }
            ],
        }
        execution_input["chapter_title"] = chapter_title
        execution_input["chapter_brief"] = chapter_brief
        execution_input["length_budget"] = {
            "chapter_id": chapter_id,
            "target_chars": target_length,
            "min_chars": max(1, int(target_length * 0.85)),
            "max_chars": max(1, int(target_length * 1.15)),
            "is_focus_chapter": True,
            "focus_reason": "Expansion benchmark must expand the close-read reference synopsis at the held-out source length.",
            "expansion_notes": [
                "严格覆盖 chapter_brief.combined_synopsis 与 must_include 中的每个核心事件。",
                "不得引入 close-read 梗概未覆盖的大剧情或替代性主线。",
                f"正文目标长度约 {target_length} 个中文字符，允许在 min_chars 与 max_chars 范围内浮动。",
            ],
            "source_chapter_target_word_count": target_length,
        }
        execution_input["fact_inputs"] = {
            "benchmark_layer": "expansion",
            "input_synopsis_source": "close_read_reference_story_synopsis",
            "story_outline": story_outline,
            "reference_document_synopses": document_synopses,
            "recent_story_synopses": story_context.get("recent_story_synopses", []),
            "character_docs": story_context.get("character_docs", []),
            "creative_kb_note": "Style and continuity references are inherited from the Writer execution input built over prefix close-read/Creative KB artifacts.",
        }
        forbidden_inputs = _normalize_string_list(execution_input.get("forbidden_inputs"))
        execution_input["forbidden_inputs"] = [
            *forbidden_inputs,
            *_normalize_string_list(reference_synopsis.get("must_avoid")),
            "不得使用 reference_truth 原文；只能根据 close-read 梗概扩写。",
        ]
        writer_rules = _normalize_string_list(execution_input.get("writer_rules"))
        execution_input["writer_rules"] = [
            *writer_rules,
            "本次 benchmark 的正文扩写事实源只以 chapter_brief 中的 close-read 梗概为准。",
            "如果 chapter_brief.reference_document_synopses 存在，必须把连续多个 document 梗概按 order 顺序合并为一个长场景/长章节来写，不得只扩写第一条。",
            "若 fact_inputs 与 chapter_brief 冲突，必须优先遵守 chapter_brief。",
            f"正文长度必须接近目标 {target_length} 字，覆盖梗概全部关键事件后再做场景化展开。",
        ]
        return execution_input

    def _plot_beats_from_chapter_summaries(self, summaries: list[dict[str, object]]) -> list[str]:
        beats: list[str] = []
        for item in summaries:
            summary_md = _normalize_text(item.get("summary_md"))
            event_chain = self._extract_markdown_section(summary_md, "剧情事件链")
            source = event_chain or _normalize_text(item.get("summary_short"))
            for line in source.splitlines():
                cleaned = re.sub(r"^\s*[-*]\s*", "", line).strip()
                if cleaned:
                    beats.append(cleaned)
        return beats or [
            _normalize_text(item.get("summary_short"))
            for item in summaries
            if _normalize_text(item.get("summary_short"))
        ]

    def _extract_markdown_section(self, markdown: str, heading: str) -> str:
        lines = str(markdown or "").splitlines()
        collected: list[str] = []
        in_section = False
        for line in lines:
            if line.startswith("## "):
                current_heading = line[3:].strip()
                if in_section and current_heading != heading:
                    break
                in_section = current_heading == heading
                continue
            if in_section:
                collected.append(line)
        return "\n".join(line for line in collected if line.strip()).strip()

    def _target_outline_summary(self, summaries: list[dict[str, object]]) -> str:
        summary = "；".join(
            _normalize_text(item.get("summary_short")) or _safe_excerpt(item.get("summary_md"), 120)
            for item in summaries
            if _normalize_text(item.get("summary_short")) or _normalize_text(item.get("summary_md"))
        ).strip("；")
        return summary or "根据 close-read 章节大纲展开下一段剧情。"

    def _target_outline_node_from_story_outline(self, story_outline_md: str) -> str:
        chapter_lines: list[str] = []
        for line in story_outline_md.splitlines():
            cleaned = line.strip()
            if not cleaned.startswith("- ["):
                continue
            chapter_line = re.sub(r"^\s*-\s*\[[^\]]+\]\s*", "", cleaned).strip()
            if chapter_line:
                chapter_lines.append(chapter_line)
        return chapter_lines[-1] if chapter_lines else ""

    def _current_position_from_recent(self, recent_summaries: list[dict[str, object]]) -> str:
        if not recent_summaries:
            return "前缀 close-read 未提供最近章节梗概。"
        latest = recent_summaries[-1]
        return _normalize_text(latest.get("summary_short")) or _safe_excerpt(latest.get("summary_md"), 160)

    def _character_names_from_context(
        self,
        story_context: dict[str, object],
    ) -> list[str]:
        names: list[str] = []
        for key in ("character_docs",):
            for item in story_context.get(key, []):
                if isinstance(item, dict):
                    names.append(_normalize_text(item.get("canonical_name")))
        return [name for name in dict.fromkeys(names) if name]

    def _build_writer_generated_synopsis(
        self,
        *,
        execution_data: dict[str, object],
        writer_run_dir: Path,
        fallback_target_chars: int,
    ) -> dict[str, object]:
        chapter_brief = dict(execution_data.get("chapter_brief") or {})
        length_budget = dict(execution_data.get("length_budget") or {})
        structure_hint = dict(chapter_brief.get("structure_hint") or {})
        beats = _normalize_string_list(structure_hint.get("beats"))
        must_include = _normalize_string_list(chapter_brief.get("must_include"))
        forbidden = _normalize_string_list(chapter_brief.get("forbidden"))
        relationship_targets = [
            item for item in chapter_brief.get("relationship_targets", [])
            if isinstance(item, dict)
        ]

        plot_beats = [
            _normalize_text(chapter_brief.get("goal")),
            _normalize_text(chapter_brief.get("conflict_goal")),
            *beats,
            _normalize_text(chapter_brief.get("ending_hook")),
        ]
        plot_beats = [beat for beat in dict.fromkeys(plot_beats) if beat]

        synopsis_parts = []
        for label, key in (
            ("章节目标", "goal"),
            ("情绪目标", "emotional_goal"),
            ("冲突目标", "conflict_goal"),
            ("结尾钩子", "ending_hook"),
        ):
            text = _normalize_text(chapter_brief.get(key))
            if text:
                synopsis_parts.append(f"{label}：{text}")
        if beats:
            synopsis_parts.append("结构节拍：" + "；".join(beats))
        if must_include:
            synopsis_parts.append("必须包含：" + "；".join(must_include))

        relationship_notes = []
        for item in relationship_targets:
            current_state = _normalize_text(item.get("current_state"))
            target_shift = _normalize_text(item.get("target_shift"))
            relation_type = _normalize_text(item.get("relation_type"))
            note = " / ".join(part for part in (relation_type, current_state, target_shift) if part)
            if note:
                relationship_notes.append(note)
        if relationship_notes:
            synopsis_parts.append("关系推进：" + "；".join(relationship_notes))

        characters_used = []
        for item in execution_data.get("planned_character_constraints", []):
            if isinstance(item, dict):
                characters_used.append(_normalize_text(item.get("canonical_name") or item.get("name")))
        target_chars = int(length_budget.get("target_chars") or fallback_target_chars or 0)
        return {
            "source": "writer_chapter_brief",
            "target_chars": target_chars,
            "chapter_id": _normalize_text(chapter_brief.get("chapter_id")),
            "chapter_title": _normalize_text(execution_data.get("chapter_title") or chapter_brief.get("title")),
            "combined_synopsis": "\n".join(synopsis_parts).strip(),
            "plot_beats": plot_beats,
            "characters_used": [name for name in dict.fromkeys(characters_used) if name],
            "locations": [],
            "tone_and_style": "\n".join(
                text for text in (
                    _normalize_text(chapter_brief.get("chapter_role")),
                    _normalize_text(chapter_brief.get("plot_function")),
                    _normalize_text(chapter_brief.get("emotional_goal")),
                )
                if text
            ),
            "must_preserve": must_include or plot_beats,
            "must_avoid": forbidden,
            "writer_artifacts": {
                "writer_run_dir": str(writer_run_dir),
                "chapter_package_path": str(writer_run_dir / "chapter_package.json"),
                "chapter_brief_path": str(writer_run_dir / "chapter_brief.json"),
                "chapter_execution_input_path": str(writer_run_dir / "chapter_execution_input.json"),
            },
            "writer_chapter_brief": chapter_brief,
            "length_budget": length_budget,
        }

    def _build_synopsis_review_prompt(
        self,
        *,
        story_outline: dict[str, object],
        recent_story_synopses: object,
        character_docs: object,
        generated_synopsis: dict[str, object],
        reference_synopsis: dict[str, object],
    ) -> dict[str, object]:
        return {
            "system_prompt": (
                "你是分层 Writer benchmark 的梗概层 Reviewer。你只比较两个故事梗概，"
                "不要评价正文文笔。重点判断 Writer 根据已有大纲生成的下一段梗概，"
                "是否与原文连续多个 document 的 reference 梗概在剧情功能、信息密度、节奏和边界上相似。"
                "必须优先检查 reference_story_synopsis 的核心 plot_beats 是否被 generated_story_synopsis 覆盖。"
                "如果主要人物行动、因果事件或关键转折不是同一组事件，即使抽象功能相似，也必须判为 fail 或 borderline，"
                "且 score 不得高于 0.45。只有核心事件大体一致时，才允许给 pass。"
                "只输出 JSON。"
            ),
            "user_payload": {
                "story_outline": story_outline,
                "recent_story_synopses": recent_story_synopses,
                "character_docs": character_docs,
                "generated_story_synopsis": generated_synopsis,
                "reference_story_synopsis": reference_synopsis,
                "schema": {
                    "decision": "pass|borderline|fail",
                    "score": "0.0-1.0",
                    "summary": "中文结论",
                    "checks": {
                        "plot_function_alignment": "剧情功能是否一致",
                        "beat_alignment": "关键 beat 是否匹配",
                        "scope_alignment": "梗概粒度/边界是否一致",
                        "information_density_alignment": "信息密度是否相近",
                        "forbidden_drift": "是否提前推进或新增大设定",
                    },
                    "issues": [{"type": "...", "severity": "fatal|warning|info", "message": "...", "evidence": "..."}],
                },
            },
        }

    def _load_story_context(self, *, db_path: Path, book_id: str) -> dict[str, object]:
        recent_story_synopses: list[dict[str, object]] = []
        character_docs: list[dict[str, object]] = []
        story_outline_md = ""
        if not db_path.exists():
            return {
                "recent_story_synopses": recent_story_synopses,
                "character_docs": character_docs,
                "story_outline_md": story_outline_md,
            }
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            asset_row = conn.execute(
                """
                SELECT outline_markdown_path
                FROM book_assets
                WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()
            if asset_row is not None:
                story_outline_md = self._read_optional_text_path(asset_row["outline_markdown_path"])
            for row in conn.execute(
                """
                SELECT document_title_index, chapter_title, summary_short, summary_md, source_total_chars
                FROM chapters
                WHERE book_id = ?
                ORDER BY document_title_index
                """,
                (book_id,),
            ).fetchall()[-5:]:
                recent_story_synopses.append(
                    {
                        "document_title_index": row["document_title_index"],
                        "chapter_title": row["chapter_title"],
                        "summary_short": row["summary_short"],
                        "summary_md": row["summary_md"],
                        "source_total_chars": row["source_total_chars"],
                    }
                )
            for row in conn.execute(
                """
                SELECT canonical_name, aliases_json, profile_summary_md, chapter_indexes_json
                FROM character_profiles
                WHERE book_id = ?
                ORDER BY canonical_name
                """,
                (book_id,),
            ).fetchall():
                character_docs.append(
                    {
                        "canonical_name": row["canonical_name"],
                        "aliases": self._safe_json_list(row["aliases_json"]),
                        "profile_summary_md": row["profile_summary_md"],
                        "chapter_indexes": self._safe_json_list(row["chapter_indexes_json"]),
                    }
                )
        finally:
            conn.close()
        return {
            "recent_story_synopses": recent_story_synopses,
            "character_docs": character_docs,
            "story_outline_md": story_outline_md,
        }

    def _read_optional_text_path(self, value: object) -> str:
        raw_path = _normalize_text(value)
        if not raw_path:
            return ""
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (self.repo_root / path).resolve()
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace").strip()

    def _safe_json_list(self, value: object) -> list[object]:
        try:
            parsed = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    def _build_expansion_review_prompt(
        self,
        *,
        reference_synopsis: dict[str, object],
        reference_truth: str,
        generated_text: str,
    ) -> dict[str, object]:
        return {
            "system_prompt": (
                "你是分层 Writer benchmark 的扩写层 Reviewer。请评估生成正文是否忠实扩写了"
                "reference_story_synopsis，并与 reference_text 在长度、信息密度、剧情边界和基调上相近。"
                "不要要求字面复刻，但要惩罚新增大剧情、长度严重失衡、提前推进主线。只输出 JSON。"
            ),
            "user_payload": {
                "reference_story_synopsis": reference_synopsis,
                "reference_text_chars": len(reference_truth.strip()),
                "reference_text": reference_truth.strip(),
                "generated_text_chars": len(generated_text.strip()),
                "generated_text": generated_text.strip(),
                "schema": {
                    "decision": "pass|borderline|fail",
                    "score": "0.0-1.0",
                    "summary": "中文结论",
                    "checks": {
                        "synopsis_coverage": "是否覆盖梗概内容",
                        "length_alignment": "是否接近原文窗口长度",
                        "density_alignment": "信息密度是否相近",
                        "tone_alignment": "语气和叙事功能是否接近",
                        "no_large_plot_drift": "是否避免新增大剧情",
                    },
                    "issues": [{"type": "...", "severity": "fatal|warning|info", "message": "...", "evidence": "..."}],
                },
            },
        }

    def _generate_json_with_model(
        self,
        *,
        generation_service: ContinuationGenerationService,
        generation_config: RunConfig,
        prompt_payload: dict[str, object],
    ) -> dict[str, object]:
        result = generation_service.generate(
            prompt=self._format_prompt_payload(prompt_payload),
            config=generation_config,
        )
        return self._parse_json_response(result.generated_text)

    def _format_prompt_payload(self, payload: dict[str, object]) -> str:
        return (
            f"{payload.get('system_prompt', '')}\n\n"
            f"输入：\n{json.dumps(payload.get('user_payload', {}), ensure_ascii=False, indent=2)}"
        ).strip()

    def _parse_json_response(self, raw_text: str) -> dict[str, object]:
        text = _normalize_text(raw_text)
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("benchmark model JSON must be an object")
        return {str(key): value for key, value in payload.items()}

    def _unwrap_run_data(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data")
        if isinstance(data, dict):
            return {str(key): value for key, value in data.items()}
        return {str(key): value for key, value in payload.items()}

    def _report_decision(self, report: dict[str, object]) -> str:
        decision = _normalize_text(report.get("decision"))
        if decision in {"pass", "borderline", "fail"}:
            return decision
        return self._decision_for_score(self._report_score(report))

    def _report_score(self, report: dict[str, object]) -> float:
        try:
            return round(max(0.0, min(1.0, float(report.get("score") or 0.0))), 4)
        except (TypeError, ValueError):
            return 0.0

    def _report_summary(self, report: dict[str, object]) -> str:
        return _normalize_text(report.get("summary")) or "Reviewer 未提供结论。"

    def _combined_score(self, synopsis_report: dict[str, object], expansion_report: dict[str, object]) -> float:
        return round((self._report_score(synopsis_report) + self._report_score(expansion_report)) / 2, 4)

    def _combined_decision(self, synopsis_report: dict[str, object], expansion_report: dict[str, object]) -> str:
        decisions = {self._report_decision(synopsis_report), self._report_decision(expansion_report)}
        if "fail" in decisions:
            return "fail"
        if "borderline" in decisions:
            return "borderline"
        return self._decision_for_score(self._combined_score(synopsis_report, expansion_report))

    def _decision_for_score(self, score: float) -> str:
        if score >= 0.60:
            return "pass"
        if score >= 0.45:
            return "borderline"
        return "fail"

    def _prepare_agentic_windows(
        self,
        *,
        source_text: str,
        minimum_prefix_chars: int,
        minimum_prefix_chunks: int,
        recent_window_size: int,
        chunk_target_chars: int = 900,
        reference_min_chars: int = 2_700,
    ) -> tuple[str, list[str], str, list[str]]:
        chunks = self._split_agentic_chunks(source_text=source_text, target_chars=chunk_target_chars)
        if len(chunks) < 2:
            raise ValueError("source must contain enough text for one prefix window and one held-out reference window")

        prefix_chunks: list[str] = []
        prefix_chars = 0
        min_chunks = max(1, int(minimum_prefix_chunks))
        min_chars = max(1, int(minimum_prefix_chars))
        for chunk in chunks[:-1]:
            prefix_chunks.append(chunk)
            prefix_chars += len(chunk)
            if len(prefix_chunks) >= min_chunks and prefix_chars >= min_chars:
                break
        next_index = len(prefix_chunks)
        if next_index >= len(chunks):
            raise ValueError("source ended before a held-out reference window could be selected")

        reference_chunks: list[str] = []
        reference_chars = 0
        for chunk in chunks[next_index:]:
            reference_chunks.append(chunk)
            reference_chars += len(chunk)
            if reference_chars >= reference_min_chars:
                break
        reference_truth = "\n\n".join(reference_chunks).strip()
        if not reference_truth:
            raise ValueError("held-out reference truth is empty")
        if len(reference_truth) < reference_min_chars:
            raise ValueError(
                "held-out reference truth is shorter than reference_min_chars; "
                f"got {len(reference_truth)} chars, need {reference_min_chars}. "
                "Lower --prefix-min-chars or --reference-min-chars, or use a longer source fixture."
            )

        recent_count = max(1, int(recent_window_size))
        recent_segments = prefix_chunks[-recent_count:]
        return "\n\n".join(prefix_chunks).strip(), recent_segments, reference_truth, prefix_chunks

    def _split_agentic_chunks(self, *, source_text: str, target_chars: int) -> list[str]:
        body = self._source_body_text(source_text)
        sentences = split_sentences(body)
        if not sentences:
            sentences = [line.strip() for line in body.splitlines() if line.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_chars = 0
        max_chars = max(200, int(target_chars))
        for sentence in sentences:
            if len(sentence) > max_chars:
                if current:
                    chunks.append(" ".join(current).strip())
                    current = []
                    current_chars = 0
                for start in range(0, len(sentence), max_chars):
                    part = sentence[start : start + max_chars].strip()
                    if part:
                        chunks.append(part)
                continue
            if current and current_chars + len(sentence) > max_chars:
                chunks.append(" ".join(current).strip())
                current = []
                current_chars = 0
            current.append(sentence)
            current_chars += len(sentence)
        if current:
            chunks.append(" ".join(current).strip())
        return [chunk for chunk in chunks if chunk]

    def _source_body_text(self, source_text: str) -> str:
        normalized = str(source_text or "").replace("\r\n", "\n").replace("\r", "\n")
        raw_lines = normalized.splitlines()
        start_index = 0
        for index, line in enumerate(raw_lines):
            if CHAPTER_HEADING_PATTERN.search(line):
                start_index = index + 1
                break
        return "\n".join(raw_lines[start_index:]).strip()
