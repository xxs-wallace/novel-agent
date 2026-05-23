from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..schemas.reviewer_schema import ReviewFinding, ReviewRequest, ReviewSuiteReport, utc_now
from .registry import ReviewerRegistry
from .runtime import ReviewerRuntime


class ReviewerSuite:
    def __init__(self, *, registry: ReviewerRegistry, runtime: ReviewerRuntime, artifact_root: Path | None = None) -> None:
        self.registry = registry
        self.runtime = runtime
        self.artifact_root = artifact_root or runtime.artifact_root

    def run(self, request: ReviewRequest, *, conn: sqlite3.Connection | None = None) -> ReviewSuiteReport:
        reports = []
        for reviewer_id in request.reviewer_ids:
            reviewer = self.registry.get(reviewer_id, target_type=request.target.target_type)
            reports.append(self.runtime.run(request, reviewer=reviewer, conn=conn))

        successful_scores = [report.score for report in reports if report.status == "success" and report.score is not None]
        any_failed = any(report.status in {"failed", "needs_model"} for report in reports)
        status = "failed" if any_failed else "success"
        overall_score = int(round(sum(successful_scores) / len(successful_scores))) if status == "success" and successful_scores else None
        top_findings = self._top_findings([finding for report in reports for finding in report.findings])
        summary = "评审套件已完成。" if status == "success" else "评审套件部分或全部未完成。"
        suite_report = ReviewSuiteReport(
            suite_report_id=f"suite-report-{request.review_request_id}-{utc_now().replace(':', '')}",
            review_request_id=request.review_request_id,
            target_id=request.target.target_id,
            status=status,
            overall_score=overall_score,
            summary_zh=summary,
            reviewer_reports=reports,
            top_findings=top_findings,
            metadata={"aggregation": "arithmetic_mean_of_success_scores; failures preserved in reviewer_reports"},
        )
        self._persist(request, suite_report)
        return suite_report

    def _top_findings(self, findings: list[ReviewFinding]) -> list[ReviewFinding]:
        rank = {"critical": 0, "major": 1, "minor": 2, "note": 3}
        return sorted(findings, key=lambda item: (rank[item.severity], -item.confidence))[:12]

    def _persist(self, request: ReviewRequest, suite_report: ReviewSuiteReport) -> None:
        run_dir = self.artifact_root / request.review_request_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "suite_report.json").write_text(
            json.dumps(suite_report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
