from __future__ import annotations

import json
import re
import uuid
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
from .smoke_sample_service import SmokeSampleService
from .smoke_reviewer_service import SmokeReviewerService


LONGZU_32KB_FIXTURE = Path("novel_agent/tests/longzu_32kb.txt")
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
    reviewer_report_path: str
    summary_path: str
    generated_chars: int
    reference_truth_chars: int
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
            "reviewer_report_path": self.reviewer_report_path,
            "summary_path": self.summary_path,
            "generated_chars": self.generated_chars,
            "reference_truth_chars": self.reference_truth_chars,
            "reviewer_decision": self.reviewer_decision,
            "reviewer_score": self.reviewer_score,
            "reviewer_summary": self.reviewer_summary,
        }


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
        prefix_count: int = 8,
        prefix_min_chars: int = 8_000,
        recent_window_size: int = 3,
    ) -> AgenticSmokeBenchmarkResult:
        return self.run_from_source(
            source_path=source_path or self.sample_service.default_longzu_source_path(),
            api_key=api_key,
            runs_dir=runs_dir,
            prefix_count=prefix_count,
            prefix_min_chars=prefix_min_chars,
            recent_window_size=recent_window_size,
        )

    def run_from_source(
        self,
        *,
        source_path: Path,
        api_key: str,
        runs_dir: Path | None = None,
        prefix_count: int = 8,
        prefix_min_chars: int = 8_000,
        recent_window_size: int = 3,
    ) -> AgenticSmokeBenchmarkResult:
        from .. import run_interactive
        from ..schemas.smoke_schema import AuthorizedInputs, DocumentsCutoff, LoadedSmokeSample, LoadedSmokeStep, SmokeSampleConfig, SmokeTextArtifact

        resolved_source = source_path.expanduser().resolve()
        if not resolved_source.exists():
            raise FileNotFoundError(f"benchmark source not found: {resolved_source}")
        if not api_key.strip():
            raise ValueError("api_key is required for real agentic smoke benchmark")

        run_id = uuid.uuid4().hex
        root = (runs_dir or self.repo_root / "runs" / "benchmarks").expanduser().resolve()
        run_dir = root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        segments = self.sample_service._split_story_segments(resolved_source.read_text(encoding="utf-8"))  # noqa: SLF001
        prefix_count = self._resolve_prefix_count(
            segments=segments,
            minimum_segments=prefix_count,
            minimum_chars=prefix_min_chars,
        )
        if len(segments) <= prefix_count:
            raise ValueError(f"source has {len(segments)} usable segments; need prefix plus held-out reference")
        prefix_segments = segments[:prefix_count]
        reference_truth = segments[prefix_count]
        recent_segments = prefix_segments[-max(1, recent_window_size):]
        prefix_source_path = run_dir / "source_prefix.txt"
        reference_truth_path = run_dir / "reference_truth.txt"
        prefix_source_path.write_text("\n\n".join(prefix_segments) + "\n", encoding="utf-8")
        reference_truth_path.write_text(reference_truth + "\n", encoding="utf-8")

        book_id = f"longzu-32kb-agentic-{run_id[:8]}"
        db_path = self.repo_root / ".indexes" / f"{book_id}.db"
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
            max_read_kb=64,
            max_close_batches=12,
            segment_step_kb=32,
            close_step_batches=1,
            build_creative_kb=True,
        )
        (run_dir / "pipeline_result.json").write_text(
            json.dumps(pipeline_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
                intent_payload={
                    "benchmark_goal": "续写 held-out 原文下一片段，用于端到端 Agentic smoke benchmark。",
                    "reference_truth_withheld": True,
                },
                target_chapter_count=1,
                chapter_count=1,
                allow_incomplete_modeling=False,
                confirm_review=lambda _stage, _artifact_path: True,
                accept_chapter_review=lambda _artifact_path: "accepted",
                execute_chapter=True,
            )
            conn.commit()
        (run_dir / "writer_result.json").write_text(
            json.dumps(run_interactive.redact_writer_result_for_terminal(writer_result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        writer_run_dir = run_dir / "writer_runs" / run_id
        draft_path = writer_run_dir / "draft.md"
        if not draft_path.exists():
            raise FileNotFoundError(f"writer draft not found after benchmark run: {draft_path}")
        generated_text = draft_path.read_text(encoding="utf-8")
        execution_input_path = writer_run_dir / "chapter_execution_input.json"
        current_unit_plan: dict[str, object] = {}
        if execution_input_path.exists():
            raw_execution = json.loads(execution_input_path.read_text(encoding="utf-8"))
            execution_data = raw_execution.get("data") if isinstance(raw_execution, dict) else raw_execution
            if isinstance(execution_data, dict):
                chapter_brief = execution_data.get("chapter_brief")
                current_unit_plan = dict(chapter_brief) if isinstance(chapter_brief, dict) else {}

        reviewer_config = RunConfig(
            prompt=None,
            model_type="OpenAIModel",
            model_id=run_interactive.DEFAULT_WRITER_MODEL_NAME,
            provider=None,
            api_base="https://api.deepseek.com",
            api_key=api_key,
            thinking="enabled",
            reasoning_effort="high",
            save_reasoning=False,
            action_type="tool_calling",
            tools=[],
            imports=[],
            verbosity_level=1,
            dry_run=False,
        )
        reviewer = SmokeReviewerService(
            generation_service=ContinuationGenerationService(),
            generation_config=reviewer_config,
        )
        step = LoadedSmokeStep(
            step_id="agentic-e2e",
            anchor_context=SmokeTextArtifact(path=str(prefix_source_path), text="\n\n".join(prefix_segments[-2:])),
            recent_window=[
                SmokeTextArtifact(path=f"recent_{index}.txt", text=text)
                for index, text in enumerate(recent_segments, start=1)
            ],
            reference_truth=SmokeTextArtifact(path=str(reference_truth_path), text=reference_truth),
        )
        sample = LoadedSmokeSample(
            config=SmokeSampleConfig(
                sample_id="longzu-32kb-agentic-e2e",
                book_id=book_id,
                target_chapter_id="held-out-next-segment",
                mode="chapter_authorized",
                anchor_context_path=str(prefix_source_path),
                recent_window_refs=[],
                documents_cutoff=DocumentsCutoff(max_document_title_index=str(prefix_count)),
                reference_truth_path=str(reference_truth_path),
            ),
            sample_path=str(run_dir / "agentic_sample_virtual.json"),
            steps=[step],
        )
        reviewer_report = reviewer.review(
            sample=sample,
            step=step,
            authorized_inputs=AuthorizedInputs(current_unit_plan=current_unit_plan),
            generated_text=generated_text,
        )
        reviewer_report_path = run_dir / "reviewer_report.json"
        reviewer_report_path.write_text(
            json.dumps(reviewer_report.to_dict(), ensure_ascii=False, indent=2),
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
            reviewer_report_path=str(reviewer_report_path),
            summary_path=str(summary_path),
            generated_chars=len(generated_text.strip()),
            reference_truth_chars=len(reference_truth.strip()),
            reviewer_decision=reviewer_report.decision,
            reviewer_score=reviewer_report.score,
            reviewer_summary=reviewer_report.summary,
        )
        summary_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _resolve_prefix_count(
        self,
        *,
        segments: list[str],
        minimum_segments: int,
        minimum_chars: int,
    ) -> int:
        if len(segments) < 2:
            raise ValueError("source must contain at least one prefix segment and one held-out reference segment")
        target_chars = max(1, int(minimum_chars))
        total_chars = 0
        resolved_count = max(1, int(minimum_segments))
        for index, segment in enumerate(segments[:-1], start=1):
            total_chars += len(segment)
            if index >= resolved_count and total_chars >= target_chars:
                return index
        return min(len(segments) - 1, max(1, resolved_count))
