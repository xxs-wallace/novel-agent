from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContinuityIssue:
    type: str
    severity: str
    message: str
    span: tuple[int, int] | None = None
    quote: str | None = None
    suggested_fix: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContinuityIssue":
        raw_span = data.get("span")
        span: tuple[int, int] | None = None
        if isinstance(raw_span, (list, tuple)) and len(raw_span) == 2:
            try:
                a = int(raw_span[0])
                b = int(raw_span[1])
                if a >= 0 and b >= a:
                    span = (a, b)
            except (TypeError, ValueError):
                span = None
        quote = data.get("quote")
        suggested_fix = data.get("suggested_fix")
        return cls(
            type=str(data.get("type") or ""),
            severity=str(data.get("severity") or ""),
            message=str(data.get("message") or ""),
            span=span,
            quote=str(quote) if quote is not None else None,
            suggested_fix=str(suggested_fix) if suggested_fix is not None else None,
        )


@dataclass(frozen=True, slots=True)
class ContinuityReport:
    issues: list[ContinuityIssue] = field(default_factory=list)
    blocked: bool = False
    summary: str = ""
    relation_state_gate: dict[str, Any] = field(default_factory=dict)
    planned_character_gate: dict[str, Any] = field(default_factory=dict)
    state_delta: dict[str, Any] = field(default_factory=dict)
    canon_ready: bool = False
    review_decision_status: str = ""
    accepted_for_writeback: bool = False
    writeback_blocked_reason: str = ""
    review_scope: str = ""
    evidence_sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [i.to_dict() for i in self.issues],
            "blocked": self.blocked,
            "summary": self.summary,
            "relation_state_gate": dict(self.relation_state_gate),
            "planned_character_gate": dict(self.planned_character_gate),
            "state_delta": dict(self.state_delta),
            "canon_ready": self.canon_ready,
            "review_decision_status": self.review_decision_status,
            "accepted_for_writeback": self.accepted_for_writeback,
            "writeback_blocked_reason": self.writeback_blocked_reason,
            "review_scope": self.review_scope,
            "evidence_sources": [dict(item) for item in self.evidence_sources],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContinuityReport":
        issues_raw = data.get("issues") or []
        issues: list[ContinuityIssue] = []
        if isinstance(issues_raw, list):
            for it in issues_raw:
                if isinstance(it, dict):
                    issues.append(ContinuityIssue.from_dict(it))
        relation_state_gate = data.get("relation_state_gate")
        planned_character_gate = data.get("planned_character_gate")
        state_delta = data.get("state_delta")
        evidence_sources_raw = data.get("evidence_sources") or []
        evidence_sources = [dict(item) for item in evidence_sources_raw if isinstance(item, dict)]
        return cls(
            issues=issues,
            blocked=bool(data.get("blocked", False)),
            summary=str(data.get("summary") or ""),
            relation_state_gate=dict(relation_state_gate) if isinstance(relation_state_gate, dict) else {},
            planned_character_gate=dict(planned_character_gate) if isinstance(planned_character_gate, dict) else {},
            state_delta=dict(state_delta) if isinstance(state_delta, dict) else {},
            canon_ready=bool(data.get("canon_ready", False)),
            review_decision_status=str(data.get("review_decision_status") or ""),
            accepted_for_writeback=bool(data.get("accepted_for_writeback", False)),
            writeback_blocked_reason=str(data.get("writeback_blocked_reason") or ""),
            review_scope=str(data.get("review_scope") or ""),
            evidence_sources=evidence_sources,
        )
