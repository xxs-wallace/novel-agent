from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..llm import JsonModelClient, ModelSettings
from ..repos.db import NovelAgentDB
from ..schemas.narrative_inquiry_schema import AnalyzerBudget
from ..utils.json_utils import extract_json_blob
from .outline_analyzer_service import OutlineAnalyzerService


DEFAULT_ANALYZER_BENCHMARK_TIMEOUT_SECONDS = 600
DEFAULT_PROMPT_SET: dict[str, str] = {
    "protagonist_character_and_next_actions": "评价男主角和女主角的人物性格，推测他们之后会采取什么样的行动，或者发生什么样的故事。",
    "worldview_story_theme": "概括描述一下本作的世界观是怎样的，这本书讲述了一个什么样的故事，并且以此推测作者想要表达的观点，或者想要传达给读者的思想。",
    "style_and_emotional_tone": "评价一下本作的文笔风格与感情基调，有哪些地方写得较为出彩。",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_source_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _token_estimate(text: str) -> int:
    # Rough estimate only; benchmark comparisons use the same estimator for both arms.
    if not text:
        return 0
    ascii_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = max(0, len(text) - cjk_chars)
    return max(1, int(math.ceil(cjk_chars * 0.8 + other_chars / 4 + ascii_words * 0.25)))


def _prompt_stats(system_prompt: str, user_prompt: str) -> dict[str, int]:
    system_bytes = len(system_prompt.encode("utf-8"))
    user_bytes = len(user_prompt.encode("utf-8"))
    total_text = system_prompt + user_prompt
    return {
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt),
        "prompt_chars": len(total_text),
        "system_bytes": system_bytes,
        "user_bytes": user_bytes,
        "prompt_bytes": system_bytes + user_bytes,
        "prompt_token_estimate": _token_estimate(total_text),
    }


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@dataclass(frozen=True, slots=True)
class AnalyzerBenchmarkModelConfig:
    model_type: str = "OpenAIModel"
    model_name: str = "deepseek-v4-pro"
    provider: str | None = "openai_compatible"
    base_url: str | None = "https://api.deepseek.com"
    api_key: str | None = None
    api_key_env: str | None = "DEEPSEEK_API_KEY"
    temperature: float = 0.2
    max_output_tokens: int = 8192
    timeout_seconds: int = DEFAULT_ANALYZER_BENCHMARK_TIMEOUT_SECONDS
    request_retry_attempts: int = 3
    request_retry_backoff_seconds: float = 1.0
    retry_without_thinking_on_failure: bool = True
    thinking: str | None = "enabled"
    reasoning_effort: str | None = "high"
    include_reasoning_content: bool = False

    def to_model_settings(self) -> ModelSettings:
        return ModelSettings(
            model_type=self.model_type,
            model_name=self.model_name,
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            api_key_env=self.api_key_env,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            timeout_seconds=self.timeout_seconds,
            request_retry_attempts=self.request_retry_attempts,
            request_retry_backoff_seconds=self.request_retry_backoff_seconds,
            retry_without_thinking_on_failure=self.retry_without_thinking_on_failure,
            thinking=self.thinking,
            reasoning_effort=self.reasoning_effort,
            include_reasoning_content=self.include_reasoning_content,
            dry_run=False,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("api_key"):
            payload["api_key"] = "***"
        return payload


@dataclass(frozen=True, slots=True)
class AnalyzerBenchmarkConfig:
    source_path: Path
    db_path: Path
    book_id: str
    artifact_dir: Path
    run_id: str = ""
    prompt_set: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PROMPT_SET))
    prompt_ids: list[str] = field(default_factory=list)
    analyzer_budget: AnalyzerBudget = field(default_factory=AnalyzerBudget)
    model_config: AnalyzerBenchmarkModelConfig = field(default_factory=AnalyzerBenchmarkModelConfig)
    reuse_baseline: bool = True

    def selected_prompts(self) -> dict[str, str]:
        if not self.prompt_ids:
            return dict(self.prompt_set)
        return {prompt_id: self.prompt_set[prompt_id] for prompt_id in self.prompt_ids if prompt_id in self.prompt_set}

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "db_path": str(self.db_path),
            "book_id": self.book_id,
            "artifact_dir": str(self.artifact_dir),
            "run_id": self.run_id,
            "prompt_set": dict(self.prompt_set),
            "prompt_ids": list(self.prompt_ids),
            "analyzer_budget": self.analyzer_budget.to_dict(),
            "model_config": self.model_config.to_dict(),
            "reuse_baseline": self.reuse_baseline,
        }


