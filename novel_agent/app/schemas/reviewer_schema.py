from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1.0"

TARGET_TYPES = {"draft", "synopsis", "outline", "chapter_brief", "planning_note", "raw_text", "source_chapter"}
PURPOSES = {"writer_assist", "benchmark", "user_review", "diagnostic"}
LEAKAGE_GUARDS = {"prefix_only", "benchmark_authorized_reference", "user_authorized", "none"}
TOOLS = {"memory_query", "kb_retrieval", "artifact_read"}
TOOL_RESULT_STATUSES = {"success", "skipped", "blocked", "failed"}
EVIDENCE_SOURCE_TYPES = {"target_text", "memory", "kb", "writer_artifact", "reference_truth", "user_input"}
FINDING_SEVERITIES = {"critical", "major", "minor", "note"}
REPORT_STATUSES = {"success", "failed", "needs_model", "skipped"}
SCORE_USAGE = "reference_only"

_SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "note": 3}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object) -> str:
    return str(value or "").strip()


def _schema(value: object) -> str:
    normalized = _text(value) or SCHEMA_VERSION
    if normalized != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    return normalized


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _enum(value: object, allowed: set[str], *, field_name: str) -> str:
    normalized = _text(value)
    if normalized not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
    return normalized


def _score(value: object, *, field_name: str = "score") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer within 0-100")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer within 0-100") from exc
    if number < 0 or number > 100:
        raise ValueError(f"{field_name} must be within 0-100")
    return number


def _confidence(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(number, 1.0))


def _contains_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _require_chinese(field_name: str, value: object) -> str:
    text = _text(value)
    if not text or not _contains_chinese(text):
        raise ValueError(f"{field_name} must be non-empty Chinese text")
    return text


@dataclass(slots=True)
class ReviewTarget:
    target_id: str
    target_type: str
    schema_version: str = SCHEMA_VERSION
    text: str = ""
    document_ids: list[str] = field(default_factory=list)
    artifact_id: str = ""
    artifact_path: str = ""
    chapter_id: str = ""
    range_hint: dict[str, Any] = field(default_factory=dict)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.target_id = _text(self.target_id)
        self.target_type = _enum(self.target_type, TARGET_TYPES, field_name="target_type")
        self.text = _text(self.text)
        self.document_ids = _string_list(self.document_ids)
        self.artifact_id = _text(self.artifact_id)
        self.artifact_path = _text(self.artifact_path)
        self.chapter_id = _text(self.chapter_id)
        self.range_hint = _dict(self.range_hint)
        self.source_refs = _dict_list(self.source_refs)
        self.metadata = _dict(self.metadata)
        if not self.target_id:
            raise ValueError("target_id is required")
        if not self.text and not self.document_ids and not self.artifact_path:
            raise ValueError("ReviewTarget requires at least one of text, document_ids, or artifact_path")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewTarget":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewContextPolicy:
    purpose: str
    schema_version: str = SCHEMA_VERSION
    allow_memory: bool = True
    allow_kb: bool = True
    allow_writer_artifacts: bool = True
    allow_reference_truth: bool = False
    allowed_artifact_kinds: list[str] = field(default_factory=lambda: ["chapter_brief", "draft", "synopsis", "outline"])
    leakage_guard: str = "prefix_only"
    notes: str = ""

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.purpose = _enum(self.purpose, PURPOSES, field_name="purpose")
        self.allow_memory = bool(self.allow_memory)
        self.allow_kb = bool(self.allow_kb)
        self.allow_writer_artifacts = bool(self.allow_writer_artifacts)
        self.allow_reference_truth = bool(self.allow_reference_truth)
        self.allowed_artifact_kinds = _string_list(self.allowed_artifact_kinds)
        self.leakage_guard = _enum(self.leakage_guard, LEAKAGE_GUARDS, field_name="leakage_guard")
        self.notes = _text(self.notes)
        if self.purpose != "benchmark" and self.allow_reference_truth:
            raise ValueError("allow_reference_truth is only allowed when purpose is benchmark")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewContextPolicy":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewBudget:
    schema_version: str = SCHEMA_VERSION
    max_model_calls: int = 6
    max_tool_calls: int = 8
    max_memory_query_rounds: int = 4
    max_kb_query_rounds: int = 3
    max_target_chars: int = 12000
    max_context_chars: int = 16000
    max_findings: int = 12
    json_repair_attempts: int = 1

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.max_model_calls = max(1, int(self.max_model_calls or 1))
        self.max_tool_calls = max(0, int(self.max_tool_calls or 0))
        self.max_memory_query_rounds = max(0, int(self.max_memory_query_rounds or 0))
        self.max_kb_query_rounds = max(0, int(self.max_kb_query_rounds or 0))
        self.max_target_chars = max(200, int(self.max_target_chars or 200))
        self.max_context_chars = max(500, int(self.max_context_chars or 500))
        self.max_findings = max(0, int(self.max_findings or 0))
        self.json_repair_attempts = max(0, int(self.json_repair_attempts or 0))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewBudget":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewRequest:
    review_request_id: str
    book_id: str
    target: ReviewTarget
    reviewer_ids: list[str]
    context_policy: ReviewContextPolicy
    budget: ReviewBudget
    created_at: str
    schema_version: str = SCHEMA_VERSION
    user_focus: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.review_request_id = _text(self.review_request_id)
        self.book_id = _text(self.book_id)
        self.target = self.target if isinstance(self.target, ReviewTarget) else ReviewTarget.from_dict(_dict(self.target))
        self.reviewer_ids = _string_list(self.reviewer_ids)
        self.context_policy = (
            self.context_policy
            if isinstance(self.context_policy, ReviewContextPolicy)
            else ReviewContextPolicy.from_dict(_dict(self.context_policy))
        )
        self.budget = self.budget if isinstance(self.budget, ReviewBudget) else ReviewBudget.from_dict(_dict(self.budget))
        self.created_at = _text(self.created_at)
        self.user_focus = _text(self.user_focus)
        self.metadata = _dict(self.metadata)
        if not self.review_request_id:
            raise ValueError("review_request_id is required")
        if not self.book_id:
            raise ValueError("book_id is required")
        if not self.reviewer_ids:
            raise ValueError("reviewer_ids must be explicit; runtime does not guess a default suite")
        if not self.created_at:
            raise ValueError("created_at is required")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target"] = self.target.to_dict()
        payload["context_policy"] = self.context_policy.to_dict()
        payload["budget"] = self.budget.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewRequest":
        return cls(**dict(data))


