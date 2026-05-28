from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from ..schemas.reviewer_schema import (
    EVIDENCE_SOURCE_TYPES,
    FINDING_SEVERITIES,
    ReviewerToolCall,
    ReviewerToolResult,
    ReviewPlan,
    ReviewReport,
    ReviewRequest,
    utc_now,
)
from ..utils.json_utils import compact_json, extract_json_blob
from .base import BaseReviewer, ModelPrompt, ReviewerLoopState
from .target_resolver import ReviewTargetResolver
from .tools import ReviewerArtifactTool, ReviewerKBTool, ReviewerMemoryTool


class ReviewerRuntime:
    def __init__(
        self,
        *,
        model_client: Any | None,
        target_resolver: ReviewTargetResolver | None = None,
        memory_tool: ReviewerMemoryTool | None = None,
        kb_tool: ReviewerKBTool | None = None,
        artifact_tool: ReviewerArtifactTool | None = None,
        artifact_root: Path | None = None,
    ) -> None:
        self.model_client = model_client
        self.target_resolver = target_resolver or ReviewTargetResolver()
        self.memory_tool = memory_tool or ReviewerMemoryTool()
        self.kb_tool = kb_tool or ReviewerKBTool()
        self.artifact_tool = artifact_tool or ReviewerArtifactTool()
        self.artifact_root = artifact_root or Path.cwd() / "runs" / "reviewer"

    def run(
        self,
        request: ReviewRequest,
        *,
        reviewer: BaseReviewer,
        conn: sqlite3.Connection | None = None,
    ) -> ReviewReport:
        manifest = reviewer.manifest()
        if request.target.target_type not in set(manifest.supported_target_types):
            raise ValueError(f"reviewer {manifest.reviewer_id} does not support {request.target.target_type}")
        run_dir = self._run_dir(request, reviewer_id=manifest.reviewer_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(run_dir / "review_request.json", request.to_dict())

        state: ReviewerLoopState | None = None
        try:
            resolved_target = self.target_resolver.resolve(request, conn=conn)
            self._write_json(run_dir / "resolved_target.json", resolved_target.to_dict())
            state = ReviewerLoopState(
                request=request,
                resolved_target=resolved_target,
                reviewer_id=manifest.reviewer_id,
                reviewer_version=manifest.reviewer_version,
            )
            state.record(status="initialized", event="runtime_initialized")

            if self.model_client is None:
                state.record(status="needs_model", event="model_client_missing")
                report = self._failure_report(request, reviewer, status="needs_model", summary_zh="模型不可用，评审未完成。")
                self._persist_terminal(run_dir, state, report)
                return report

            plan = self._planning(request, reviewer, state, run_dir)
            state.plan = plan.to_dict()
            self._write_json(run_dir / "review_plan.json", state.plan)

            tool_results = self._query_context(request, manifest_allowed_tools=set(manifest.allowed_tools), state=state, conn=conn)
            state.tool_results = [result.to_dict() for result in tool_results]

            state.record(status="evidence_sufficiency_check", event="tool_results_collected", payload={"tool_result_count": len(tool_results)})
            report = self._judging(request, reviewer, state, run_dir)
            checked = self._self_check(request, reviewer, state, report, run_dir)
            self._persist_terminal(run_dir, state, checked)
            return checked
        except _NeedsModel:
            if state is not None:
                state.record(status="needs_model", event="model_unavailable")
                report = self._failure_report(request, reviewer, status="needs_model", summary_zh="模型不可用，评审未完成。")
                self._persist_terminal(run_dir, state, report)
                return report
            return self._failure_report(request, reviewer, status="needs_model", summary_zh="模型不可用，评审未完成。")
        except Exception as exc:
            if state is not None:
                state.record(status="failed", event="runtime_failed", payload={"error": str(exc)})
                report = self._failure_report(request, reviewer, status="failed", summary_zh=f"评审运行失败：{exc}")
                self._persist_terminal(run_dir, state, report)
                return report
            return self._failure_report(request, reviewer, status="failed", summary_zh=f"评审运行失败：{exc}")

    def _planning(self, request: ReviewRequest, reviewer: BaseReviewer, state: ReviewerLoopState, run_dir: Path) -> ReviewPlan:
        state.record(status="planning", event="planning_prompt_started")
        raw_payload, raw_path = self._call_json(
            reviewer.build_planning_prompt(request, state.resolved_target),
            request=request,
            run_dir=run_dir,
            label="planning",
        )
        state.raw_model_response_paths.append(str(raw_path))
        if not isinstance(raw_payload, Mapping):
            raise ValueError("planning model output must be a JSON object")
        payload = dict(raw_payload)
        payload.setdefault("schema_version", "1.0")
        payload.setdefault("reviewer_id", reviewer.manifest().reviewer_id)
        payload.setdefault("target_id", request.target.target_id)
        if not payload.get("dimensions"):
            payload["dimensions"] = reviewer.manifest().dimensions
        plan = ReviewPlan.from_dict(payload)
        state.record(status="planning", event="planning_completed", payload={"tool_request_count": len(plan.tool_requests)})
        return plan

    def _query_context(
        self,
        request: ReviewRequest,
        *,
        manifest_allowed_tools: set[str],
        state: ReviewerLoopState,
        conn: sqlite3.Connection | None,
    ) -> list[ReviewerToolResult]:
        plan = ReviewPlan.from_dict(state.plan or {})
        results: list[ReviewerToolResult] = []
        if not plan.tool_requests:
            state.record(status="querying_context", event="no_tool_requests")
            return results
        state.record(status="querying_context", event="tool_requests_started")
        for index, tool_request in enumerate(plan.tool_requests, start=1):
            if len(results) >= request.budget.max_tool_calls:
                state.record(status="querying_context", event="tool_budget_exhausted")
                break
            call = self._tool_call_from_request(tool_request, index=index)
            state.tool_calls.append(call.to_dict())
            if call.tool not in manifest_allowed_tools:
                result = ReviewerToolResult(
                    tool_call_id=call.tool_call_id,
                    tool=call.tool,
                    status="blocked",
                    trace=[{"operation": "policy_guard", "blocked": True, "reason": f"reviewer 未声明工具: {call.tool}"}],
                    error=f"reviewer 未声明工具: {call.tool}",
                )
            elif call.tool == "memory_query":
                result = self.memory_tool.query(
                    conn,
                    book_id=request.book_id,
                    tool_call=call,
                    context_policy=request.context_policy,
                    review_budget=request.budget,
                )
            elif call.tool == "kb_retrieval":
                result = self.kb_tool.retrieve(
                    conn,
                    book_id=request.book_id,
                    tool_call=call,
                    target_excerpt=state.resolved_target.resolved_text,
                    context_policy=request.context_policy,
                    review_budget=request.budget,
                )
            else:
                result = self.artifact_tool.read(tool_call=call, context_policy=request.context_policy)
            results.append(result)
            state.record(
                status="querying_context",
                event="tool_call_completed",
                payload={"tool": call.tool, "status": result.status, "tool_call_id": call.tool_call_id},
            )
        return results

    def _judging(self, request: ReviewRequest, reviewer: BaseReviewer, state: ReviewerLoopState, run_dir: Path) -> ReviewReport:
        state.record(status="judging", event="judging_prompt_started")
        base_prompt = reviewer.build_judging_prompt(state)
        attempts = 1 + request.budget.json_repair_attempts
        last_error: Exception | None = None
        last_payload: dict[str, Any] | list[Any] | None = None
        report: ReviewReport | None = None
        for attempt in range(1, attempts + 1):
            prompt = (
                base_prompt
                if attempt == 1
                else self._schema_repair_prompt(
                    base_prompt,
                    contract_name="ReviewReport",
                    error=str(last_error or "schema validation failed"),
                    invalid_payload=last_payload,
                )
            )
            raw_payload, raw_path = self._call_json(
                prompt,
                request=request,
                run_dir=run_dir,
                label="judging" if attempt == 1 else f"judging_schema_repair_{attempt}",
            )
            state.raw_model_response_paths.append(str(raw_path))
            last_payload = raw_payload
            if not isinstance(raw_payload, Mapping):
                last_error = ValueError("judging model output must be a JSON object")
                if attempt >= attempts:
                    raise last_error
                state.record(status="judging", event="judging_schema_repair_requested", payload={"error": str(last_error)})
                continue
            payload = self._enrich_report_payload(dict(raw_payload), request=request, reviewer=reviewer, state=state, raw_path=raw_path)
            try:
                report = ReviewReport.from_dict(payload)
                if report.status != "success":
                    raise ValueError("judging model must produce a success ReviewReport before self-check")
            except ValueError as exc:
                last_error = exc
                last_payload = payload
                if attempt >= attempts:
                    raise
                state.record(status="judging", event="judging_schema_repair_requested", payload={"error": str(exc)})
                continue
            break
        if report is None:
            raise ValueError(f"judging schema validation failed: {last_error}")
        self._guard_reference_truth(request, report)
        state.record(status="judging", event="judging_completed", payload={"score": report.score})
        return report

    def _self_check(
        self,
        request: ReviewRequest,
        reviewer: BaseReviewer,
        state: ReviewerLoopState,
        report: ReviewReport,
        run_dir: Path,
    ) -> ReviewReport:
        state.record(status="self_check", event="self_check_prompt_started")
        raw_payload, raw_path = self._call_json(
            reviewer.build_self_check_prompt(report, state),
            request=request,
            run_dir=run_dir,
            label="self_check",
        )
        state.raw_model_response_paths.append(str(raw_path))
        if not isinstance(raw_payload, Mapping):
            raise ValueError("self-check model output must be a JSON object")
        status = str(raw_payload.get("status") or "").strip().lower()
        if status not in {"passed", "success", "ok"}:
            notes = str(raw_payload.get("notes_zh") or raw_payload.get("reason_zh") or "模型自检未通过。")
            raise ValueError(notes)
        payload = report.to_dict()
        payload["self_check"] = dict(raw_payload)
        checked = ReviewReport.from_dict(payload)
        state.record(status="completed", event="self_check_completed")
        return checked

    def _call_json(
        self,
        prompt: ModelPrompt,
        *,
        request: ReviewRequest,
        run_dir: Path,
        label: str,
    ) -> tuple[dict[str, Any] | list[Any], Path]:
        attempts = 1 + request.budget.json_repair_attempts
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            if self._model_calls_used(run_dir) >= request.budget.max_model_calls:
                raise RuntimeError("review model call budget exhausted")
            try:
                raw_text = self._generate_text(prompt, repair_attempt=attempt > 1)
                raw_path = self._write_raw_response(run_dir, label=label, attempt=attempt, raw_text=raw_text)
                payload = extract_json_blob(raw_text)
                return payload, raw_path
            except _NeedsModel:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    raise ValueError(f"{label} JSON parsing failed after {attempts} attempts: {exc}") from exc
        raise ValueError(f"{label} JSON parsing failed: {last_error}")

    def _generate_text(self, prompt: ModelPrompt, *, repair_attempt: bool) -> str:
        if self.model_client is None:
            raise _NeedsModel()
        system_prompt = prompt.system_prompt
        user_prompt = prompt.user_prompt
        if repair_attempt:
            user_prompt = f"{user_prompt}\n\n请只返回符合 contract 的 JSON，不要解释。"
        if hasattr(self.model_client, "generate_text"):
            return str(self.model_client.generate_text(system_prompt=system_prompt, user_prompt=user_prompt))
        if hasattr(self.model_client, "generate_json"):
            payload, raw_text = self.model_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
            return str(raw_text or compact_json(payload))
        raise _NeedsModel()

    def _model_calls_used(self, run_dir: Path) -> int:
        return len(list((run_dir / "raw_model_responses").glob("*.txt"))) if (run_dir / "raw_model_responses").exists() else 0

    def _write_raw_response(self, run_dir: Path, *, label: str, attempt: int, raw_text: str) -> Path:
        raw_dir = run_dir / "raw_model_responses"
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / f"{label}_{attempt}.txt"
        path.write_text(raw_text, encoding="utf-8")
        return path

    def _schema_repair_prompt(
        self,
        base_prompt: ModelPrompt,
        *,
        contract_name: str,
        error: str,
        invalid_payload: dict[str, Any] | list[Any] | None,
    ) -> ModelPrompt:
        user_prompt = (
            f"{base_prompt.user_prompt}\n\n"
            f"上一轮输出未通过 {contract_name} contract 校验。\n"
            f"校验错误：{error}\n"
            "请基于同一评审判断重新输出完整、严格的 JSON，不要输出 Markdown 或解释。\n"
            "不得新增本地规则式判断；只修复 contract 字段、枚举和缺失字段。\n"
            f"evidence_refs[].source_type 只能是：{', '.join(sorted(EVIDENCE_SOURCE_TYPES))}。\n"
            f"findings[].severity 只能是：{', '.join(sorted(FINDING_SEVERITIES))}。\n"
            "不要使用 document、tool_result、artifact、warning、info、high、medium、low 等非 contract 枚举。\n\n"
            "上一轮 JSON：\n"
            f"{json.dumps(invalid_payload or {}, ensure_ascii=False, indent=2)}"
        )
        return ModelPrompt(system_prompt=base_prompt.system_prompt, user_prompt=user_prompt)

    def _tool_call_from_request(self, data: Mapping[str, Any], *, index: int) -> ReviewerToolCall:
        tool = str(data.get("tool") or "").strip()
        budget = dict(data.get("budget") or {}) if isinstance(data.get("budget"), Mapping) else {}
        for key in (
            "request_type",
            "type",
            "expected_evidence",
            "priority",
            "expected_depth",
            "name",
            "concept",
            "chapter_refs",
            "document_ids",
            "source_doc_ids",
            "read_reason",
            "expected_confirmation",
            "affects_analysis",
            "excerpt_focus",
        ):
            if key in data and key not in budget:
                budget[key] = data[key]
        return ReviewerToolCall(
            tool_call_id=str(data.get("tool_call_id") or f"tool-call-{index:03d}"),
            tool=tool,
            intent=str(data.get("intent") or data.get("query") or data.get("expected_evidence") or ""),
            query=str(data.get("query") or data.get("intent") or ""),
            budget=budget,
            reason_zh=str(data.get("reason_zh") or data.get("notes_zh") or ""),
        )

    def _enrich_report_payload(
        self,
        payload: dict[str, Any],
        *,
        request: ReviewRequest,
        reviewer: BaseReviewer,
        state: ReviewerLoopState,
        raw_path: Path,
    ) -> dict[str, Any]:
        manifest = reviewer.manifest()
        payload.setdefault("schema_version", "1.0")
        payload.setdefault("review_report_id", f"review-report-{request.review_request_id}-{manifest.reviewer_id}")
        payload.setdefault("review_request_id", request.review_request_id)
        payload.setdefault("target_id", request.target.target_id)
        payload.setdefault("target_type", request.target.target_type)
        payload.setdefault("reviewer_id", manifest.reviewer_id)
        payload.setdefault("reviewer_version", manifest.reviewer_version)
        payload.setdefault("status", "success")
        payload.setdefault("score_usage", "reference_only")
        payload.setdefault("model_id", self._model_id())
        payload.setdefault("created_at", utc_now())
        payload.setdefault("raw_model_response_path", str(raw_path))
        payload["memory_query_trace"] = [trace for result in state.tool_results or [] if result.get("tool") == "memory_query" for trace in result.get("trace", [])]
        payload["kb_query_trace"] = [trace for result in state.tool_results or [] if result.get("tool") == "kb_retrieval" for trace in result.get("trace", [])]
        payload["artifact_trace"] = [trace for result in state.tool_results or [] if result.get("tool") == "artifact_read" for trace in result.get("trace", [])]
        payload.setdefault("metadata", {})
        if isinstance(payload["metadata"], Mapping):
            payload["metadata"] = dict(payload["metadata"])
            payload["metadata"]["score_usage_note"] = "reference_only; not a writer or benchmark pass/fail decision"
        return payload

    def _guard_reference_truth(self, request: ReviewRequest, report: ReviewReport) -> None:
        if request.context_policy.allow_reference_truth:
            return
        if any(ref.source_type == "reference_truth" for ref in report.evidence_refs):
            raise ValueError("reference_truth evidence is not authorized for this review context")

    def _failure_report(self, request: ReviewRequest, reviewer: BaseReviewer, *, status: str, summary_zh: str) -> ReviewReport:
        manifest = reviewer.manifest()
        return ReviewReport(
            review_report_id=f"review-report-{request.review_request_id}-{manifest.reviewer_id}",
            review_request_id=request.review_request_id,
            target_id=request.target.target_id,
            target_type=request.target.target_type,
            reviewer_id=manifest.reviewer_id,
            reviewer_version=manifest.reviewer_version,
            status=status,
            summary_zh=summary_zh,
            model_id=self._model_id() if self.model_client is not None else "",
            metadata={"score_usage_note": "no formal score because the review did not complete successfully"},
        )

    def _persist_terminal(self, run_dir: Path, state: ReviewerLoopState, report: ReviewReport) -> None:
        self._write_json(run_dir / "loop_trace.json", state.loop_trace)
        self._write_json(run_dir / "reviewer_report.json", report.to_dict())

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _run_dir(self, request: ReviewRequest, *, reviewer_id: str) -> Path:
        return self.artifact_root / request.review_request_id / reviewer_id

    def _model_id(self) -> str:
        settings = getattr(self.model_client, "settings", None)
        model_name = getattr(settings, "model_name", "") if settings is not None else ""
        return str(model_name or getattr(self.model_client, "model_id", "") or "unknown-model")


class _NeedsModel(RuntimeError):
    pass
