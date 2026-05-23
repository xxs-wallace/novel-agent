from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ..llm import JsonModelClient, ModelSettings
from ..constants import DEFAULT_CLOSE_READING_STAGE
from ..repos.creative_kb_storage import init_creative_kb_schema
from ..repos.db import NovelAgentDB
from ..repos.documents_repo import DocumentsRepo
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..repos.narrative_memory_pages_repo import NarrativeMemoryPagesRepo
from ..repos.reading_progress_repo import ReadingProgressRepo
from ..reviewer.registry import ReviewerRegistry
from ..reviewer.reviewers import default_reviewers
from ..reviewer.runtime import ReviewerRuntime
from ..reviewer.tools import ReviewerKBTool
from ..schemas.config_schema import CloseReadAgentConfig
from ..schemas.narrative_memory_schema import MemoryQueryBudget
from ..schemas.reviewer_schema import (
    ReviewBudget,
    ReviewContextPolicy,
    ReviewRequest,
    ReviewTarget,
    utc_now,
)
from ..services.creative_kb_facade import CreativeKnowledgeBaseFacade
from ..services.chunk_reader_service import ChunkReaderService
from ..services.document_ingest_service import DocumentIngestService
from ..services.fragment_card_builder_service import FragmentCardBuilderService
from ..services.narrative_memory_query_service import NarrativeMemoryQueryService
from ..services.rerank_service import RerankService
from ..services.retrieval_facade import RetrievalFacade
from ..runner.close_read_runner import CloseReadRunner
from ..utils.json_utils import extract_json_blob


REVIEWER_SMOKE_IDS = (
    "outline_plot_development",
    "chapter_synopsis_plot_character",
    "local_draft_continuity",
    "memory_draft_consistency",
    "kb_draft_style_atmosphere",
)

DEFAULT_LONGZU_120KB_FIXTURE = Path("novel_agent/tests/longzu_120kb.txt")


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, *, limit: int = 280) -> str:
    compact = re.sub(r"\s+", " ", _text(text))
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


@dataclass(frozen=True, slots=True)
class ReviewerSmokeModelConfig:
    model_type: str = "OpenAIModel"
    model_name: str = "deepseek-chat"
    provider: str = "openai_compatible"
    base_url: str | None = "https://api.deepseek.com"
    api_key: str | None = None
    api_key_file: str | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.2
    max_output_tokens: int = 8192
    timeout_seconds: int = 180
    thinking: str | None = None
    reasoning_effort: str | None = None
    include_reasoning_content: bool = False

    def to_settings(self, *, timeout_seconds: int | None = None, max_output_tokens: int | None = None) -> ModelSettings:
        return ModelSettings(
            model_type=self.model_type,
            model_name=self.model_name,
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            api_key_file=self.api_key_file,
            api_key_env=self.api_key_env,
            temperature=self.temperature,
            max_output_tokens=max_output_tokens or self.max_output_tokens,
            timeout_seconds=timeout_seconds or self.timeout_seconds,
            retry_without_thinking_on_failure=True,
            thinking=self.thinking,
            reasoning_effort=self.reasoning_effort,
            include_reasoning_content=self.include_reasoning_content,
            dry_run=False,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("api_key"):
            payload["api_key"] = "***"
        return payload


@dataclass(frozen=True, slots=True)
class ReviewerSmokeConfig:
    repo_root: Path
    run_id: str | None = None
    source_path: Path | None = None
    output_root: Path | None = None
    case_fixture_path: Path | None = None
    book_id: str | None = None
    source_tail_chars: int = 48000
    heldout_ratio: float = 0.1
    heldout_min_chars: int = 3200
    segmentation_max_read_chars: int = 48000
    segmentation_target_chunk_chars_min: int = 5000
    segmentation_target_chunk_chars_max: int = 9000
    segmentation_preferred_document_chars_min: int = 2200
    segmentation_preferred_document_chars_max: int = 5000
    close_read_document_chars_budget: int = 48000
    close_read_max_chapters: int | None = None
    creative_kb_commit_batch_size: int = 8
    reviewer_json_repair_attempts: int = 0
    model: ReviewerSmokeModelConfig = field(default_factory=ReviewerSmokeModelConfig)

    def resolved_output_root(self) -> Path:
        root = self.output_root or self.repo_root / "runs" / "reviewer_smoke"
        root = root.expanduser()
        return (root if root.is_absolute() else self.repo_root / root).resolve()

    def resolved_source_path(self) -> Path:
        source = self.source_path or self.repo_root / DEFAULT_LONGZU_120KB_FIXTURE
        source = source.expanduser()
        return (source if source.is_absolute() else self.repo_root / source).resolve()

    def resolved_case_fixture_path(self) -> Path | None:
        if self.case_fixture_path is None:
            return None
        path = self.case_fixture_path.expanduser()
        return (path if path.is_absolute() else self.repo_root / path).resolve()


@dataclass(frozen=True, slots=True)
class ReviewerSmokeModelingArtifacts:
    run_dir: Path
    db_path: Path
    book_id: str
    source_path: Path
    source_manifest: dict[str, Any]
    memory_manifest: dict[str, Any]
    kb_manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReviewerSmokeSourceSplit:
    prefix_path: Path
    heldout_path: Path
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReviewerSmokeCase:
    reviewer_id: str
    target_type: str
    text: str
    expected_issue_types: list[str]
    dynamic_evidence: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    artifact_path: Path | None = None
    document_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_path"] = str(self.artifact_path) if self.artifact_path else ""
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewerSmokeCase":
        artifact_path = _text(data.get("artifact_path"))
        return cls(
            reviewer_id=_text(data.get("reviewer_id")),
            target_type=_text(data.get("target_type")),
            text=_text(data.get("text")),
            expected_issue_types=[_text(item) for item in data.get("expected_issue_types") or [] if _text(item)],
            dynamic_evidence=[dict(item) for item in data.get("dynamic_evidence") or [] if isinstance(item, Mapping)],
            metadata=dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), Mapping) else {},
            artifact_path=Path(artifact_path) if artifact_path else None,
            document_ids=[_text(item) for item in data.get("document_ids") or [] if _text(item)],
        )


