from __future__ import annotations

import re
from collections import Counter

from ..schemas.orchestration_schema import WriterInputBundle
from ..schemas.smoke_schema import (
    AuthorizedInputs,
    LoadedSmokeSample,
    LoadedSmokeStep,
    SmokeCompareIssue,
    SmokeCompareReport,
    SmokeCompareScores,
    SmokeDecision,
    SmokeEvidenceRef,
    SmokeHardGate,
    SmokeScoreExplanation,
)

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")


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


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


class SmokeCompareService:
    def compare(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep | None = None,
        authorized_inputs: AuthorizedInputs,
        writer_input_bundle: WriterInputBundle,
        generated_text: str,
    ) -> SmokeCompareReport:
        active_step = step or sample.first_step
        generated = _normalize_text(generated_text)
        reference_truth = active_step.reference_truth.text.strip()
        fatal_issues = self._build_fatal_issues(
            sample=sample,
            authorized_inputs=authorized_inputs,
            generated_text=generated,
        )
        hard_gate = SmokeHardGate(
            passed=not fatal_issues,
            fatal_issues=fatal_issues,
        )
        scores = SmokeCompareScores(
            hard_consistency=1.0 if hard_gate.passed else 0.0,
            recent_window_coherence=self._score_recent_window_coherence(
                recent_window_summary=active_step.recent_window_summary,
                generated_text=generated,
            ),
            chapter_outline_fulfillment=self._score_outline_fulfillment(
                current_unit_plan=authorized_inputs.current_unit_plan,
                generated_text=generated,
                mode=sample.config.mode,
            ),
            forward_guidance_adherence=self._score_forward_guidance(
                authorized_inputs=authorized_inputs,
                generated_text=generated,
                mode=sample.config.mode,
            ),
            character_consistency=self._score_character_consistency(
                character_names=authorized_inputs.related_character_names,
                generated_text=generated,
            ),
            relationship_transition_legality=self._score_relationship_legality(
                writer_input_bundle=writer_input_bundle,
                generated_text=generated,
            ),
            world_rule_compliance=self._score_world_rule_compliance(
                writer_input_bundle=writer_input_bundle,
                generated_text=generated,
            ),
            style_alignment=self._score_style_alignment(
                reference_truth=reference_truth,
                generated_text=generated,
            ),
            retrieval_effectiveness=self._score_retrieval_effectiveness(
                writer_input_bundle=writer_input_bundle,
                generated_text=generated,
            ),
        )
        weighted_score = self._compute_weighted_score(scores=scores, hard_gate=hard_gate)
        decision = self._decide(weighted_score=weighted_score, hard_gate=hard_gate)
        return SmokeCompareReport(
            sample_id=sample.config.sample_id,
            mode=sample.config.mode,
            step_id=active_step.step_id,
            hard_gate=hard_gate,
            scores=scores,
            weighted_score=weighted_score,
            decision=decision,
            explanations=self._build_explanations(
                scores=scores,
                hard_gate=hard_gate,
            ),
            evidence_refs=self._build_evidence_refs(
                sample=sample,
                step=active_step,
                writer_input_bundle=writer_input_bundle,
            ),
            generated_chars=len(generated),
            reference_truth_chars=len(reference_truth),
        )

    def _build_fatal_issues(
        self,
        *,
        sample: LoadedSmokeSample,
        authorized_inputs: AuthorizedInputs,
        generated_text: str,
    ) -> list[SmokeCompareIssue]:
        issues: list[SmokeCompareIssue] = []
        if not generated_text:
            issues.append(
                SmokeCompareIssue(
                    type="empty_output",
                    severity="fatal",
                    message="生成结果为空，无法进行有效续写对比。",
                )
            )
        forbidden_terms = _normalize_string_list(authorized_inputs.current_unit_plan.get("must_avoid"))
        forbidden_terms.extend(
            _normalize_string_list(
                authorized_inputs.bounded_future_hint.get("must_not_reveal")
                if authorized_inputs.bounded_future_hint is not None
                else []
            )
        )
        for term in forbidden_terms:
            if term and term in generated_text and "避免设定冲突" not in term:
                issues.append(
                    SmokeCompareIssue(
                        type="forbidden_reveal",
                        severity="fatal",
                        message=f"生成结果出现未授权或禁止内容：{term}",
                        evidence=term,
                    )
                )
                break
        if sample.config.mode == "blind_prefix" and authorized_inputs.current_unit_plan:
            issues.append(
                SmokeCompareIssue(
                    type="mode_boundary_violation",
                    severity="fatal",
                    message="blind_prefix 模式下不应存在 current_unit_plan。",
                )
            )
        return issues

    def _score_recent_window_coherence(self, *, recent_window_summary: str, generated_text: str) -> float:
        if not recent_window_summary.strip():
            return 1.0
        return max(
            self._token_overlap_score(recent_window_summary, generated_text),
            self._keyword_presence_score(recent_window_summary, generated_text),
        )

    def _score_outline_fulfillment(
        self,
        *,
        current_unit_plan: dict[str, object],
        generated_text: str,
        mode: str,
    ) -> float | None:
        if mode == "blind_prefix":
            return None
        objective = _normalize_text(current_unit_plan.get("chapter_goal"))
        emotional_goal = _normalize_text(current_unit_plan.get("emotional_goal"))
        conflict_goal = _normalize_text(current_unit_plan.get("conflict_goal"))
        scores = [
            max(
                self._token_overlap_score(objective, generated_text),
                self._keyword_presence_score(objective, generated_text),
            ),
            max(
                self._token_overlap_score(emotional_goal, generated_text),
                self._keyword_presence_score(emotional_goal, generated_text),
            ),
            max(
                self._token_overlap_score(conflict_goal, generated_text),
                self._keyword_presence_score(conflict_goal, generated_text),
            ),
        ]
        usable_scores = [score for score in scores if score > 0]
        if not usable_scores:
            return 0.25
        return _clamp_score(sum(usable_scores) / len(usable_scores))

    def _score_forward_guidance(
        self,
        *,
        authorized_inputs: AuthorizedInputs,
        generated_text: str,
        mode: str,
    ) -> float | None:
        if mode != "bounded_future_hint":
            return None
        guidance = authorized_inputs.bounded_future_hint or {}
        forbidden_terms = _normalize_string_list(guidance.get("must_not_reveal"))
        if not forbidden_terms:
            return 1.0
        violations = sum(1 for term in forbidden_terms if term and term in generated_text)
        if violations <= 0:
            return 1.0
        return _clamp_score(max(0.0, 1.0 - violations / max(1, len(forbidden_terms))))

    def _score_character_consistency(self, *, character_names: list[str], generated_text: str) -> float:
        names = [name for name in character_names if name]
        if not names:
            return 1.0
        matched = sum(1 for name in names if name in generated_text)
        return _clamp_score(matched / len(names))

    def _score_relationship_legality(
        self,
        *,
        writer_input_bundle: WriterInputBundle,
        generated_text: str,
    ) -> float:
        relationship_state = _normalize_string_list(writer_input_bundle.scene_brief.relationship_state)
        if not relationship_state:
            return 1.0
        matched = sum(1 for item in relationship_state if item in generated_text)
        if matched > 0:
            return 1.0
        if any(token in generated_text for token in ("和解", "表白", "彻底原谅")):
            return 0.2
        return 0.7

    def _score_world_rule_compliance(
        self,
        *,
        writer_input_bundle: WriterInputBundle,
        generated_text: str,
    ) -> float:
        world_summary = writer_input_bundle.context_payload.world_summary_md.strip()
        if not world_summary:
            return 1.0
        if "没有超自然设定" in world_summary and any(
            token in generated_text for token in ("法术", "灵力", "异能", "魔法")
        ):
            return 0.0
        return 1.0

    def _score_style_alignment(self, *, reference_truth: str, generated_text: str) -> float:
        if not reference_truth.strip() or not generated_text.strip():
            return 0.0
        reference_dialogue = reference_truth.count("“") + reference_truth.count('"')
        generated_dialogue = generated_text.count("“") + generated_text.count('"')
        dialogue_score = 1.0 - min(1.0, abs(reference_dialogue - generated_dialogue) / max(1, reference_dialogue + 1))
        reference_avg = self._average_sentence_length(reference_truth)
        generated_avg = self._average_sentence_length(generated_text)
        if reference_avg <= 0 or generated_avg <= 0:
            rhythm_score = 0.5
        else:
            rhythm_score = 1.0 - min(1.0, abs(reference_avg - generated_avg) / max(reference_avg, 1.0))
        return _clamp_score((dialogue_score + rhythm_score) / 2)

    def _score_retrieval_effectiveness(
        self,
        *,
        writer_input_bundle: WriterInputBundle,
        generated_text: str,
    ) -> float:
        if not writer_input_bundle.reference_fragments:
            return 0.0
        scores: list[float] = []
        for item in writer_input_bundle.reference_fragments:
            scores.append(
                max(
                    self._token_overlap_score(item.source_excerpt, generated_text),
                    self._keyword_presence_score(item.source_excerpt, generated_text),
                )
            )
            if item.content_summary:
                scores.append(
                    max(
                        self._token_overlap_score(item.content_summary, generated_text),
                        self._keyword_presence_score(item.content_summary, generated_text),
                    )
                )
        usable = [score for score in scores if score > 0]
        if not usable:
            return 0.2
        return _clamp_score(sum(usable) / len(usable))

    def _compute_weighted_score(
        self,
        *,
        scores: SmokeCompareScores,
        hard_gate: SmokeHardGate,
    ) -> float:
        if not hard_gate.passed:
            return 0.0
        metric_values = [
            scores.hard_consistency,
            scores.recent_window_coherence,
            scores.chapter_outline_fulfillment,
            scores.forward_guidance_adherence,
            scores.character_consistency,
            scores.relationship_transition_legality,
            scores.world_rule_compliance,
            scores.style_alignment,
            scores.retrieval_effectiveness,
        ]
        usable_values = [float(value) for value in metric_values if value is not None]
        if not usable_values:
            return 0.0
        return _clamp_score(sum(usable_values) / len(usable_values))

    def _decide(self, *, weighted_score: float, hard_gate: SmokeHardGate) -> SmokeDecision:
        if not hard_gate.passed:
            return "fail"
        if weighted_score >= 0.8:
            return "pass"
        if weighted_score >= 0.65:
            return "borderline"
        return "fail"

    def _build_explanations(
        self,
        *,
        scores: SmokeCompareScores,
        hard_gate: SmokeHardGate,
    ) -> list[SmokeScoreExplanation]:
        explanations: list[SmokeScoreExplanation] = []
        if hard_gate.fatal_issues:
            explanations.append(
                SmokeScoreExplanation(
                    metric="hard_consistency",
                    summary=hard_gate.fatal_issues[0].message,
                )
            )
        explanations.append(
            SmokeScoreExplanation(
                metric="recent_window_coherence",
                summary=(
                    "最近窗口冲突与人物状态有明显承接。"
                    if (scores.recent_window_coherence or 0.0) >= 0.6
                    else "最近窗口承接较弱，生成文本和前缀摘要重合不足。"
                ),
            )
        )
        if scores.chapter_outline_fulfillment is not None:
            explanations.append(
                SmokeScoreExplanation(
                    metric="chapter_outline_fulfillment",
                    summary=(
                        "生成文本能够覆盖当前授权目标的主要语义。"
                        if scores.chapter_outline_fulfillment >= 0.6
                        else "当前授权目标覆盖不足，章节目标或情绪目标承接偏弱。"
                    ),
                )
            )
        if scores.style_alignment is not None:
            explanations.append(
                SmokeScoreExplanation(
                    metric="style_alignment",
                    summary=(
                        "句长和对白密度与真值大体接近。"
                        if scores.style_alignment >= 0.6
                        else "句长节奏或对白密度与真值差异较大。"
                    ),
                )
            )
        if scores.retrieval_effectiveness is not None:
            explanations.append(
                SmokeScoreExplanation(
                    metric="retrieval_effectiveness",
                    summary=(
                        "生成文本吸收了部分参考片段特征。"
                        if scores.retrieval_effectiveness >= 0.5
                        else "参考片段特征在生成文本中的体现较弱。"
                    ),
                )
            )
        return explanations

    def _build_evidence_refs(
        self,
        *,
        sample: LoadedSmokeSample,
        step: LoadedSmokeStep,
        writer_input_bundle: WriterInputBundle,
    ) -> list[SmokeEvidenceRef]:
        refs = [
            SmokeEvidenceRef(type="anchor_context", ref=step.anchor_context.path),
            SmokeEvidenceRef(type="reference_truth", ref=step.reference_truth.path),
        ]
        for item in step.recent_window:
            refs.append(SmokeEvidenceRef(type="recent_window", ref=item.path))
        for item in writer_input_bundle.sources:
            if isinstance(item, dict):
                ref = _normalize_text(item.get("path"))
                if ref:
                    refs.append(SmokeEvidenceRef(type="reference_fragment", ref=ref))
        return refs

    def _token_overlap_score(self, left_text: str, right_text: str) -> float:
        left_tokens = self._token_counter(left_text)
        right_tokens = self._token_counter(right_text)
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = sum(min(left_tokens[token], right_tokens[token]) for token in left_tokens if token in right_tokens)
        total = sum(left_tokens.values())
        return _clamp_score(overlap / max(1, total))

    def _keyword_presence_score(self, left_text: str, right_text: str) -> float:
        left_tokens = set(self._token_counter(left_text).keys())
        right_tokens = set(self._token_counter(right_text).keys())
        if not left_tokens or not right_tokens:
            return 0.0
        matched = len(left_tokens & right_tokens)
        denominator = min(6, max(1, len(left_tokens)))
        return _clamp_score(matched / denominator)

    def _token_counter(self, text: str) -> Counter[str]:
        tokens: list[str] = []
        for token in TOKEN_PATTERN.findall(text):
            normalized = token.strip().lower()
            if len(normalized) <= 1:
                continue
            tokens.append(normalized)
            if re.fullmatch(r"[\u4e00-\u9fff]+", normalized):
                for index in range(len(normalized) - 1):
                    bigram = normalized[index : index + 2]
                    if len(bigram) == 2:
                        tokens.append(bigram)
        return Counter(tokens)

    def _average_sentence_length(self, text: str) -> float:
        sentences = [item.strip() for item in re.split(r"[。！？!?；;\n]+", text) if item.strip()]
        if not sentences:
            return 0.0
        return sum(len(item) for item in sentences) / len(sentences)