@dataclass(frozen=True, slots=True)
class PromptCallRecord:
    stage: str
    call_index: int
    started_at: str
    ended_at: str
    elapsed_seconds: float
    prompt_stats: dict[str, int]
    response_chars: int
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "call_index": self.call_index,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "elapsed_seconds": self.elapsed_seconds,
            **self.prompt_stats,
            "response_chars": self.response_chars,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class AnalyzerBenchmarkPromptResult:
    prompt_id: str
    user_prompt: str
    baseline_answer: str
    analyzer_answer: str
    judge_report: dict[str, Any]
    baseline_prompt_stats: dict[str, Any]
    analyzer_prompt_stats: dict[str, Any]
    analyzer_status: str
    artifact_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "user_prompt": self.user_prompt,
            "baseline_answer": self.baseline_answer,
            "analyzer_answer": self.analyzer_answer,
            "judge_report": dict(self.judge_report),
            "baseline_prompt_stats": dict(self.baseline_prompt_stats),
            "analyzer_prompt_stats": dict(self.analyzer_prompt_stats),
            "analyzer_status": self.analyzer_status,
            "artifact_dir": str(self.artifact_dir),
        }


@dataclass(frozen=True, slots=True)
class AnalyzerBenchmarkResult:
    run_id: str
    status: str
    artifact_dir: Path
    prompt_results: list[AnalyzerBenchmarkPromptResult]
    summary_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "artifact_dir": str(self.artifact_dir),
            "summary_path": str(self.summary_path),
            "prompt_results": [item.to_dict() for item in self.prompt_results],
        }


class _RecordingModelClient:
    def __init__(self, wrapped: Any) -> None:
        self.wrapped = wrapped
        self.calls: list[PromptCallRecord] = []

    @property
    def settings(self) -> Any:
        return getattr(self.wrapped, "settings", None)

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        stage = self._stage(system_prompt)
        started_monotonic = time.monotonic()
        started_at = _utc_now()
        error = ""
        response = ""
        try:
            response = str(self.wrapped.generate_text(system_prompt=system_prompt, user_prompt=user_prompt))
            return response
        except Exception as exc:  # noqa: BLE001 - benchmark must persist failed call stats.
            error = str(exc)
            raise
        finally:
            ended_at = _utc_now()
            self.calls.append(
                PromptCallRecord(
                    stage=stage,
                    call_index=len(self.calls) + 1,
                    started_at=started_at,
                    ended_at=ended_at,
                    elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
                    prompt_stats=_prompt_stats(system_prompt, user_prompt),
                    response_chars=len(response),
                    error=error,
                )
            )

    def _stage(self, system_prompt: str) -> str:
        if "evidence triage" in system_prompt:
            return "triage"
        if "每轮只返回 JSON" in system_prompt:
            return "loop"
        if "用户可读中文分析" in system_prompt:
            return "final"
        return "unknown"


