from __future__ import annotations

from typing import Iterable

from ..schemas.reviewer_schema import ReviewerManifest
from .base import BaseReviewer


class ReviewerRegistry:
    def __init__(self, reviewers: Iterable[BaseReviewer] | None = None) -> None:
        self._reviewers: dict[str, BaseReviewer] = {}
        for reviewer in reviewers or []:
            self.register(reviewer)

    def register(self, reviewer: BaseReviewer) -> None:
        manifest = reviewer.manifest()
        self._validate_formal_manifest(manifest)
        if manifest.reviewer_id in self._reviewers:
            raise ValueError(f"reviewer already registered: {manifest.reviewer_id}")
        self._reviewers[manifest.reviewer_id] = reviewer

    def get(self, reviewer_id: str, *, target_type: str | None = None) -> BaseReviewer:
        try:
            reviewer = self._reviewers[reviewer_id]
        except KeyError as exc:
            raise KeyError(f"unknown reviewer_id: {reviewer_id}") from exc
        manifest = reviewer.manifest()
        if target_type is not None and target_type not in set(manifest.supported_target_types):
            raise ValueError(f"reviewer {reviewer_id} does not support target_type={target_type}")
        return reviewer

    def manifests(self) -> list[ReviewerManifest]:
        return [reviewer.manifest() for reviewer in self._reviewers.values()]

    def manifest_dicts(self) -> list[dict]:
        return [manifest.to_dict() for manifest in self.manifests()]

    def available_for(self, target_type: str) -> list[ReviewerManifest]:
        return [manifest for manifest in self.manifests() if target_type in set(manifest.supported_target_types)]

    def _validate_formal_manifest(self, manifest: ReviewerManifest) -> None:
        # ReviewerManifest validates most invariants. Keep this explicit so callers
        # cannot bypass the formal registry with test or benchmark reviewers.
        marker = f"{manifest.reviewer_id} {manifest.metadata.get('kind', '')}".lower()
        if not manifest.requires_model or any(token in marker for token in ("fake", "baseline", "dry_run", "dry-run")):
            raise ValueError("fake, baseline, and non-model reviewers cannot be registered")
