from __future__ import annotations

import json
import re

from ...schemas import RunConfig
from ..schemas.smoke_schema import (
    AuthorizedInputs,
    LoadedSmokeSample,
    LoadedSmokeStep,
    SmokeReviewerCheck,
    SmokeReviewerIssue,
    SmokeReviewerReport,
)
from .continuation_generation_service import ContinuationGenerationService


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


class SmokeReviewerService:
    """LLM-first continuity reviewer for the MVP smoke benchmark."""

    PLAN_KEYS = (
        "target_chapter_id",
        "target_segment_id",
        "chapter_goal",
        "emotional_goal",
        "conflict_goal",
        "outline_excerpt",
    )

    def __init__(
        self,
        *,
        generation_service: ContinuationGenerationService,
        generation_config: RunConfig,
    ) -> None:
        self.generation_service = generation_service
        self.generation_config = generation_config

    def build_input_payload(
        self,
        *,
        step: LoadedSmokeStep,
        authorized_inputs: AuthorizedInputs,
        generated_text: str,
    ) -> dict[str, object]:
        current_unit_plan = _normalize_mapping(authorized_inputs.current_unit_plan)
        return {
            "recent_window_summary": step.recent_window_summary,
            "current_unit_plan": {
                key: current_unit_plan[key]
                for key in self.PLAN_KEYS
                if _normalize_text(current_unit_plan.get(key))
            },
            "generated_text": _normalize_text(generated_text),
            "reference_truth": step.reference_truth.text.strip(),
            "stitched_recent_plus_generated": "\n\n".join(
                item
                for item in [step.recent_window_summary, _normalize_text(generated_text)]
                if item
            ).strip(),
        }

    def build_prompt(self, payload: dict[str, object]) -> str:
        prompt_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        return (
            "你是小说续写 benchmark 的外部剧情连续性 Reviewer。请从读者视角评估生成文本是否是合法后继。\n"
            "你可以使用 reference_truth 作为原文下一段的剧情方向参考，但不要把字面重合当作唯一目标。\n"
            "重点评估：生成是否为空或过短；拼接到最近剧情窗口后是否自然；内部逻辑是否通顺；"
            "是否符合 current_unit_plan；与 reference_truth 的主要剧情方向是否存在严重偏离。\n"
            "禁止评价或依赖人物档案、人物关系档案、世界观摘要、检索参考片段，因为这些输入没有提供给你。\n"
            "只输出 JSON，不要输出 Markdown 或解释文字。JSON schema：\n"
            "{\n"
            '  "decision": "pass|borderline|fail",\n'
            '  "score": 0.0,\n'
            '  "summary": "简短中文结论",\n'
            '  "checks": {\n'
            '    "non_empty_length": {"status": "pass|borderline|fail", "score": 0.0, "summary": "..."},\n'
            '    "recent_window_coherence": {"status": "pass|borderline|fail", "score": 0.0, "summary": "..."},\n'
            '    "logic_flow": {"status": "pass|borderline|fail", "score": 0.0, "summary": "..."},\n'
            '    "outline_alignment": {"status": "pass|borderline|fail", "score": 0.0, "summary": "..."},\n'
            '    "reference_direction_alignment": {"status": "pass|borderline|fail", "score": 0.0, "summary": "..."}\n'
            "  },\n"
            '  "issues": [{"type": "...", "severity": "fatal|warning|info", "message": "...", "evidence": "..."}]\n'
            "}\n\n"
            f"Reviewer 输入：\n{prompt_payload}"
        ).strip()

    def review(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        authorized_inputs: AuthorizedInputs,
        generated_text: str,
    ) -> SmokeReviewerReport:
        payload = self.build_input_payload(
            step=step,
            authorized_inputs=authorized_inputs,
            generated_text=generated_text,
        )
        return self._review_with_model(
            sample=sample,
            step=step,
            payload=payload,
        )

    def _review_with_model(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        payload: dict[str, object],
    ) -> SmokeReviewerReport:
        prompt = self.build_prompt(payload)
        result = self.generation_service.generate(prompt=prompt, config=self.generation_config)
        parsed = self._parse_model_report(result.generated_text)
        return self._report_from_payload(
            sample=sample,
            step=step,
            generated_text=_normalize_text(payload.get("generated_text")),
            payload=parsed,
        )

    def _parse_model_report(self, raw_text: str) -> dict[str, object]:
        text = _normalize_text(raw_text)
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("reviewer JSON must be an object")
        return {str(key): value for key, value in payload.items()}

    def _report_from_payload(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        generated_text: str,
        payload: dict[str, object],
    ) -> SmokeReviewerReport:
        decision = _normalize_text(payload.get("decision"))
        if decision not in {"pass", "borderline", "fail"}:
            score_for_decision = _clamp_score(float(payload.get("score") or 0.0))
            decision = self._decision_for_score(score_for_decision)
        checks_payload = payload.get("checks")
        checks = self._parse_checks(checks_payload if isinstance(checks_payload, dict) else {})
        issues_payload = payload.get("issues")
        issues = [
            SmokeReviewerIssue(
                type=_normalize_text(item.get("type")) or "reviewer_issue",
                severity=_normalize_text(item.get("severity")) or "warning",
                message=_normalize_text(item.get("message")),
                evidence=_normalize_text(item.get("evidence")),
            )
            for item in (issues_payload if isinstance(issues_payload, list) else [])
            if isinstance(item, dict)
        ]
        score = _clamp_score(float(payload.get("score") or self._weighted_score(checks)))
        return SmokeReviewerReport(
            decision=decision,  # type: ignore[arg-type]
            score=score,
            summary=_normalize_text(payload.get("summary")) or "Reviewer 模型未提供 summary。",
            checks=checks,
            issues=issues,
            generated_chars=len(generated_text),
            reference_truth_chars=len(step.reference_truth.text.strip()),
        )

    def _parse_checks(self, payload: dict[str, object]) -> dict[str, SmokeReviewerCheck]:
        checks: dict[str, SmokeReviewerCheck] = {}
        for name in (
            "non_empty_length",
            "recent_window_coherence",
            "logic_flow",
            "outline_alignment",
            "reference_direction_alignment",
        ):
            item = payload.get(name)
            if isinstance(item, dict):
                score = _clamp_score(float(item.get("score") or 0.0))
                status = _normalize_text(item.get("status")) or self._status_for_score(score)
                if status not in {"pass", "borderline", "fail"}:
                    status = self._status_for_score(score)
                checks[name] = SmokeReviewerCheck(
                    name=name,
                    status=status,  # type: ignore[arg-type]
                    score=score,
                    summary=_normalize_text(item.get("summary")),
                )
        return checks

    def _weighted_score(self, checks: dict[str, SmokeReviewerCheck]) -> float:
        weights = {
            "non_empty_length": 0.25,
            "recent_window_coherence": 0.30,
            "logic_flow": 0.25,
            "outline_alignment": 0.15,
            "reference_direction_alignment": 0.05,
        }
        weighted = 0.0
        total = 0.0
        for key, weight in weights.items():
            check = checks.get(key)
            if check is None:
                continue
            weighted += check.score * weight
            total += weight
        return _clamp_score(weighted / max(total, 1e-9))

    def _status_for_score(self, score: float) -> str:
        if score >= 0.60:
            return "pass"
        if score >= 0.45:
            return "borderline"
        return "fail"

    def _decision_for_score(self, score: float) -> str:
        if score >= 0.60:
            return "pass"
        if score >= 0.45:
            return "borderline"
        return "fail"
