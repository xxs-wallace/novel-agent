from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..schemas.creative_kb_schema import SceneBrief
from ..schemas.narrative_inquiry_schema import AnalyzerBudget, EvidenceBundle, NarrativeInquiryRequest
from ..schemas.orchestration_schema import RetrievalContext
from ..schemas.reviewer_schema import (
    ReviewBudget,
    ReviewContextPolicy,
    ReviewerToolCall,
    ReviewerToolResult,
)
from ..services.narrative_inquiry_broker import NarrativeInquiryBroker
from ..services.narrative_memory_query_service import NarrativeMemoryQueryService
from ..services.retrieval_facade import RetrievalFacade


class ReviewerMemoryTool:
    def __init__(
        self,
        *,
        query_service: NarrativeMemoryQueryService | None = None,
        inquiry_broker: NarrativeInquiryBroker | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).expanduser().resolve()
        self.query_service = query_service or NarrativeMemoryQueryService(repo_root=self.repo_root)
        self.inquiry_broker = inquiry_broker or NarrativeInquiryBroker(
            repo_root=self.repo_root,
            memory_query_service=self.query_service,
        )

    def query(
        self,
        conn: sqlite3.Connection | None,
        *,
        book_id: str,
        tool_call: ReviewerToolCall,
        context_policy: ReviewContextPolicy,
        review_budget: ReviewBudget,
    ) -> ReviewerToolResult:
        if not context_policy.allow_memory:
            return self._blocked(tool_call, "Memory 查询未授权。")
        if conn is None:
            return self._failed(tool_call, "Memory 查询需要数据库连接。")
        try:
            inquiry_budget = self._inquiry_budget(tool_call.budget, review_budget)
            bundles, usage = self.inquiry_broker.resolve_requests(
                conn,
                book_id=book_id,
                requests=self._inquiry_requests(tool_call),
                budget=inquiry_budget,
            )
            evidence_items = self._evidence_items_from_bundles(
                bundles,
                max_context_chars=review_budget.max_context_chars,
            )
            trace = self._trace_from_bundles(tool_call=tool_call, bundles=bundles, usage=usage, budget=inquiry_budget)
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status=self._status_from_bundles(bundles),
                evidence_items=evidence_items,
                source_refs=self._source_refs_from_bundles(bundles),
                trace=trace,
            )
        except Exception as exc:
            return self._failed(tool_call, str(exc))

    def _inquiry_requests(self, tool_call: ReviewerToolCall) -> list[NarrativeInquiryRequest]:
        query = tool_call.query or tool_call.intent
        purpose = tool_call.reason_zh or tool_call.intent
        return [
            NarrativeInquiryRequest(
                request_id=f"{tool_call.tool_call_id}:scene-cards",
                request_type="narrative_scene_card_search",
                query=query,
                purpose=purpose or "定位与评审问题相关的关键场景卡片。",
                priority="high",
                expected_depth="index_card",
                metadata={"consumer": "reviewer", "tool_call_id": tool_call.tool_call_id},
            ),
            NarrativeInquiryRequest(
                request_id=f"{tool_call.tool_call_id}:outline-segments",
                request_type="story_detail",
                query=query,
                purpose=purpose or "定位与评审问题相关的历史剧情压缩段落。",
                priority="high",
                expected_depth="outline_segment",
                metadata={"consumer": "reviewer", "tool_call_id": tool_call.tool_call_id},
            ),
        ]

    def _inquiry_budget(self, data: Mapping[str, Any], review_budget: ReviewBudget) -> AnalyzerBudget:
        evidence_chars = int(data.get("max_evidence_chars_per_request") or min(2500, max(600, review_budget.max_context_chars // 4)))
        return AnalyzerBudget(
            max_rounds=1,
            max_requests_per_round=2,
            max_total_requests=2,
            max_raw_excerpt_requests=0,
            max_evidence_chars_per_request=evidence_chars,
            max_prompt_bytes=max(4096, review_budget.max_context_chars * 4),
        )

    def _evidence_items_from_bundles(
        self,
        bundles: Sequence[EvidenceBundle],
        *,
        max_context_chars: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        remaining = max(500, int(max_context_chars or 500))
        for bundle in bundles:
            bundle_prefix = {
                "source_type": "memory",
                "inquiry_request_id": bundle.request_id,
                "inquiry_request_type": bundle.request_type,
                "query": bundle.query,
                "status": bundle.status,
                "fact_status": bundle.fact_status,
            }
            for index, item in enumerate(bundle.evidence_items, start=1):
                payload = {
                    **bundle_prefix,
                    "evidence_id": f"{bundle.request_id}:evidence-{index:03d}",
                    "evidence": self._trim_mapping(item, limit=max(240, min(1200, remaining))),
                }
                remaining -= len(str(payload))
                if remaining < 0 and items:
                    return items
                items.append(payload)
            for index, excerpt in enumerate(bundle.excerpts, start=1):
                payload = {
                    **bundle_prefix,
                    "evidence_id": f"{bundle.request_id}:excerpt-{index:03d}",
                    "evidence_type": "raw_excerpt",
                    "evidence": self._trim_mapping(excerpt, limit=max(240, min(1200, remaining))),
                }
                remaining -= len(str(payload))
                if remaining < 0 and items:
                    return items
                items.append(payload)
        return items

    def _source_refs_from_bundles(self, bundles: Sequence[EvidenceBundle]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for bundle in bundles:
            for source in bundle.sources:
                source_id = str(
                    source.get("card_id")
                    or source.get("source_id")
                    or source.get("path")
                    or source.get("source_doc_range")
                    or bundle.request_id
                )
                key = (bundle.request_type, source_id)
                if key in seen:
                    continue
                seen.add(key)
                refs.append(
                    {
                        "source_type": "memory",
                        "source_id": source_id,
                        "label": str(source.get("card_type") or source.get("type") or bundle.request_type),
                    }
                )
        return refs

    def _trace_from_bundles(
        self,
        *,
        tool_call: ReviewerToolCall,
        bundles: Sequence[EvidenceBundle],
        usage: Mapping[str, int],
        budget: AnalyzerBudget,
    ) -> list[dict[str, Any]]:
        trace = [
            {
                "operation": "reviewer_memory_query",
                "query": tool_call.query,
                "source": "reviewer_agent",
                "broker": "NarrativeInquiryBroker",
                "request_types": [bundle.request_type for bundle in bundles],
                "usage": dict(usage),
                "budget": budget.to_dict(),
            }
        ]
        for bundle in bundles:
            trace.extend(bundle.trace)
        return trace

    def _status_from_bundles(self, bundles: Sequence[EvidenceBundle]) -> str:
        if not bundles:
            return "failed"
        statuses = {bundle.status for bundle in bundles}
        if statuses == {"failed"}:
            return "failed"
        if statuses == {"blocked"}:
            return "blocked"
        return "success"

    def _trim_mapping(self, data: Mapping[str, Any], *, limit: int) -> dict[str, Any]:
        payload = dict(data)
        for key in ("summary", "text", "content", "source_excerpt"):
            value = payload.get(key)
            if isinstance(value, str) and len(value) > limit:
                payload[key] = f"{value[:limit].rstrip()}..."
        return payload

    def _blocked(self, tool_call: ReviewerToolCall, error: str) -> ReviewerToolResult:
        return ReviewerToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool=tool_call.tool,
            status="blocked",
            trace=[{"operation": "policy_guard", "blocked": True, "reason": error}],
            error=error,
        )

    def _failed(self, tool_call: ReviewerToolCall, error: str) -> ReviewerToolResult:
        return ReviewerToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool=tool_call.tool,
            status="failed",
            trace=[{"operation": "reviewer_memory_query", "status": "failed", "error": error}],
            error=error,
        )


class ReviewerKBTool:
    def __init__(self, *, retrieval_facade: RetrievalFacade | None = None) -> None:
        self.retrieval_facade = retrieval_facade or RetrievalFacade()

    def retrieve(
        self,
        conn: sqlite3.Connection | None,
        *,
        book_id: str,
        tool_call: ReviewerToolCall,
        target_excerpt: str,
        context_policy: ReviewContextPolicy,
        review_budget: ReviewBudget,
    ) -> ReviewerToolResult:
        _ = book_id
        if not context_policy.allow_kb:
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="blocked",
                trace=[{"operation": "policy_guard", "blocked": True, "reason": "KB 查询未授权。"}],
                error="KB 查询未授权。",
            )
        if conn is None:
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="failed",
                trace=[{"operation": "reviewer_kb_retrieval", "status": "failed", "error": "KB 查询需要数据库连接。"}],
                error="KB 查询需要数据库连接。",
            )
        try:
            scene_brief = SceneBrief(
                scene_objective=tool_call.query or tool_call.intent,
                emotional_goal=str(tool_call.budget.get("emotional_goal") or ""),
                conflict_goal=str(tool_call.budget.get("conflict_goal") or ""),
                narrative_function=[str(item) for item in tool_call.budget.get("narrative_function", [])]
                if isinstance(tool_call.budget.get("narrative_function"), list)
                else [],
                emotion_mode=[str(item) for item in tool_call.budget.get("emotion_mode", [])]
                if isinstance(tool_call.budget.get("emotion_mode"), list)
                else [],
                style_need=[str(item) for item in tool_call.budget.get("style_need", [])]
                if isinstance(tool_call.budget.get("style_need"), list)
                else [],
                preferred_tags=[str(item) for item in tool_call.budget.get("preferred_tags", [])]
                if isinstance(tool_call.budget.get("preferred_tags"), list)
                else [],
            )
            result = self.retrieval_facade.retrieve_reference_fragments(
                conn,
                scene_brief=scene_brief,
                retrieval_context=RetrievalContext(),
                anchor_context=target_excerpt[: min(len(target_excerpt), review_budget.max_context_chars)],
                recent_window_summary=str(tool_call.budget.get("recent_window_summary") or ""),
                include_coarse_result=True,
                expand_reference_fragments=True,
            )
            payload = result.to_dict()
            refs = payload.get("reference_fragments") or []
            trace = [
                {
                    "operation": "reviewer_kb_retrieval",
                    "query": tool_call.query,
                    "selected_fragment_ids": payload.get("rerank_result", {}).get("selected_fragment_ids", []),
                    "source_scope": "creative_kb_read_only",
                    "truncation": {
                        "target_excerpt_chars": min(len(target_excerpt), review_budget.max_context_chars),
                        "strategy": "prefix_context_for_retrieval",
                    },
                }
            ]
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="success",
                evidence_items=[dict(item) for item in refs if isinstance(item, Mapping)],
                source_refs=[
                    {"source_type": "kb", "source_id": str(item.get("fragment_id") or ""), "label": str(item.get("source_path") or "")}
                    for item in refs
                    if isinstance(item, Mapping)
                ],
                trace=trace,
            )
        except Exception as exc:
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="failed",
                trace=[{"operation": "reviewer_kb_retrieval", "status": "failed", "error": str(exc)}],
                error=str(exc),
            )


