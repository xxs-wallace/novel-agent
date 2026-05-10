from __future__ import annotations

import json
import re
from typing import Any, Sequence

from ..prompts.creative_kb_review_prompt import (
    CLUSTER_RUBRIC,
    FRAGMENT_CARD_RUBRIC,
    RETRIEVAL_RUBRIC,
    WRITER_AB_RUBRIC,
    build_cluster_review_prompt,
    build_fragment_card_review_prompt,
    build_retrieval_review_prompt,
    build_writer_ab_review_prompt,
)
from ..schemas.creative_kb_benchmark_schema import (
    CLUSTER_REVIEW_CHECKS,
    FRAGMENT_CARD_REVIEW_CHECKS,
    RETRIEVAL_REVIEW_CHECKS,
    WRITER_AB_REVIEW_CHECKS,
    KBClusterReviewReport,
    KBFragmentCardReviewReport,
    KBRetrievalReviewReport,
    KBWriterABReport,
)
from ..schemas.creative_kb_schema import FragmentCard, FragmentCluster


SOURCE_EXCERPT_REVIEW_CHARS = 1800
CLUSTER_MEMBER_REVIEW_LIMIT = 6


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


class CreativeKBReviewerService:
    """LLM reviewer for Creative KB card and cluster quality checks."""

    def __init__(self, *, model_client: Any | None) -> None:
        self.model_client = model_client

    def build_fragment_card_prompt_artifact(
        self,
        *,
        original_document_excerpt: str,
        fragment_card: FragmentCard,
    ) -> dict[str, Any]:
        input_payload = {
            "original_document_excerpt": _normalize_text(original_document_excerpt)[:SOURCE_EXCERPT_REVIEW_CHARS],
            "fragment_card": fragment_card.to_dict(),
            "field_rubric": dict(FRAGMENT_CARD_RUBRIC),
        }
        system_prompt, user_prompt = build_fragment_card_review_prompt(input_payload)
        return {
            "review_type": "fragment_card",
            "fragment_id": fragment_card.fragment_id,
            "doc_id": fragment_card.doc_id,
            "input": input_payload,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "expected_checks": list(FRAGMENT_CARD_REVIEW_CHECKS),
        }

    def build_cluster_prompt_artifact(
        self,
        *,
        cluster: FragmentCluster,
        members: Sequence[FragmentCard],
        representative_card: FragmentCard | None,
    ) -> dict[str, Any]:
        limited_members = list(members)[:CLUSTER_MEMBER_REVIEW_LIMIT]
        input_payload = {
            "cluster": cluster.to_dict(),
            "dedup_reason": cluster.dedup_reason,
            "representative_card": representative_card.to_dict() if representative_card is not None else None,
            "member_cards": [member.to_dict() for member in limited_members],
            "field_rubric": dict(CLUSTER_RUBRIC),
        }
        system_prompt, user_prompt = build_cluster_review_prompt(input_payload)
        return {
            "review_type": "fragment_cluster",
            "cluster_id": cluster.cluster_id,
            "representative_fragment_id": cluster.representative_fragment_id,
            "member_fragment_ids": [member.fragment_id for member in limited_members],
            "input": input_payload,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "expected_checks": list(CLUSTER_REVIEW_CHECKS),
        }

    def build_retrieval_prompt_artifact(
        self,
        *,
        case_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        input_payload = {
            **payload,
            "field_rubric": dict(RETRIEVAL_RUBRIC),
            "relative_judgment_rule": (
                "Do not score absolute literary quality. Compare selected references against "
                "decoy and rejected references for this SceneBrief."
            ),
        }
        system_prompt, user_prompt = build_retrieval_review_prompt(input_payload)
        selected_ids = [
            str(item.get("fragment_id"))
            for item in payload.get("selected_references", [])
            if isinstance(item, dict) and item.get("fragment_id")
        ]
        decoy_ids = [
            str(item.get("fragment_id"))
            for item in payload.get("decoy_references", [])
            if isinstance(item, dict) and item.get("fragment_id")
        ]
        return {
            "review_type": "retrieval_case",
            "case_id": case_id,
            "selected_fragment_ids": selected_ids,
            "decoy_fragment_ids": decoy_ids,
            "input": input_payload,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "expected_checks": list(RETRIEVAL_REVIEW_CHECKS),
        }

    def build_writer_ab_prompt_artifact(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        input_payload = {
            **payload,
            "field_rubric": dict(WRITER_AB_RUBRIC),
            "diagnostic_rule": (
                "Compare observable gains from KB references. The result is diagnostic only and must not "
                "override retrieval/rerank benchmark decisions."
            ),
        }
        system_prompt, user_prompt = build_writer_ab_review_prompt(input_payload)
        variants = input_payload.get("variants")
        variant_names = sorted(str(name) for name in variants) if isinstance(variants, dict) else []
        return {
            "review_type": "writer_ab",
            "variant_names": variant_names,
            "input": input_payload,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "expected_checks": list(WRITER_AB_REVIEW_CHECKS),
        }

    def review_fragment_card(
        self,
        *,
        original_document_excerpt: str,
        fragment_card: FragmentCard,
    ) -> KBFragmentCardReviewReport:
        artifact = self.build_fragment_card_prompt_artifact(
            original_document_excerpt=original_document_excerpt,
            fragment_card=fragment_card,
        )
        payload = self._generate_json(artifact)
        payload.update({"fragment_id": fragment_card.fragment_id, "doc_id": fragment_card.doc_id})
        return KBFragmentCardReviewReport.from_dict(payload)

    def review_cluster(
        self,
        *,
        cluster: FragmentCluster,
        members: Sequence[FragmentCard],
        representative_card: FragmentCard | None,
    ) -> KBClusterReviewReport:
        artifact = self.build_cluster_prompt_artifact(
            cluster=cluster,
            members=members,
            representative_card=representative_card,
        )
        payload = self._generate_json(artifact)
        payload.update(
            {
                "cluster_id": cluster.cluster_id,
                "representative_fragment_id": cluster.representative_fragment_id,
                "member_fragment_ids": [member.fragment_id for member in members],
            }
        )
        return KBClusterReviewReport.from_dict(payload)

    def review_retrieval_case(
        self,
        *,
        case_id: str,
        payload: dict[str, Any],
    ) -> KBRetrievalReviewReport:
        artifact = self.build_retrieval_prompt_artifact(case_id=case_id, payload=payload)
        model_payload = self._generate_json(artifact)
        model_payload.update(
            {
                "case_id": case_id,
                "selected_fragment_ids": artifact["selected_fragment_ids"],
                "decoy_fragment_ids": artifact["decoy_fragment_ids"],
            }
        )
        return KBRetrievalReviewReport.from_dict(model_payload)

    def review_writer_ab(self, *, payload: dict[str, Any]) -> KBWriterABReport:
        artifact = self.build_writer_ab_prompt_artifact(payload=payload)
        model_payload = self._generate_json(artifact)
        return KBWriterABReport.from_dict(model_payload)

    def _generate_json(self, prompt_artifact: dict[str, Any]) -> dict[str, Any]:
        if self.model_client is None:
            raise ValueError("CreativeKBReviewerService requires a model_client")
        fallback_factory = lambda: self._fallback_payload(prompt_artifact)
        use_fallback = bool(getattr(getattr(self.model_client, "settings", None), "dry_run", False))
        try:
            result = self.model_client.generate_json(
                system_prompt=prompt_artifact["system_prompt"],
                user_prompt=prompt_artifact["user_prompt"],
                fallback_factory=fallback_factory,
                use_fallback_on_error=use_fallback,
            )
        except TypeError:
            result = self.model_client.generate_json(
                system_prompt=prompt_artifact["system_prompt"],
                user_prompt=prompt_artifact["user_prompt"],
            )
        if isinstance(result, tuple):
            payload = result[0]
        else:
            payload = result
        if isinstance(payload, str):
            payload = self._parse_json_text(payload)
        if not isinstance(payload, dict):
            raise ValueError("creative kb reviewer JSON must be an object")
        return {str(key): value for key, value in payload.items()}

    def _fallback_payload(self, prompt_artifact: dict[str, Any]) -> dict[str, Any]:
        if prompt_artifact.get("review_type") == "fragment_cluster":
            return {
                "decision": "borderline",
                "score": 0.45,
                "summary": "Dry-run fallback cluster review; no real reviewer judgment was produced.",
                "checks": {name: "borderline" for name in CLUSTER_REVIEW_CHECKS},
                "issues": ["dry_run_fallback"],
            }
        if prompt_artifact.get("review_type") == "retrieval_case":
            return {
                "decision": "borderline",
                "score": 0.45,
                "summary": "Dry-run fallback retrieval review; no real reviewer judgment was produced.",
                "checks": {name: "borderline" for name in RETRIEVAL_REVIEW_CHECKS},
                "selected_fragment_ids": list(prompt_artifact.get("selected_fragment_ids") or []),
                "decoy_fragment_ids": list(prompt_artifact.get("decoy_fragment_ids") or []),
                "issues": ["dry_run_fallback"],
            }
        if prompt_artifact.get("review_type") == "writer_ab":
            return {
                "decision": "borderline",
                "score": 0.45,
                "winner": "tie",
                "variant_scores": {variant: 0.45 for variant in prompt_artifact.get("variant_names", [])},
                "negative_transfer_issues": ["dry_run_fallback"],
                "summary": "Dry-run fallback Writer A/B review; no real reviewer judgment was produced.",
                "checks": {name: "borderline" for name in WRITER_AB_REVIEW_CHECKS},
                "issues": ["dry_run_fallback"],
            }
        return {
            "decision": "borderline",
            "score": 0.45,
            "summary": "Dry-run fallback fragment card review; no real reviewer judgment was produced.",
            "checks": {name: "borderline" for name in FRAGMENT_CARD_REVIEW_CHECKS},
            "issues": ["dry_run_fallback"],
        }

    def _parse_json_text(self, raw_text: str) -> dict[str, Any]:
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
            raise ValueError("creative kb reviewer JSON must be an object")
        return {str(key): value for key, value in payload.items()}