@dataclass(slots=True)
class ResolvedReviewTarget:
    target_id: str
    target_type: str
    resolved_text: str
    schema_version: str = SCHEMA_VERSION
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    document_refs: list[dict[str, Any]] = field(default_factory=list)
    truncation: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.target_id = _text(self.target_id)
        self.target_type = _enum(self.target_type, TARGET_TYPES, field_name="target_type")
        self.resolved_text = _text(self.resolved_text)
        self.source_refs = _dict_list(self.source_refs)
        self.artifact_refs = _dict_list(self.artifact_refs)
        self.document_refs = _dict_list(self.document_refs)
        self.truncation = _dict(self.truncation) or {
            "truncated": False,
            "strategy": "",
            "original_chars": len(self.resolved_text),
            "resolved_chars": len(self.resolved_text),
        }
        if not self.target_id:
            raise ValueError("target_id is required")
        if not self.resolved_text:
            raise ValueError("resolved_text is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResolvedReviewTarget":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewPlan:
    reviewer_id: str
    target_id: str
    dimensions: list[str]
    schema_version: str = SCHEMA_VERSION
    initial_risks: list[str] = field(default_factory=list)
    tool_requests: list[dict[str, Any]] = field(default_factory=list)
    can_judge_without_context: bool = True
    notes_zh: str = ""

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.reviewer_id = _text(self.reviewer_id)
        self.target_id = _text(self.target_id)
        self.dimensions = _string_list(self.dimensions)
        self.initial_risks = _string_list(self.initial_risks)
        self.tool_requests = _dict_list(self.tool_requests)
        self.can_judge_without_context = bool(self.can_judge_without_context)
        self.notes_zh = _text(self.notes_zh)
        if not self.reviewer_id:
            raise ValueError("reviewer_id is required")
        if not self.target_id:
            raise ValueError("target_id is required")
        if not self.dimensions:
            raise ValueError("dimensions are required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewPlan":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewerToolCall:
    tool_call_id: str
    tool: str
    intent: str
    query: str
    schema_version: str = SCHEMA_VERSION
    budget: dict[str, Any] = field(default_factory=dict)
    reason_zh: str = ""
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.tool_call_id = _text(self.tool_call_id)
        self.tool = _enum(self.tool, TOOLS, field_name="tool")
        self.intent = _text(self.intent)
        self.query = _text(self.query) or self.intent
        self.budget = _dict(self.budget)
        self.reason_zh = _text(self.reason_zh)
        self.created_at = _text(self.created_at) or utc_now()
        if not self.tool_call_id:
            raise ValueError("tool_call_id is required")
        if not self.intent:
            raise ValueError("intent is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewerToolCall":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewerToolResult:
    tool_call_id: str
    tool: str
    status: str
    schema_version: str = SCHEMA_VERSION
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.tool_call_id = _text(self.tool_call_id)
        self.tool = _enum(self.tool, TOOLS, field_name="tool")
        self.status = _enum(self.status, TOOL_RESULT_STATUSES, field_name="status")
        self.evidence_items = _dict_list(self.evidence_items)
        self.source_refs = _dict_list(self.source_refs)
        self.trace = _dict_list(self.trace)
        self.error = _text(self.error)
        if not self.tool_call_id:
            raise ValueError("tool_call_id is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewerToolResult":
        return cls(**dict(data))


@dataclass(slots=True)
class EvidenceRef:
    evidence_id: str
    source_type: str
    source_id: str
    quote: str = ""
    summary_zh: str = ""
    location: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.evidence_id = _text(self.evidence_id)
        self.source_type = _enum(self.source_type, EVIDENCE_SOURCE_TYPES, field_name="source_type")
        self.source_id = _text(self.source_id)
        self.quote = _text(self.quote)
        self.summary_zh = _text(self.summary_zh)
        self.location = _dict(self.location)
        if not self.evidence_id:
            raise ValueError("evidence_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceRef":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewFinding:
    finding_id: str
    severity: str
    category: str
    message_zh: str
    evidence_refs: list[str] = field(default_factory=list)
    suggestion_zh: str = ""
    confidence: float = 0.0

    def __post_init__(self) -> None:
        self.finding_id = _text(self.finding_id)
        self.severity = _enum(self.severity, FINDING_SEVERITIES, field_name="severity")
        self.category = _text(self.category)
        self.message_zh = _require_chinese("message_zh", self.message_zh)
        self.evidence_refs = _string_list(self.evidence_refs)
        self.suggestion_zh = _text(self.suggestion_zh)
        self.confidence = _confidence(self.confidence)
        if not self.finding_id:
            raise ValueError("finding_id is required")
        if not self.category:
            raise ValueError("category is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewFinding":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewReport:
    review_report_id: str
    review_request_id: str
    target_id: str
    target_type: str
    reviewer_id: str
    reviewer_version: str
    status: str
    summary_zh: str
    model_id: str
    schema_version: str = SCHEMA_VERSION
    score: int | None = None
    score_usage: str = SCORE_USAGE
    dimension_scores: dict[str, int] = field(default_factory=dict)
    findings: list[ReviewFinding] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    suggested_revision_focus: list[str] = field(default_factory=list)
    confidence: float = 0.0
    memory_query_trace: list[dict[str, Any]] = field(default_factory=list)
    kb_query_trace: list[dict[str, Any]] = field(default_factory=list)
    artifact_trace: list[dict[str, Any]] = field(default_factory=list)
    self_check: dict[str, Any] = field(default_factory=dict)
    raw_model_response_path: str = ""
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.review_report_id = _text(self.review_report_id)
        self.review_request_id = _text(self.review_request_id)
        self.target_id = _text(self.target_id)
        self.target_type = _enum(self.target_type, TARGET_TYPES, field_name="target_type")
        self.reviewer_id = _text(self.reviewer_id)
        self.reviewer_version = _text(self.reviewer_version)
        self.status = _enum(self.status, REPORT_STATUSES, field_name="status")
        self.summary_zh = _require_chinese("summary_zh", self.summary_zh)
        self.model_id = _text(self.model_id)
        if self.score_usage != SCORE_USAGE:
            raise ValueError("score_usage must be reference_only")
        if self.score is not None:
            self.score = _score(self.score)
        if self.status == "success":
            if self.score is None:
                raise ValueError("score is required when status is success")
            if not self.model_id:
                raise ValueError("model_id is required when status is success")
        elif self.score is not None:
            raise ValueError("status != success must not provide a formal score")
        self.dimension_scores = {str(key): _score(value, field_name=f"dimension_scores.{key}") for key, value in _dict(self.dimension_scores).items()}
        self.findings = [
            item if isinstance(item, ReviewFinding) else ReviewFinding.from_dict(_dict(item))
            for item in self.findings
            if isinstance(item, (ReviewFinding, Mapping))
        ]
        self.findings.sort(key=lambda item: _SEVERITY_RANK[item.severity])
        self.evidence_refs = [
            item if isinstance(item, EvidenceRef) else EvidenceRef.from_dict(_dict(item))
            for item in self.evidence_refs
            if isinstance(item, (EvidenceRef, Mapping))
        ]
        self.suggested_revision_focus = _string_list(self.suggested_revision_focus)
        self.confidence = _confidence(self.confidence)
        self.memory_query_trace = _dict_list(self.memory_query_trace)
        self.kb_query_trace = _dict_list(self.kb_query_trace)
        self.artifact_trace = _dict_list(self.artifact_trace)
        self.self_check = _dict(self.self_check)
        self.raw_model_response_path = _text(self.raw_model_response_path)
        self.created_at = _text(self.created_at) or utc_now()
        self.metadata = _dict(self.metadata)
        if not all([self.review_report_id, self.review_request_id, self.target_id, self.reviewer_id, self.reviewer_version]):
            raise ValueError("review report ids and reviewer metadata are required")
        if "quality_decision" in self.metadata or "verdict" in self.metadata:
            raise ValueError("ReviewReport must not contain quality verdict fields")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [item.to_dict() for item in self.findings]
        payload["evidence_refs"] = [item.to_dict() for item in self.evidence_refs]
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewReport":
        if "quality_decision" in data or "verdict" in data:
            raise ValueError("ReviewReport must not contain quality verdict fields")
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewSuiteReport:
    suite_report_id: str
    review_request_id: str
    target_id: str
    status: str
    summary_zh: str
    schema_version: str = SCHEMA_VERSION
    overall_score: int | None = None
    score_usage: str = SCORE_USAGE
    reviewer_reports: list[ReviewReport] = field(default_factory=list)
    top_findings: list[ReviewFinding] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.suite_report_id = _text(self.suite_report_id)
        self.review_request_id = _text(self.review_request_id)
        self.target_id = _text(self.target_id)
        self.status = _enum(self.status, REPORT_STATUSES, field_name="status")
        self.summary_zh = _require_chinese("summary_zh", self.summary_zh)
        if self.score_usage != SCORE_USAGE:
            raise ValueError("score_usage must be reference_only")
        if self.overall_score is not None:
            self.overall_score = _score(self.overall_score, field_name="overall_score")
        if self.status != "success" and self.overall_score is not None:
            raise ValueError("status != success must not provide an overall_score")
        self.reviewer_reports = [
            item if isinstance(item, ReviewReport) else ReviewReport.from_dict(_dict(item))
            for item in self.reviewer_reports
            if isinstance(item, (ReviewReport, Mapping))
        ]
        self.top_findings = [
            item if isinstance(item, ReviewFinding) else ReviewFinding.from_dict(_dict(item))
            for item in self.top_findings
            if isinstance(item, (ReviewFinding, Mapping))
        ]
        self.top_findings.sort(key=lambda item: _SEVERITY_RANK[item.severity])
        self.created_at = _text(self.created_at) or utc_now()
        self.metadata = _dict(self.metadata)
        if not all([self.suite_report_id, self.review_request_id, self.target_id]):
            raise ValueError("suite report ids are required")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reviewer_reports"] = [item.to_dict() for item in self.reviewer_reports]
        payload["top_findings"] = [item.to_dict() for item in self.top_findings]
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewSuiteReport":
        return cls(**dict(data))


@dataclass(slots=True)
class ReviewerManifest:
    reviewer_id: str
    reviewer_version: str
    display_name_zh: str
    supported_target_types: list[str]
    dimensions: list[str]
    requires_model: bool
    allowed_tools: list[str]
    schema_version: str = SCHEMA_VERSION
    default_budget: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.schema_version = _schema(self.schema_version)
        self.reviewer_id = _text(self.reviewer_id)
        self.reviewer_version = _text(self.reviewer_version)
        self.display_name_zh = _require_chinese("display_name_zh", self.display_name_zh)
        self.supported_target_types = _string_list(self.supported_target_types)
        unknown_targets = set(self.supported_target_types) - TARGET_TYPES
        if unknown_targets:
            raise ValueError(f"unsupported target types: {sorted(unknown_targets)}")
        self.dimensions = _string_list(self.dimensions)
        self.requires_model = bool(self.requires_model)
        self.allowed_tools = _string_list(self.allowed_tools)
        unknown_tools = set(self.allowed_tools) - TOOLS
        if unknown_tools:
            raise ValueError(f"unsupported reviewer tools: {sorted(unknown_tools)}")
        self.default_budget = _dict(self.default_budget)
        self.metadata = _dict(self.metadata)
        if not self.requires_model:
            raise ValueError("formal ReviewerManifest.requires_model must be true")
        marker = f"{self.reviewer_id} {self.metadata.get('kind', '')}".lower()
        if any(token in marker for token in ("fake", "baseline", "dry_run", "dry-run")):
            raise ValueError("fake, dry-run, and baseline reviewers cannot be formal manifests")
        if not all([self.reviewer_id, self.reviewer_version, self.supported_target_types, self.dimensions]):
            raise ValueError("reviewer_id, reviewer_version, supported_target_types, and dimensions are required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewerManifest":
        return cls(**dict(data))
