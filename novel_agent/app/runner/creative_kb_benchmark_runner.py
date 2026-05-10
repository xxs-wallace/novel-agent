from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..schemas.creative_kb_benchmark_schema import CreativeKBBenchmarkInput, CreativeKBBenchmarkResult
from ..services.creative_kb_benchmark_service import CreativeKBBenchmarkService


ProgressCallback = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True, slots=True)
class CreativeKBBenchmarkRunConfig:
    source_path: Path | None = None
    fixture: str | None = "longzu_32kb"
    run_id: str | None = None
    case_count: int = 3
    artifact_dir: Path | None = None
    enable_writer_ab: bool = False
    seed: int = 17
    prefix_min_chars: int = 1200
    recent_window_size: int = 3
    use_real_model: bool = False
    dry_run_model: bool = False
    model_type: str = "InferenceClientModel"
    model_id: str = "Qwen/Qwen3-Next-80B-A3B-Thinking"
    provider: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.2
    max_output_tokens: int = 8192
    timeout_seconds: int = 120
    thinking: str | None = None
    reasoning_effort: str | None = None


class CreativeKBBenchmarkRunner:
    """CLI-facing wrapper for CreativeKBBenchmarkService.

    The runner owns argument-to-service wiring only. It does not build reviewer prompts
    directly and does not modify any existing user KB; the service writes an isolated
    benchmark DB under the run artifact directory.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        service: CreativeKBBenchmarkService | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.progress_callback = progress_callback
        self.service = service or CreativeKBBenchmarkService(
            repo_root=self.repo_root,
            progress_callback=progress_callback,
        )

    def run(self, config: CreativeKBBenchmarkRunConfig) -> CreativeKBBenchmarkResult:
        benchmark_input = CreativeKBBenchmarkInput(
            source_path=str(config.source_path) if config.source_path is not None else None,
            fixture=config.fixture,
            run_id=config.run_id,
            case_count=config.case_count,
            artifact_dir=str(config.artifact_dir) if config.artifact_dir is not None else None,
            enable_writer_ab=config.enable_writer_ab,
            model_config=self._model_config(config),
            seed=config.seed,
            prefix_min_chars=config.prefix_min_chars,
            recent_window_size=config.recent_window_size,
        )
        return self.service.run(benchmark_input)

    def _model_config(self, config: CreativeKBBenchmarkRunConfig) -> dict[str, Any] | None:
        if not config.use_real_model and not config.dry_run_model:
            return None
        return {
            "model_type": config.model_type,
            "model_id": config.model_id,
            "provider": config.provider,
            "api_base": config.api_base,
            "api_key": config.api_key,
            "api_key_env": config.api_key_env,
            "temperature": config.temperature,
            "max_output_tokens": config.max_output_tokens,
            "timeout_seconds": config.timeout_seconds,
            "thinking": config.thinking,
            "reasoning_effort": config.reasoning_effort,
            "dry_run": config.dry_run_model,
        }


class CreativeKBBenchmarkSummaryPresenter:
    """Formats Creative KB benchmark results for humans."""

    def to_json_summary(self, result: CreativeKBBenchmarkResult | Mapping[str, Any]) -> dict[str, Any]:
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        build_quality = self._build_quality_summary(payload)
        retrieval = dict(payload.get("retrieval_review_summary") or {})
        writer_ab = payload.get("writer_ab_summary")
        issues = self._major_issues(payload)
        return {
            "title": "Creative KB Benchmark",
            "run_id": payload.get("run_id", ""),
            "status": payload.get("status", ""),
            "build_quality_decision": build_quality["decision"],
            "build_quality_score": build_quality["score"],
            "retrieval_decision": str(retrieval.get("decision") or "pending"),
            "retrieval_score": self._score(retrieval.get("score")),
            "major_issues": issues,
            "writer_ab": self._writer_ab_text(writer_ab),
            "artifact_dir": str(payload.get("artifact_dir") or ""),
            "summary_path": str(payload.get("summary_path") or ""),
        }

    def to_text(self, result: CreativeKBBenchmarkResult | Mapping[str, Any]) -> str:
        summary = self.to_json_summary(result)
        issues = "；".join(summary["major_issues"]) if summary["major_issues"] else "暂无显著问题。"
        return "\n".join(
            [
                "Creative KB Benchmark",
                f"状态：{summary['status'] or 'unknown'}",
                (
                    "建卡质量："
                    f"{summary['build_quality_decision']} / {summary['build_quality_score']:.2f}"
                ),
                (
                    "检索与 rerank："
                    f"{summary['retrieval_decision']} / {summary['retrieval_score']:.2f}"
                ),
                f"主要问题：{issues}",
                f"Writer A/B：{summary['writer_ab']}",
                f"artifact_dir：{summary['artifact_dir']}",
            ]
        )

    def exception_to_text(self, exc: Exception, *, artifact_dir: Path | None = None) -> str:
        message = str(exc) or exc.__class__.__name__
        prefix = self._exception_prefix(exc, message)
        lines = [
            "Creative KB Benchmark",
            "状态：failed",
            f"主要问题：{prefix}：{message}",
        ]
        if artifact_dir is not None:
            lines.append(f"artifact_dir：{artifact_dir}")
        return "\n".join(lines)

    def _build_quality_summary(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        build_summary = payload.get("build_summary")
        build_summary = build_summary if isinstance(build_summary, Mapping) else {}
        quality = build_summary.get("quality_review")
        if isinstance(quality, Mapping):
            return {
                "decision": str(quality.get("decision") or "pending"),
                "score": self._score(quality.get("score")),
            }
        if int(build_summary.get("fragment_card_count") or 0) <= 0 and build_summary:
            return {"decision": "fail", "score": 0.0}
        return {"decision": "pending", "score": 0.0}

    def _major_issues(self, payload: Mapping[str, Any]) -> list[str]:
        issues: list[str] = []
        for error in payload.get("errors") or []:
            text = str(error).strip()
            if text:
                issues.append(self._humanize_issue(text))

        build_summary = payload.get("build_summary")
        build_summary = build_summary if isinstance(build_summary, Mapping) else {}
        quality = build_summary.get("quality_review")
        quality = quality if isinstance(quality, Mapping) else {}
        if quality.get("decision") in {"fail", "borderline"}:
            summary = str(quality.get("summary") or "").strip()
            if summary:
                issues.append(self._humanize_issue(summary))
        for group_name in ("fragment_card_review", "cluster_review"):
            group = quality.get(group_name)
            group = group if isinstance(group, Mapping) else {}
            for report in group.get("reports") or []:
                if not isinstance(report, Mapping):
                    continue
                for issue in report.get("issues") or []:
                    issues.append(self._humanize_issue(str(issue)))

        retrieval = payload.get("retrieval_review_summary")
        retrieval = retrieval if isinstance(retrieval, Mapping) else {}
        for report in retrieval.get("case_reports") or []:
            if not isinstance(report, Mapping):
                continue
            for issue in report.get("issues") or []:
                issues.append(self._humanize_issue(str(issue)))
            summary = str(report.get("summary") or "").strip()
            if report.get("decision") == "fail" and summary:
                issues.append(self._humanize_issue(summary))

        retrieval_summary = str(retrieval.get("summary") or "").strip()
        if retrieval.get("decision") in {"fail", "borderline"} and retrieval_summary:
            issues.append(self._humanize_issue(retrieval_summary))

        warnings = payload.get("warnings") or []
        for warning in warnings[:2]:
            text = str(warning).strip()
            if text:
                issues.append(self._humanize_issue(text))

        normalized: list[str] = []
        seen: set[str] = set()
        for issue in issues:
            text = issue.strip()
            if not text or text in seen:
                continue
            normalized.append(text)
            seen.add(text)
        return normalized[:5]

    def _humanize_issue(self, issue: str) -> str:
        normalized = issue.strip()
        lowered = normalized.lower()
        if "empty_kb" in lowered or "no fragment_cards" in lowered:
            return "空 KB：Creative KB 没有可评测的 fragment_cards"
        if "empty_selected_references" in lowered or "no selected reference" in lowered:
            return "空 references：检索与 rerank 没有选出参考片段"
        if "trace_missing" in lowered or "missing from fragment_cards" in lowered:
            return "references 无法回源：选中或 decoy 片段无法追溯到 fragment_cards"
        if "reviewer_failed" in lowered or "reviewer failed" in lowered:
            return "Reviewer 失败：外部评审没有返回可用结果"
        if "llm" in lowered or "model" in lowered or "api_key" in lowered or "api key" in lowered:
            return f"真实 LLM 调用失败：{normalized}"
        artifact_write_markers = (
            "write failed",
            "write_text",
            "failed to write",
            "permission",
            "is a directory",
            "not a directory",
            "read-only file system",
        )
        if any(marker in lowered for marker in artifact_write_markers):
            return f"产物写入失败：{normalized}"
        return normalized

    def _writer_ab_text(self, writer_ab: object) -> str:
        if not isinstance(writer_ab, Mapping):
            return "未启用"
        status = str(writer_ab.get("status") or "pending")
        winner = str(writer_ab.get("winner") or "pending")
        decision = str(writer_ab.get("decision") or "pending")
        score = self._score(writer_ab.get("score"))
        summary = str(writer_ab.get("summary") or "").strip()
        if status == "completed":
            return f"{winner}；{decision} / {score:.2f}。{summary}".strip()
        if summary:
            return f"{status}：{summary}"
        return status

    def _exception_prefix(self, exc: Exception, message: str) -> str:
        lowered = message.lower()
        if isinstance(exc, OSError) or "write" in lowered or "permission" in lowered:
            return "产物写入失败"
        if "llm" in lowered or "model" in lowered or "api_key" in lowered or "api key" in lowered:
            return "真实 LLM 调用失败"
        return "运行失败"

    @staticmethod
    def _score(value: object) -> float:
        try:
            return round(float(value or 0.0), 4)
        except (TypeError, ValueError):
            return 0.0
