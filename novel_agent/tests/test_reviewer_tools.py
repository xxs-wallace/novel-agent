from __future__ import annotations

import sqlite3
from pathlib import Path

from novel_agent.app.reviewer.target_resolver import ReviewTargetResolver
from novel_agent.app.reviewer.tools import ReviewerArtifactTool, ReviewerKBTool, ReviewerMemoryTool
from novel_agent.app.schemas.creative_kb_schema import (
    CreativeKBRetrievalResult,
    ExpandedReferenceFragment,
    RerankResult,
)
from novel_agent.app.schemas.narrative_inquiry_schema import AnalyzerBudget, EvidenceBundle, NarrativeInquiryRequest
from novel_agent.app.schemas.narrative_memory_schema import MemoryQueryBudget, MemoryQueryState
from novel_agent.app.schemas.reviewer_schema import (
    ReviewBudget,
    ReviewContextPolicy,
    ReviewerToolCall,
    ReviewRequest,
    ReviewTarget,
)


class _FakeMemoryQueryService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def root_scan(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        query: str,
        budget: MemoryQueryBudget | None = None,
    ) -> MemoryQueryState:
        self.calls.append({"book_id": book_id, "query": query, "budget": budget})
        return MemoryQueryState(
            original_query=query,
            current_level="event_summary",
            current_candidates=[{"id": "event-summary-1", "level": "event_summary", "summary": "候选记忆"}],
            budget=budget or MemoryQueryBudget(),
            trace=[{"operation": "root_scan", "query": query, "candidate_ids": ["event-summary-1"]}],
        )


class _FakeRetrievalFacade:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def retrieve_reference_fragments(self, conn: sqlite3.Connection, **kwargs: object) -> CreativeKBRetrievalResult:
        self.calls.append(dict(kwargs))
        return CreativeKBRetrievalResult(
            rerank_result=RerankResult(selected_fragment_ids=["fragment-1"]),
            reference_fragments=[
                ExpandedReferenceFragment(
                    fragment_id="fragment-1",
                    doc_id="1",
                    source_path="/tmp/source.md",
                    source_excerpt="原作片段",
                    content_summary="相似氛围片段。",
                    style_profile_text="克制、低对白。",
                )
            ],
        )


class _FakeInquiryBroker:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve_requests(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        requests: list[NarrativeInquiryRequest],
        budget: AnalyzerBudget,
    ) -> tuple[list[EvidenceBundle], dict[str, int]]:
        self.calls.append({"book_id": book_id, "requests": requests, "budget": budget})
        return (
            [
                EvidenceBundle(
                    request_id=requests[0].request_id,
                    request_type=requests[0].request_type,
                    query=requests[0].query,
                    evidence_items=[{"card_id": "scene-card-1", "card_type": "narrative_scene", "summary": "关键场景"}],
                    sources=[{"card_id": "scene-card-1", "card_type": "narrative_scene"}],
                    trace=[{"operation": "narrative_index_search", "consumer": "reviewer"}],
                ),
                EvidenceBundle(
                    request_id=requests[1].request_id,
                    request_type=requests[1].request_type,
                    query=requests[1].query,
                    evidence_items=[{"page_id": "outline-segment-1", "page_type": "outline_segment", "summary": "连续剧情压缩"}],
                    sources=[{"path": "memory:outline_segment:outline-segment-1", "type": "outline_segment"}],
                    trace=[{"operation": "narrative_inquiry_outline_segment_scan"}],
                ),
            ],
            {"total_requests_used": 2, "raw_requests_used": 0},
        )


def _tool_call(tool: str) -> ReviewerToolCall:
    return ReviewerToolCall(
        tool_call_id=f"call-{tool}",
        tool=tool,
        intent="查询相关证据",
        query="人物关系状态",
    )


def test_reviewer_memory_tool_uses_narrative_inquiry_broker_scene_cards_and_outline_segments() -> None:
    fake_broker = _FakeInquiryBroker()
    tool = ReviewerMemoryTool(inquiry_broker=fake_broker)  # type: ignore[arg-type]
    conn = sqlite3.connect(":memory:")

    result = tool.query(
        conn,
        book_id="book-1",
        tool_call=_tool_call("memory_query"),
        context_policy=ReviewContextPolicy(purpose="writer_assist", allow_memory=True),
        review_budget=ReviewBudget(),
    )

    assert result.status == "success"
    request_types = [request.request_type for request in fake_broker.calls[0]["requests"]]  # type: ignore[index]
    assert request_types == ["narrative_scene_card_search", "story_detail"]
    assert result.evidence_items[0]["evidence"]["card_id"] == "scene-card-1"
    assert result.evidence_items[1]["evidence"]["page_type"] == "outline_segment"
    assert any(item["operation"] == "narrative_inquiry_outline_segment_scan" for item in result.trace)