class ReviewerArtifactTool:
    def __init__(self, *, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path.cwd()

    def read(
        self,
        *,
        tool_call: ReviewerToolCall,
        context_policy: ReviewContextPolicy,
    ) -> ReviewerToolResult:
        if not context_policy.allow_writer_artifacts:
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="blocked",
                trace=[{"operation": "policy_guard", "blocked": True, "reason": "Writer artifact 读取未授权。"}],
                error="Writer artifact 读取未授权。",
            )
        artifact_kind = str(tool_call.budget.get("artifact_kind") or "").strip()
        if artifact_kind and artifact_kind not in set(context_policy.allowed_artifact_kinds):
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="blocked",
                trace=[{"operation": "policy_guard", "blocked": True, "reason": f"artifact_kind 未授权: {artifact_kind}"}],
                error=f"artifact_kind 未授权: {artifact_kind}",
            )
        path_text = str(tool_call.budget.get("artifact_path") or tool_call.query or "").strip()
        if not path_text:
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="failed",
                trace=[{"operation": "artifact_read", "status": "failed", "error": "artifact_path is required"}],
                error="artifact_path is required",
            )
        path = Path(path_text)
        resolved = path if path.is_absolute() else self.repo_root / path
        try:
            text = resolved.read_text(encoding="utf-8")
        except Exception as exc:
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="failed",
                trace=[{"operation": "artifact_read", "status": "failed", "error": str(exc), "path": str(resolved)}],
                error=str(exc),
            )
        return ReviewerToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool=tool_call.tool,
            status="success",
            evidence_items=[{"path": str(resolved), "text": text}],
            source_refs=[{"source_type": "writer_artifact", "source_id": path_text, "label": str(resolved)}],
            trace=[{"operation": "artifact_read", "path": str(resolved), "chars": len(text), "source_scope": "authorized_artifact"}],
        )
