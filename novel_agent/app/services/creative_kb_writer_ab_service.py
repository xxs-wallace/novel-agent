from __future__ import annotations

import json
import random
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..schemas.creative_kb_benchmark_schema import (
    KBWriterABReport,
    WRITER_AB_REVIEW_CHECKS,
)


DEFAULT_AGENTIC_SMOKE_KB_VARIANT = "kb_enabled"


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _score_from_reference(reference: Mapping[str, Any]) -> float:
    rerank_score = reference.get("rerank_score")
    if isinstance(rerank_score, Mapping):
        for score_key in ("final_score", "score", "coarse_score"):
            if score_key not in rerank_score:
                continue
            try:
                return float(rerank_score.get(score_key) or 0.0)
            except (TypeError, ValueError):
                continue
    for container_key in ("score", "coarse_score"):
        value = reference.get(container_key)
        if value is None:
            continue
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            continue
    return 0.0


class CreativeKBWriterABService:
    """Builds explicit Writer A/B KB variants and writes diagnostic artifacts.

    This adapter does not own the Writer pipeline. It prepares isolated execution
    inputs that match the existing Writer execution shape, then calls an injected
    writer/reviewer when available.
    """

    def __init__(
        self,
        *,
        writer: Any | None = None,
        reviewer_service: Any | None = None,
    ) -> None:
        self.writer = writer
        self.reviewer_service = reviewer_service

    @staticmethod
    def agentic_smoke_default_variant() -> str:
        """The current Agentic smoke path carries KB references, so it is kb_enabled."""

        return DEFAULT_AGENTIC_SMOKE_KB_VARIANT

    def build_variant_inputs(
        self,
        *,
        base_execution_input: Mapping[str, Any],
        selected_references: Sequence[Mapping[str, Any]],
        decoy_references: Sequence[Mapping[str, Any]],
        seed: int = 17,
        include_oracle: bool = False,
        oracle_references: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        selected = list(selected_references)
        decoys = self._stable_decoy_references(
            decoy_references=list(decoy_references),
            count=max(1, len(selected) or 1),
            seed=seed,
        )
        variants = {
            "kb_enabled": self._execution_input_with_references(
                base_execution_input=base_execution_input,
                variant_name="kb_enabled",
                references=selected,
                reference_source="official_rerank_selected",
                preserve_existing_when_empty=True,
            ),
            "kb_disabled": self._execution_input_with_references(
                base_execution_input=base_execution_input,
                variant_name="kb_disabled",
                references=[],
                reference_source="no_kb_baseline",
                preserve_existing_when_empty=False,
            ),
            "kb_random": self._execution_input_with_references(
                base_execution_input=base_execution_input,
                variant_name="kb_random",
                references=decoys,
                reference_source="random_decoy",
                preserve_existing_when_empty=False,
            ),
        }
        if include_oracle:
            variants["kb_oracle"] = self._execution_input_with_references(
                base_execution_input=base_execution_input,
                variant_name="kb_oracle",
                references=list(oracle_references or []),
                reference_source="oracle_reference",
                preserve_existing_when_empty=False,
            )
        return variants

    def run(
        self,
        *,
        artifact_dir: Path,
        base_execution_input: Mapping[str, Any],
        reference_story_synopsis: Mapping[str, Any],
        reference_truth: str,
        selected_references: Sequence[Mapping[str, Any]],
        decoy_references: Sequence[Mapping[str, Any]],
        seed: int = 17,
        include_oracle: bool = False,
        oracle_references: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        writer_ab_dir = artifact_dir / "writer_ab"
        writer_ab_dir.mkdir(parents=True, exist_ok=True)

        variant_inputs = self.build_variant_inputs(
            base_execution_input=base_execution_input,
            selected_references=selected_references,
            decoy_references=decoy_references,
            seed=seed,
            include_oracle=include_oracle,
            oracle_references=oracle_references,
        )
        variant_payloads: dict[str, dict[str, Any]] = {}
        for variant_name, execution_input in variant_inputs.items():
            variant_dir = writer_ab_dir / variant_name
            variant_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(variant_dir / "writer_execution_input.json", execution_input)
            draft, writer_issue = self._run_writer(execution_input)
            (variant_dir / "draft.md").write_text(draft, encoding="utf-8")
            variant_report = self._variant_artifact_report(
                variant_name=variant_name,
                execution_input=execution_input,
                draft=draft,
                writer_issue=writer_issue,
            )
            self._write_json(variant_dir / "reviewer_report.json", variant_report)
            variant_payloads[variant_name] = {
                "draft": draft,
                "selected_fragment_ids": self._selected_fragment_ids(execution_input),
                "reference_fragment_summaries": self._reference_summaries(execution_input),
                "reviewer_report": variant_report,
            }

        reviewer_payload = {
            "reference_story_synopsis": dict(reference_story_synopsis),
            "reference_truth": _normalize_text(reference_truth),
            "variants": variant_payloads,
            "canonical_pass_fail_scope": "diagnostic_only_writer_ab_does_not_override_retrieval",
        }
        prompt_artifact = self._build_prompt_artifact(reviewer_payload)
        self._write_json(writer_ab_dir / "writer_ab_reviewer_prompt.json", prompt_artifact)

        if self.writer is None:
            summary = self._pending_summary(
                reason="writer_not_configured",
                variant_payloads=variant_payloads,
            )
            self._write_json(writer_ab_dir / "writer_ab_reviewer_report.json", summary)
            return summary
        if self.reviewer_service is None:
            summary = self._pending_summary(
                reason="writer_ab_reviewer_not_configured",
                variant_payloads=variant_payloads,
            )
            self._write_json(writer_ab_dir / "writer_ab_reviewer_report.json", summary)
            return summary

        try:
            report = self._review_writer_ab(reviewer_payload)
            summary = {
                "enabled": True,
                "status": "completed",
                **report.to_dict(),
                "variant_artifacts": self._variant_artifact_summary(variant_payloads),
            }
        except Exception as exc:
            report = KBWriterABReport(
                decision="fail",
                score=0.0,
                winner="tie",
                variant_scores={variant: 0.0 for variant in variant_payloads},
                negative_transfer_issues=["writer_ab_reviewer_failed"],
                summary=f"Writer A/B reviewer failed: {exc}",
                checks={name: "fail" for name in WRITER_AB_REVIEW_CHECKS},
                issues=["reviewer_failed"],
            )
            summary = {
                "enabled": True,
                "status": "failed_reviewer",
                **report.to_dict(),
                "variant_artifacts": self._variant_artifact_summary(variant_payloads),
            }
        self._write_json(writer_ab_dir / "writer_ab_reviewer_report.json", summary)
        return summary

    def _execution_input_with_references(
        self,
        *,
        base_execution_input: Mapping[str, Any],
        variant_name: str,
        references: Sequence[Mapping[str, Any]],
        reference_source: str,
        preserve_existing_when_empty: bool,
    ) -> dict[str, Any]:
        execution_input = deepcopy(dict(base_execution_input))
        style_bundle = dict(execution_input.get("style_reference_bundle") or {})
        existing_references = list(style_bundle.get("references") or [])
        existing_ids = list(style_bundle.get("selected_fragment_ids") or execution_input.get("selected_fragment_ids") or [])
        style_items = self._style_reference_items(references=references, reference_source=reference_source)
        if not style_items and preserve_existing_when_empty:
            style_items = [dict(item) for item in existing_references if isinstance(item, Mapping)]
        selected_ids = [str(item.get("fragment_id")) for item in style_items if item.get("fragment_id")]
        if not selected_ids and preserve_existing_when_empty:
            selected_ids = [str(item) for item in existing_ids if _normalize_text(item)]

        style_bundle["references"] = style_items
        style_bundle["selected_fragment_ids"] = selected_ids
        style_bundle["selection_notes"] = self._selection_notes(
            variant_name=variant_name,
            reference_source=reference_source,
            selected_ids=selected_ids,
        )
        style_bundle["kb_variant"] = variant_name
        style_bundle["reference_source"] = reference_source
        execution_input["style_reference_bundle"] = style_bundle
        execution_input["selected_fragment_ids"] = selected_ids
        execution_input["kb_variant"] = {
            "name": variant_name,
            "reference_source": reference_source,
            "selected_fragment_ids": selected_ids,
            "is_no_kb_baseline": variant_name == "kb_disabled",
        }
        fact_inputs = dict(execution_input.get("fact_inputs") or {})
        fact_inputs.update(
            {
                "kb_variant": variant_name,
                "kb_reference_source": reference_source,
                "selected_fragment_ids": selected_ids,
            }
        )
        execution_input["fact_inputs"] = fact_inputs
        return execution_input

    def _style_reference_items(
        self,
        *,
        references: Sequence[Mapping[str, Any]],
        reference_source: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for reference in references:
            fragment_id = _normalize_text(reference.get("fragment_id"))
            if not fragment_id:
                continue
            card = reference.get("fragment_card")
            card_payload = card if isinstance(card, Mapping) else {}
            items.append(
                {
                    "fragment_id": fragment_id,
                    "source_path": _normalize_text(card_payload.get("source_path") or reference.get("source_path")),
                    "narrative_function": self._string_list(
                        reference.get("narrative_function") or card_payload.get("narrative_function")
                    ),
                    "relationship_state": self._string_list(
                        reference.get("relationship_state") or card_payload.get("relationship_state")
                    ),
                    "style_profile_text": _normalize_text(
                        reference.get("style_profile_text") or card_payload.get("style_profile_text")
                    ),
                    "pov_mode": _normalize_text(card_payload.get("pov_mode")),
                    "excerpt": _normalize_text(
                        reference.get("source_excerpt")
                        or card_payload.get("source_excerpt")
                        or reference.get("content_summary")
                        or card_payload.get("content_summary")
                    ),
                    "score": _score_from_reference(reference),
                    "reference_source": reference_source,
                    "reference_origin": _normalize_text(
                        reference.get("decoy_type") or reference.get("reference_type") or reference_source
                    ),
                }
            )
        return items

    def _stable_decoy_references(
        self,
        *,
        decoy_references: Sequence[Mapping[str, Any]],
        count: int,
        seed: int,
    ) -> list[Mapping[str, Any]]:
        decoys = [reference for reference in decoy_references if _normalize_text(reference.get("fragment_id"))]
        if len(decoys) <= count:
            return decoys
        indexes = sorted(random.Random(seed).sample(range(len(decoys)), count))
        return [decoys[index] for index in indexes]

    def _run_writer(self, execution_input: dict[str, Any]) -> tuple[str, str]:
        if self.writer is None:
            return "", "writer_not_configured"
        try:
            if hasattr(self.writer, "generate_draft_from_execution_input"):
                draft = self.writer.generate_draft_from_execution_input(execution_input)
            elif hasattr(self.writer, "run"):
                draft = self.writer.run(execution_input)
            elif callable(self.writer):
                draft = self.writer(execution_input)
            else:
                return "", "writer_interface_not_supported"
        except Exception as exc:
            return "", f"writer_failed: {exc}"
        if isinstance(draft, Mapping):
            for key in ("draft", "text", "content", "markdown"):
                text = _normalize_text(draft.get(key))
                if text:
                    return text, ""
            return json.dumps(draft, ensure_ascii=False, indent=2), ""
        return _normalize_text(draft), ""

    def _variant_artifact_report(
        self,
        *,
        variant_name: str,
        execution_input: Mapping[str, Any],
        draft: str,
        writer_issue: str,
    ) -> dict[str, Any]:
        selected_ids = self._selected_fragment_ids(execution_input)
        return {
            "variant": variant_name,
            "status": "pending_ab_reviewer" if not writer_issue else "writer_unavailable",
            "draft_chars": len(draft),
            "selected_fragment_ids": selected_ids,
            "reference_count": len(self._references(execution_input)),
            "issues": [writer_issue] if writer_issue else [],
        }

    def _build_prompt_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.reviewer_service is not None and hasattr(self.reviewer_service, "build_writer_ab_prompt_artifact"):
            return self.reviewer_service.build_writer_ab_prompt_artifact(payload=payload)
        from .creative_kb_reviewer_service import CreativeKBReviewerService

        return CreativeKBReviewerService(model_client=None).build_writer_ab_prompt_artifact(payload=payload)

    def _review_writer_ab(self, payload: dict[str, Any]) -> KBWriterABReport:
        if self.reviewer_service is None:
            raise ValueError("writer_ab reviewer is not configured")
        result = self.reviewer_service.review_writer_ab(payload=payload)
        if isinstance(result, KBWriterABReport):
            return result
        if isinstance(result, Mapping):
            return KBWriterABReport.from_dict(dict(result))
        if hasattr(result, "to_dict"):
            return KBWriterABReport.from_dict(result.to_dict())
        raise ValueError("writer_ab reviewer returned unsupported payload")

    def _pending_summary(self, *, reason: str, variant_payloads: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "enabled": True,
            "status": "pending_writer_ab",
            "decision": "pending",
            "score": 0.0,
            "winner": "pending",
            "variant_scores": {},
            "negative_transfer_issues": [reason],
            "summary": f"Writer A/B artifacts were generated but final review is pending: {reason}.",
            "variant_artifacts": self._variant_artifact_summary(variant_payloads),
        }

    def _variant_artifact_summary(self, variant_payloads: Mapping[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for variant_name, payload in variant_payloads.items():
            if not isinstance(payload, Mapping):
                continue
            reviewer_report = payload.get("reviewer_report") if isinstance(payload.get("reviewer_report"), Mapping) else {}
            summary[variant_name] = {
                "draft_chars": int(reviewer_report.get("draft_chars") or len(_normalize_text(payload.get("draft")))),
                "selected_fragment_ids": list(payload.get("selected_fragment_ids") or []),
                "reference_count": len(payload.get("reference_fragment_summaries") or []),
            }
        return summary

    def _reference_summaries(self, execution_input: Mapping[str, Any]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for reference in self._references(execution_input):
            summaries.append(
                {
                    "fragment_id": reference.get("fragment_id"),
                    "reference_source": reference.get("reference_source"),
                    "reference_origin": reference.get("reference_origin"),
                    "narrative_function": list(reference.get("narrative_function") or []),
                    "relationship_state": list(reference.get("relationship_state") or []),
                    "style_profile_text": reference.get("style_profile_text"),
                    "excerpt": reference.get("excerpt"),
                    "score": reference.get("score"),
                }
            )
        return summaries

    def _references(self, execution_input: Mapping[str, Any]) -> list[dict[str, Any]]:
        bundle = execution_input.get("style_reference_bundle")
        if not isinstance(bundle, Mapping):
            return []
        references = bundle.get("references")
        if not isinstance(references, list):
            return []
        return [dict(item) for item in references if isinstance(item, Mapping)]

    def _selected_fragment_ids(self, execution_input: Mapping[str, Any]) -> list[str]:
        bundle = execution_input.get("style_reference_bundle")
        ids: object = None
        if isinstance(bundle, Mapping):
            ids = bundle.get("selected_fragment_ids")
        if not ids:
            ids = execution_input.get("selected_fragment_ids")
        return [str(item) for item in ids or [] if _normalize_text(item)]

    def _selection_notes(self, *, variant_name: str, reference_source: str, selected_ids: Sequence[str]) -> str:
        if variant_name == "kb_disabled":
            return "Creative KB references disabled for explicit no-KB baseline."
        if variant_name == "kb_random":
            return f"Random/decoy Creative KB references injected: {', '.join(selected_ids) or 'none'}."
        if variant_name == "kb_oracle":
            return "Oracle references injected for diagnostic upper-bound only."
        return f"Official Creative KB rerank references preserved: {', '.join(selected_ids) or reference_source}."

    def _string_list(self, value: object) -> list[str]:
        if isinstance(value, str):
            text = _normalize_text(value)
            return [text] if text else []
        if isinstance(value, Sequence) and not isinstance(value, bytes):
            return [str(item) for item in value if _normalize_text(item)]
        return []

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
