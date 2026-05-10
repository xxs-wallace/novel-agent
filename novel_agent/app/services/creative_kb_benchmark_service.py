from __future__ import annotations

import json
import random
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..repos.creative_kb_storage import init_creative_kb_schema
from ..repos.db import NovelAgentDB
from ..repos.documents_repo import DocumentRow, DocumentsRepo
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..repos.fragment_clusters_repo import FragmentClustersRepo
from ..schemas.creative_kb_benchmark_schema import (
    CLUSTER_REVIEW_CHECKS,
    FRAGMENT_CARD_REVIEW_CHECKS,
    RETRIEVAL_REVIEW_CHECKS,
    CreativeKBBenchmarkInput,
    CreativeKBBenchmarkResult,
    KBClusterReviewReport,
    KBFragmentCardReviewReport,
    KBRetrievalReviewReport,
    KBBenchmarkCase,
)
from ..schemas.creative_kb_schema import CreativeKBBuildResult, FragmentCard, FragmentCluster, SceneBrief
from ..schemas.orchestration_schema import CreativeKBRetrievalInput, RetrievalContext


FRAGMENT_CARD_REVIEW_SAMPLE_SIZE = 3
FRAGMENT_CLUSTER_REVIEW_SAMPLE_SIZE = 2
FIXTURE_PATHS = {
    "longzu_32kb": Path("novel_agent/tests/longzu_32kb.txt"),
    "longzu_96kb": Path("novel_agent/tests/longzu_96kb.txt"),
}
SEGMENT_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
CHAPTER_HEADING_PATTERN = re.compile(r"^\s*(第[一二三四五六七八九十百千万\d]+[章节幕卷回部]|chapter\b)", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


@dataclass(frozen=True, slots=True)
class _BenchmarkWindows:
    source_path: Path
    source_text: str
    prefix_segments: list[str]
    reference_segments: list[str]
    source_prefix: str
    reference_truth: str


class CreativeKBBenchmarkService:
    """Orchestrates Creative KB benchmark runs without replacing KB or retrieval facades."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        creative_kb_facade: Any | None = None,
        retrieval_facade: Any | None = None,
        kb_reviewer_service: Any | None = None,
        model_client: Any | None = None,
        writer_ab_service: Any | None = None,
        documents_repo: DocumentsRepo | None = None,
        fragment_cards_repo: FragmentCardsRepo | None = None,
        fragment_clusters_repo: FragmentClustersRepo | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve() if repo_root is not None else Path.cwd().resolve()
        self.documents_repo = documents_repo or DocumentsRepo()
        self.fragment_cards_repo = fragment_cards_repo or FragmentCardsRepo()
        self.fragment_clusters_repo = fragment_clusters_repo or FragmentClustersRepo()
        self.creative_kb_facade = creative_kb_facade
        self.retrieval_facade = retrieval_facade
        self.kb_reviewer_service = kb_reviewer_service
        self.model_client = model_client
        self.writer_ab_service = writer_ab_service
        self.progress_callback = progress_callback

    def _emit_benchmark_progress(
        self,
        phase: str,
        *,
        run_id: str,
        artifact_dir: Path,
        **payload: Any,
    ) -> None:
        self._emit_progress(
            {
                "stage": "creative_kb_benchmark",
                "phase": phase,
                "run_id": run_id,
                "artifact_dir": str(artifact_dir),
                **payload,
            }
        )

    def _emit_creative_kb_progress(self, event: dict[str, Any]) -> None:
        self._emit_progress({"stage": "creative_kb", **dict(event)})

    def _emit_progress(self, event: dict[str, Any]) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(event)
        except Exception:
            return

    def _build_creative_kb_with_progress(
        self,
        facade: Any,
        conn: Any,
        *,
        documents: Sequence[DocumentRow],
    ) -> CreativeKBBuildResult:
        try:
            return facade.build_creative_kb(
                conn,
                documents=documents,
                progress_callback=self._emit_creative_kb_progress,
            )
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return facade.build_creative_kb(conn, documents=documents)

    def run(self, benchmark_input: CreativeKBBenchmarkInput) -> CreativeKBBenchmarkResult:
        run_id = benchmark_input.run_id or uuid.uuid4().hex
        artifact_dir = self._resolve_artifact_dir(benchmark_input, run_id=run_id)
        self._emit_benchmark_progress(
            "benchmark_start",
            run_id=run_id,
            artifact_dir=artifact_dir,
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)

        errors: list[str] = []
        warnings: list[str] = []
        build_summary: dict[str, Any] = {}
        case_summary: dict[str, Any] = {}
        kb_quality_review_summary: dict[str, Any] = self._pending_kb_quality_summary()
        retrieval_review_summary: dict[str, Any] = self._pending_retrieval_summary(case_reports=[])
        writer_ab_summary = self._writer_ab_summary(enabled=benchmark_input.enable_writer_ab)

        self._write_json(artifact_dir / "benchmark_input.json", benchmark_input.to_dict())
        try:
            self._emit_benchmark_progress("windows_start", run_id=run_id, artifact_dir=artifact_dir)
            windows = self._build_windows(benchmark_input)
            self._emit_benchmark_progress(
                "windows_ready",
                run_id=run_id,
                artifact_dir=artifact_dir,
                prefix_segment_count=len(windows.prefix_segments),
                reference_segment_count=len(windows.reference_segments),
            )
            (artifact_dir / "source_prefix.txt").write_text(windows.source_prefix.rstrip() + "\n", encoding="utf-8")
            (artifact_dir / "reference_truth.txt").write_text(
                windows.reference_truth.rstrip() + "\n",
                encoding="utf-8",
            )

            db_path = artifact_dir / "creative_kb_benchmark.db"
            if db_path.exists():
                db_path.unlink()
            db = NovelAgentDB(db_path)
            book_id = f"creative-kb-benchmark-{run_id}"
            with db.connect() as conn:
                db.init_schema(conn)
                init_creative_kb_schema(conn)
                self._emit_benchmark_progress("documents_start", run_id=run_id, artifact_dir=artifact_dir)
                documents = self._persist_prefix_documents(
                    conn,
                    book_id=book_id,
                    source_path=windows.source_path,
                    prefix_segments=windows.prefix_segments,
                )
                conn.commit()
                if not documents:
                    raise ValueError("benchmark prefix produced no buildable documents")
                self._emit_benchmark_progress(
                    "documents_ready",
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    document_count=len(documents),
                )

                facade = self._resolve_creative_kb_facade(benchmark_input)
                self._emit_benchmark_progress(
                    "creative_kb_build_start",
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    document_count=len(documents),
                )
                kb_build_result = self._build_creative_kb_with_progress(
                    facade,
                    conn,
                    documents=documents,
                )
                self._emit_benchmark_progress(
                    "creative_kb_build_done",
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    built_fragment_count=kb_build_result.built_fragment_count,
                    built_cluster_count=kb_build_result.built_cluster_count,
                )
                conn.commit()

                fragment_cards = self.fragment_cards_repo.list_all(conn)
                fragment_clusters = self.fragment_clusters_repo.list_all(conn)
                self._write_json(artifact_dir / "kb_build_result.json", kb_build_result.to_dict())
                self._write_json(
                    artifact_dir / "fragment_cards_sample.json",
                    [card.to_dict() for card in fragment_cards[:20]],
                )
                self._write_json(
                    artifact_dir / "fragment_clusters_sample.json",
                    [cluster.to_dict() for cluster in fragment_clusters[:20]],
                )

                build_summary = self._build_summary(
                    source_path=windows.source_path,
                    db_path=db_path,
                    documents=documents,
                    windows=windows,
                    kb_build_result=kb_build_result,
                    fragment_card_count=len(fragment_cards),
                    fragment_cluster_count=len(fragment_clusters),
                )
                if not fragment_cards:
                    errors.append("creative kb build produced no fragment_cards")
                self._emit_benchmark_progress(
                    "kb_quality_review_start",
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    fragment_card_count=len(fragment_cards),
                    fragment_cluster_count=len(fragment_clusters),
                )
                kb_quality_review_summary = self._run_kb_quality_reviews(
                    conn=conn,
                    artifact_dir=artifact_dir,
                    benchmark_input=benchmark_input,
                    documents=documents,
                    fragment_cards=fragment_cards,
                    fragment_clusters=fragment_clusters,
                )
                build_summary["quality_review"] = kb_quality_review_summary
                warnings.extend(str(warning) for warning in kb_quality_review_summary.get("warnings", []))
                self._emit_benchmark_progress(
                    "kb_quality_review_done",
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    decision=kb_quality_review_summary.get("decision"),
                    score=kb_quality_review_summary.get("score"),
                )

                self._emit_benchmark_progress("cases_start", run_id=run_id, artifact_dir=artifact_dir)
                cases = self.build_benchmark_cases(
                    prefix_segments=windows.prefix_segments,
                    reference_segments=windows.reference_segments,
                    case_count=benchmark_input.case_count,
                    seed=benchmark_input.seed,
                )
                self._write_json(
                    artifact_dir / "scene_brief_cases.json",
                    [case.to_dict() for case in cases],
                )
                case_summary = self._case_summary(cases)
                self._emit_benchmark_progress(
                    "cases_ready",
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    case_count=len(cases),
                )

                case_reports = self._run_retrieval_cases(
                    conn=conn,
                    artifact_dir=artifact_dir,
                    benchmark_input=benchmark_input,
                    cases=cases,
                    fragment_cards=fragment_cards,
                    fragment_clusters=fragment_clusters,
                    seed=benchmark_input.seed,
                    empty_kb=not fragment_cards,
                )
                retrieval_review_summary = self._aggregate_retrieval_reports(case_reports)
                self._emit_benchmark_progress(
                    "retrieval_review_done",
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    decision=retrieval_review_summary.get("decision"),
                    score=retrieval_review_summary.get("score"),
                )
                self._write_json(
                    artifact_dir / "kb_reviewer_report.json",
                    self._compose_kb_reviewer_report(
                        retrieval_review_summary=retrieval_review_summary,
                        kb_quality_review_summary=kb_quality_review_summary,
                        writer_ab_summary=writer_ab_summary,
                    ),
                )
                if retrieval_review_summary.get("decision") == "fail":
                    errors.append(str(retrieval_review_summary.get("summary") or "retrieval review precheck failed"))

            if benchmark_input.enable_writer_ab:
                self._emit_benchmark_progress("writer_ab_start", run_id=run_id, artifact_dir=artifact_dir)
                writer_ab_summary = self._run_writer_ab(
                    artifact_dir=artifact_dir,
                    cases=cases,
                    windows=windows,
                    seed=benchmark_input.seed,
                )
                self._write_json(
                    artifact_dir / "kb_reviewer_report.json",
                    self._compose_kb_reviewer_report(
                        retrieval_review_summary=retrieval_review_summary,
                        kb_quality_review_summary=kb_quality_review_summary,
                        writer_ab_summary=writer_ab_summary,
                    ),
                )
                self._emit_benchmark_progress(
                    "writer_ab_done",
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    status=writer_ab_summary.get("status"),
                    winner=writer_ab_summary.get("winner"),
                )

            status = self._final_status(errors=errors, retrieval_summary=retrieval_review_summary)
            return self._write_result(
                artifact_dir=artifact_dir,
                run_id=run_id,
                status=status,
                build_summary=build_summary,
                case_summary=case_summary,
                retrieval_review_summary=retrieval_review_summary,
                writer_ab_summary=writer_ab_summary,
                errors=errors,
                warnings=warnings,
            )
        except Exception as exc:
            errors.append(str(exc))
            failure_summary = self._failure_retrieval_summary(str(exc))
            self._write_json(
                artifact_dir / "kb_reviewer_report.json",
                self._compose_kb_reviewer_report(
                    retrieval_review_summary=failure_summary,
                    kb_quality_review_summary=kb_quality_review_summary,
                    writer_ab_summary=writer_ab_summary,
                ),
            )
            return self._write_result(
                artifact_dir=artifact_dir,
                run_id=run_id,
                status="failed",
                build_summary=build_summary,
                case_summary=case_summary,
                retrieval_review_summary=failure_summary,
                writer_ab_summary=writer_ab_summary,
                errors=errors,
                warnings=warnings,
            )

    def build_benchmark_cases(
        self,
        *,
        prefix_segments: Sequence[str],
        reference_segments: Sequence[str],
        case_count: int = 3,
        seed: int = 17,
    ) -> list[KBBenchmarkCase]:
        normalized_prefix = [_normalize_text(item) for item in prefix_segments if _normalize_text(item)]
        normalized_references = [_normalize_text(item) for item in reference_segments if _normalize_text(item)]
        normalized_case_count = max(3, min(5, int(case_count or 3)))
        if len(normalized_prefix) < 2:
            raise ValueError("at least two prefix segments are required to build benchmark cases")
        if len(normalized_references) < normalized_case_count:
            raise ValueError(
                f"need at least {normalized_case_count} reference windows, got {len(normalized_references)}"
            )

        templates = self._case_templates()
        rng = random.Random(seed)
        anchor_pool = normalized_prefix[-max(2, min(len(normalized_prefix), normalized_case_count + 1)) :]
        cases: list[KBBenchmarkCase] = []
        for index, template in enumerate(templates[:normalized_case_count], start=1):
            reference_segment = normalized_references[index - 1]
            anchor_start = min(max(0, len(anchor_pool) - 2), max(0, index - 1))
            anchor_context = "\n\n".join(anchor_pool[anchor_start : anchor_start + 2]).strip()
            if not anchor_context:
                anchor_context = "\n\n".join(normalized_prefix[-2:]).strip()
            recent_window_summary = self._recent_window_summary(
                prefix_segments=normalized_prefix,
                case_goal=str(template["goal"]),
                jitter=rng.randint(0, 9999),
            )
            cases.append(
                KBBenchmarkCase(
                    case_id=f"case-{index:03d}",
                    anchor_context=anchor_context,
                    recent_window_summary=recent_window_summary,
                    goal=str(template["goal"]),
                    scene_brief=template["scene_brief"],  # type: ignore[arg-type]
                    reference_synopsis=self._reference_synopsis(
                        category=str(template["category"]),
                        reference_segment=reference_segment,
                    ),
                    expected_traits=list(template["expected_traits"]),  # type: ignore[arg-type]
                    reference_window_index=index,
                    category=str(template["category"]),
                )
            )
        return cases

    def _resolve_artifact_dir(self, benchmark_input: CreativeKBBenchmarkInput, *, run_id: str) -> Path:
        if benchmark_input.artifact_dir:
            path = Path(benchmark_input.artifact_dir).expanduser()
            return path if path.is_absolute() else (self.repo_root / path).resolve()
        return self.repo_root / "runs" / "creative_kb_benchmarks" / run_id

    def _build_windows(self, benchmark_input: CreativeKBBenchmarkInput) -> _BenchmarkWindows:
        source_path = self._resolve_source_path(benchmark_input)
        if not source_path.exists():
            raise FileNotFoundError(f"benchmark source not found: {source_path}")
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
        segments = self._split_source_text(source_text)
        case_count = benchmark_input.case_count
        if len(segments) < case_count + 2:
            raise ValueError(
                f"source only has {len(segments)} usable story segments; "
                f"need at least {case_count + 2} for prefix plus benchmark cases"
            )

        prefix_count = max(2, min(len(segments) - case_count, max(case_count + 1, int(len(segments) * 0.65))))
        while (
            prefix_count < len(segments) - case_count
            and len("\n\n".join(segments[:prefix_count])) < benchmark_input.prefix_min_chars
        ):
            prefix_count += 1
        prefix_segments = segments[:prefix_count]
        reference_segments = segments[prefix_count : prefix_count + case_count]
        if not prefix_segments:
            raise ValueError("benchmark prefix is empty")
        if len(reference_segments) < case_count:
            raise ValueError("benchmark reference windows are incomplete")
        return _BenchmarkWindows(
            source_path=source_path,
            source_text=source_text,
            prefix_segments=prefix_segments,
            reference_segments=reference_segments,
            source_prefix="\n\n".join(prefix_segments).strip(),
            reference_truth="\n\n".join(reference_segments).strip(),
        )

    def _resolve_source_path(self, benchmark_input: CreativeKBBenchmarkInput) -> Path:
        if benchmark_input.source_path:
            path = Path(benchmark_input.source_path).expanduser()
            return path if path.is_absolute() else (self.repo_root / path).resolve()
        fixture = benchmark_input.fixture or "longzu_32kb"
        if fixture in FIXTURE_PATHS:
            return (self.repo_root / FIXTURE_PATHS[fixture]).resolve()
        fixture_path = Path(fixture).expanduser()
        return fixture_path if fixture_path.is_absolute() else (self.repo_root / fixture_path).resolve()

    def _split_source_text(self, source_text: str) -> list[str]:
        normalized = str(source_text or "").replace("\r\n", "\n").replace("\r", "\n")
        raw_lines = normalized.splitlines()
        start_index = 0
        for index, line in enumerate(raw_lines):
            if CHAPTER_HEADING_PATTERN.search(line):
                start_index = index + 1
                break
        candidate_text = "\n".join(raw_lines[start_index:])
        candidates = [item.strip() for item in SEGMENT_SPLIT_PATTERN.split(candidate_text) if item.strip()]
        if len(candidates) < 10:
            candidates = [line.strip() for line in candidate_text.splitlines() if line.strip()]
        segments = [
            candidate
            for candidate in candidates
            if len(candidate) >= 20
            and any(token in candidate for token in ("。", "？", "！", "；", "，", "“", "”"))
        ]
        if len(segments) >= 5:
            return segments
        candidates = [item.strip() for item in SEGMENT_SPLIT_PATTERN.split(normalized) if item.strip()]
        if len(candidates) < 5:
            candidates = [line.strip() for line in normalized.splitlines() if line.strip()]
        return [
            candidate
            for candidate in candidates
            if len(candidate) >= 10
            and any(token in candidate for token in ("。", "？", "！", "；", ".", "?", "!"))
        ]

    def _persist_prefix_documents(
        self,
        conn: Any,
        *,
        book_id: str,
        source_path: Path,
        prefix_segments: Sequence[str],
    ) -> list[DocumentRow]:
        doc_ids: list[int] = []
        offset = 0
        for index, segment in enumerate(prefix_segments, start=1):
            content = _normalize_text(segment)
            if not content:
                continue
            doc_id = self.documents_repo.insert_document(
                conn,
                {
                    "book_id": book_id,
                    "path": str(source_path),
                    "scope": "benchmark_prefix",
                    "title": f"benchmark prefix segment {index}",
                    "content": content,
                    "source_path": str(source_path),
                    "source_file_name": source_path.name,
                    "source_start_offset": offset,
                    "source_end_offset": offset + len(content),
                    "document_title": f"Benchmark Prefix Segment {index}",
                    "document_title_index": index,
                    "inferred_chapter_no": index,
                    "content_chars": len(content),
                    "character_keywords": [],
                    "content_tags": [],
                    "ingestion_run_id": "creative-kb-benchmark",
                    "created_at": _utc_now(),
                    "updated_at": _utc_now(),
                },
            )
            doc_ids.append(doc_id)
            offset += len(content)
        if not doc_ids:
            return []
        return self.documents_repo.fetch_after_doc_id(conn, book_id=book_id)

    def _resolve_creative_kb_facade(self, benchmark_input: CreativeKBBenchmarkInput) -> Any:
        if self.creative_kb_facade is not None:
            return self.creative_kb_facade
        from .creative_kb_facade import CreativeKnowledgeBaseFacade
        from .fragment_card_builder_service import FragmentCardBuilderService

        model_client = self.model_client or self._build_model_client(benchmark_input.model_config)
        self.model_client = model_client
        builder = FragmentCardBuilderService(
            model_client=model_client,
            fragment_cards_repo=self.fragment_cards_repo,
        )
        return CreativeKnowledgeBaseFacade(
            fragment_card_builder_service=builder,
            fragment_cards_repo=self.fragment_cards_repo,
            fragment_clusters_repo=self.fragment_clusters_repo,
        )

    def _build_model_client(self, model_config: object) -> Any:
        from ..llm import JsonModelClient, ModelSettings

        if model_config is None:
            raise ValueError("model_config or an injected creative_kb_facade is required for Creative KB build")
        if isinstance(model_config, ModelSettings):
            return JsonModelClient(model_config)
        if hasattr(model_config, "to_dict"):
            model_config = model_config.to_dict()
        if not isinstance(model_config, dict):
            raise ValueError("model_config must be a mapping, ModelSettings, or RunConfig-like object")
        model_name = _normalize_text(model_config.get("model_name") or model_config.get("model_id"))
        if not model_name:
            raise ValueError("model_config.model_name or model_config.model_id is required")
        settings = ModelSettings(
            model_type=_normalize_text(model_config.get("model_type") or "OpenAIModel"),
            model_name=model_name,
            provider=model_config.get("provider"),  # type: ignore[arg-type]
            base_url=model_config.get("base_url") or model_config.get("api_base"),  # type: ignore[arg-type]
            api_key=model_config.get("api_key"),  # type: ignore[arg-type]
            api_key_file=model_config.get("api_key_file"),  # type: ignore[arg-type]
            api_key_env=model_config.get("api_key_env"),  # type: ignore[arg-type]
            temperature=float(model_config.get("temperature", 0.2)),
            max_output_tokens=int(model_config.get("max_output_tokens", 8192)),
            timeout_seconds=int(model_config.get("timeout_seconds", 120)),
            thinking=model_config.get("thinking"),  # type: ignore[arg-type]
            reasoning_effort=model_config.get("reasoning_effort"),  # type: ignore[arg-type]
            include_reasoning_content=bool(model_config.get("include_reasoning_content", False)),
            dry_run=bool(model_config.get("dry_run", False)),
        )
        return JsonModelClient(settings)

    def _resolve_kb_reviewer_service(self, benchmark_input: CreativeKBBenchmarkInput) -> Any | None:
        if self.kb_reviewer_service is not None:
            return self.kb_reviewer_service
        if self.model_client is None and benchmark_input.model_config is not None:
            self.model_client = self._build_model_client(benchmark_input.model_config)
        if self.model_client is None:
            return None
        from .creative_kb_reviewer_service import CreativeKBReviewerService

        self.kb_reviewer_service = CreativeKBReviewerService(model_client=self.model_client)
        return self.kb_reviewer_service

    def _resolve_retrieval_facade(self) -> Any:
        if self.retrieval_facade is not None:
            return self.retrieval_facade
        from .retrieval_facade import RetrievalFacade

        self.retrieval_facade = RetrievalFacade(
            fragment_cards_repo=self.fragment_cards_repo,
            fragment_clusters_repo=self.fragment_clusters_repo,
        )
        return self.retrieval_facade

    def _run_kb_quality_reviews(
        self,
        *,
        conn: Any,
        artifact_dir: Path,
        benchmark_input: CreativeKBBenchmarkInput,
        documents: Sequence[DocumentRow],
        fragment_cards: Sequence[FragmentCard],
        fragment_clusters: Sequence[FragmentCluster],
    ) -> dict[str, Any]:
        review_root = artifact_dir / "kb_build_reviews"
        card_review_root = review_root / "fragment_cards"
        cluster_review_root = review_root / "fragment_clusters"
        card_review_root.mkdir(parents=True, exist_ok=True)
        cluster_review_root.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        if len(fragment_cards) < FRAGMENT_CARD_REVIEW_SAMPLE_SIZE:
            warnings.append(
                "fragment_card sample count below target: "
                f"{len(fragment_cards)}/{FRAGMENT_CARD_REVIEW_SAMPLE_SIZE}"
            )
        if len(fragment_clusters) < FRAGMENT_CLUSTER_REVIEW_SAMPLE_SIZE:
            warnings.append(
                "fragment_cluster sample count below target: "
                f"{len(fragment_clusters)}/{FRAGMENT_CLUSTER_REVIEW_SAMPLE_SIZE}"
            )
        if not fragment_cards:
            summary = self._empty_kb_quality_summary(warnings=warnings)
            self._write_json(review_root / "fragment_card_review_reports.json", [])
            self._write_json(review_root / "fragment_cluster_review_reports.json", [])
            self._write_json(review_root / "summary.json", summary)
            return summary

        from .creative_kb_reviewer_service import CreativeKBReviewerService

        reviewer_service = self._resolve_kb_reviewer_service(benchmark_input)
        prompt_builder = reviewer_service or CreativeKBReviewerService(model_client=None)
        documents_by_id = {str(document.doc_id): document for document in documents}
        card_reports: list[dict[str, Any]] = []
        cluster_reports: list[dict[str, Any]] = []

        sampled_cards = self._stable_sample_cards(fragment_cards, seed=benchmark_input.seed)
        for card in sampled_cards:
            card_dir = card_review_root / self._safe_artifact_name(card.fragment_id)
            card_dir.mkdir(parents=True, exist_ok=True)
            original_excerpt = self._original_document_excerpt(card=card, documents_by_id=documents_by_id)
            prompt_artifact = prompt_builder.build_fragment_card_prompt_artifact(
                original_document_excerpt=original_excerpt,
                fragment_card=card,
            )
            self._write_json(card_dir / "prompt.json", prompt_artifact)
            report_payload = self._review_fragment_card_sample(
                reviewer_service=reviewer_service,
                original_document_excerpt=original_excerpt,
                fragment_card=card,
            )
            self._write_json(card_dir / "report.json", report_payload)
            card_reports.append(report_payload)

        sampled_clusters = self._stable_sample_clusters(fragment_clusters, seed=benchmark_input.seed)
        cards_by_id = {card.fragment_id: card for card in fragment_cards}
        for cluster in sampled_clusters:
            cluster_dir = cluster_review_root / self._safe_artifact_name(cluster.cluster_id)
            cluster_dir.mkdir(parents=True, exist_ok=True)
            members = self.fragment_cards_repo.list_by_cluster_id(conn, cluster_id=cluster.cluster_id)
            representative_card = cards_by_id.get(cluster.representative_fragment_id)
            if representative_card is None:
                representative_card = next((card for card in members if card.is_cluster_representative), None)
            prompt_artifact = prompt_builder.build_cluster_prompt_artifact(
                cluster=cluster,
                members=members,
                representative_card=representative_card,
            )
            self._write_json(cluster_dir / "prompt.json", prompt_artifact)
            report_payload = self._review_cluster_sample(
                reviewer_service=reviewer_service,
                cluster=cluster,
                members=members,
                representative_card=representative_card,
            )
            self._write_json(cluster_dir / "report.json", report_payload)
            cluster_reports.append(report_payload)

        self._write_json(review_root / "fragment_card_review_reports.json", card_reports)
        self._write_json(review_root / "fragment_cluster_review_reports.json", cluster_reports)
        summary = self._aggregate_kb_quality_reviews(
            card_reports=card_reports,
            cluster_reports=cluster_reports,
            warnings=warnings,
            reviewer_available=reviewer_service is not None,
        )
        self._write_json(review_root / "summary.json", summary)
        return summary

    def _review_fragment_card_sample(
        self,
        *,
        reviewer_service: Any | None,
        original_document_excerpt: str,
        fragment_card: FragmentCard,
    ) -> dict[str, Any]:
        if reviewer_service is None:
            return {
                "fragment_id": fragment_card.fragment_id,
                "doc_id": fragment_card.doc_id,
                "status": "pending_reviewer",
                "decision": "pending",
                "score": 0.0,
                "summary": "KBFragmentCardReviewer is not configured.",
                "checks": {name: "pending" for name in FRAGMENT_CARD_REVIEW_CHECKS},
                "issues": ["reviewer_not_configured"],
            }
        try:
            report = reviewer_service.review_fragment_card(
                original_document_excerpt=original_document_excerpt,
                fragment_card=fragment_card,
            )
            return report.to_dict()
        except Exception as exc:
            return KBFragmentCardReviewReport(
                fragment_id=fragment_card.fragment_id,
                doc_id=fragment_card.doc_id,
                decision="fail",
                score=0.0,
                summary=f"Fragment card reviewer failed: {exc}",
                checks={name: "fail" for name in FRAGMENT_CARD_REVIEW_CHECKS},
                issues=["reviewer_failed"],
            ).to_dict()

    def _review_cluster_sample(
        self,
        *,
        reviewer_service: Any | None,
        cluster: FragmentCluster,
        members: Sequence[FragmentCard],
        representative_card: FragmentCard | None,
    ) -> dict[str, Any]:
        member_ids = [member.fragment_id for member in members]
        if reviewer_service is None:
            return {
                "cluster_id": cluster.cluster_id,
                "representative_fragment_id": cluster.representative_fragment_id,
                "member_fragment_ids": member_ids,
                "status": "pending_reviewer",
                "decision": "pending",
                "score": 0.0,
                "summary": "KBClusterReviewer is not configured.",
                "checks": {name: "pending" for name in CLUSTER_REVIEW_CHECKS},
                "issues": ["reviewer_not_configured"],
            }
        try:
            report = reviewer_service.review_cluster(
                cluster=cluster,
                members=members,
                representative_card=representative_card,
            )
            return report.to_dict()
        except Exception as exc:
            return KBClusterReviewReport(
                cluster_id=cluster.cluster_id,
                representative_fragment_id=cluster.representative_fragment_id,
                member_fragment_ids=member_ids,
                decision="fail",
                score=0.0,
                summary=f"Cluster reviewer failed: {exc}",
                checks={name: "fail" for name in CLUSTER_REVIEW_CHECKS},
                issues=["reviewer_failed"],
            ).to_dict()

    def _aggregate_kb_quality_reviews(
        self,
        *,
        card_reports: Sequence[dict[str, Any]],
        cluster_reports: Sequence[dict[str, Any]],
        warnings: Sequence[str],
        reviewer_available: bool,
    ) -> dict[str, Any]:
        if not reviewer_available:
            return {
                "status": "pending_reviewer",
                "decision": "pending",
                "score": 0.0,
                "summary": "KB card/cluster reviewer is not configured; prompt artifacts were generated.",
                "fragment_card_review": self._pending_review_group(card_reports),
                "cluster_review": self._pending_review_group(cluster_reports),
                "warnings": list(warnings),
            }
        all_reports = [
            report
            for report in [*card_reports, *cluster_reports]
            if report.get("decision") in {"pass", "borderline", "fail"}
        ]
        if not all_reports:
            return self._empty_kb_quality_summary(warnings=warnings)
        score = round(sum(float(report.get("score") or 0.0) for report in all_reports) / len(all_reports), 4)
        decision = self._decision_for_score(score)
        if warnings and decision == "pass":
            decision = "borderline"
        return {
            "status": "completed",
            "decision": decision,
            "score": score,
            "summary": self._kb_quality_summary_text(
                card_reports=card_reports,
                cluster_reports=cluster_reports,
                warnings=warnings,
                decision=decision,
            ),
            "fragment_card_review": self._review_group_summary(
                reports=card_reports,
                target_sample_count=FRAGMENT_CARD_REVIEW_SAMPLE_SIZE,
            ),
            "cluster_review": self._review_group_summary(
                reports=cluster_reports,
                target_sample_count=FRAGMENT_CLUSTER_REVIEW_SAMPLE_SIZE,
            ),
            "warnings": list(warnings),
        }

    def _pending_kb_quality_summary(self) -> dict[str, Any]:
        return {
            "status": "pending_reviewer",
            "decision": "pending",
            "score": 0.0,
            "summary": "KB card/cluster reviewer has not run yet.",
            "fragment_card_review": self._pending_review_group([]),
            "cluster_review": self._pending_review_group([]),
            "warnings": [],
        }

    def _empty_kb_quality_summary(self, *, warnings: Sequence[str]) -> dict[str, Any]:
        return {
            "status": "failed_precheck",
            "decision": "fail",
            "score": 0.0,
            "summary": "Creative KB has no fragment_card samples to review.",
            "fragment_card_review": {
                "decision": "fail",
                "score": 0.0,
                "sample_count": 0,
                "target_sample_count": FRAGMENT_CARD_REVIEW_SAMPLE_SIZE,
                "reports": [],
            },
            "cluster_review": {
                "decision": "fail",
                "score": 0.0,
                "sample_count": 0,
                "target_sample_count": FRAGMENT_CLUSTER_REVIEW_SAMPLE_SIZE,
                "reports": [],
            },
            "warnings": list(warnings),
        }

    def _review_group_summary(
        self,
        *,
        reports: Sequence[dict[str, Any]],
        target_sample_count: int,
    ) -> dict[str, Any]:
        scored_reports = [
            report
            for report in reports
            if report.get("decision") in {"pass", "borderline", "fail"}
        ]
        if not scored_reports:
            return self._pending_review_group(reports, target_sample_count=target_sample_count)
        score = round(sum(float(report.get("score") or 0.0) for report in scored_reports) / len(scored_reports), 4)
        return {
            "decision": self._decision_for_score(score),
            "score": score,
            "sample_count": len(reports),
            "target_sample_count": target_sample_count,
            "reports": list(reports),
        }

    def _pending_review_group(
        self,
        reports: Sequence[dict[str, Any]],
        *,
        target_sample_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "decision": "pending",
            "score": 0.0,
            "sample_count": len(reports),
            "target_sample_count": target_sample_count,
            "reports": list(reports),
        }

    def _kb_quality_summary_text(
        self,
        *,
        card_reports: Sequence[dict[str, Any]],
        cluster_reports: Sequence[dict[str, Any]],
        warnings: Sequence[str],
        decision: str,
    ) -> str:
        warning_text = f" warnings: {'; '.join(warnings)}" if warnings else ""
        return (
            f"KB quality review {decision}: "
            f"{len(card_reports)} card sample(s), {len(cluster_reports)} cluster sample(s)."
            f"{warning_text}"
        )

    def _stable_sample_cards(self, fragment_cards: Sequence[FragmentCard], *, seed: int) -> list[FragmentCard]:
        cards = sorted(fragment_cards, key=lambda card: card.fragment_id)
        return self._stable_sample(cards, sample_size=FRAGMENT_CARD_REVIEW_SAMPLE_SIZE, seed=seed)

    def _stable_sample_clusters(
        self,
        fragment_clusters: Sequence[FragmentCluster],
        *,
        seed: int,
    ) -> list[FragmentCluster]:
        clusters = sorted(fragment_clusters, key=lambda cluster: cluster.cluster_id)
        return self._stable_sample(clusters, sample_size=FRAGMENT_CLUSTER_REVIEW_SAMPLE_SIZE, seed=seed + 131)

    def _stable_sample(self, items: Sequence[Any], *, sample_size: int, seed: int) -> list[Any]:
        normalized = list(items)
        if len(normalized) <= sample_size:
            return normalized
        indexes = sorted(random.Random(seed).sample(range(len(normalized)), sample_size))
        return [normalized[index] for index in indexes]

    def _original_document_excerpt(
        self,
        *,
        card: FragmentCard,
        documents_by_id: dict[str, DocumentRow],
    ) -> str:
        document = documents_by_id.get(card.doc_id)
        if document is not None and document.content.strip():
            return document.content.strip()
        return card.source_excerpt or card.content_summary

    def _compose_kb_reviewer_report(
        self,
        *,
        retrieval_review_summary: dict[str, Any],
        kb_quality_review_summary: dict[str, Any],
        writer_ab_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(retrieval_review_summary)
        payload["retrieval_review"] = dict(retrieval_review_summary)
        payload["build_quality_review"] = dict(kb_quality_review_summary)
        if writer_ab_summary is not None:
            payload["writer_ab_review"] = dict(writer_ab_summary)
        return payload

    def _decision_for_score(self, score: float) -> str:
        if score >= 0.60:
            return "pass"
        if score >= 0.45:
            return "borderline"
        return "fail"

    def _safe_artifact_name(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "item"

    def _run_retrieval_cases(
        self,
        *,
        conn: Any,
        artifact_dir: Path,
        benchmark_input: CreativeKBBenchmarkInput,
        cases: Sequence[KBBenchmarkCase],
        fragment_cards: Sequence[FragmentCard],
        fragment_clusters: Sequence[FragmentCluster],
        seed: int,
        empty_kb: bool,
    ) -> list[dict[str, Any]]:
        cards_by_id = {card.fragment_id: card for card in fragment_cards}
        clusters_by_id = {cluster.cluster_id: cluster for cluster in fragment_clusters}
        case_reports: list[dict[str, Any]] = []
        retrieval_root = artifact_dir / "retrieval_cases"
        retrieval_root.mkdir(parents=True, exist_ok=True)
        from .creative_kb_reviewer_service import CreativeKBReviewerService

        reviewer_service = self._resolve_kb_reviewer_service(benchmark_input)
        prompt_builder = reviewer_service or CreativeKBReviewerService(model_client=None)
        for index, case in enumerate(cases):
            self._emit_progress(
                {
                    "stage": "creative_kb_benchmark",
                    "phase": "retrieval_case_start",
                    "case_id": case.case_id,
                    "case_index": index + 1,
                    "case_count": len(cases),
                    "artifact_dir": str(artifact_dir),
                }
            )
            case_dir = retrieval_root / case.case_id
            case_dir.mkdir(parents=True, exist_ok=True)
            retrieval_input = CreativeKBRetrievalInput(
                anchor_context=case.anchor_context,
                recent_window_summary=case.recent_window_summary,
                goal=case.goal,
                documents=[],
                retrieval_context=RetrievalContext(),
                scene_plan={},
            )
            retrieval_result = self._resolve_retrieval_facade().build_scene_brief_and_retrieve(
                conn,
                retrieval_input=retrieval_input,
                scene_brief=case.scene_brief,
                include_coarse_result=True,
                expand_reference_fragments=True,
            )
            selected_ids = list(retrieval_result.rerank_result.selected_fragment_ids)
            selected_references = self._selected_references(
                selected_ids=selected_ids,
                cards_by_id=cards_by_id,
                clusters_by_id=clusters_by_id,
                rerank_scores=retrieval_result.rerank_result.scores,
                expanded_fragments=retrieval_result.reference_fragments,
            )
            decoy_payload = self._build_decoy_fragments(
                case=case,
                fragment_cards=list(fragment_cards),
                clusters_by_id=clusters_by_id,
                selected_ids=selected_ids,
                rerank_scores=retrieval_result.rerank_result.scores,
                coarse_scores=(
                    retrieval_result.coarse_result.coarse_scores
                    if retrieval_result.coarse_result is not None
                    else {}
                ),
                seed=seed + index,
            )
            decoy_fragments = list(decoy_payload["decoy_references"])
            rejected_high_score_references = self._rejected_high_score_references(
                selected_ids=selected_ids,
                cards_by_id=cards_by_id,
                clusters_by_id=clusters_by_id,
                rerank_scores=retrieval_result.rerank_result.scores,
            )
            reviewer_input = {
                "case_id": case.case_id,
                "scene_brief": case.scene_brief.to_dict(),
                "anchor_context": case.anchor_context,
                "recent_window_summary": case.recent_window_summary,
                "selected_references": selected_references,
                "rerank_scores": [score.to_dict() for score in retrieval_result.rerank_result.scores],
                "decoy_references": decoy_fragments,
                "decoy_missing_reasons": decoy_payload["missing_reasons"],
                "rejected_high_score_references": rejected_high_score_references,
                "rubric_checks": list(RETRIEVAL_REVIEW_CHECKS),
            }
            prompt_artifact = prompt_builder.build_retrieval_prompt_artifact(
                case_id=case.case_id,
                payload=reviewer_input,
            )
            reviewer_report = self._review_retrieval_case(
                reviewer_service=reviewer_service,
                case_id=case.case_id,
                selected_ids=selected_ids,
                decoy_ids=[str(item["fragment_id"]) for item in decoy_fragments],
                empty_kb=empty_kb,
                selected_references=selected_references,
                decoy_references=decoy_fragments,
                reviewer_input=reviewer_input,
            )
            self._write_json(case_dir / "scene_brief.json", case.scene_brief.to_dict())
            self._write_json(
                case_dir / "coarse_result.json",
                retrieval_result.coarse_result.to_dict() if retrieval_result.coarse_result is not None else {},
            )
            self._write_json(case_dir / "rerank_result.json", retrieval_result.rerank_result.to_dict())
            self._write_json(case_dir / "selected_reference_fragments.json", selected_references)
            self._write_json(case_dir / "decoy_fragments.json", decoy_payload)
            self._write_json(case_dir / "kb_retrieval_reviewer_prompt.json", prompt_artifact)
            self._write_json(case_dir / "kb_retrieval_reviewer_report.json", reviewer_report)
            case_reports.append(reviewer_report)
            self._emit_progress(
                {
                    "stage": "creative_kb_benchmark",
                    "phase": "retrieval_case_done",
                    "case_id": case.case_id,
                    "case_index": index + 1,
                    "case_count": len(cases),
                    "decision": reviewer_report.get("decision"),
                    "score": reviewer_report.get("score"),
                    "artifact_dir": str(case_dir),
                }
            )
        return case_reports

    def _selected_references(
        self,
        *,
        selected_ids: Sequence[str],
        cards_by_id: dict[str, FragmentCard],
        clusters_by_id: dict[str, FragmentCluster],
        rerank_scores: Sequence[Any],
        expanded_fragments: Sequence[Any],
    ) -> list[dict[str, Any]]:
        expanded_by_id = {
            str(getattr(fragment, "fragment_id", "")): self._to_jsonable(fragment)
            for fragment in expanded_fragments
        }
        scores_by_id = {str(getattr(score, "candidate_id", "")): score for score in rerank_scores}
        selected_references: list[dict[str, Any]] = []
        for fragment_id in selected_ids:
            if fragment_id in cards_by_id:
                selected_references.append(
                    self._reference_payload(
                        card=cards_by_id[fragment_id],
                        clusters_by_id=clusters_by_id,
                        reference_type="selected",
                        rerank_score=scores_by_id.get(fragment_id),
                        expanded_fragment=expanded_by_id.get(fragment_id),
                    )
                )
            elif fragment_id in expanded_by_id:
                payload = dict(expanded_by_id[fragment_id])
                payload["traceability"] = {
                    "fragment_card": False,
                    "fragment_cluster": False,
                    "missing_reason": "selected reference is missing from fragment_cards",
                }
                selected_references.append(payload)
            else:
                selected_references.append(
                    {
                        "fragment_id": fragment_id,
                        "missing": True,
                        "traceability": {
                            "fragment_card": False,
                            "fragment_cluster": False,
                            "missing_reason": "selected reference is missing from fragment_cards",
                        },
                    }
                )
        return selected_references

    def _build_decoy_fragments(
        self,
        *,
        case: KBBenchmarkCase,
        fragment_cards: list[FragmentCard],
        clusters_by_id: dict[str, FragmentCluster],
        selected_ids: Sequence[str],
        rerank_scores: Sequence[Any],
        coarse_scores: dict[str, float],
        seed: int,
    ) -> dict[str, Any]:
        decoy_types = [
            "random_decoy",
            "same_cluster_decoy",
            "tag_similar_decoy",
            "high_dependency_decoy",
            "rejected_high_score",
        ]
        missing_reasons: dict[str, str] = {}
        if not fragment_cards:
            return {
                "decoy_references": [],
                "missing_reasons": {decoy_type: "empty_kb" for decoy_type in decoy_types},
            }
        selected_set = set(selected_ids)
        selected_cards = [card for card in fragment_cards if card.fragment_id in selected_set]
        non_selected = [card for card in fragment_cards if card.fragment_id not in selected_set]
        rng = random.Random(seed)
        decoys: list[tuple[str, FragmentCard]] = []

        top_card = selected_cards[0] if selected_cards else None
        if top_card is not None and top_card.cluster_id:
            sibling = next(
                (
                    card
                    for card in non_selected
                    if card.cluster_id == top_card.cluster_id and card.fragment_id != top_card.fragment_id
                ),
                None,
            )
            if sibling is not None:
                decoys.append(("same_cluster_decoy", sibling))
            else:
                missing_reasons["same_cluster_decoy"] = "top selected cluster has no non-selected sibling"
        elif top_card is None:
            missing_reasons["same_cluster_decoy"] = "no selected top reference"
        else:
            missing_reasons["same_cluster_decoy"] = "top selected reference has no cluster_id"
        high_dependency = next((card for card in non_selected if card.context_dependency_level == "high"), None)
        if high_dependency is not None:
            decoys.append(("high_dependency_decoy", high_dependency))
        else:
            missing_reasons["high_dependency_decoy"] = "no non-selected high dependency fragment"
        scene_tags = set(case.scene_brief.preferred_tags)
        tag_similar = next(
            (
                card
                for card in non_selected
                if scene_tags.intersection(card.preferred_tags)
                and card.relationship_state != case.scene_brief.relationship_state
            ),
            None,
        )
        if tag_similar is not None:
            decoys.append(("tag_similar_decoy", tag_similar))
        else:
            missing_reasons["tag_similar_decoy"] = (
                "no tag-similar fragment with mismatched relationship or emotion state"
            )
        rejected_high_score = self._pick_rejected_high_score_card(
            selected_ids=selected_ids,
            cards_by_id={card.fragment_id: card for card in fragment_cards},
            rerank_scores=rerank_scores,
            coarse_scores=coarse_scores,
        )
        if rejected_high_score is not None:
            decoys.append(("rejected_high_score", rejected_high_score))
        else:
            missing_reasons["rejected_high_score"] = "no rejected rerank or coarse candidate available"
        used_ids = {card.fragment_id for _decoy_type, card in decoys}
        random_pool = [card for card in non_selected if card.fragment_id not in used_ids] or non_selected
        if random_pool:
            decoys.insert(0, ("random_decoy", rng.choice(random_pool)))
        else:
            missing_reasons["random_decoy"] = "no non-selected fragment_cards available"

        payloads: list[dict[str, Any]] = []
        for decoy_type, card in decoys:
            payload = self._reference_payload(
                card=card,
                clusters_by_id=clusters_by_id,
                reference_type="decoy",
                decoy_type=decoy_type,
                rerank_score=self._score_for_fragment(card.fragment_id, rerank_scores),
                coarse_score=coarse_scores.get(card.fragment_id),
            )
            payloads.append(payload)
        return {
            "decoy_references": payloads[:5],
            "missing_reasons": {
                decoy_type: reason
                for decoy_type, reason in missing_reasons.items()
                if decoy_type not in {str(item.get("decoy_type")) for item in payloads}
            },
        }

    def _rejected_high_score_references(
        self,
        *,
        selected_ids: Sequence[str],
        cards_by_id: dict[str, FragmentCard],
        clusters_by_id: dict[str, FragmentCluster],
        rerank_scores: Sequence[Any],
    ) -> list[dict[str, Any]]:
        selected_set = set(selected_ids)
        rejected = [
            score
            for score in rerank_scores
            if getattr(score, "candidate_id", "") not in selected_set
        ]
        rejected.sort(key=lambda score: float(getattr(score, "final_score", 0.0)), reverse=True)
        payloads: list[dict[str, Any]] = []
        for score in rejected[:3]:
            fragment_id = str(getattr(score, "candidate_id", ""))
            card = cards_by_id.get(fragment_id)
            if card is None:
                payloads.append(
                    {
                        "fragment_id": fragment_id,
                        "missing": True,
                        "rerank_score": score.to_dict() if hasattr(score, "to_dict") else self._to_jsonable(score),
                        "traceability": {
                            "fragment_card": False,
                            "fragment_cluster": False,
                            "missing_reason": "rejected candidate is missing from fragment_cards",
                        },
                    }
                )
                continue
            payloads.append(
                self._reference_payload(
                    card=card,
                    clusters_by_id=clusters_by_id,
                    reference_type="rejected_high_score",
                    rerank_score=score,
                )
            )
        return payloads

    def _reference_payload(
        self,
        *,
        card: FragmentCard,
        clusters_by_id: dict[str, FragmentCluster],
        reference_type: str,
        decoy_type: str | None = None,
        rerank_score: Any | None = None,
        coarse_score: float | None = None,
        expanded_fragment: Any | None = None,
    ) -> dict[str, Any]:
        cluster = clusters_by_id.get(card.cluster_id or "")
        payload: dict[str, Any] = {
            "reference_type": reference_type,
            "fragment_id": card.fragment_id,
            "cluster_id": card.cluster_id,
            "fragment_card": card.to_dict(),
            "cluster": cluster.to_dict() if cluster is not None else None,
            "source_excerpt": card.source_excerpt,
            "content_summary": card.content_summary,
            "narrative_function": list(card.narrative_function),
            "emotion_mechanism_text": card.emotion_mechanism_text,
            "relationship_state": list(card.relationship_state),
            "style_profile_text": card.style_profile_text,
            "transferability_score": card.transferability_score,
            "context_dependency_level": card.context_dependency_level,
            "traceability": {
                "fragment_card": True,
                "fragment_cluster": cluster is not None,
                "missing_reason": "" if cluster is not None else "fragment cluster missing or cluster_id is empty",
            },
        }
        if decoy_type is not None:
            payload["decoy_type"] = decoy_type
        if rerank_score is not None:
            payload["rerank_score"] = (
                rerank_score.to_dict() if hasattr(rerank_score, "to_dict") else self._to_jsonable(rerank_score)
            )
        if coarse_score is not None:
            payload["coarse_score"] = float(coarse_score)
        if expanded_fragment is not None:
            payload["expanded_reference_fragment"] = self._to_jsonable(expanded_fragment)
        return payload

    def _score_for_fragment(self, fragment_id: str, rerank_scores: Sequence[Any]) -> Any | None:
        return next(
            (score for score in rerank_scores if str(getattr(score, "candidate_id", "")) == fragment_id),
            None,
        )

    def _pick_rejected_high_score_card(
        self,
        *,
        selected_ids: Sequence[str],
        cards_by_id: dict[str, FragmentCard],
        rerank_scores: Sequence[Any],
        coarse_scores: dict[str, float],
    ) -> FragmentCard | None:
        selected_set = set(selected_ids)
        rejected_scores = [
            score
            for score in rerank_scores
            if str(getattr(score, "candidate_id", "")) not in selected_set
            and str(getattr(score, "candidate_id", "")) in cards_by_id
        ]
        rejected_scores.sort(key=lambda score: float(getattr(score, "final_score", 0.0)), reverse=True)
        if rejected_scores:
            return cards_by_id[str(getattr(rejected_scores[0], "candidate_id", ""))]

        coarse_candidates = [
            (fragment_id, score)
            for fragment_id, score in coarse_scores.items()
            if fragment_id not in selected_set and fragment_id in cards_by_id
        ]
        coarse_candidates.sort(key=lambda item: item[1], reverse=True)
        if coarse_candidates:
            return cards_by_id[coarse_candidates[0][0]]
        return None

    def _review_retrieval_case(
        self,
        *,
        reviewer_service: Any | None,
        case_id: str,
        selected_ids: Sequence[str],
        decoy_ids: Sequence[str],
        empty_kb: bool,
        selected_references: Sequence[dict[str, Any]],
        decoy_references: Sequence[dict[str, Any]],
        reviewer_input: dict[str, Any],
    ) -> dict[str, Any]:
        precheck_issues = self._retrieval_precheck_issues(
            selected_ids=selected_ids,
            selected_references=selected_references,
            decoy_references=decoy_references,
            empty_kb=empty_kb,
        )
        if precheck_issues:
            return KBRetrievalReviewReport(
                case_id=case_id,
                decision="fail",
                score=0.0,
                summary="Retrieval case failed precheck: " + ", ".join(precheck_issues),
                checks={name: "fail" for name in RETRIEVAL_REVIEW_CHECKS},
                selected_fragment_ids=list(selected_ids),
                decoy_fragment_ids=list(decoy_ids),
                issues=precheck_issues,
            ).to_dict()
        if reviewer_service is None:
            return {
                "case_id": case_id,
                "status": "pending_reviewer",
                "decision": "pending",
                "score": 0.0,
                "summary": "KBRetrievalReviewer is not configured.",
                "checks": {name: "pending" for name in RETRIEVAL_REVIEW_CHECKS},
                "selected_fragment_ids": list(selected_ids),
                "decoy_fragment_ids": list(decoy_ids),
                "issues": ["reviewer_not_configured"],
            }
        try:
            report = reviewer_service.review_retrieval_case(
                case_id=case_id,
                payload=reviewer_input,
            )
            return self._apply_retrieval_report_guards(
                report.to_dict(),
                selected_references=selected_references,
            )
        except Exception as exc:
            return KBRetrievalReviewReport(
                case_id=case_id,
                decision="fail",
                score=0.0,
                summary=f"KBRetrievalReviewer failed: {exc}",
                checks={name: "fail" for name in RETRIEVAL_REVIEW_CHECKS},
                selected_fragment_ids=list(selected_ids),
                decoy_fragment_ids=list(decoy_ids),
                issues=["reviewer_failed"],
            ).to_dict()

    def _retrieval_precheck_issues(
        self,
        *,
        selected_ids: Sequence[str],
        selected_references: Sequence[dict[str, Any]],
        decoy_references: Sequence[dict[str, Any]],
        empty_kb: bool,
    ) -> list[str]:
        issues: list[str] = []
        if empty_kb:
            issues.append("empty_kb")
        if not selected_ids:
            issues.append("empty_selected_references")
        if any(not self._reference_traces_to_kb(reference) for reference in selected_references):
            issues.append("selected_reference_trace_missing")
        if decoy_references and any(not self._reference_traces_to_kb(reference) for reference in decoy_references):
            issues.append("decoy_reference_trace_missing")
        return issues

    def _reference_traces_to_kb(self, reference: dict[str, Any]) -> bool:
        traceability = reference.get("traceability")
        if not isinstance(traceability, dict):
            return False
        return bool(traceability.get("fragment_card"))

    def _apply_retrieval_report_guards(
        self,
        report: dict[str, Any],
        *,
        selected_references: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        checks = dict(report.get("checks") or {})
        issues = list(report.get("issues") or [])
        score = float(report.get("score") or 0.0)
        decision = str(report.get("decision") or self._decision_for_score(score))
        top_reference = selected_references[0] if selected_references else {}
        top_card = top_reference.get("fragment_card") if isinstance(top_reference, dict) else {}
        if isinstance(top_card, dict) and top_card.get("context_dependency_level") == "high":
            if checks.get("context_dependency_risk") != "pass":
                issues.append("top_selected_high_context_dependency")
                decision = "borderline" if decision == "pass" else decision
        if checks.get("top1_beats_decoys") == "fail" and decision == "pass":
            issues.append("top1_loses_to_decoy")
            decision = "borderline"
        if checks.get("context_dependency_risk") == "fail" and decision == "pass":
            issues.append("context_dependency_risk_failed")
            decision = "borderline"
        report["decision"] = decision
        report["issues"] = list(dict.fromkeys(str(issue) for issue in issues if str(issue).strip()))
        return KBRetrievalReviewReport.from_dict(report).to_dict()

    def _pending_case_report(
        self,
        *,
        case_id: str,
        selected_ids: Sequence[str],
        decoy_ids: Sequence[str],
        empty_kb: bool,
    ) -> dict[str, Any]:
        if empty_kb:
            return {
                "case_id": case_id,
                "status": "failed_precheck",
                "decision": "fail",
                "score": 0.0,
                "summary": "Creative KB is empty; retrieval quality cannot be reviewed.",
                "checks": {name: "fail" for name in RETRIEVAL_REVIEW_CHECKS},
                "selected_fragment_ids": [],
                "decoy_fragment_ids": [],
                "issues": ["empty_kb"],
            }
        if not selected_ids:
            return {
                "case_id": case_id,
                "status": "failed_precheck",
                "decision": "fail",
                "score": 0.0,
                "summary": "Retrieval returned no selected reference fragments.",
                "checks": {name: "fail" for name in RETRIEVAL_REVIEW_CHECKS},
                "selected_fragment_ids": [],
                "decoy_fragment_ids": list(decoy_ids),
                "issues": ["empty_selected_references"],
            }
        return {
            "case_id": case_id,
            "status": "pending_reviewer",
            "decision": "pending",
            "score": 0.0,
            "summary": "Retrieval artifacts are ready; KBRetrievalReviewer is not wired yet.",
            "checks": {name: "pending" for name in RETRIEVAL_REVIEW_CHECKS},
            "selected_fragment_ids": list(selected_ids),
            "decoy_fragment_ids": list(decoy_ids),
            "issues": [] if decoy_ids else ["decoy_fragments_missing"],
        }

    def _aggregate_retrieval_reports(self, case_reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not case_reports:
            return self._failure_retrieval_summary("no retrieval cases were generated")
        failed_reports = [report for report in case_reports if report.get("decision") == "fail"]
        if failed_reports:
            score = round(
                sum(float(report.get("score") or 0.0) for report in case_reports)
                / max(len(case_reports), 1),
                4,
            )
            return {
                "status": "completed",
                "decision": "fail",
                "score": score,
                "summary": f"{len(failed_reports)} retrieval case(s) failed or failed precheck.",
                "case_reports": list(case_reports),
                "aggregate_checks": {
                    "empty_kb": (
                        "fail"
                        if any("empty_kb" in report.get("issues", []) for report in failed_reports)
                        else "pass"
                    ),
                    "empty_selection": (
                        "fail"
                        if any("empty_selected_references" in report.get("issues", []) for report in failed_reports)
                        else "pass"
                    ),
                    "traceability": (
                        "fail"
                        if any(
                            issue in report.get("issues", [])
                            for report in failed_reports
                            for issue in ("selected_reference_trace_missing", "decoy_reference_trace_missing")
                        )
                        else "pass"
                    ),
                    "rerank_relevance": self._worst_case_check(case_reports, "selected_fragments_match_scene_brief"),
                    "cluster_diversity": self._worst_case_check(case_reports, "cluster_diversity"),
                    "negative_transfer_risk": self._worst_case_check(case_reports, "negative_transfer_risk"),
                },
            }
        scored_reports = [
            report
            for report in case_reports
            if report.get("decision") in {"pass", "borderline", "fail"}
        ]
        if not scored_reports:
            return self._pending_retrieval_summary(case_reports=case_reports)
        score = round(
            sum(float(report.get("score") or 0.0) for report in scored_reports) / len(scored_reports),
            4,
        )
        decision = self._decision_for_score(score)
        if self._has_failed_check(case_reports, "top1_beats_decoys") and decision == "pass":
            decision = "borderline"
        if self._has_failed_check(case_reports, "context_dependency_risk") and decision == "pass":
            decision = "borderline"
        return {
            "status": "completed",
            "decision": decision,
            "score": score,
            "summary": self._retrieval_summary_text(
                decision=decision,
                score=score,
                case_reports=case_reports,
            ),
            "case_reports": list(case_reports),
            "aggregate_checks": {
                "empty_kb": "pass",
                "empty_selection": "pass",
                "traceability": "pass",
                "rerank_relevance": self._worst_case_check(case_reports, "selected_fragments_match_scene_brief"),
                "cluster_diversity": self._worst_case_check(case_reports, "cluster_diversity"),
                "negative_transfer_risk": self._worst_case_check(case_reports, "negative_transfer_risk"),
            },
        }

    def _has_failed_check(self, case_reports: Sequence[dict[str, Any]], check_name: str) -> bool:
        return any(dict(report.get("checks") or {}).get(check_name) == "fail" for report in case_reports)

    def _worst_case_check(self, case_reports: Sequence[dict[str, Any]], check_name: str) -> str:
        values = [dict(report.get("checks") or {}).get(check_name) for report in case_reports]
        if "fail" in values:
            return "fail"
        if "borderline" in values:
            return "borderline"
        if "pending" in values:
            return "pending"
        return "pass"

    def _retrieval_summary_text(
        self,
        *,
        decision: str,
        score: float,
        case_reports: Sequence[dict[str, Any]],
    ) -> str:
        counts = {
            "pass": sum(1 for report in case_reports if report.get("decision") == "pass"),
            "borderline": sum(1 for report in case_reports if report.get("decision") == "borderline"),
            "fail": sum(1 for report in case_reports if report.get("decision") == "fail"),
        }
        return (
            f"Retrieval review {decision} at {score:.2f}: "
            f"{counts['pass']} pass, {counts['borderline']} borderline, {counts['fail']} fail."
        )

    def _pending_retrieval_summary(self, *, case_reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
        return {
            "status": "pending_reviewer",
            "decision": "pending",
            "score": 0.0,
            "summary": (
                "KBRetrievalReviewer is not wired yet; "
                "generated artifacts keep the reviewer input shape stable."
            ),
            "case_reports": list(case_reports),
            "aggregate_checks": {
                "empty_kb": "pass",
                "empty_selection": "pass",
                "rerank_relevance": "pending",
                "cluster_diversity": "pending",
                "negative_transfer_risk": "pending",
            },
        }

    def _failure_retrieval_summary(self, message: str) -> dict[str, Any]:
        return {
            "status": "failed_precheck",
            "decision": "fail",
            "score": 0.0,
            "summary": message,
            "case_reports": [],
            "aggregate_checks": {
                "empty_kb": "fail",
                "empty_selection": "fail",
                "rerank_relevance": "pending",
                "cluster_diversity": "pending",
                "negative_transfer_risk": "pending",
            },
        }

    def _resolve_writer_ab_service(self) -> Any:
        if self.writer_ab_service is not None:
            return self.writer_ab_service
        from .creative_kb_writer_ab_service import CreativeKBWriterABService

        self.writer_ab_service = CreativeKBWriterABService(
            writer=None,
            reviewer_service=self.kb_reviewer_service,
        )
        return self.writer_ab_service

    def _run_writer_ab(
        self,
        *,
        artifact_dir: Path,
        cases: Sequence[KBBenchmarkCase],
        windows: _BenchmarkWindows,
        seed: int,
    ) -> dict[str, Any]:
        writer_ab_service = self._resolve_writer_ab_service()
        reference_payload = self._collect_writer_ab_references(artifact_dir)
        base_execution_input = self._build_writer_ab_execution_input(
            cases=cases,
            windows=windows,
            selected_references=reference_payload["selected_references"],
        )
        reference_story_synopsis = self._writer_ab_reference_story_synopsis(cases=cases, windows=windows)
        if not hasattr(writer_ab_service, "run"):
            summary = self._write_pending_writer_ab(
                artifact_dir=artifact_dir,
                reason="writer_ab_service_does_not_implement_run",
            )
            return summary
        try:
            return writer_ab_service.run(
                artifact_dir=artifact_dir,
                base_execution_input=base_execution_input,
                reference_story_synopsis=reference_story_synopsis,
                reference_truth=windows.reference_truth,
                selected_references=reference_payload["selected_references"],
                decoy_references=reference_payload["decoy_references"],
                seed=seed,
            )
        except Exception as exc:
            return self._write_pending_writer_ab(
                artifact_dir=artifact_dir,
                reason=f"writer_ab_failed: {exc}",
            )

    def _collect_writer_ab_references(self, artifact_dir: Path) -> dict[str, list[dict[str, Any]]]:
        retrieval_root = artifact_dir / "retrieval_cases"
        selected_references: list[dict[str, Any]] = []
        decoy_references: list[dict[str, Any]] = []
        seen_selected: set[str] = set()
        seen_decoys: set[str] = set()
        if not retrieval_root.exists():
            return {"selected_references": [], "decoy_references": []}
        for case_dir in sorted(path for path in retrieval_root.iterdir() if path.is_dir()):
            selected_path = case_dir / "selected_reference_fragments.json"
            for reference in self._read_json_list(selected_path):
                fragment_id = _normalize_text(reference.get("fragment_id"))
                if fragment_id and fragment_id not in seen_selected:
                    selected_references.append(reference)
                    seen_selected.add(fragment_id)
            decoy_path = case_dir / "decoy_fragments.json"
            decoy_payload = self._read_json_object(decoy_path)
            for reference in decoy_payload.get("decoy_references", []) if isinstance(decoy_payload, dict) else []:
                if not isinstance(reference, dict):
                    continue
                fragment_id = _normalize_text(reference.get("fragment_id"))
                decoy_key = f"{reference.get('decoy_type') or 'decoy'}:{fragment_id}"
                if fragment_id and decoy_key not in seen_decoys and fragment_id not in seen_selected:
                    decoy_references.append(reference)
                    seen_decoys.add(decoy_key)
        return {
            "selected_references": selected_references,
            "decoy_references": decoy_references,
        }

    def _read_json_list(self, path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    def _read_json_object(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _build_writer_ab_execution_input(
        self,
        *,
        cases: Sequence[KBBenchmarkCase],
        windows: _BenchmarkWindows,
        selected_references: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        reference_story_synopsis = self._writer_ab_reference_story_synopsis(cases=cases, windows=windows)
        first_case = cases[0] if cases else None
        scene_brief_payload = first_case.scene_brief.to_dict() if first_case is not None else {}
        base_execution_data = {
            "chapter_id": "creative-kb-writer-ab",
            "chapter_title": "Creative KB Writer A/B diagnostic",
            "chapter_brief": {
                "goal": reference_story_synopsis["combined_synopsis"],
                "must_include": list(reference_story_synopsis["must_preserve"]),
            },
            "fact_inputs": {
                "benchmark_layer": "creative_kb_writer_ab",
                "case_ids": [case.case_id for case in cases],
            },
            "style_reference_bundle": {
                "scene_brief": scene_brief_payload,
                "selected_fragment_ids": [
                    str(reference.get("fragment_id"))
                    for reference in selected_references
                    if reference.get("fragment_id")
                ],
                "references": self._writer_style_reference_items(selected_references),
                "selection_notes": "Official Creative KB retrieval references for Writer A/B kb_enabled variant.",
            },
            "writer_rules": ["沿用 Writer execution 接口，基于 close-read reference synopsis 扩写正文。"],
            "forbidden_inputs": ["不得直接复制 reference_truth 原文。"],
        }
        try:
            from .smoke_benchmark_service import AgenticSmokeBenchmarkService

            return AgenticSmokeBenchmarkService(repo_root=self.repo_root)._build_reference_synopsis_execution_input(
                base_execution_data=base_execution_data,
                reference_synopsis=reference_story_synopsis,
                story_outline={"next_outline_node": "Creative KB Writer A/B diagnostic expansion."},
                story_context={
                    "recent_story_synopses": [
                        {"summary_short": _safe_excerpt(segment, 180)}
                        for segment in windows.prefix_segments[-3:]
                    ],
                    "character_docs": [],
                },
                target_chars=max(600, min(len(windows.reference_truth), 2400)),
            )
        except Exception:
            fallback = dict(base_execution_data)
            fallback["length_budget"] = {
                "chapter_id": "creative-kb-writer-ab",
                "target_chars": max(600, min(len(windows.reference_truth), 2400)),
            }
            return fallback

    def _writer_ab_reference_story_synopsis(
        self,
        *,
        cases: Sequence[KBBenchmarkCase],
        windows: _BenchmarkWindows,
    ) -> dict[str, Any]:
        plot_beats = [case.reference_synopsis for case in cases]
        must_preserve: list[str] = []
        for case in cases:
            must_preserve.extend(case.expected_traits)
        return {
            "source": "creative_kb_benchmark_cases",
            "source_chars": len(windows.reference_truth),
            "combined_synopsis": "\n".join(plot_beats),
            "plot_beats": plot_beats,
            "must_preserve": list(dict.fromkeys(must_preserve)),
            "must_avoid": ["不得直接复制 reference_truth 原文", "不得让 KB references 覆盖 SceneBrief 事实约束"],
            "tone_and_style": "延续 prefix close-read 的节奏、情绪机制与关系阶段。",
        }

    def _writer_style_reference_items(self, references: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        style_items: list[dict[str, Any]] = []
        for reference in references:
            card = reference.get("fragment_card")
            card_payload = card if isinstance(card, dict) else {}
            fragment_id = _normalize_text(reference.get("fragment_id"))
            if not fragment_id:
                continue
            style_items.append(
                {
                    "fragment_id": fragment_id,
                    "source_path": _normalize_text(card_payload.get("source_path") or reference.get("source_path")),
                    "narrative_function": list(
                        reference.get("narrative_function")
                        or card_payload.get("narrative_function")
                        or []
                    ),
                    "relationship_state": list(
                        reference.get("relationship_state")
                        or card_payload.get("relationship_state")
                        or []
                    ),
                    "style_profile_text": _normalize_text(
                        reference.get("style_profile_text") or card_payload.get("style_profile_text")
                    ),
                    "pov_mode": _normalize_text(card_payload.get("pov_mode")),
                    "excerpt": _normalize_text(
                        reference.get("source_excerpt")
                        or card_payload.get("source_excerpt")
                        or reference.get("content_summary")
                        or card_payload.get("content_summary")
                    ),
                    "score": self._reference_score(reference),
                }
            )
        return style_items

    def _reference_score(self, reference: Mapping[str, Any]) -> float:
        rerank_score = reference.get("rerank_score")
        if isinstance(rerank_score, dict):
            try:
                return float(rerank_score.get("final_score") or rerank_score.get("score") or 0.0)
            except (TypeError, ValueError):
                return 0.0
        try:
            return float(reference.get("score") or reference.get("coarse_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _writer_ab_summary(self, *, enabled: bool) -> dict[str, Any] | None:
        if not enabled:
            return None
        return {
            "enabled": True,
            "status": "pending_writer_ab",
            "decision": "pending",
            "score": 0.0,
            "winner": "pending",
            "variant_scores": {},
            "negative_transfer_issues": [],
            "summary": "Writer A/B has not run yet.",
        }

    def _write_pending_writer_ab(
        self,
        *,
        artifact_dir: Path,
        reason: str = "writer_ab_not_configured",
    ) -> dict[str, Any]:
        writer_ab_dir = artifact_dir / "writer_ab"
        writer_ab_dir.mkdir(parents=True, exist_ok=True)
        prompt = {
            "status": "pending_writer_ab",
            "required_variants": ["kb_enabled", "kb_disabled", "kb_random"],
            "note": f"Writer A/B execution did not complete: {reason}.",
        }
        report = self._writer_ab_summary(enabled=True)
        if report is not None:
            report["negative_transfer_issues"] = [reason]
            report["summary"] = f"Writer A/B artifacts are pending: {reason}."
        self._write_json(writer_ab_dir / "writer_ab_reviewer_prompt.json", prompt)
        self._write_json(writer_ab_dir / "writer_ab_reviewer_report.json", report)
        return report or {}

    def _final_status(self, *, errors: Sequence[str], retrieval_summary: dict[str, Any]) -> str:
        if errors or retrieval_summary.get("decision") == "fail":
            return "failed"
        if retrieval_summary.get("decision") == "pending":
            return "pending_review"
        return "completed"

    def _write_result(
        self,
        *,
        artifact_dir: Path,
        run_id: str,
        status: str,
        build_summary: dict[str, Any],
        case_summary: dict[str, Any],
        retrieval_review_summary: dict[str, Any],
        writer_ab_summary: dict[str, Any] | None,
        errors: Sequence[str],
        warnings: Sequence[str],
    ) -> CreativeKBBenchmarkResult:
        summary_path = artifact_dir / "summary.json"
        result = CreativeKBBenchmarkResult(
            run_id=run_id,
            artifact_dir=str(artifact_dir),
            status=status,
            build_summary=build_summary,
            case_summary=case_summary,
            retrieval_review_summary=retrieval_review_summary,
            writer_ab_summary=writer_ab_summary,
            errors=list(errors),
            warnings=list(warnings),
            summary_path=str(summary_path),
        )
        self._write_json(summary_path, result.to_dict())
        self._emit_progress(
            {
                "stage": "creative_kb_benchmark",
                "phase": "summary_written",
                "run_id": run_id,
                "status": status,
                "summary_path": str(summary_path),
                "artifact_dir": str(artifact_dir),
            }
        )
        return result

    def _build_summary(
        self,
        *,
        source_path: Path,
        db_path: Path,
        documents: Sequence[DocumentRow],
        windows: _BenchmarkWindows,
        kb_build_result: CreativeKBBuildResult,
        fragment_card_count: int,
        fragment_cluster_count: int,
    ) -> dict[str, Any]:
        return {
            "source_path": str(source_path),
            "db_path": str(db_path),
            "document_count": len(documents),
            "prefix_segment_count": len(windows.prefix_segments),
            "reference_segment_count": len(windows.reference_segments),
            "prefix_chars": len(windows.source_prefix),
            "reference_truth_chars": len(windows.reference_truth),
            "fragment_card_count": fragment_card_count,
            "fragment_cluster_count": fragment_cluster_count,
            "kb_build_result": kb_build_result.to_dict(),
        }

    def _case_summary(self, cases: Sequence[KBBenchmarkCase]) -> dict[str, Any]:
        coverage = []
        for case in cases:
            coverage.extend(case.expected_traits)
        return {
            "case_count": len(cases),
            "case_ids": [case.case_id for case in cases],
            "coverage": list(dict.fromkeys(coverage)),
            "categories": [case.category for case in cases],
        }

    def _recent_window_summary(
        self,
        *,
        prefix_segments: Sequence[str],
        case_goal: str,
        jitter: int,
    ) -> str:
        _ = jitter
        recent = list(prefix_segments[-3:])
        lines = [f"- {_safe_excerpt(segment, 120)}" for segment in recent]
        lines.append(f"- 当前 benchmark 目标：{case_goal}")
        return "\n".join(lines).strip()

    def _reference_synopsis(self, *, category: str, reference_segment: str) -> str:
        return f"{category}: {_safe_excerpt(reference_segment, 260)}"

    def _case_templates(self) -> list[dict[str, object]]:
        return [
            {
                "category": "情绪停顿 / 关系收束",
                "goal": "写一段克制的情绪停顿，让紧张关系暂时收束但不彻底和解。",
                "scene_brief": SceneBrief(
                    scene_objective="承接前文压力，写出关系收束前的短暂停顿。",
                    emotional_goal="用沉默、动作和未说出口的话压住情绪。",
                    conflict_goal="让矛盾暂时降温，但保留未解决的关系张力。",
                    narrative_function=["情绪停顿", "关系收束"],
                    emotion_mode=["克制", "迟疑"],
                    character_temperament=["敏感", "克制"],
                    relationship_state=["对峙后未完全和解"],
                    style_need=["短句", "低对白", "动作停顿"],
                    must_avoid=["突然和解", "强行解释全部秘密"],
                    preferred_tags=["告别", "停顿"],
                ),
                "expected_traits": ["情绪停顿", "关系收束", "克制表达"],
            },
            {
                "category": "冲突升级 / 行动推进",
                "goal": "写一段外部压力升级后的行动推进，让角色必须立刻做选择。",
                "scene_brief": SceneBrief(
                    scene_objective="让冲突升级并推动角色采取明确行动。",
                    emotional_goal="保持紧张、压迫和来不及解释的急促感。",
                    conflict_goal="外部威胁逼近，角色以行动回应而不是停在解释。",
                    narrative_function=["冲突升级", "行动推进"],
                    emotion_mode=["紧张", "压迫"],
                    character_temperament=["果断", "警觉"],
                    relationship_state=["临时协作"],
                    style_need=["动作连贯", "节奏加快"],
                    must_avoid=["跳过因果", "无代价胜利"],
                    preferred_tags=["追逐", "对抗", "调查"],
                ),
                "expected_traits": ["冲突升级", "行动推进", "动作因果"],
            },
            {
                "category": "信息揭示 / 设定承接",
                "goal": "写一段关键信息揭示，同时承接既有设定并避免突兀补设定。",
                "scene_brief": SceneBrief(
                    scene_objective="揭示一个关键信息，并让它自然接上已有设定。",
                    emotional_goal="让角色在惊疑中保持克制判断。",
                    conflict_goal="新信息改变下一步选择，但不一次性解开全部谜题。",
                    narrative_function=["信息揭示", "设定承接"],
                    emotion_mode=["惊疑", "克制"],
                    character_temperament=["谨慎", "观察敏锐"],
                    relationship_state=["信息不对称"],
                    style_need=["线索递进", "少量解释"],
                    must_avoid=["设定冲突", "大段百科式说明"],
                    preferred_tags=["线索", "调查", "秘密"],
                ),
                "expected_traits": ["信息揭示", "设定承接", "线索递进"],
            },
            {
                "category": "余波整理 / 情绪消化",
                "goal": "写一段事件后的余波整理，用具体动作消化损失和压力。",
                "scene_brief": SceneBrief(
                    scene_objective="承接事件后果，以整理现场或物件的动作表现余波。",
                    emotional_goal="把失落和疲惫压在具体动作里。",
                    conflict_goal="确认代价存在，同时为下一步行动留下压力。",
                    narrative_function=["余波整理", "情绪消化"],
                    emotion_mode=["疲惫", "克制"],
                    character_temperament=["负责", "隐忍"],
                    relationship_state=["共同承担后果"],
                    style_need=["动作细节", "低对白"],
                    must_avoid=["立刻抹平代价", "过度煽情"],
                    preferred_tags=["余波", "整理", "沉默"],
                ),
                "expected_traits": ["余波整理", "情绪消化", "代价承接"],
            },
            {
                "category": "关系试探 / 立场转换",
                "goal": "写一段关系试探，让角色在不完全信任中出现立场松动。",
                "scene_brief": SceneBrief(
                    scene_objective="通过一次试探性互动表现关系阶段的轻微转向。",
                    emotional_goal="在防备和动摇之间保持含蓄。",
                    conflict_goal="角色仍未完全信任对方，但愿意交换有限信息。",
                    narrative_function=["关系试探", "立场转换"],
                    emotion_mode=["防备", "动摇"],
                    character_temperament=["谨慎", "自持"],
                    relationship_state=["互相试探"],
                    style_need=["含蓄对白", "动作反应"],
                    must_avoid=["突然完全信任", "关系跳级"],
                    preferred_tags=["试探", "交易", "秘密"],
                ),
                "expected_traits": ["关系试探", "立场转换", "关系阶段"],
            },
        ]

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._to_jsonable(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _to_jsonable(self, value: Any) -> Any:
        if hasattr(value, "to_dict"):
            return self._to_jsonable(value.to_dict())
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): self._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._to_jsonable(item) for item in value]
        return value
