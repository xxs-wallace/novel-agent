from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunLayout:
    base_dir: Path

    def ensure(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def freeze_root(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "freezes"

    def freeze_dir(self, run_id: str, freeze_stage: str) -> Path:
        return self.freeze_root(run_id) / freeze_stage

    def freeze_record_file(self, run_id: str, freeze_stage: str) -> Path:
        return self.freeze_dir(run_id, freeze_stage) / "freeze.json"

    def freeze_manifest_file(self, run_id: str) -> Path:
        return self.freeze_root(run_id) / "index.json"

    def current_file(self) -> Path:
        return self.base_dir / "current"

    def set_current(self, run_id: str) -> None:
        self.ensure()
        self.current_file().write_text(run_id, encoding="utf-8")

    def get_current(self) -> str | None:
        path = self.current_file()
        if not path.exists():
            return None
        run_id = path.read_text(encoding="utf-8").strip()
        return run_id or None
