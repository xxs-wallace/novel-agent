from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, cast

from ..app.schemas.orchestration_schema import (
    ChapterReplanRequest,
    FreezeArtifact,
    FreezeManifest,
    FreezeRecord,
    LengthPlanUpdate,
)
from ..schemas import RunConfig
from .layout import RunLayout


@dataclass(frozen=True, slots=True)
class RunWriter:
    layout: RunLayout

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _serialize_payload(self, payload: Any) -> Any:
        if hasattr(payload, "to_dict") and callable(payload.to_dict):
            return payload.to_dict()
        if is_dataclass(payload):
            return asdict(cast(Any, payload))
        if isinstance(payload, dict):
            return {str(key): self._serialize_payload(value) for key, value in payload.items()}
        if isinstance(payload, (list, tuple)):
            return [self._serialize_payload(item) for item in payload]
        return payload

    def _write_json_document(self, path: Path, payload: dict[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _artifact_kind_for_name(self, name: str) -> str:
        suffix = Path(name).suffix.lower()
        if suffix == ".md":
            return "markdown"
        if suffix == ".txt":
            return "text"
        return "json"

    def _load_json_data(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = raw.get("data") if isinstance(raw, dict) else raw
        return dict(payload) if isinstance(payload, dict) else {}

    def _draft_retention_index_path(self, run_id: str) -> Path:
        return self.layout.run_dir(run_id) / "draft_retention_index.json"

    def _draft_artifact_dir(self, run_id: str, draft_id: str) -> Path:
        return self.layout.run_dir(run_id) / "drafts" / draft_id

    def _load_draft_retention_index(self, run_id: str) -> dict[str, dict[str, Any]]:
        payload = self._load_json_data(self._draft_retention_index_path(run_id))
        drafts = payload.get("drafts")
        if not isinstance(drafts, dict):
            return {}
        normalized: dict[str, dict[str, Any]] = {}
        for draft_id, item in drafts.items():
            if isinstance(item, dict):
                normalized[str(draft_id)] = dict(item)
        return normalized

    def _write_draft_retention_index(
        self,
        run_id: str,
        drafts: Mapping[str, Mapping[str, Any]],
    ) -> Path:
        serialized = {
            str(draft_id): self._serialize_payload(payload)
            for draft_id, payload in drafts.items()
        }
        return self.write_json(run_id, "draft_retention_index.json", {"drafts": serialized})

    def prepare_run_dir(self, run_id: str) -> Path:
        self.layout.ensure()
        path = self.layout.run_dir(run_id)
        path.mkdir(parents=True, exist_ok=True)
        self.layout.set_current(run_id)
        return path

    def write_run_config(self, run_id: str, config: RunConfig) -> Path:
        run_dir = self.prepare_run_dir(run_id)
        path = run_dir / "config.json"
        payload: dict[str, Any] = {
            "run_id": run_id,
            "created_at": self._now_iso(),
            "config": config.to_dict(),
        }
        return self._write_json_document(path, payload)

    def write_json(self, run_id: str, name: str, payload: Any) -> Path:
        run_dir = self.prepare_run_dir(run_id)
        path = run_dir / name
        doc: dict[str, Any] = {
            "run_id": run_id,
            "created_at": self._now_iso(),
            "data": self._serialize_payload(payload),
        }
        return self._write_json_document(path, doc)

    def write_generation_review_decision(
        self,
        run_id: str,
        payload: Any,
        *,
        defaults: Mapping[str, Any] | None = None,
    ) -> Path:
        merged = self._merge_serialized_defaults(payload=payload, defaults=defaults)
        if not str(merged.get("schema_version") or "").strip():
            merged["schema_version"] = "1.0"
        merged["run_id"] = str(merged.get("run_id") or run_id).strip() or run_id
        if not str(merged.get("created_at") or "").strip():
            merged["created_at"] = self._now_iso()
        return self.write_json(run_id, "generation_review_decision.json", merged)

    def write_length_plan_update(
        self,
        run_id: str,
        payload: Any,
        *,
        defaults: Mapping[str, Any] | None = None,
    ) -> Path:
        merged = self._merge_serialized_defaults(payload=payload, defaults=defaults)
        if not str(merged.get("schema_version") or "").strip():
            merged["schema_version"] = "1.0"
        if not str(merged.get("created_at") or "").strip():
            merged["created_at"] = self._now_iso()
        normalized = LengthPlanUpdate(**merged).to_dict()
        return self.write_json(run_id, "length_plan_update.json", normalized)

    def write_chapter_replan_request(
        self,
        run_id: str,
        payload: Any,
        *,
        defaults: Mapping[str, Any] | None = None,
    ) -> Path:
        merged = self._merge_serialized_defaults(payload=payload, defaults=defaults)
        if not str(merged.get("schema_version") or "").strip():
            merged["schema_version"] = "1.0"
        if not str(merged.get("created_at") or "").strip():
            merged["created_at"] = self._now_iso()
        normalized = ChapterReplanRequest(**merged).to_dict()
        return self.write_json(run_id, "chapter_replan_request.json", normalized)

    def write_text(self, run_id: str, name: str, content: str) -> Path:
        run_dir = self.prepare_run_dir(run_id)
        path = run_dir / name
        path.write_text(str(content), encoding="utf-8")
        return path

    def rebuild_accepted_chapters_markdown(self, run_id: str) -> Path:
        index = self._load_draft_retention_index(run_id)
        accepted_records = [
            dict(record)
            for record in index.values()
            if str(record.get("retention_status") or "") == "accepted"
        ]
        accepted_records.sort(
            key=lambda record: (
                str(record.get("chapter_id") or ""),
                str(record.get("created_at") or ""),
                str(record.get("draft_id") or ""),
            )
        )

        sections = [f"# Accepted Chapters\n\nrun_id: {run_id}\n"]
        for record in accepted_records:
            draft_path = Path(str((record.get("archived_artifacts") or {}).get("draft.md") or ""))
            if not draft_path.exists():
                continue
            chapter_id = str(record.get("chapter_id") or "").strip()
            draft_id = str(record.get("draft_id") or "").strip()
            decision_id = str(record.get("decision_id") or "").strip()
            sections.append(
                "\n".join(
                    [
                        "",
                        f"## {chapter_id or 'chapter'}",
                        "",
                        f"- draft_id: {draft_id}",
                        f"- decision_id: {decision_id}",
                        "",
                        draft_path.read_text(encoding="utf-8"),
                        "",
                    ]
                )
            )
        return self.write_text(run_id, "accepted_chapters.md", "\n".join(sections).rstrip() + "\n")

    def sync_draft_retention_record(
        self,
        run_id: str,
        *,
        draft_id: str,
        chapter_id: str,
        decision_id: str,
        retention_status: str,
        decision_status: str,
        supersedes_draft_id: str = "",
        reviewer_type: str = "",
        created_at: str = "",
        include_memory_writeback: bool = False,
    ) -> dict[str, Any]:
        if not draft_id:
            raise ValueError("draft_id is required")
        run_dir = self.prepare_run_dir(run_id)
        draft_dir = self._draft_artifact_dir(run_id, draft_id)
        draft_dir.mkdir(parents=True, exist_ok=True)
        retained_artifacts = {
            "draft.md",
            "continuity_report.json",
            "state_delta.json",
            "generation_review_decision.json",
            "length_plan_update.json",
            "chapter_replan_request.json",
        }
        if include_memory_writeback:
            retained_artifacts.add("memory_writeback.json")

        index = self._load_draft_retention_index(run_id)
        record = dict(index.get(draft_id) or {})
        archived_artifacts = dict(record.get("archived_artifacts") or {})
        for name in sorted(retained_artifacts):
            source_path = run_dir / name
            if not source_path.exists():
                continue
            target_path = draft_dir / name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
            archived_artifacts[name] = str(target_path)

        memory_writeback_source_path = str(record.get("memory_writeback_source_path") or "").strip()
        if include_memory_writeback and (run_dir / "memory_writeback.json").exists():
            memory_writeback_source_path = str(run_dir / "memory_writeback.json")

        record.update(
            {
                "draft_id": draft_id,
                "chapter_id": chapter_id,
                "decision_id": decision_id,
                "decision_status": decision_status,
                "retention_status": retention_status,
                "active_for_consumption": retention_status in {"drafted", "accepted"},
                "eligible_for_writeback": retention_status == "accepted",
                "eligible_for_canon": retention_status == "accepted",
                "supersedes_draft_id": supersedes_draft_id,
                "superseded_by_draft_id": str(record.get("superseded_by_draft_id") or "").strip(),
                "reviewer_type": reviewer_type,
                "artifact_dir": str(draft_dir),
                "archived_artifacts": archived_artifacts,
                "memory_writeback_source_path": memory_writeback_source_path,
                "created_at": created_at or str(record.get("created_at") or "").strip() or self._now_iso(),
                "updated_at": self._now_iso(),
            }
        )
        index[draft_id] = record
        self._write_draft_retention_index(run_id, index)
        return record

    def mark_draft_superseded(
        self,
        run_id: str,
        *,
        draft_id: str,
        replacement_draft_id: str,
    ) -> dict[str, Any]:
        if not draft_id:
            raise ValueError("draft_id is required")
        index = self._load_draft_retention_index(run_id)
        record = dict(index.get(draft_id) or {})
        draft_dir = self._draft_artifact_dir(run_id, draft_id)
        draft_dir.mkdir(parents=True, exist_ok=True)
        record.update(
            {
                "draft_id": draft_id,
                "retention_status": "superseded",
                "active_for_consumption": False,
                "eligible_for_writeback": False,
                "eligible_for_canon": False,
                "superseded_by_draft_id": replacement_draft_id,
                "artifact_dir": str(draft_dir),
                "updated_at": self._now_iso(),
            }
        )
        index[draft_id] = record
        self._write_draft_retention_index(run_id, index)
        return record

    def _merge_serialized_defaults(
        self,
        *,
        payload: Any,
        defaults: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        serialized = self._serialize_payload(payload)
        if not isinstance(serialized, dict):
            raise TypeError("payload must serialize to a dict")
        merged: dict[str, Any] = {}
        default_payload = self._serialize_payload(defaults) if defaults is not None else {}
        if isinstance(default_payload, dict):
            merged.update({str(key): value for key, value in default_payload.items()})
        for key, value in serialized.items():
            key_text = str(key)
            if key_text in merged and value in ("", None):
                continue
            merged[key_text] = value
        return merged

    def list_freeze_records(self, run_id: str) -> list[FreezeRecord]:
        manifest_path = self.layout.freeze_manifest_file(run_id)
        if not manifest_path.exists():
            return []
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = FreezeManifest.from_dict(raw)
        return manifest.records

    def get_freeze_record(self, run_id: str, freeze_stage: str) -> FreezeRecord | None:
        for record in self.list_freeze_records(run_id):
            if record.freeze_stage == freeze_stage:
                return record
        return None

    def update_freeze_record_status(
        self,
        run_id: str,
        *,
        freeze_stage: str,
        status: str,
        summary: str | None = None,
    ) -> FreezeRecord:
        existing = self.get_freeze_record(run_id, freeze_stage)
        if existing is None:
            raise FileNotFoundError(f"Freeze record not found: {freeze_stage}")
        updated = replace(
            existing,
            status=status,
            summary=summary if summary is not None else existing.summary,
        )
        records = [record for record in self.list_freeze_records(run_id) if record.freeze_stage != freeze_stage]
        records.append(updated)
        records.sort(key=lambda item: item.freeze_stage)
        manifest_path = self.layout.freeze_manifest_file(run_id)
        self._write_json_document(
            manifest_path,
            {
                "run_id": run_id,
                "updated_at": self._now_iso(),
                **FreezeManifest(records=records).to_dict(),
            },
        )
        record_path = self.layout.freeze_record_file(run_id, freeze_stage)
        if record_path.exists():
            existing_doc = json.loads(record_path.read_text(encoding="utf-8"))
            created_at = str(existing_doc.get("created_at") or updated.frozen_at or self._now_iso())
        else:
            created_at = updated.frozen_at or self._now_iso()
        self._write_json_document(
            record_path,
            {
                "run_id": run_id,
                "created_at": created_at,
                "data": updated.to_dict(),
            },
        )
        return updated

    def invalidate_freezes(
        self,
        run_id: str,
        *,
        freeze_stages: list[str],
        reason: str = "",
    ) -> list[FreezeRecord]:
        updated: list[FreezeRecord] = []
        for freeze_stage in freeze_stages:
            record = self.get_freeze_record(run_id, freeze_stage)
            if record is None:
                continue
            updated.append(
                self.update_freeze_record_status(
                    run_id,
                    freeze_stage=freeze_stage,
                    status="invalidated",
                    summary=reason or record.summary,
                )
            )
        return updated

    def write_freeze_record(
        self,
        run_id: str,
        freeze_record: FreezeRecord,
        artifact_payloads: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        self.prepare_run_dir(run_id)
        frozen_at = freeze_record.frozen_at or self._now_iso()
        freeze_dir = self.layout.freeze_dir(run_id, freeze_record.freeze_stage)
        freeze_dir.mkdir(parents=True, exist_ok=True)

        recorded_artifacts = list(freeze_record.artifacts)
        written_paths: dict[str, str] = {}
        for name, payload in (artifact_payloads or {}).items():
            artifact_path = freeze_dir / name
            kind = self._artifact_kind_for_name(name)
            if kind == "json":
                self._write_json_document(
                    artifact_path,
                    {
                        "run_id": run_id,
                        "freeze_stage": freeze_record.freeze_stage,
                        "created_at": frozen_at,
                        "data": self._serialize_payload(payload),
                    },
                )
            else:
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_path.write_text(str(payload), encoding="utf-8")
            written_paths[name] = str(artifact_path)
            recorded_artifacts.append(
                FreezeArtifact(name=name, path=str(artifact_path), kind=cast(Any, self._artifact_kind_for_name(name)))
            )

        stored_record = replace(
            freeze_record,
            artifacts=recorded_artifacts,
            frozen_at=frozen_at,
        )
        record_path = self.layout.freeze_record_file(run_id, stored_record.freeze_stage)
        self._write_json_document(
            record_path,
            {
                "run_id": run_id,
                "created_at": frozen_at,
                "data": stored_record.to_dict(),
            },
        )
        written_paths["freeze.json"] = str(record_path)

        manifest_records = [
            record for record in self.list_freeze_records(run_id) if record.freeze_stage != stored_record.freeze_stage
        ]
        manifest_records.append(stored_record)
        manifest_records.sort(key=lambda item: item.freeze_stage)
        manifest = FreezeManifest(records=manifest_records)
        manifest_path = self.layout.freeze_manifest_file(run_id)
        self._write_json_document(
            manifest_path,
            {
                "run_id": run_id,
                "updated_at": frozen_at,
                **manifest.to_dict(),
            },
        )
        written_paths["freezes/index.json"] = str(manifest_path)
        return written_paths

    def write_run_artifacts(
        self,
        run_id: str,
        *,
        task: dict[str, Any],
        reading_pack: dict[str, Any],
        retrieval_bundle: dict[str, Any],
        scene_plan: dict[str, Any],
        draft_md: str,
        continuity_report: dict[str, Any],
        final_md: str,
    ) -> dict[str, str]:
        paths = {
            "task.json": str(self.write_json(run_id, "task.json", task)),
            "reading_pack.json": str(self.write_json(run_id, "reading_pack.json", reading_pack)),
            "retrieval_bundle.json": str(self.write_json(run_id, "retrieval_bundle.json", retrieval_bundle)),
            "scene_plan.json": str(self.write_json(run_id, "scene_plan.json", scene_plan)),
            "draft.md": str(self.write_text(run_id, "draft.md", draft_md)),
            "continuity_report.json": str(self.write_json(run_id, "continuity_report.json", continuity_report)),
            "final.md": str(self.write_text(run_id, "final.md", final_md)),
        }
        return paths