class ReviewerSmokeCaseBuilder:
    """Builds constructed ReviewTarget.text values from a masked real-text split.

    Memory and KB are created from the prefix only. Held-out real text is then
    transformed by the model into Writer-like targets for each reviewer. The
    constructed targets are saved as smoke artifacts and are never written back
    into Memory or KB.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        model_client: JsonModelClient | None = None,
        case_fixture_path: Path | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.model_client = model_client
        self.case_fixture_path = case_fixture_path
        self._case_fixture_cache: dict[str, dict[str, Any]] | None = None
        self.memory_query_service = NarrativeMemoryQueryService(repo_root=repo_root)

    def build_cases(
        self,
        conn,
        *,
        book_id: str,
        run_dir: Path,
    ) -> list[ReviewerSmokeCase]:
        memory_evidence = self._select_memory_evidence(conn, book_id=book_id)
        kb_evidence = self._select_kb_evidence(conn)
        documents = DocumentsRepo().fetch_after_doc_id(conn, book_id=book_id)
        if not memory_evidence:
            raise RuntimeError("Reviewer smoke requires real Narrative Memory evidence; no memory candidates were found")
        if not kb_evidence:
            raise RuntimeError("Reviewer smoke requires real Creative KB evidence; no fragment cards were found")
        if not documents:
            raise RuntimeError("Reviewer smoke requires real segmented documents; no documents were found")
        if self.model_client is None:
            raise RuntimeError("Reviewer smoke case construction requires an available model_client")

        recent_docs = documents[-min(3, len(documents)) :]
        heldout_text = self._load_heldout_text(run_dir)
        generation_dir = run_dir / "modeling" / "case_generation"
        shared_context = {
            "heldout_excerpt": _safe_excerpt(heldout_text, limit=4200),
            "memory_evidence": memory_evidence[:6],
            "kb_evidence": kb_evidence[:6],
            "recent_document_window": [
                {
                    "doc_id": str(doc.doc_id),
                    "title": getattr(doc, "document_title", "") or "",
                    "excerpt": _safe_excerpt(doc.content, limit=700),
                }
                for doc in recent_docs
            ],
        }

        return [
            self._case_or_generate(
                reviewer_id="outline_plot_development",
                target_type="outline",
                expected_issue_types=["阶段推进跳跃", "剧情方向偏离", "因果链缺失"],
                construction_source="heldout_real_text_plus_real_memory",
                dynamic_evidence=memory_evidence[:2],
                shared_context=shared_context,
                generation_dir=generation_dir,
                instruction_zh=(
                    "把留出正文改造成一份 Writer 可能提交的后续 event list / 大纲。"
                    "它应保留部分真实素材，但故意制造阶段推进跳跃、剧情方向偏离或因果链缺失。"
                    "文本必须像大纲本身，不要写评语、测试说明或证据标签。"
                ),
            ),
            self._case_or_generate(
                reviewer_id="chapter_synopsis_plot_character",
                target_type="chapter_brief",
                expected_issue_types=["剧情合理性问题", "人物设定或关系状态冲突", "应触发真实 Memory Query"],
                construction_source="heldout_real_text_plus_real_memory",
                dynamic_evidence=memory_evidence[:3],
                shared_context=shared_context,
                generation_dir=generation_dir,
                instruction_zh=(
                    "把留出正文改造成一份自然的章节梗概 / chapter_brief。"
                    "它应像 Writer 对下一章的概述，包含章节开端、推进、人物行动和结尾，"
                    "但故意让人物设定、关系状态或行动动机与前 90% Memory 冲突。"
                    "文本必须是梗概，不要写‘虚假章节梗概’、评审意见或测试说明。"
                ),
            ),
            self._case_or_generate(
                reviewer_id="local_draft_continuity",
                target_type="draft",
                expected_issue_types=["局部承接断裂", "剧情发展中断", "文风突变"],
                construction_source="heldout_real_text_plus_recent_prefix_documents",
                dynamic_evidence=[
                    {
                        "source_type": "document",
                        "source_id": ",".join(str(doc.doc_id) for doc in recent_docs),
                        "summary_zh": "用于 Reviewer 解析的最近真实正文窗口，未写入构造 target.text。",
                    },
                    *memory_evidence[:1],
                ],
                shared_context=shared_context,
                generation_dir=generation_dir,
                document_ids=[str(doc.doc_id) for doc in recent_docs],
                instruction_zh=(
                    "把留出正文改造成一段 Writer 可能提交的最新草稿正文。"
                    "Reviewer 会通过 document_ids 看到最近真实正文窗口，所以 target.text 只写最新草稿本身。"
                    "草稿应故意不承接最近几段的动作、地点、情绪或句式节奏，出现局部断裂或文风突变。"
                    "不要把最近真实正文窗口、测试说明或证据标签写进 target.text。"
                ),
            ),
            self._case_or_generate(
                reviewer_id="memory_draft_consistency",
                target_type="draft",
                expected_issue_types=["历史矛盾", "人物状态或事件记录冲突", "应触发真实多轮 Memory Query"],
                construction_source="heldout_real_text_plus_real_memory",
                dynamic_evidence=memory_evidence[:4],
                shared_context=shared_context,
                generation_dir=generation_dir,
                instruction_zh=(
                    "把留出正文改造成一段自然正文草稿。"
                    "草稿应提及从真实 Memory 中动态抽取的人物、事件、关系、地点或设定，"
                    "并故意引入一个需要多轮 Memory Query 才能确认的历史矛盾。"
                    "不要暴露 Memory 证据文本，不要写评语或测试说明。"
                ),
            ),
            self._case_or_generate(
                reviewer_id="kb_draft_style_atmosphere",
                target_type="draft",
                expected_issue_types=["文笔偏离", "文风突变", "氛围偏离", "应触发真实 KB 查询"],
                construction_source="heldout_real_text_plus_real_creative_kb",
                dynamic_evidence=kb_evidence[:3],
                shared_context=shared_context,
                generation_dir=generation_dir,
                instruction_zh=(
                    "把留出正文改造成一段自然正文草稿，但故意偏离 Creative KB 中体现的文笔、节奏和氛围。"
                    "可以变得像现代汇报、说明书、轻浮吐槽或节奏过快的摘要，但仍要保留小说正文外观。"
                    "不要写评审意见、测试说明、KB 证据标签或‘文风偏离’这样的显式标签。"
                ),
            ),
        ]

    def _select_memory_evidence(self, conn, *, book_id: str) -> list[dict[str, Any]]:
        budget = MemoryQueryBudget(max_root_candidates=6, max_child_candidates=8, max_candidate_chars=1000, excerpt_budget=700)
        queries = ["主要人物 关系 状态 历史行动", "关键事件 因果链 当前阶段", "地点 设定 约束 冲突"]
        evidence: list[dict[str, Any]] = []
        seen: set[str] = set()
        for query in queries:
            state = self.memory_query_service.root_scan(conn, book_id=book_id, query=query, budget=budget)
            for item in state.current_candidates:
                source_id = _text(item.get("id"))
                if not source_id or source_id in seen:
                    continue
                seen.add(source_id)
                evidence.append(
                    {
                        "source_type": "memory",
                        "source_id": source_id,
                        "level": _text(item.get("level")),
                        "summary_zh": _safe_excerpt(_text(item.get("summary") or item.get("text")), limit=420),
                        "trace": state.trace[-2:],
                    }
                )
                if len(evidence) >= 6:
                    return evidence
        if evidence:
            return evidence
        pages = NarrativeMemoryPagesRepo().list_by_book(conn, book_id=book_id)
        for page in pages[:6]:
            evidence.append(
                {
                    "source_type": "memory",
                    "source_id": page.page_id,
                    "level": page.page_type,
                    "summary_zh": _safe_excerpt(page.summary, limit=420),
                    "trace": [{"operation": "memory_page_scan_for_case_selection", "source_scope": "real_memory_pages"}],
                }
            )
        return evidence

    def _select_kb_evidence(self, conn) -> list[dict[str, Any]]:
        cards = FragmentCardsRepo().list_representatives(conn)
        if not cards:
            cards = FragmentCardsRepo().list_all(conn)
        evidence: list[dict[str, Any]] = []
        for card in cards[:6]:
            evidence.append(
                {
                    "source_type": "kb",
                    "source_id": card.fragment_id,
                    "summary_zh": _safe_excerpt(card.content_summary or card.narrative_function_text, limit=360),
                    "style_profile_text": _safe_excerpt(card.style_profile_text, limit=360),
                    "source_excerpt": _safe_excerpt(card.source_excerpt, limit=360),
                    "preferred_tags": list(card.preferred_tags),
                }
            )
        return evidence

    def _load_heldout_text(self, run_dir: Path) -> str:
        manifest_path = run_dir / "modeling" / "source_manifest.json"
        if not manifest_path.exists():
            raise RuntimeError("Reviewer smoke source_manifest.json is required for held-out case construction")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        split = manifest.get("source_split") if isinstance(manifest.get("source_split"), Mapping) else {}
        heldout_path = Path(str(split.get("heldout_path") or ""))
        if not heldout_path.exists():
            raise RuntimeError("Reviewer smoke held-out source is missing; cannot construct real-text cases")
        heldout_text = heldout_path.read_text(encoding="utf-8").strip()
        if len(heldout_text) < 200:
            raise RuntimeError("Reviewer smoke held-out source is too short for meaningful case construction")
        return heldout_text

    def _generate_case(
        self,
        *,
        reviewer_id: str,
        target_type: str,
        expected_issue_types: list[str],
        construction_source: str,
        dynamic_evidence: list[dict[str, Any]],
        shared_context: Mapping[str, Any],
        generation_dir: Path,
        instruction_zh: str,
        document_ids: list[str] | None = None,
    ) -> ReviewerSmokeCase:
        system_prompt = (
            "你是 Reviewer Agent smoke 测试输入构造器。"
            "你的任务不是评审，而是把真实小说留出文本改造成 Writer 可能提交的自然输入。"
            "只能输出 JSON，不要解释。不得硬编码某部小说的专名映射；只能使用用户给出的文本和证据。"
        )
        user_prompt = (
            "请根据前 90% 已建模材料、真实 Memory/KB 摘要、最近正文窗口和后 10% 留出正文，"
            "构造一个用于指定 Reviewer 的 target.text。\n\n"
            f"reviewer_id: {reviewer_id}\n"
            f"target_type: {target_type}\n"
            f"构造要求: {instruction_zh}\n\n"
            "硬性约束：\n"
            "- 输出必须是 JSON object。\n"
            "- text 字段只能包含 Writer 可能提交的目标文本本身。\n"
            "- text 不得包含：constructed_for_smoke、Reviewer Smoke、虚假、测试、评审、证据、Memory 证据、KB 证据、最近真实正文窗口。\n"
            "- 不得把前序 Memory/KB 摘要原样粘贴进 text。\n"
            "- 可以利用留出正文的人物、事件、场景、语气和动作，然后进行有意但自然的扭曲。\n"
            "- local_draft_continuity 的 text 不得包含最近正文窗口；Reviewer 会通过 document_ids 另行获得上下文。\n\n"
            "返回 schema：\n"
            "{\n"
            '  "text": "Writer-like target text",\n'
            '  "construction_notes_zh": "简述如何从留出文本改造，不能写入 text",\n'
            '  "expected_issue_types": ["..."]\n'
            "}\n\n"
            f"shared_context:\n{json.dumps(shared_context, ensure_ascii=False, indent=2)}"
        )
        raw_text = str(self.model_client.generate_text(system_prompt=system_prompt, user_prompt=user_prompt))  # type: ignore[union-attr]
        generation_dir.mkdir(parents=True, exist_ok=True)
        raw_path = generation_dir / f"{reviewer_id}_raw.txt"
        raw_path.write_text(raw_text, encoding="utf-8")
        payload = extract_json_blob(raw_text)
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"case generation for {reviewer_id} must return a JSON object")
        text = _text(payload.get("text"))
        self._validate_generated_target_text(reviewer_id=reviewer_id, text=text)
        notes = _text(payload.get("construction_notes_zh"))
        model_expected = payload.get("expected_issue_types")
        if isinstance(model_expected, list):
            expected_issue_types = [_text(item) for item in model_expected if _text(item)] or expected_issue_types
        case_payload = {
            "reviewer_id": reviewer_id,
            "target_type": target_type,
            "text": text,
            "construction_notes_zh": notes,
            "expected_issue_types": expected_issue_types,
            "dynamic_evidence": dynamic_evidence,
            "document_ids": document_ids or [],
        }
        _write_json(generation_dir / f"{reviewer_id}.json", case_payload)
        return ReviewerSmokeCase(
            reviewer_id=reviewer_id,
            target_type=target_type,
            text=text,
            expected_issue_types=expected_issue_types,
            dynamic_evidence=dynamic_evidence,
            document_ids=document_ids or [],
            metadata={
                "constructed_for_smoke": True,
                "construction_source": construction_source,
                "heldout_text_used": True,
                "case_generation_model_id": getattr(getattr(self.model_client, "settings", None), "model_name", ""),
                "case_generation_raw_response_path": str(raw_path),
                "construction_notes_zh": notes,
            },
        )

    def _case_or_generate(
        self,
        *,
        reviewer_id: str,
        target_type: str,
        expected_issue_types: list[str],
        construction_source: str,
        dynamic_evidence: list[dict[str, Any]],
        shared_context: Mapping[str, Any],
        generation_dir: Path,
        instruction_zh: str,
        document_ids: list[str] | None = None,
    ) -> ReviewerSmokeCase:
        cached = self._case_from_fixture(
            reviewer_id=reviewer_id,
            target_type=target_type,
            expected_issue_types=expected_issue_types,
            construction_source=construction_source,
            dynamic_evidence=dynamic_evidence,
            document_ids=document_ids or [],
        )
        if cached is not None:
            generation_dir.mkdir(parents=True, exist_ok=True)
            _write_json(generation_dir / f"{reviewer_id}.json", cached.to_dict())
            return cached
        return self._generate_case(
            reviewer_id=reviewer_id,
            target_type=target_type,
            expected_issue_types=expected_issue_types,
            construction_source=construction_source,
            dynamic_evidence=dynamic_evidence,
            shared_context=shared_context,
            generation_dir=generation_dir,
            instruction_zh=instruction_zh,
            document_ids=document_ids,
        )

    def _case_from_fixture(
        self,
        *,
        reviewer_id: str,
        target_type: str,
        expected_issue_types: list[str],
        construction_source: str,
        dynamic_evidence: list[dict[str, Any]],
        document_ids: list[str],
    ) -> ReviewerSmokeCase | None:
        fixtures = self._load_case_fixtures()
        fixture = fixtures.get(reviewer_id)
        if fixture is None:
            return None
        text = _text(fixture.get("text"))
        self._validate_generated_target_text(reviewer_id=reviewer_id, text=text)
        metadata = dict(fixture.get("metadata") or {}) if isinstance(fixture.get("metadata"), Mapping) else {}
        metadata.update(
            {
                "constructed_for_smoke": True,
                "construction_source": metadata.get("construction_source") or construction_source,
                "heldout_text_used": bool(metadata.get("heldout_text_used", True)),
                "case_fixture_reused": True,
                "case_fixture_path": str(self.case_fixture_path or ""),
            }
        )
        cached_expected = fixture.get("expected_issue_types")
        return ReviewerSmokeCase(
            reviewer_id=reviewer_id,
            target_type=_text(fixture.get("target_type")) or target_type,
            text=text,
            expected_issue_types=[_text(item) for item in cached_expected or [] if _text(item)] or expected_issue_types,
            dynamic_evidence=dynamic_evidence,
            document_ids=document_ids or [_text(item) for item in fixture.get("document_ids") or [] if _text(item)],
            metadata=metadata,
        )

    def _load_case_fixtures(self) -> dict[str, dict[str, Any]]:
        if self._case_fixture_cache is not None:
            return self._case_fixture_cache
        self._case_fixture_cache = {}
        if self.case_fixture_path is None:
            return self._case_fixture_cache
        if not self.case_fixture_path.exists():
            raise RuntimeError(f"Reviewer smoke case fixture not found: {self.case_fixture_path}")
        payload = json.loads(self.case_fixture_path.read_text(encoding="utf-8"))
        raw_cases = payload.get("cases") if isinstance(payload, Mapping) else payload
        if isinstance(raw_cases, Mapping):
            items = raw_cases.values()
        elif isinstance(raw_cases, list):
            items = raw_cases
        else:
            raise RuntimeError("Reviewer smoke case fixture must contain a cases object or list")
        for item in items:
            if isinstance(item, Mapping):
                reviewer_id = _text(item.get("reviewer_id"))
                if reviewer_id:
                    self._case_fixture_cache[reviewer_id] = dict(item)
        return self._case_fixture_cache

    def _validate_generated_target_text(self, *, reviewer_id: str, text: str) -> None:
        if len(text) < 80:
            raise RuntimeError(f"case generation for {reviewer_id} returned an unusably short target.text")
        forbidden = (
            "constructed_for_smoke",
            "Reviewer Smoke",
            "虚假",
            "评审",
            "Memory 证据",
            "KB 证据",
            "最近真实正文窗口",
        )
        hits = [item for item in forbidden if item in text]
        if hits:
            raise RuntimeError(f"case generation for {reviewer_id} leaked smoke labels into target.text: {hits}")


class ReviewerSmokeService:
    def __init__(
        self,
        *,
        repo_root: Path,
        model_client_factory: Callable[[ReviewerSmokeModelConfig], JsonModelClient] | None = None,
        modeling_builder: Callable[[ReviewerSmokeConfig, Path, str], ReviewerSmokeModelingArtifacts] | None = None,
        case_builder: ReviewerSmokeCaseBuilder | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.model_client_factory = model_client_factory or self._build_model_client
        self.modeling_builder = modeling_builder
        self.case_builder = case_builder

    def run(self, config: ReviewerSmokeConfig) -> dict[str, Any]:
        run_id = _text(config.run_id) or f"{_utc_compact()}-{uuid.uuid4().hex[:8]}"
        run_dir = config.resolved_output_root() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = run_dir / "summary.json"
        summary: dict[str, Any] = {
            "schema_version": "1.0",
            "run_id": run_id,
            "status": "initialized",
            "score_usage": "reference_only",
            "run_dir": str(run_dir),
            "created_at": utc_now(),
            "model": config.model.to_dict(),
            "reviewers": {},
            "notes_zh": "Reviewer 分数和意见只作为参考，不作为 Writer 或 Benchmark 通过标准。",
        }
        _write_json(summary_path, summary)
        try:
            model_client = self.model_client_factory(config.model)
            modeling = (self.modeling_builder or self._build_real_modeling)(config, run_dir, run_id)
            summary["modeling"] = {
                "book_id": modeling.book_id,
                "db_path": str(modeling.db_path),
                "source_manifest_path": str(run_dir / "modeling" / "source_manifest.json"),
                "memory_manifest_path": str(run_dir / "modeling" / "memory_manifest.json"),
                "kb_manifest_path": str(run_dir / "modeling" / "kb_manifest.json"),
            }
            reports = self._run_reviewer_cases(config, run_dir=run_dir, modeling=modeling, model_client=model_client)
            summary["reviewers"] = reports
            summary["status"] = "success" if all(item["status"] == "success" for item in reports.values()) else "failed"
            summary["case_fixture_path"] = str(self._write_successful_case_fixtures(run_dir=run_dir, reports=reports))
            summary["markdown_report_path"] = str(self._write_markdown_report(run_dir=run_dir, summary=summary))
            summary["completed_at"] = utc_now()
            _write_json(summary_path, summary)
            return summary
        except RuntimeError as exc:
            status = "needs_model" if "api key" in str(exc).lower() or "model" in str(exc).lower() else "failed"
            summary.update({"status": status, "error": str(exc), "completed_at": utc_now()})
            _write_json(summary_path, summary)
            return summary
        except Exception as exc:
            summary.update({"status": "failed", "error": str(exc), "completed_at": utc_now()})
            _write_json(summary_path, summary)
            return summary

    def _run_reviewer_cases(
        self,
        config: ReviewerSmokeConfig,
        *,
        run_dir: Path,
        modeling: ReviewerSmokeModelingArtifacts,
        model_client: JsonModelClient,
    ) -> dict[str, dict[str, Any]]:
        registry = ReviewerRegistry(default_reviewers())
        runtime_artifacts = run_dir / "_runtime_artifacts"
        runtime = ReviewerRuntime(
            model_client=model_client,
            artifact_root=runtime_artifacts,
            kb_tool=ReviewerKBTool(
                retrieval_facade=RetrievalFacade(rerank_service=RerankService(model_client=model_client))
            ),
        )
        builder = self.case_builder or ReviewerSmokeCaseBuilder(
            repo_root=self.repo_root,
            model_client=model_client,
            case_fixture_path=config.resolved_case_fixture_path(),
        )
        reports: dict[str, dict[str, Any]] = {}
        db = NovelAgentDB(modeling.db_path)
        with db.connect() as conn:
            cases = builder.build_cases(conn, book_id=modeling.book_id, run_dir=run_dir)
            missing = set(REVIEWER_SMOKE_IDS) - {case.reviewer_id for case in cases}
            if missing:
                raise RuntimeError(f"Reviewer smoke case builder did not produce required cases: {sorted(missing)}")
            for case in cases:
                case_dir = run_dir / "cases" / case.reviewer_id
                case_dir.mkdir(parents=True, exist_ok=True)
                _write_json(case_dir / "smoke_case.json", case.to_dict())
                reviewer = registry.get(case.reviewer_id, target_type=case.target_type)
                manifest = reviewer.manifest()
                request = self._request_for_case(
                    run_id=run_dir.name,
                    book_id=modeling.book_id,
                    case=case,
                    budget=self._budget_for_smoke(manifest.default_budget, config=config),
                )
                report = runtime.run(request, reviewer=reviewer, conn=conn)
                self._copy_runtime_case_artifacts(runtime_artifacts, request_id=request.review_request_id, reviewer_id=case.reviewer_id, case_dir=case_dir)
                report_path = case_dir / "report.json"
                if not report_path.exists() and (case_dir / "reviewer_report.json").exists():
                    (case_dir / "reviewer_report.json").replace(report_path)
                reports[case.reviewer_id] = self._summary_for_report(report.to_dict())
        return reports

    def _budget_for_smoke(self, default_budget: Mapping[str, Any], *, config: ReviewerSmokeConfig) -> ReviewBudget:
        payload = dict(default_budget)
        payload["json_repair_attempts"] = max(0, int(config.reviewer_json_repair_attempts))
        return ReviewBudget.from_dict(payload)

    def _request_for_case(
        self,
        *,
        run_id: str,
        book_id: str,
        case: ReviewerSmokeCase,
        budget: ReviewBudget,
    ) -> ReviewRequest:
        target = ReviewTarget(
            target_id=f"target-{run_id}-{case.reviewer_id}",
            target_type=case.target_type,
            text=case.text,
            document_ids=case.document_ids,
            artifact_path=str(case.artifact_path) if case.artifact_path else "",
            artifact_id=f"smoke-artifact-{case.reviewer_id}" if case.artifact_path else "",
            source_refs=[
                {
                    "source_type": item.get("source_type", "memory"),
                    "source_id": item.get("source_id", ""),
                    "label": item.get("level", item.get("summary_zh", "")),
                }
                for item in case.dynamic_evidence
            ],
            metadata={
                **case.metadata,
                "expected_issue_types": case.expected_issue_types,
                "dynamic_evidence": case.dynamic_evidence,
            },
        )
        return ReviewRequest(
            review_request_id=f"review-smoke-{run_id}-{case.reviewer_id}",
            book_id=book_id,
            target=target,
            reviewer_ids=[case.reviewer_id],
            context_policy=ReviewContextPolicy(
                purpose="diagnostic",
                allow_memory=True,
                allow_kb=True,
                allow_writer_artifacts=True,
                allow_reference_truth=False,
                leakage_guard="prefix_only",
                notes="Reviewer real-model smoke; constructed targets are not written to Memory/KB.",
            ),
            budget=budget,
            user_focus="真实模型 smoke：检查构造目标中的明显偏离，并保留 score_usage=reference_only。",
            created_at=utc_now(),
            metadata={
                "constructed_for_smoke": True,
                "score_usage_note": "reference_only; not a writer or benchmark pass/fail decision",
            },
        )

    def _copy_runtime_case_artifacts(self, artifact_root: Path, *, request_id: str, reviewer_id: str, case_dir: Path) -> None:
        source_dir = artifact_root / request_id / reviewer_id
        if not source_dir.exists():
            return
        for name in ("review_request.json", "resolved_target.json", "loop_trace.json"):
            src = source_dir / name
            if src.exists():
                shutil.copy2(src, case_dir / name)
        report_src = source_dir / "reviewer_report.json"
        if report_src.exists():
            shutil.copy2(report_src, case_dir / "report.json")
        raw_src = source_dir / "raw_model_responses"
        if raw_src.exists():
            raw_dst = case_dir / "raw_model_responses"
            if raw_dst.exists():
                shutil.rmtree(raw_dst)
            shutil.copytree(raw_src, raw_dst)

    def _summary_for_report(self, report: Mapping[str, Any]) -> dict[str, Any]:
        findings = [
            {
                "severity": item.get("severity"),
                "category": item.get("category"),
                "message_zh": item.get("message_zh"),
                "evidence_refs": item.get("evidence_refs", []),
            }
            for item in list(report.get("findings") or [])[:5]
            if isinstance(item, Mapping)
        ]
        return {
            "status": report.get("status"),
            "score_usage": report.get("score_usage", "reference_only"),
            "score": report.get("score"),
            "summary_zh": report.get("summary_zh", ""),
            "main_findings": findings,
            "memory_trace_present": bool(report.get("memory_query_trace")),
            "kb_trace_present": bool(report.get("kb_query_trace")),
            "model_id": report.get("model_id", ""),
        }

    def _write_markdown_report(self, *, run_dir: Path, summary: Mapping[str, Any]) -> Path:
        path = run_dir / "reviewer_smoke_constructed_cases_and_reports.md"
        lines = [
            "# Reviewer Smoke Constructed Cases And Reports",
            "",
            f"- run_id: {summary.get('run_id', run_dir.name)}",
            f"- status: {summary.get('status', '')}",
            f"- score_usage: {summary.get('score_usage', 'reference_only')}",
            f"- run_dir: {run_dir}",
            "",
        ]
        source_manifest_path = run_dir / "modeling" / "source_manifest.json"
        if source_manifest_path.exists():
            source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
            split = source_manifest.get("source_split") if isinstance(source_manifest.get("source_split"), Mapping) else {}
            lines.extend(
                [
                    "## Source Split",
                    "",
                    f"- memory_kb_source_scope: {split.get('memory_kb_source_scope', '')}",
                    f"- review_target_source_scope: {split.get('review_target_source_scope', '')}",
                    f"- prefix_chars: {split.get('prefix_chars', '')}",
                    f"- heldout_chars: {split.get('heldout_chars', '')}",
                    "",
                ]
            )
        for reviewer_id in REVIEWER_SMOKE_IDS:
            case_dir = run_dir / "cases" / reviewer_id
            smoke_case_path = case_dir / "smoke_case.json"
            report_path = case_dir / "report.json"
            if not smoke_case_path.exists():
                continue
            smoke_case = json.loads(smoke_case_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
            lines.extend(
                [
                    f"## {reviewer_id}",
                    "",
                    f"- target_type: {smoke_case.get('target_type', '')}",
                    f"- constructed_for_smoke: {smoke_case.get('metadata', {}).get('constructed_for_smoke')}",
                    f"- construction_source: {smoke_case.get('metadata', {}).get('construction_source', '')}",
                    f"- status: {report.get('status', '')}",
                    f"- score_usage: {report.get('score_usage', 'reference_only')}",
                    f"- score: {report.get('score', '')}",
                    "",
                    "### Constructed Target",
                    "",
                    "```text",
                    str(smoke_case.get("text", "")).strip(),
                    "```",
                    "",
                    "### Review Summary",
                    "",
                    str(report.get("summary_zh", "")).strip() or "(no report summary)",
                    "",
                    "### Main Findings",
                    "",
                ]
            )
            findings = report.get("findings") if isinstance(report.get("findings"), list) else []
            if findings:
                for item in findings[:6]:
                    if isinstance(item, Mapping):
                        lines.append(
                            f"- [{item.get('severity', '')}] {item.get('category', '')}: {item.get('message_zh', '')}"
                        )
            else:
                lines.append("- (no findings)")
            lines.append("")
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    def _write_successful_case_fixtures(self, *, run_dir: Path, reports: Mapping[str, Mapping[str, Any]]) -> Path:
        cases: dict[str, dict[str, Any]] = {}
        for reviewer_id, report in reports.items():
            if report.get("status") != "success":
                continue
            smoke_case_path = run_dir / "cases" / reviewer_id / "smoke_case.json"
            if not smoke_case_path.exists():
                continue
            payload = json.loads(smoke_case_path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                cases[reviewer_id] = dict(payload)
        fixture = {
            "schema_version": "1.0",
            "source_run_id": run_dir.name,
            "created_at": utc_now(),
            "usage_zh": "传给 run_reviewer_smoke.py --case-fixture 可复用已成功 Reviewer 的构造输入；未包含的 Reviewer 会重新构造。",
            "case_count": len(cases),
            "cases": cases,
        }
        path = run_dir / "modeling" / "case_generation" / "successful_case_fixtures.json"
        _write_json(path, fixture)
        return path

    def _build_model_client(self, model_config: ReviewerSmokeModelConfig) -> JsonModelClient:
        return JsonModelClient(model_config.to_settings())

    def _build_real_modeling(self, config: ReviewerSmokeConfig, run_dir: Path, run_id: str) -> ReviewerSmokeModelingArtifacts:
        book_id = _text(config.book_id) or f"reviewer-smoke-{run_id}"
        modeling_dir = run_dir / "modeling"
        source_root = modeling_dir / "source"
        source_root.mkdir(parents=True, exist_ok=True)
        source_split = self._prepare_source_split(config, source_root=source_root)
        db_path = modeling_dir / "reviewer_smoke.db"
        source_manifest = self._run_segmentation(
            config,
            db_path=db_path,
            book_id=book_id,
            source_root=source_root,
            source_path=source_split.prefix_path,
        )
        source_manifest["source_split"] = source_split.manifest
        close_manifest = self._run_close_read(config, db_path=db_path, book_id=book_id, modeling_dir=modeling_dir)
        kb_manifest = self._run_creative_kb(config, db_path=db_path, book_id=book_id)
        memory_manifest = self._memory_manifest(db_path=db_path, book_id=book_id)
        _write_json(modeling_dir / "source_manifest.json", source_manifest)
        _write_json(modeling_dir / "rough_read_summary.json", source_manifest)
        _write_json(modeling_dir / "close_read_summary.json", close_manifest)
        _write_json(modeling_dir / "memory_manifest.json", memory_manifest)
        _write_json(modeling_dir / "kb_manifest.json", kb_manifest)
        return ReviewerSmokeModelingArtifacts(
            run_dir=run_dir,
            db_path=db_path,
            book_id=book_id,
            source_path=source_split.prefix_path,
            source_manifest=source_manifest,
            memory_manifest=memory_manifest,
            kb_manifest=kb_manifest,
        )

    def _prepare_source_split(self, config: ReviewerSmokeConfig, *, source_root: Path) -> ReviewerSmokeSourceSplit:
        resolved_source = config.resolved_source_path()
        if not resolved_source.exists():
            raise FileNotFoundError(f"reviewer smoke source not found: {resolved_source}")
        raw = resolved_source.read_text(encoding="utf-8", errors="replace")
        tail = raw[-max(1000, int(config.source_tail_chars)) :]
        normalized = self._sentence_per_line_tail(tail)
        sentences = [item.strip() for item in normalized.splitlines() if item.strip()]
        if len(sentences) < 12:
            raise RuntimeError("Reviewer smoke source needs enough sentence boundaries for prefix/held-out split")
        heldout_ratio = min(0.4, max(0.05, float(config.heldout_ratio)))
        total_chars = sum(len(item) for item in sentences)
        target_heldout_chars = max(int(total_chars * heldout_ratio), int(config.heldout_min_chars))
        heldout_sentences: list[str] = []
        heldout_chars = 0
        for sentence in reversed(sentences):
            if heldout_sentences and heldout_chars >= target_heldout_chars:
                break
            heldout_sentences.append(sentence)
            heldout_chars += len(sentence)
        heldout_sentences.reverse()
        prefix_sentences = sentences[: len(sentences) - len(heldout_sentences)]
        if len(prefix_sentences) < 8 or not heldout_sentences:
            raise RuntimeError("Reviewer smoke prefix/held-out split produced too little usable text")
        prefix_text = "\n".join(prefix_sentences).strip() + "\n"
        heldout_text = "\n".join(heldout_sentences).strip() + "\n"
        prefix_path = source_root / "reviewer_smoke_prefix_source.txt"
        heldout_path = source_root / "reviewer_smoke_heldout_source.txt"
        prefix_path.write_text(prefix_text, encoding="utf-8")
        heldout_path.write_text(heldout_text, encoding="utf-8")
        manifest = {
            "schema_version": "1.0",
            "original_source_path": str(resolved_source),
            "source_tail_chars_requested": int(config.source_tail_chars),
            "heldout_ratio_requested": float(config.heldout_ratio),
            "heldout_min_chars": int(config.heldout_min_chars),
            "split_strategy": "tail_window_sentence_boundary_prefix_heldout",
            "prefix_path": str(prefix_path),
            "heldout_path": str(heldout_path),
            "prefix_chars": len(prefix_text),
            "heldout_chars": len(heldout_text),
            "prefix_sentence_count": len(prefix_sentences),
            "heldout_sentence_count": len(heldout_sentences),
            "memory_kb_source_scope": "prefix_only",
            "review_target_source_scope": "heldout_transformed_only",
            "constructed_for_smoke_written_to_memory_or_kb": False,
        }
        _write_json(source_root / "source_split_manifest.json", manifest)
        return ReviewerSmokeSourceSplit(prefix_path=prefix_path, heldout_path=heldout_path, manifest=manifest)

    def _sentence_per_line_tail(self, text: str) -> str:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        sentences = [item.strip() for item in re.split(r"(?<=。)\s*", normalized) if item.strip()]
        if len(sentences) < 8:
            sentences = [item.strip() for item in normalized.splitlines() if item.strip()]
        return "\n".join(sentences).strip() + "\n"

    def _run_segmentation(
        self,
        config: ReviewerSmokeConfig,
        *,
        db_path: Path,
        book_id: str,
        source_root: Path,
        source_path: Path,
    ) -> dict[str, Any]:
        model_client = JsonModelClient(config.model.to_settings())
        reader = ChunkReaderService(
            target_min_chars=int(config.segmentation_target_chunk_chars_min),
            target_max_chars=int(config.segmentation_target_chunk_chars_max),
            stop_at_newline_after_limit=True,
            max_total_chars=int(config.segmentation_max_read_chars),
        )
        batches = reader.iter_batches([source_path])
        if not batches:
            raise RuntimeError("Reviewer smoke source produced no rough-read batches")
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            result = DocumentIngestService(
                model_client=model_client,
                documents_repo=DocumentsRepo(),
                progress_repo=ReadingProgressRepo(),
                preferred_document_chars_min=int(config.segmentation_preferred_document_chars_min),
                preferred_document_chars_max=int(config.segmentation_preferred_document_chars_max),
            ).ingest_batches(
                conn=conn,
                repo_root=self.repo_root,
                book_id=book_id,
                batches=batches,
                run_id=f"reviewer-smoke-segmentation-{uuid.uuid4().hex[:8]}",
                reset_book=True,
                initial_title_index=1,
            )
            ReadingProgressRepo().upsert(
                conn,
                {
                    "book_id": book_id,
                    "agent_stage": DEFAULT_CLOSE_READING_STAGE,
                    "current_doc_id": None,
                    "current_document_title_index": None,
                    "current_source_path": None,
                    "current_source_offset": None,
                    "last_completed_doc_id": None,
                    "last_completed_title_index": None,
                    "last_completed_chapter_id": None,
                    "status": {"state": "idle"},
                    "checkpoint_token": None,
                    "updated_at": utc_now(),
                },
            )
            conn.commit()
        return {
            "schema_version": "1.0",
            "source_path": str(source_path),
            "source_root": str(source_root),
            "db_path": str(db_path),
            "book_id": result.book_id,
            "inserted_documents": result.inserted_documents,
            "batch_count": result.batch_count,
            "real_model_required": True,
            "constructed_for_smoke": False,
            "rough_read_entry": "DocumentIngestService.real_segmentation_prompt",
        }

    def _run_close_read(self, config: ReviewerSmokeConfig, *, db_path: Path, book_id: str, modeling_dir: Path) -> dict[str, Any]:
        close_config = CloseReadAgentConfig(book_id=book_id, sqlite_path=str(db_path))
        close_config.model.model_type = config.model.model_type
        close_config.model.model_name = config.model.model_name
        close_config.model.provider = config.model.provider
        close_config.model.base_url = config.model.base_url
        close_config.model.api_key = config.model.api_key
        close_config.model.api_key_file = config.model.api_key_file
        close_config.model.api_key_env = config.model.api_key_env
        close_config.model.temperature = config.model.temperature
        close_config.model.max_output_tokens = config.model.max_output_tokens
        close_config.model.timeout_seconds = config.model.timeout_seconds
        close_config.model.thinking = config.model.thinking
        close_config.model.reasoning_effort = config.model.reasoning_effort
        close_config.model.include_reasoning_content = config.model.include_reasoning_content
        close_config.runtime.document_chars_budget = int(config.close_read_document_chars_budget)
        close_config.runtime.max_chapters = config.close_read_max_chapters
        close_config.runtime.debug_markdown_path = str(modeling_dir / "close_read_debug.md")
        close_config.runtime.dry_run = False
        result = CloseReadRunner(repo_root=self.repo_root, db_path=db_path, config=close_config).run()
        return {
            "schema_version": "1.0",
            "book_id": result.book_id,
            "processed_batches": result.processed_batches,
            "exported_markdown": str(result.exported_markdown) if result.exported_markdown else "",
            "batch_metrics": result.batch_metrics,
            "real_model_required": True,
        }

    def _run_creative_kb(self, config: ReviewerSmokeConfig, *, db_path: Path, book_id: str) -> dict[str, Any]:
        model_client = JsonModelClient(config.model.to_settings(max_output_tokens=max(8192, config.model.max_output_tokens)))
        fragment_cards_repo = FragmentCardsRepo()
        facade = CreativeKnowledgeBaseFacade(
            fragment_card_builder_service=FragmentCardBuilderService(
                model_client=model_client,
                fragment_cards_repo=fragment_cards_repo,
            ),
            fragment_cards_repo=fragment_cards_repo,
        )
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            init_creative_kb_schema(conn)
            documents = DocumentsRepo().fetch_after_doc_id(conn, book_id=book_id)
            result = facade.build_creative_kb(
                conn,
                documents=documents,
                commit_batch_size=max(1, int(config.creative_kb_commit_batch_size)),
            )
            conn.commit()
        payload = result.to_dict()
        payload.update({"schema_version": "1.0", "book_id": book_id, "real_model_required": True})
        return payload

    def _memory_manifest(self, *, db_path: Path, book_id: str) -> dict[str, Any]:
        db = NovelAgentDB(db_path)
        with db.connect() as conn:
            db.init_schema(conn)
            pages = NarrativeMemoryPagesRepo().list_by_book(conn, book_id=book_id)
            documents = DocumentsRepo().fetch_after_doc_id(conn, book_id=book_id)
        page_counts: dict[str, int] = {}
        for page in pages:
            page_counts[page.page_type] = page_counts.get(page.page_type, 0) + 1
        if not pages:
            raise RuntimeError("close read did not create Narrative Memory pages")
        return {
            "schema_version": "1.0",
            "book_id": book_id,
            "page_counts": page_counts,
            "page_count": len(pages),
            "document_count": len(documents),
            "sample_pages": [
                {"page_id": page.page_id, "page_type": page.page_type, "summary_zh": _safe_excerpt(page.summary, limit=240)}
                for page in pages[:8]
            ],
            "real_model_required": True,
        }
