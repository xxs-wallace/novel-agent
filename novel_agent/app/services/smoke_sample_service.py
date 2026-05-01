from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ..schemas.smoke_schema import (
    AllowedOutlineScope,
    DocumentsCutoff,
    ForwardGuidance,
    LoadedSmokeStep,
    LoadedSmokeSample,
    SmokeMode,
    SmokeContinuationStepConfig,
    SmokeSampleConfig,
    SmokeTextArtifact,
)


class SmokeSampleService:
    def __init__(self, *, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root.resolve() if repo_root is not None else None

    def load(self, sample_path: str | Path) -> LoadedSmokeSample:
        sample_file = Path(sample_path).expanduser().resolve()
        payload = self._read_json(sample_file)
        config = self._build_config(payload)
        base_dir = sample_file.parent
        anchor_context = self._load_text_artifact(
            config.anchor_context_path,
            base_dir=base_dir,
        )
        recent_window = [
            self._load_text_artifact(path_text, base_dir=base_dir)
            for path_text in config.recent_window_refs
        ]
        reference_truth = self._load_text_artifact(
            config.reference_truth_path,
            base_dir=base_dir,
        )
        continuation_steps = config.continuation_steps or [
            SmokeContinuationStepConfig(
                step_id="step-1",
                target_segment_id=config.target_segment_id,
                anchor_context_path=config.anchor_context_path,
                recent_window_refs=list(config.recent_window_refs),
                reference_truth_path=config.reference_truth_path,
                metadata={},
            )
        ]
        steps = [
            LoadedSmokeStep(
                step_id=step_config.step_id,
                target_segment_id=step_config.target_segment_id,
                anchor_context=self._load_text_artifact(step_config.anchor_context_path, base_dir=base_dir),
                recent_window=[
                    self._load_text_artifact(path_text, base_dir=base_dir)
                    for path_text in (
                        step_config.recent_window_refs or list(config.recent_window_refs)
                    )
                ],
                reference_truth=self._load_text_artifact(step_config.reference_truth_path, base_dir=base_dir),
                metadata=dict(step_config.metadata),
            )
            for step_config in continuation_steps
        ]
        if steps:
            steps[0] = LoadedSmokeStep(
                step_id=steps[0].step_id,
                target_segment_id=steps[0].target_segment_id,
                anchor_context=anchor_context,
                recent_window=recent_window,
                reference_truth=reference_truth,
                metadata=dict(steps[0].metadata),
            )
        return LoadedSmokeSample(
            config=config,
            sample_path=str(sample_file),
            steps=steps,
        )

    def load_config(self, sample_path: str | Path) -> SmokeSampleConfig:
        sample_file = Path(sample_path).expanduser().resolve()
        payload = self._read_json(sample_file)
        return self._build_config(payload)

    def _read_json(self, sample_file: Path) -> dict[str, Any]:
        if not sample_file.exists():
            raise FileNotFoundError(f"smoke sample file not found: {sample_file}")
        payload = json.loads(sample_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("smoke sample json must contain an object")
        return {str(key): value for key, value in payload.items()}

    def _build_config(self, payload: dict[str, Any]) -> SmokeSampleConfig:
        documents_cutoff_payload = payload.get("documents_cutoff") or {}
        if not isinstance(documents_cutoff_payload, dict):
            raise ValueError("documents_cutoff must be an object")
        allowed_outline_scope_payload = payload.get("allowed_outline_scope") or {}
        if not isinstance(allowed_outline_scope_payload, dict):
            raise ValueError("allowed_outline_scope must be an object")
        forward_guidance_payload = payload.get("forward_guidance")
        if forward_guidance_payload is not None and not isinstance(forward_guidance_payload, dict):
            raise ValueError("forward_guidance must be null or an object")

        return SmokeSampleConfig(
            sample_id=str(payload.get("sample_id") or ""),
            book_id=str(payload.get("book_id") or ""),
            target_chapter_id=str(payload.get("target_chapter_id") or ""),
            target_segment_id=payload.get("target_segment_id"),
            mode=cast(SmokeMode, str(payload.get("mode") or "chapter_authorized")),
            anchor_context_path=str(payload.get("anchor_context_path") or ""),
            recent_window_refs=list(payload.get("recent_window_refs") or []),
            documents_cutoff=DocumentsCutoff(
                max_document_title_index=str(
                    documents_cutoff_payload.get("max_document_title_index") or ""
                )
            ),
            allowed_outline_scope=AllowedOutlineScope(
                chapter_range=list(allowed_outline_scope_payload.get("chapter_range") or []),
                allow_future_outline=bool(
                    allowed_outline_scope_payload.get("allow_future_outline", False)
                ),
            ),
            forward_guidance=(
                ForwardGuidance(**forward_guidance_payload)
                if forward_guidance_payload is not None
                else None
            ),
            reference_truth_path=str(payload.get("reference_truth_path") or ""),
            metadata=dict(payload.get("metadata") or {}),
            continuation_steps=[
                SmokeContinuationStepConfig(**item)
                for item in list(payload.get("continuation_steps") or [])
                if isinstance(item, dict)
            ],
        )

    def _load_text_artifact(
        self,
        path_text: str,
        *,
        base_dir: Path,
    ) -> SmokeTextArtifact:
        resolved_path = self._resolve_path(path_text, base_dir=base_dir)
        if not resolved_path.exists():
            raise FileNotFoundError(f"smoke sample text file not found: {resolved_path}")
        return SmokeTextArtifact(
            path=str(resolved_path),
            text=resolved_path.read_text(encoding="utf-8").strip(),
        )

    def _resolve_path(self, path_text: str, *, base_dir: Path) -> Path:
        candidate = Path(path_text).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()

        sample_relative = (base_dir / candidate).resolve()
        if sample_relative.exists():
            return sample_relative

        if self.repo_root is not None:
            repo_relative = (self.repo_root / candidate).resolve()
            if repo_relative.exists():
                return repo_relative

        return sample_relative
