from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

from ..constants import (
    DEFAULT_CLOSE_READ_DOC_BUDGET,
    DEFAULT_DOCUMENT_CHARS_MAX,
    DEFAULT_DOCUMENT_CHARS_MIN,
    DEFAULT_SEGMENT_CHUNK_MAX,
    DEFAULT_SEGMENT_CHUNK_MIN,
)


@dataclass(slots=True)
class SegmentationBookConfig:
    book_id: str
    source_root: str
    include_globs: list[str] = field(default_factory=lambda: ["**/*.md", "**/*.txt"])
    exclude_globs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SegmentationModelConfig:
    provider: str = "openai_compatible"
    model_name: str = "deepseek-chat"
    base_url: str | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: int = 120
    temperature: float = 0.2
    max_output_tokens: int = 8192
    model_type: str = "OpenAIModel"
    api_key: str | None = None
    api_key_file: str | None = None
    thinking: str | None = None
    reasoning_effort: str | None = None
    include_reasoning_content: bool = False


@dataclass(slots=True)
class SegmentationReadStrategyConfig:
    target_chunk_chars_min: int = DEFAULT_SEGMENT_CHUNK_MIN
    target_chunk_chars_max: int = DEFAULT_SEGMENT_CHUNK_MAX
    stop_at_newline_after_limit: bool = True
    preferred_document_chars_min: int = DEFAULT_DOCUMENT_CHARS_MIN
    preferred_document_chars_max: int = DEFAULT_DOCUMENT_CHARS_MAX
    allow_cross_file_merge: bool = False
    max_total_chars: int | None = None


@dataclass(slots=True)
class SegmentationStorageConfig:
    sqlite_path: str = '.indexes/novel.db'
    create_fts: bool = True
    upsert_on_conflict: bool = True


@dataclass(slots=True)
class SegmentationRuntimeConfig:
    dry_run: bool = False
    log_level: str = "INFO"
    save_raw_prompt_io: bool = True
    max_retries: int = 3
    resume_from_checkpoint: bool = False


@dataclass(slots=True)
class SegmentationAgentConfig:
    book: SegmentationBookConfig
    model: SegmentationModelConfig = field(default_factory=SegmentationModelConfig)
    read_strategy: SegmentationReadStrategyConfig = field(default_factory=SegmentationReadStrategyConfig)
    storage: SegmentationStorageConfig = field(default_factory=SegmentationStorageConfig)
    runtime: SegmentationRuntimeConfig = field(default_factory=SegmentationRuntimeConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "SegmentationAgentConfig":
        return cls(
            book=SegmentationBookConfig(**mapping["book"]),
            model=SegmentationModelConfig(**mapping.get("model", {})),
            read_strategy=SegmentationReadStrategyConfig(**mapping.get("read_strategy", {})),
            storage=SegmentationStorageConfig(**mapping.get("storage", {})),
            runtime=SegmentationRuntimeConfig(**mapping.get("runtime", {})),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "SegmentationAgentConfig":
        file_path = Path(path)
        raw = file_path.read_text(encoding="utf-8", errors="replace")
        if file_path.suffix.lower() == ".json":
            return cls.from_mapping(json.loads(raw))
        if yaml is None:
            raise RuntimeError("PyYAML is required to load YAML config files")
        loaded = yaml.safe_load(raw) or {}
        if not isinstance(loaded, dict):
            raise ValueError("Segmentation config must be a mapping")
        return cls.from_mapping(loaded)


@dataclass(slots=True)
class CloseReadModelConfig:
    model_type: str = "OpenAIModel"
    model_name: str = "deepseek-chat"
    provider: str = "openai_compatible"
    base_url: str | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"
    api_key: str | None = None
    api_key_file: str | None = None
    timeout_seconds: int = 180
    temperature: float = 0.2
    max_output_tokens: int = 8192
    thinking: str | None = None
    reasoning_effort: str | None = None
    include_reasoning_content: bool = False


@dataclass(slots=True)
class CloseReadRuntimeConfig:
    document_chars_budget: int = DEFAULT_CLOSE_READ_DOC_BUDGET
    dry_run: bool = False
    max_chapters: int | None = None
    export_debug_markdown: bool = True
    debug_markdown_path: str | None = None
    close_read_extraction_window_count: int = 1
    close_read_extraction_max_workers: int = 4
    character_evidence_coverage_audit: bool = True
    character_reduce_max_workers: int = 4
    character_reduce_pending_min_evidence_count: int = 6
    character_reduce_pending_min_evidence_chars: int = 3000
    world_evidence_signal_threshold: int = 70
    profile_update_detailed_min_doc_count: int = 2
    profile_update_detailed_min_total_chars: int = 1000


@dataclass(slots=True)
class CloseReadAgentConfig:
    book_id: str
    sqlite_path: str = '.indexes/novel.db'
    model: CloseReadModelConfig = field(default_factory=CloseReadModelConfig)
    runtime: CloseReadRuntimeConfig = field(default_factory=CloseReadRuntimeConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