def test_reviewer_memory_tool_blocks_unauthorized_memory_query() -> None:
    fake_service = _FakeMemoryQueryService()
    tool = ReviewerMemoryTool(query_service=fake_service)  # type: ignore[arg-type]

    result = tool.query(
        sqlite3.connect(":memory:"),
        book_id="book-1",
        tool_call=_tool_call("memory_query"),
        context_policy=ReviewContextPolicy(purpose="user_review", allow_memory=False),
        review_budget=ReviewBudget(),
    )

    assert result.status == "blocked"
    assert fake_service.calls == []
    assert "未授权" in result.error


def test_reviewer_kb_tool_uses_read_only_retrieval_facade() -> None:
    facade = _FakeRetrievalFacade()
    tool = ReviewerKBTool(retrieval_facade=facade)  # type: ignore[arg-type]

    result = tool.retrieve(
        sqlite3.connect(":memory:"),
        book_id="book-1",
        tool_call=_tool_call("kb_retrieval"),
        target_excerpt="当前草稿片段",
        context_policy=ReviewContextPolicy(purpose="writer_assist", allow_kb=True),
        review_budget=ReviewBudget(),
    )

    assert result.status == "success"
    assert facade.calls
    assert result.evidence_items[0]["fragment_id"] == "fragment-1"
    assert result.source_refs[0]["source_type"] == "kb"
    assert result.trace[0]["source_scope"] == "creative_kb_read_only"


def test_reviewer_artifact_tool_blocks_disallowed_artifact_kind(tmp_path: Path) -> None:
    artifact = tmp_path / "draft.md"
    artifact.write_text("草稿", encoding="utf-8")
    tool = ReviewerArtifactTool(repo_root=tmp_path)
    call = ReviewerToolCall(
        tool_call_id="call-artifact",
        tool="artifact_read",
        intent="读取 artifact",
        query=str(artifact),
        budget={"artifact_kind": "reference_truth", "artifact_path": str(artifact)},
    )

    result = tool.read(
        tool_call=call,
        context_policy=ReviewContextPolicy(
            purpose="writer_assist",
            allow_writer_artifacts=True,
            allowed_artifact_kinds=["draft"],
        ),
    )

    assert result.status == "blocked"
    assert "未授权" in result.error


def test_review_target_resolver_supports_text_document_and_artifact(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE documents (
            doc_id INTEGER,
            book_id TEXT,
            content TEXT,
            document_title TEXT,
            document_title_index INTEGER,
            source_path TEXT,
            source_start_offset INTEGER,
            source_end_offset INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO documents VALUES (1, 'book-1', '数据库正文', '第一章', 1, '/tmp/source.md', 0, 4)"
    )
    artifact = tmp_path / "artifact.md"
    artifact.write_text("artifact 正文", encoding="utf-8")
    request = ReviewRequest(
        review_request_id="req-1",
        book_id="book-1",
        target=ReviewTarget(
            target_id="target-1",
            target_type="draft",
            text="inline 正文",
            document_ids=["1"],
            artifact_path=str(artifact),
            source_refs=[{"source_type": "document", "source_id": "1", "label": "第一章"}],
        ),
        reviewer_ids=["unit_runtime_reviewer"],
        context_policy=ReviewContextPolicy(purpose="writer_assist"),
        budget=ReviewBudget(max_target_chars=200),
        created_at="2026-05-20T10:00:00Z",
    )

    resolved = ReviewTargetResolver(repo_root=tmp_path).resolve(request, conn=conn)

    assert "inline 正文" in resolved.resolved_text
    assert "数据库正文" in resolved.resolved_text
    assert "artifact 正文" in resolved.resolved_text
    assert resolved.document_refs[0]["document_id"] == "1"
    assert resolved.artifact_refs[0]["path"] == str(artifact)
    source_types = [item["source_type"] for item in resolved.source_refs]
    assert "document" not in source_types
    assert "target_text" in source_types
    assert "writer_artifact" in source_types
