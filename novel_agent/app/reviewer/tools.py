from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

from ..schemas.creative_kb_schema import SceneBrief
from ..schemas.narrative_memory_schema import MemoryQueryBudget
from ..schemas.orchestration_schema import RetrievalContext
from ..schemas.reviewer_schema import (
    ReviewBudget,
    ReviewContextPolicy,
    ReviewerToolCall,
    ReviewerToolResult,
)
from ..services.narrative_memory_query_service import NarrativeMemoryQueryService
from ..services.retrieval_facade import RetrievalFacade


class ReviewerMemoryTool:
    def __init__(self, *, query_service: NarrativeMemoryQueryService | None = None, repo_root: Path | None = None) -> None:
        self.query_service = query_service or NarrativeMemoryQueryService(repo_root=repo_root or Path.cwd())

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
            budget = self._memory_budget(tool_call.budget, review_budget)
            state = self.query_service.root_scan(conn, book_id=book_id, query=tool_call.query, budget=budget)
            trace = [
                {"operation": "reviewer_memory_query", "query": tool_call.query, "source": "reviewer_agent"},
                *state.trace,
            ]
            return ReviewerToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool=tool_call.tool,
                status="success",
                evidence_items=state.current_candidates,
                source_refs=[{"source_type": "memory", "source_id": item.get("id", ""), "label": item.get("level", "")} for item in state.current_candidates],
                trace=trace,
            )
        except Exception as exc:
            return self._failed(tool_call, str(exc))

    def _memory_budget(self, data: Mapping[str, Any], review_budget: ReviewBudget) -> MemoryQueryBudget:
        return MemoryQueryBudget(
            max_root_candidates=int(data.get("max_root_candidates") or min(8, max(1, review_budget.max_context_chars // 2000))),
            max_child_candidates=int(data.get("max_child_candidates") or 12),
            max_path_context_chars=int(data.get("max_path_context_chars") or 1600),
            max_candidate_chars=int(data.get("max_candidate_chars") or 2400),
            max_trace_items=int(data.get("max_trace_items") or 80),
            excerpt_budget=int(data.get("excerpt_budget") or 1200),
        )

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
