from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .creative_kb_schema import SceneBrief


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list | tuple | set):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


KBReviewDecision = Literal["pass", "borderline", "fail"]
KB_REVIEW_DECISIONS = {"pass", "borderline", "fail"}


def _clamp_score(value: object) -> float:
    try:
        score = float(value or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return round(max(0.0, min(1.0, score)), 4)


def _decision_for_score(score: float) -> str:
    if score >= 0.60:
        return "pass"
    if score >= 0.45:
        return "borderline"
    return "fail"


def _normalize_decision(value: object, *, score: float) -> KBReviewDecision:
    decision = _normalize_text(value).lower()
    if decision not in KB_REVIEW_DECISIONS:
        decision = _decision_for_score(score)
    return decision  # type: ignore[return-value]


def _normalize_checks(value: object, *, allowed_names: tuple[str, ...]) -> dict[str, str]:
    payload = value if isinstance(value, dict) else {}
    checks: dict[str, str] = {}
    for name in allowed_names:
        raw_value = payload.get(name)
        status = ""
        if isinstance(raw_value, dict):
            status = _normalize_text(raw_value.get("status")).lower()
            if status not in KB_REVIEW_DECISIONS:
                status = _decision_for_score(_clamp_score(raw_value.get("score")))
        else:
            status = _normalize_text(raw_value).lower()
        if status not in KB_REVIEW_DECISIONS:
            status = "borderline"
        checks[name] = status
    return checks


FRAGMENT_CARD_REVIEW_CHECKS = (
    "faithfulness",
    "retrievability",
    "narrative_function",
    "emotion_mechanism",
    "relationship_facts",
    "style_transferability",
    "context_dependency_risk",
)

CLUSTER_REVIEW_CHECKS = (
    "near_duplicate_fit",
    "false_merge_risk",
    "representative_quality",
)

RETRIEVAL_REVIEW_CHECKS = (
    "top1_beats_decoys",
    "selected_fragments_match_scene_brief",
    "scene_function_fit",
    "emotion_mechanism_fit",
    "relationship_state_fit",
    "style_reference_value",
    "transferability",
    "cluster_diversity",
    "context_dependency_risk",
    "negative_transfer_risk",
)

WRITER_AB_VARIANTS = ("kb_enabled", "kb_disabled", "kb_random", "kb_oracle")
WRITER_AB_REQUIRED_VARIANTS = ("kb_enabled", "kb_disabled", "kb_random")
WRITER_AB_WINNERS = (*WRITER_AB_VARIANTS, "tie")
WRITER_AB_REVIEW_CHECKS = (
    "synopsis_coverage",
    "recent_window_coherence",
    "emotion_mechanism_quality",
    "relationship_state_fit",
    "style_stability",
    "negative_transfer_from_references",
)


@dataclass(slots=True)
class KBFragmentCardReviewReport:
    fragment_id: str
    doc_id: str
    decision: KBReviewDecision
    score: float
    summary: str
    checks: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.fragment_id = _normalize_text(self.fragment_id)
        self.doc_id = _normalize_text(self.doc_id)
        self.score = _clamp_score(self.score)
        self.decision = _normalize_decision(self.decision, score=self.score)
        self.summary = _normalize_text(self.summary)
        self.checks = _normalize_checks(self.checks, allowed_names=FRAGMENT_CARD_REVIEW_CHECKS)
        self.issues = _normalize_string_list(self.issues)
        if not self.fragment_id:
            raise ValueError("KBFragmentCardReviewReport.fragment_id is required")
        if not self.doc_id:
            raise ValueError("KBFragmentCardReviewReport.doc_id is required")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "KBFragmentCardReviewReport":
        checks = payload.get("checks")
        return cls(
            fragment_id=payload.get("fragment_id", ""),
            doc_id=payload.get("doc_id", ""),
            decision=payload.get("decision", "fail"),  # type: ignore[arg-type]
            score=payload.get("score", 0.0),
            summary=payload.get("summary", ""),
            checks=dict(checks) if isinstance(checks, dict) else {},
            issues=_normalize_issue_list(payload.get("issues")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "doc_id": self.doc_id,
            "decision": self.decision,
            "score": self.score,
            "summary": self.summary,
            "checks": dict(self.checks),
            "issues": list(self.issues),
        }


@dataclass(slots=True)
class KBClusterReviewReport:
    cluster_id: str
    representative_fragment_id: str
    member_fragment_ids: list[str]
    decision: KBReviewDecision
    score: float
    summary: str
    checks: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cluster_id = _normalize_text(self.cluster_id)
        self.representative_fragment_id = _normalize_text(self.representative_fragment_id)
        self.member_fragment_ids = _normalize_string_list(self.member_fragment_ids)
        self.score = _clamp_score(self.score)
        self.decision = _normalize_decision(self.decision, score=self.score)
        self.summary = _normalize_text(self.summary)
        self.checks = _normalize_checks(self.checks, allowed_names=CLUSTER_REVIEW_CHECKS)
        self.issues = _normalize_string_list(self.issues)
        if not self.cluster_id:
            raise ValueError("KBClusterReviewReport.cluster_id is required")
        if not self.representative_fragment_id:
            raise ValueError("KBClusterReviewReport.representative_fragment_id is required")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "KBClusterReviewReport":
        checks = payload.get("checks")
        return cls(
            cluster_id=payload.get("cluster_id", ""),
            representative_fragment_id=payload.get("representative_fragment_id", ""),
            member_fragment_ids=_normalize_string_list(payload.get("member_fragment_ids")),
            decision=payload.get("decision", "fail"),  # type: ignore[arg-type]
            score=payload.get("score", 0.0),
            summary=payload.get("summary", ""),
            checks=dict(checks) if isinstance(checks, dict) else {},
            issues=_normalize_issue_list(payload.get("issues")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "representative_fragment_id": self.representative_fragment_id,
            "member_fragment_ids": list(self.member_fragment_ids),
            "decision": self.decision,
            "score": self.score,
            "summary": self.summary,
            "checks": dict(self.checks),
            "issues": list(self.issues),
        }


@dataclass(slots=True)
class KBRetrievalReviewReport:
    case_id: str
    decision: KBReviewDecision
    score: float
    summary: str
    checks: dict[str, str] = field(default_factory=dict)
    selected_fragment_ids: list[str] = field(default_factory=list)
    decoy_fragment_ids: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.case_id = _normalize_text(self.case_id)
        self.score = _clamp_score(self.score)
        self.decision = _normalize_decision(self.decision, score=self.score)
        self.summary = _normalize_text(self.summary)
        self.checks = _normalize_checks(self.checks, allowed_names=RETRIEVAL_REVIEW_CHECKS)
        self.selected_fragment_ids = _normalize_string_list(self.selected_fragment_ids)
        self.decoy_fragment_ids = _normalize_string_list(self.decoy_fragment_ids)
        self.issues = _normalize_string_list(self.issues)
        if not self.case_id:
            raise ValueError("KBRetrievalReviewReport.case_id is required")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "KBRetrievalReviewReport":
        checks = payload.get("checks")
        return cls(
            case_id=payload.get("case_id", ""),
            decision=payload.get("decision", "fail"),  # type: ignore[arg-type]
            score=payload.get("score", 0.0),
            summary=payload.get("summary", ""),
            checks=dict(checks) if isinstance(checks, dict) else {},
            selected_fragment_ids=_normalize_string_list(payload.get("selected_fragment_ids")),
            decoy_fragment_ids=_normalize_string_list(payload.get("decoy_fragment_ids")),
            issues=_normalize_issue_list(payload.get("issues")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "decision": self.decision,
            "score": self.score,
            "summary": self.summary,
            "checks": dict(self.checks),
            "selected_fragment_ids": list(self.selected_fragment_ids),
            "decoy_fragment_ids": list(self.decoy_fragment_ids),
            "issues": list(self.issues),
        }


@dataclass(slots=True)
class KBWriterABReport:
    decision: KBReviewDecision
    score: float
    winner: str
    variant_scores: dict[str, float]
    negative_transfer_issues: list[str]
    summary: str = ""
    checks: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.score = _clamp_score(self.score)
        self.decision = _normalize_decision(self.decision, score=self.score)
        self.variant_scores = _normalize_score_map(self.variant_scores)
        self.winner = _normalize_text(self.winner).lower()
        if self.winner not in WRITER_AB_WINNERS:
            self.winner = self._winner_from_scores()
        self.negative_transfer_issues = _normalize_string_list(self.negative_transfer_issues)
        self.summary = _normalize_text(self.summary)
        self.checks = _normalize_checks(self.checks, allowed_names=WRITER_AB_REVIEW_CHECKS)
        self.issues = _normalize_string_list(self.issues)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "KBWriterABReport":
        checks = payload.get("checks")
        return cls(
            decision=payload.get("decision", "fail"),  # type: ignore[arg-type]
            score=payload.get("score", 0.0),
            winner=payload.get("winner", ""),
            variant_scores=_normalize_score_map(payload.get("variant_scores")),
            negative_transfer_issues=_normalize_issue_list(payload.get("negative_transfer_issues")),
            summary=payload.get("summary", ""),
            checks=dict(checks) if isinstance(checks, dict) else {},
            issues=_normalize_issue_list(payload.get("issues")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "score": self.score,
            "winner": self.winner,
            "variant_scores": dict(self.variant_scores),
            "negative_transfer_issues": list(self.negative_transfer_issues),
            "summary": self.summary,
            "checks": dict(self.checks),
            "issues": list(self.issues),
        }

    def _winner_from_scores(self) -> str:
        if not self.variant_scores:
            return "tie"
        sorted_scores = sorted(self.variant_scores.items(), key=lambda item: item[1], reverse=True)
        if len(sorted_scores) > 1 and sorted_scores[0][1] == sorted_scores[1][1]:
            return "tie"
        return sorted_scores[0][0]


def _normalize_issue_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    issues: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _normalize_text(item.get("message") or item.get("type") or item)
        else:
            text = _normalize_text(item)
        if text:
            issues.append(text)
    return _normalize_string_list(issues)


def _normalize_score_map(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    scores: dict[str, float] = {}
    for key, raw_score in value.items():
        variant = _normalize_text(key).lower()
        if not variant:
            continue
        scores[variant] = _clamp_score(raw_score)
    return scores


@dataclass(slots=True)
class CreativeKBBenchmarkInput:
    source_path: str | None = None
    fixture: str | None = "longzu_32kb"
    run_id: str | None = None
    case_count: int = 3
    artifact_dir: str | None = None
    enable_writer_ab: bool = False
    model_config: dict[str, Any] | None = None
    seed: int = 17
    prefix_min_chars: int = 1200
    recent_window_size: int = 3

    def __post_init__(self) -> None:
        self.source_path = _normalize_text(self.source_path) or None
        self.fixture = _normalize_text(self.fixture) or None
        self.run_id = _normalize_text(self.run_id) or None
        self.case_count = max(3, min(5, int(self.case_count or 3)))
        self.artifact_dir = _normalize_text(self.artifact_dir) or None
        self.seed = int(self.seed or 0)
        self.prefix_min_chars = max(0, int(self.prefix_min_chars or 0))
        self.recent_window_size = max(1, int(self.recent_window_size or 3))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class KBBenchmarkCase:
    case_id: str
    anchor_context: str
    recent_window_summary: str
    goal: str
    scene_brief: SceneBrief
    reference_synopsis: str
    expected_traits: list[str] = field(default_factory=list)
    reference_window_index: int = 0
    category: str = ""

    def __post_init__(self) -> None:
        self.case_id = _normalize_text(self.case_id)
        self.anchor_context = _normalize_text(self.anchor_context)
        self.recent_window_summary = _normalize_text(self.recent_window_summary)
        self.goal = _normalize_text(self.goal)
        self.reference_synopsis = _normalize_text(self.reference_synopsis)
        self.expected_traits = _normalize_string_list(self.expected_traits)
        self.reference_window_index = max(0, int(self.reference_window_index or 0))
        self.category = _normalize_text(self.category)
        if not self.case_id:
            raise ValueError("KBBenchmarkCase.case_id is required")
        if not self.anchor_context:
            raise ValueError("KBBenchmarkCase.anchor_context is required")
        if not self.recent_window_summary:
            raise ValueError("KBBenchmarkCase.recent_window_summary is required")
        if not self.goal:
            raise ValueError("KBBenchmarkCase.goal is required")
        if not self.reference_synopsis:
            raise ValueError("KBBenchmarkCase.reference_synopsis is required")
        if not self.expected_traits:
            raise ValueError("KBBenchmarkCase.expected_traits is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "anchor_context": self.anchor_context,
            "recent_window_summary": self.recent_window_summary,
            "goal": self.goal,
            "scene_brief": self.scene_brief.to_dict(),
            "reference_synopsis": self.reference_synopsis,
            "expected_traits": list(self.expected_traits),
            "reference_window_index": self.reference_window_index,
            "category": self.category,
        }


@dataclass(slots=True)
class CreativeKBBenchmarkResult:
    run_id: str
    artifact_dir: str
    status: str
    build_summary: dict[str, Any] = field(default_factory=dict)
    case_summary: dict[str, Any] = field(default_factory=dict)
    retrieval_review_summary: dict[str, Any] = field(default_factory=dict)
    writer_ab_summary: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary_path: str = ""

    def __post_init__(self) -> None:
        self.run_id = _normalize_text(self.run_id)
        self.artifact_dir = _normalize_text(self.artifact_dir)
        self.status = _normalize_text(self.status) or "failed"
        self.errors = _normalize_string_list(self.errors)
        self.warnings = _normalize_string_list(self.warnings)
        self.summary_path = _normalize_text(self.summary_path)
        if not self.run_id:
            raise ValueError("CreativeKBBenchmarkResult.run_id is required")
        if not self.artifact_dir:
            raise ValueError("CreativeKBBenchmarkResult.artifact_dir is required")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "artifact_dir": self.artifact_dir,
            "status": self.status,
            "build_summary": dict(self.build_summary),
            "case_summary": dict(self.case_summary),
            "retrieval_review_summary": dict(self.retrieval_review_summary),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "summary_path": self.summary_path,
        }
        if self.writer_ab_summary is not None:
            payload["writer_ab_summary"] = dict(self.writer_ab_summary)
        return payload