class OutlineAnalyzerBenchmarkService:
    """Runs the full-text baseline vs. Analyzer Agent Loop smoke benchmark."""

    def __init__(self, *, repo_root: Path, model_client: Any | None = None) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.model_client = model_client

    def run(self, config: AnalyzerBenchmarkConfig) -> AnalyzerBenchmarkResult:
        source_path = self._resolve_path(config.source_path)
        db_path = self._resolve_path(config.db_path)
        artifact_root = self._resolve_path(config.artifact_dir)
        if not source_path.exists():
            raise FileNotFoundError(f"Analyzer benchmark source not found: {source_path}")
        if not db_path.exists():
            raise FileNotFoundError(f"Analyzer benchmark close-read sqlite not found: {db_path}")
        prompts = config.selected_prompts()
        if not prompts:
            raise ValueError("Analyzer benchmark requires at least one prompt")
        run_id = config.run_id or f"outline-analyzer-{uuid.uuid4().hex[:12]}"
        run_dir = artifact_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        source_text = source_path.read_text(encoding="utf-8", errors="replace")
        compact_source_text = _compact_source_text(source_text)
        source_fingerprint = hashlib.sha256(compact_source_text.encode("utf-8")).hexdigest()
        model_client = self.model_client or JsonModelClient(config.model_config.to_model_settings())
        _write_json(run_dir / "config.json", {**config.to_dict(), "run_id": run_id})
        _write_json(
            run_dir / "source_metadata.json",
            self._source_metadata(source_path=source_path, db_path=db_path, book_id=config.book_id, source_text=source_text),
        )
        _write_json(run_dir / "prompt_set.json", prompts)

        db = NovelAgentDB(db_path)
        prompt_results: list[AnalyzerBenchmarkPromptResult] = []
        with db.connect() as conn:
            for prompt_id, user_prompt in prompts.items():
                prompt_results.append(
                    self._run_one_prompt(
                        conn,
                        book_id=config.book_id,
                        prompt_id=prompt_id,
                        user_prompt=user_prompt,
                        compact_source_text=compact_source_text,
                        model_client=model_client,
                        run_dir=run_dir / prompt_id,
                        baseline_cache_dir=artifact_root / "_baseline_cache",
                        source_fingerprint=source_fingerprint,
                        model_config=config.model_config,
                        reuse_baseline=config.reuse_baseline,
                        analyzer_budget=config.analyzer_budget,
                    )
                )

        summary = self._build_summary(run_id=run_id, run_dir=run_dir, prompt_results=prompt_results)
        summary_path = run_dir / "summary.json"
        _write_json(summary_path, summary)
        status = "pass" if all(item.get("status") == "pass" for item in summary["prompts"]) else "needs_review"
        return AnalyzerBenchmarkResult(
            run_id=run_id,
            status=status,
            artifact_dir=run_dir,
            prompt_results=prompt_results,
            summary_path=summary_path,
        )

    def _run_one_prompt(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        prompt_id: str,
        user_prompt: str,
        compact_source_text: str,
        model_client: Any,
        run_dir: Path,
        baseline_cache_dir: Path,
        source_fingerprint: str,
        model_config: AnalyzerBenchmarkModelConfig,
        reuse_baseline: bool,
        analyzer_budget: AnalyzerBudget,
    ) -> AnalyzerBenchmarkPromptResult:
        run_dir.mkdir(parents=True, exist_ok=True)
        baseline_answer, baseline_stats, baseline_raw = self._load_or_run_baseline(
            prompt_id=prompt_id,
            user_prompt=user_prompt,
            compact_source_text=compact_source_text,
            model_client=model_client,
            baseline_cache_dir=baseline_cache_dir,
            source_fingerprint=source_fingerprint,
            model_config=model_config,
            reuse_baseline=reuse_baseline,
        )
        _write_json(run_dir / "baseline" / "request_prompt_stats.json", baseline_stats)
        _write_text(run_dir / "baseline" / "answer.md", baseline_answer + "\n")
        _write_json(run_dir / "baseline" / "raw_response.json", baseline_raw)

        recording_client = _RecordingModelClient(model_client)
        analyzer_service = OutlineAnalyzerService(
            repo_root=self.repo_root,
            model_client=recording_client,
            budget=analyzer_budget,
        )
        analyzer_result = analyzer_service.chat(conn, book_id=book_id, question=user_prompt)
        analyzer_prompt_stats = self._aggregate_analyzer_prompt_stats(recording_client.calls)
        _write_json(run_dir / "analyzer" / "seed_packet.json", analyzer_result.seed.to_dict() if analyzer_result.seed else {})
        _write_json(run_dir / "analyzer" / "prompt_stats.json", analyzer_prompt_stats)
        _write_json(run_dir / "analyzer" / "loop_trace.json", analyzer_result.trace)
        _write_json(run_dir / "analyzer" / "committed_evidence.json", [item.to_dict() for item in analyzer_result.evidence_bundles])
        _write_json(run_dir / "analyzer" / "rejected_evidence.json", self._rejected_evidence(analyzer_result.trace))
        _write_text(run_dir / "analyzer" / "answer.md", analyzer_result.answer + "\n")
        _write_json(run_dir / "analyzer" / "raw_response.json", analyzer_result.to_dict())

        judge_report, judge_prompt = self._run_judge(
            user_prompt=user_prompt,
            baseline_answer=baseline_answer,
            analyzer_answer=analyzer_result.answer,
            analyzer_evidence=[item.to_dict() for item in analyzer_result.evidence_bundles],
            analyzer_trace=analyzer_result.trace,
            model_client=model_client,
        )
        _write_json(run_dir / "judge" / "comparison_prompt.json", judge_prompt)
        _write_json(run_dir / "judge" / "comparison_report.json", judge_report)
        return AnalyzerBenchmarkPromptResult(
            prompt_id=prompt_id,
            user_prompt=user_prompt,
            baseline_answer=baseline_answer,
            analyzer_answer=analyzer_result.answer,
            judge_report=judge_report,
            baseline_prompt_stats=baseline_stats,
            analyzer_prompt_stats=analyzer_prompt_stats,
            analyzer_status=analyzer_result.status,
            artifact_dir=run_dir,
        )

    def _load_or_run_baseline(
        self,
        *,
        prompt_id: str,
        user_prompt: str,
        compact_source_text: str,
        model_client: Any,
        baseline_cache_dir: Path,
        source_fingerprint: str,
        model_config: AnalyzerBenchmarkModelConfig,
        reuse_baseline: bool,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        cache_key = self._baseline_cache_key(
            prompt_id=prompt_id,
            user_prompt=user_prompt,
            source_fingerprint=source_fingerprint,
            model_config=model_config,
        )
        cache_dir = baseline_cache_dir / cache_key
        answer_path = cache_dir / "answer.md"
        stats_path = cache_dir / "request_prompt_stats.json"
        raw_path = cache_dir / "raw_response.json"
        if reuse_baseline and answer_path.exists() and stats_path.exists() and raw_path.exists():
            answer = answer_path.read_text(encoding="utf-8").strip()
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            if isinstance(stats, Mapping) and isinstance(raw, Mapping) and answer:
                stats = {**dict(stats), "cache_hit": True, "cache_key": cache_key}
                raw = {**dict(raw), "cache_hit": True, "cache_key": cache_key}
                return answer, stats, raw
        answer, stats, raw = self._run_baseline(
            user_prompt=user_prompt,
            compact_source_text=compact_source_text,
            model_client=model_client,
        )
        stats = {**stats, "cache_hit": False, "cache_key": cache_key}
        raw = {**raw, "cache_hit": False, "cache_key": cache_key}
        _write_text(answer_path, answer + "\n")
        _write_json(stats_path, stats)
        _write_json(raw_path, raw)
        return answer, stats, raw

    def _baseline_cache_key(
        self,
        *,
        prompt_id: str,
        user_prompt: str,
        source_fingerprint: str,
        model_config: AnalyzerBenchmarkModelConfig,
    ) -> str:
        model_payload = model_config.to_dict()
        model_payload.pop("api_key", None)
        payload = {
            "version": 1,
            "prompt_id": prompt_id,
            "user_prompt": user_prompt,
            "source_fingerprint": source_fingerprint,
            "model_config": model_payload,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]

    def _run_baseline(
        self,
        *,
        user_prompt: str,
        compact_source_text: str,
        model_client: Any,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        system_prompt = (
            "你是小说分析 benchmark baseline。你会收到完整原文，原文仅去除了空格和换行。\n"
            "请只根据原文回答用户的分析问题，不要续写正文，不要输出 JSON。"
        )
        prompt_payload = {
            "full_source_text_without_whitespace": compact_source_text,
            "user_prompt": user_prompt,
        }
        user_payload = json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"))
        stats = _prompt_stats(system_prompt, user_payload)
        started = _utc_now()
        started_monotonic = time.monotonic()
        answer = str(model_client.generate_text(system_prompt=system_prompt, user_prompt=user_payload)).strip()
        ended = _utc_now()
        if not answer:
            raise RuntimeError("Analyzer benchmark baseline returned empty answer")
        raw = {
            "started_at": started,
            "ended_at": ended,
            "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
            "response_chars": len(answer),
        }
        return answer, {**stats, **raw}, {"text": answer, **raw}

    def _run_judge(
        self,
        *,
        user_prompt: str,
        baseline_answer: str,
        analyzer_answer: str,
        analyzer_evidence: list[dict[str, Any]],
        analyzer_trace: Mapping[str, Any],
        model_client: Any,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        system_prompt = (
            "你是 Outline Analyzer smoke benchmark 的独立 Judge。比较 baseline answer 与 Analyzer answer。\n"
            "你不能读取完整原文；baseline answer 只是参照。请按题型评分，并惩罚幻觉、过度断言和证据缺失。\n"
            "`hallucination_or_overclaim_penalty` 是反向惩罚分：0 表示没有发现幻觉或过度断言，"
            "5 表示严重幻觉或严重过度断言；不要把它当作质量分。\n"
            "`key_evidence_coverage` 必须结合 Analyzer committed evidence 判断；如果 evidence 为空，"
            "除非 Analyzer 明确声明证据不足，否则该项通常不能高于 2。\n"
            "只返回 JSON 对象。"
        )
        user_payload = {
            "benchmark_user_prompt": user_prompt,
            "baseline_answer": baseline_answer,
            "analyzer_answer": analyzer_answer,
            "analyzer_committed_evidence_digest": analyzer_evidence,
            "analyzer_trace_summary": self._trace_summary(analyzer_trace),
            "score_schema": {
                "same_core_conclusion": "0-5",
                "character_reading_accuracy": "0-5",
                "worldview_theme_coverage": "0-5",
                "style_tone_sensitivity": "0-5",
                "key_evidence_coverage": "0-5",
                "canon_consistency": "0-5",
                "hallucination_or_overclaim_penalty": "0-5，反向惩罚分；0=无问题，5=严重问题",
                "notes": [],
            },
        }
        user_prompt_text = json.dumps(user_payload, ensure_ascii=False, indent=2)
        raw = str(model_client.generate_text(system_prompt=system_prompt, user_prompt=user_prompt_text)).strip()
        parsed = extract_json_blob(raw)
        if not isinstance(parsed, Mapping):
            raise RuntimeError("Analyzer benchmark judge did not return a JSON object")
        return dict(parsed), {"system_prompt": system_prompt, "user_prompt": user_prompt_text}

    def _source_metadata(self, *, source_path: Path, db_path: Path, book_id: str, source_text: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "source_path": str(source_path),
            "db_path": str(db_path),
            "book_id": book_id,
            "source_chars": len(source_text),
            "source_chars_without_whitespace": len(_compact_source_text(source_text)),
        }
        try:
            db = NovelAgentDB(db_path)
            with db.connect() as conn:
                for table in ("documents", "chapters", "character_profiles"):
                    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE book_id = ?", (book_id,)).fetchone()
                    metadata[f"{table}_count"] = int(row["count"] or 0) if row else 0
        except Exception as exc:  # noqa: BLE001 - metadata should not hide primary benchmark execution.
            metadata["db_metadata_error"] = str(exc)
        return metadata

    def _aggregate_analyzer_prompt_stats(self, calls: Sequence[PromptCallRecord]) -> dict[str, Any]:
        call_dicts = [item.to_dict() for item in calls]
        total_chars = sum(int(item.prompt_stats["prompt_chars"]) for item in calls)
        total_bytes = sum(int(item.prompt_stats["prompt_bytes"]) for item in calls)
        total_tokens = sum(int(item.prompt_stats["prompt_token_estimate"]) for item in calls)
        return {
            "calls": call_dicts,
            "max_single_prompt_chars": max((int(item.prompt_stats["prompt_chars"]) for item in calls), default=0),
            "max_single_prompt_bytes": max((int(item.prompt_stats["prompt_bytes"]) for item in calls), default=0),
            "total_prompt_chars": total_chars,
            "total_prompt_bytes": total_bytes,
            "total_token_estimate": total_tokens,
            "round_count": sum(1 for item in calls if item.stage == "loop"),
            "triage_count": sum(1 for item in calls if item.stage == "triage"),
        }

    def _rejected_evidence(self, trace: Mapping[str, Any]) -> list[dict[str, Any]]:
        rejected: list[dict[str, Any]] = []
        rounds = trace.get("rounds") if isinstance(trace, Mapping) else []
        if not isinstance(rounds, Sequence):
            return rejected
        for round_item in rounds:
            if not isinstance(round_item, Mapping):
                continue
            rejected_ids = set((round_item.get("triage") or {}).get("rejected_request_ids") or [])
            candidates = round_item.get("candidate_evidence_digests") or []
            candidate_items = candidates if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)) else []
            for candidate in candidate_items:
                if isinstance(candidate, Mapping) and candidate.get("request_id") in rejected_ids:
                    rejected.append(dict(candidate))
        return rejected

    def _trace_summary(self, trace: Mapping[str, Any]) -> dict[str, Any]:
        rounds = trace.get("rounds") if isinstance(trace, Mapping) else []
        summary_rounds: list[dict[str, Any]] = []
        round_items = rounds if isinstance(rounds, Sequence) and not isinstance(rounds, (str, bytes)) else []
        for round_item in round_items:
            if not isinstance(round_item, Mapping):
                continue
            loop_output = dict(round_item.get("loop_output") or {})
            triage = dict(round_item.get("triage") or {})
            summary_rounds.append(
                {
                    "round": round_item.get("round"),
                    "status": loop_output.get("status"),
                    "request_types": [
                        str(request.get("type") or request.get("request_type") or "")
                        for request in loop_output.get("requests", [])
                        if isinstance(request, Mapping)
                    ],
                    "kept_request_ids": triage.get("kept_request_ids") or [],
                    "rejected_request_ids": triage.get("rejected_request_ids") or [],
                    "budget_state": round_item.get("budget_state") or {},
                }
            )
        return {
            "rounds": summary_rounds,
            "final_budget_state": trace.get("final_budget_state") if isinstance(trace, Mapping) else {},
            "failure": trace.get("failure") if isinstance(trace, Mapping) else "",
        }

    def _build_summary(
        self,
        *,
        run_id: str,
        run_dir: Path,
        prompt_results: Sequence[AnalyzerBenchmarkPromptResult],
    ) -> dict[str, Any]:
        prompts = []
        for item in prompt_results:
            baseline_chars = int(item.baseline_prompt_stats.get("prompt_chars") or 0)
            analyzer_max = int(item.analyzer_prompt_stats.get("max_single_prompt_chars") or 0)
            analyzer_total = int(item.analyzer_prompt_stats.get("total_prompt_chars") or 0)
            length_informational = baseline_chars < 20000
            length_pass = length_informational or (
                analyzer_max <= 0.35 * baseline_chars and analyzer_total <= 0.80 * baseline_chars
            )
            quality_pass = self._quality_pass(item.prompt_id, item.judge_report)
            prompts.append(
                {
                    "prompt_id": item.prompt_id,
                    "status": "pass" if length_pass and quality_pass and item.analyzer_status == "ok" else "needs_review",
                    "baseline_prompt_chars": baseline_chars,
                    "analyzer_max_single_prompt_chars": analyzer_max,
                    "analyzer_total_prompt_chars": analyzer_total,
                    "length_informational": length_informational,
                    "length_pass": length_pass,
                    "quality_pass": quality_pass,
                    "analyzer_status": item.analyzer_status,
                    "judge_report": item.judge_report,
                    "artifact_dir": str(item.artifact_dir),
                }
            )
        return {
            "run_id": run_id,
            "artifact_dir": str(run_dir),
            "created_at": _utc_now(),
            "prompts": prompts,
        }

    def _quality_pass(self, prompt_id: str, judge_report: Mapping[str, Any]) -> bool:
        same_core = self._score(judge_report.get("same_core_conclusion"))
        evidence = self._score(judge_report.get("key_evidence_coverage"))
        canon = self._score(judge_report.get("canon_consistency"))
        penalty = self._score(judge_report.get("hallucination_or_overclaim_penalty"))
        specialty_key = {
            "protagonist_character_and_next_actions": "character_reading_accuracy",
            "worldview_story_theme": "worldview_theme_coverage",
            "style_and_emotional_tone": "style_tone_sensitivity",
        }.get(prompt_id)
        specialty = self._score(judge_report.get(specialty_key)) if specialty_key else 4.0
        return same_core >= 4.0 and specialty >= 4.0 and evidence >= 3.0 and canon >= 4.0 and penalty <= 1.0

    def _score(self, value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _resolve_path(self, path: Path) -> Path:
        expanded = path.expanduser()
        return expanded.resolve() if expanded.is_absolute() else (self.repo_root / expanded).resolve()


def build_default_longzu_120kb_config(
    *,
    repo_root: Path,
    run_id: str = "",
    prompt_ids: list[str] | None = None,
    db_path: Path | None = None,
    book_id: str | None = None,
    artifact_dir: Path | None = None,
    model_config: AnalyzerBenchmarkModelConfig | None = None,
    reuse_baseline: bool = True,
) -> AnalyzerBenchmarkConfig:
    resolved_db = db_path or repo_root / ".indexes" / "longzu-120kb-web-real-20260518b.db"
    resolved_book_id = book_id or "longzu-120kb-web-real-20260518b"
    return AnalyzerBenchmarkConfig(
        source_path=repo_root / "novel_agent" / "tests" / "longzu_120kb.txt",
        db_path=resolved_db,
        book_id=resolved_book_id,
        artifact_dir=artifact_dir or repo_root / "runs" / "benchmarks" / "outline_analyzer",
        run_id=run_id,
        prompt_ids=prompt_ids or [],
        model_config=model_config or AnalyzerBenchmarkModelConfig(),
        reuse_baseline=reuse_baseline,
    )
