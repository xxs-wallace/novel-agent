from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


def _normalize_text(value: object) -> str:
    return str(value).strip()


def _normalize_string_list(items: object) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        text = items.strip()
        return [text] if text else []
    if not isinstance(items, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


ParagraphBenchmarkDecision = Literal["pass", "borderline", "fail"]


@dataclass(slots=True)
class ParagraphBenchmarkSample:
    source_path: str
    prefix_count: int
    target_segment_index: int
    recent_window_size: int
    prefix_segments: list[str]
    recent_segments: list[str]
    reference_truth: str
    outline_text: str = ""
    character_names: list[str] = field(default_factory=list)
    target_length_chars: int = 600
    total_segments: int = 0

    def __post_init__(self) -> None:
        self.source_path = _normalize_text(self.source_path)
        self.prefix_count = max(1, int(self.prefix_count))
        self.target_segment_index = max(0, int(self.target_segment_index))
        self.recent_window_size = max(1, int(self.recent_window_size))
        self.prefix_segments = [_normalize_text(item) for item in self.prefix_segments if _normalize_text(item)]
        self.recent_segments = [_normalize_text(item) for item in self.recent_segments if _normalize_text(item)]
        self.reference_truth = _normalize_text(self.reference_truth)
        self.outline_text = _normalize_text(self.outline_text)
        self.character_names = _normalize_string_list(self.character_names)
        self.target_length_chars = max(80, int(self.target_length_chars or 600))
        self.total_segments = max(self.total_segments, len(self.prefix_segments) + 1)

    @property
    def recent_window_text(self) -> str:
        return "\n\n".join(self.recent_segments).strip()

    @property
    def prefix_text(self) -> str:
        return "\n\n".join(self.prefix_segments).strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ParagraphBenchmarkIssue:
    type: str
    severity: str
    message: str
    evidence: str = ""

    def __post_init__(self) -> None:
        self.type = _normalize_text(self.type)
        self.severity = _normalize_text(self.severity)
        self.message = _normalize_text(self.message)
        self.evidence = _normalize_text(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ParagraphBenchmarkReviewerReport:
    decision: ParagraphBenchmarkDecision
    score: float
    summary: str
    issues: list[ParagraphBenchmarkIssue] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)
    generated_chars: int = 0
    reference_truth_chars: int = 0

    def __post_init__(self) -> None:
        normalized_decision = _normalize_text(self.decision)
        if normalized_decision not in {"pass", "borderline", "fail"}:
            raise ValueError("decision must be pass, borderline, or fail")
        self.decision = normalized_decision  # type: ignore[assignment]
        self.score = round(max(0.0, min(1.0, float(self.score))), 4)
        self.summary = _normalize_text(self.summary)
        self.generated_chars = max(0, int(self.generated_chars))
        self.reference_truth_chars = max(0, int(self.reference_truth_chars))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "score": self.score,
            "summary": self.summary,
            "issues": [item.to_dict() for item in self.issues],
            "metrics": dict(self.metrics),
            "generated_chars": self.generated_chars,
            "reference_truth_chars": self.reference_truth_chars,
        }


@dataclass(slots=True)
class ParagraphBenchmarkRunResult:
    run_id: str
    run_dir: str
    sample: ParagraphBenchmarkSample
    prompt_text: str
    generated_text: str
    reviewer_report: ParagraphBenchmarkReviewerReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "sample": self.sample.to_dict(),
            "prompt_text": self.prompt_text,
            "generated_text": self.generated_text,
            "reviewer_report": self.reviewer_report.to_dict(),
        }
