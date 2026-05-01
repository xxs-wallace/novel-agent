from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schemas.context_assembly_schema import ContextAssemblyPayload
from ..schemas.creative_kb_schema import CreativeKBRetrievalResult, SceneBrief
from ..schemas.orchestration_schema import (
    CreativeKBRetrievalInput,
    MemoryAssemblyInput,
    ReferenceFragment,
    RetrievalContext,
    WriterInputBundle,
    WriterSource,
)
from ..services.context_assembly_service import ContextAssemblyService
from ..services.retrieval_context_adapter import build_retrieval_context
from ..services.retrieval_facade import RetrievalFacade


def _normalize_text(value: object) -> str:
    return str(value).strip()


@dataclass(slots=True)
class MainLayerCreativeKBRetrievalRequest:
    anchor_context: str
    recent_window_summary: str
    goal: str
    previous_generated_segment: str | None = None
    retrieval_context: RetrievalContext = field(default_factory=RetrievalContext)
    scene_plan: dict[str, Any] = field(default_factory=dict)
    scene_brief: SceneBrief | None = None
    documents: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.anchor_context = _normalize_text(self.anchor_context)
        self.recent_window_summary = _normalize_text(self.recent_window_summary)
        self.goal = _normalize_text(self.goal)
        self.previous_generated_segment = (
            _normalize_text(self.previous_generated_segment)
            if self.previous_generated_segment is not None
            else None
        )
        self.documents = [dict(item) for item in self.documents]
        self.scene_plan = dict(self.scene_plan)


class MainLayerOrchestrator:
    """Main-layer bridge for the online Creative KB retrieval path."""

    def __init__(
        self,
        *,
        retrieval_facade: RetrievalFacade | None = None,
        context_assembly_service: ContextAssemblyService | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.retrieval_facade = retrieval_facade or RetrievalFacade()
        self.context_assembly_service = context_assembly_service
        self.repo_root = repo_root

    def prepare_creative_kb_input(
        self,
        *,
        anchor_context: str,
        recent_window_summary: str,
        goal: str,
        previous_generated_segment: str | None = None,
        retrieval_context: RetrievalContext | dict[str, Any] | None = None,
        scene_plan: dict[str, Any] | None = None,
        documents: list[dict[str, Any]] | None = None,
    ) -> CreativeKBRetrievalInput:
        return CreativeKBRetrievalInput(
            anchor_context=_normalize_text(anchor_context),
            recent_window_summary=_normalize_text(recent_window_summary),
            goal=_normalize_text(goal),
            documents=[dict(item) for item in (documents or [])],
            previous_generated_segment=(
                _normalize_text(previous_generated_segment)
                if previous_generated_segment is not None
                else None
            ),
            retrieval_context=build_retrieval_context(retrieval_context),
            scene_plan=dict(scene_plan or {}),
        )

    def build_online_creative_kb_request(
        self,
        *,
        anchor_context: str,
        recent_window_summary: str,
        goal: str,
        previous_generated_segment: str | None = None,
        retrieval_context: RetrievalContext | dict[str, Any] | None = None,
        scene_plan: dict[str, Any] | None = None,
        scene_brief: SceneBrief | None = None,
        documents: list[dict[str, Any]] | None = None,
    ) -> MainLayerCreativeKBRetrievalRequest:
        prepared_input = self.prepare_creative_kb_input(
            anchor_context=anchor_context,
            recent_window_summary=recent_window_summary,
            goal=goal,
            previous_generated_segment=previous_generated_segment,
            retrieval_context=retrieval_context,
            scene_plan=scene_plan,
            documents=documents,
        )
        return MainLayerCreativeKBRetrievalRequest(
            anchor_context=prepared_input.anchor_context,
            recent_window_summary=prepared_input.recent_window_summary,
            goal=prepared_input.goal,
            previous_generated_segment=prepared_input.previous_generated_segment,
            retrieval_context=prepared_input.retrieval_context,
            scene_plan=prepared_input.scene_plan,
            scene_brief=scene_brief,
            documents=prepared_input.documents,
        )

    def retrieve_reference_bundle(
        self,
        conn: sqlite3.Connection,
        *,
        request: MainLayerCreativeKBRetrievalRequest,
        include_coarse_result: bool = False,
        expand_reference_fragments: bool = False,
    ) -> CreativeKBRetrievalResult:
        retrieval_input = CreativeKBRetrievalInput(
            anchor_context=request.anchor_context,
            recent_window_summary=request.recent_window_summary,
            goal=request.goal,
            documents=[dict(item) for item in request.documents],
            previous_generated_segment=request.previous_generated_segment,
            retrieval_context=request.retrieval_context,
            scene_plan=dict(request.scene_plan),
        )
        return self.retrieval_facade.build_scene_brief_and_retrieve(
            conn,
            retrieval_input=retrieval_input,
            scene_brief=request.scene_brief,
            include_coarse_result=include_coarse_result,
            expand_reference_fragments=expand_reference_fragments,
        )

    def run_online_creative_kb_path(
        self,
        conn: sqlite3.Connection,
        *,
        anchor_context: str,
        recent_window_summary: str,
        goal: str,
        previous_generated_segment: str | None = None,
        retrieval_context: RetrievalContext | dict[str, Any] | None = None,
        scene_plan: dict[str, Any] | None = None,
        scene_brief: SceneBrief | None = None,
        documents: list[dict[str, Any]] | None = None,
        include_coarse_result: bool = False,
        expand_reference_fragments: bool = False,
    ) -> CreativeKBRetrievalResult:
        request = self.build_online_creative_kb_request(
            anchor_context=anchor_context,
            recent_window_summary=recent_window_summary,
            goal=goal,
            previous_generated_segment=previous_generated_segment,
            retrieval_context=retrieval_context,
            scene_plan=scene_plan,
            scene_brief=scene_brief,
            documents=documents,
        )
        return self.retrieve_reference_bundle(
            conn,
            request=request,
            include_coarse_result=include_coarse_result,
            expand_reference_fragments=expand_reference_fragments,
        )

    def prepare_memory_assembly_input(
        self,
        *,
        book_id: str,
        document_title_index: str | None = None,
        related_character_names: list[str] | None = None,
    ) -> MemoryAssemblyInput:
        return MemoryAssemblyInput(
            book_id=_normalize_text(book_id),
            document_title_index=_normalize_text(document_title_index) or None,
            related_character_names=[
                _normalize_text(name)
                for name in (related_character_names or [])
                if _normalize_text(name)
            ],
        )

    def assemble_context_payload(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        document_title_index: str | None = None,
        related_character_names: list[str] | None = None,
    ) -> ContextAssemblyPayload:
        assembly_input = self.prepare_memory_assembly_input(
            book_id=book_id,
            document_title_index=document_title_index,
            related_character_names=related_character_names,
        )
        return self._get_context_assembly_service().assemble(
            conn,
            assembly_input=assembly_input,
        )

    def build_writer_input_bundle(
        self,
        *,
        anchor_context: str,
        recent_window_summary: str,
        retrieval_result: CreativeKBRetrievalResult,
        context_payload: ContextAssemblyPayload | None = None,
    ) -> WriterInputBundle:
        if retrieval_result.scene_brief is None:
            raise ValueError("retrieval_result.scene_brief is required to build WriterInputBundle")
        reference_fragments = [
            ReferenceFragment(
                fragment_id=item.fragment_id,
                source_excerpt=item.source_excerpt,
                content_summary=item.content_summary,
                style_profile_text=item.style_profile_text,
            )
            for item in retrieval_result.reference_fragments
        ]
        sources = [
            WriterSource(
                path=item.source_path,
                snippet=item.source_excerpt,
            )
            for item in retrieval_result.reference_fragments
            if item.source_path or item.source_excerpt
        ]
        return WriterInputBundle(
            anchor_context=_normalize_text(anchor_context),
            recent_window_summary=_normalize_text(recent_window_summary),
            scene_brief=retrieval_result.scene_brief,
            reference_fragments=reference_fragments,
            context_payload=context_payload or ContextAssemblyPayload(),
            sources=sources,
        )

    def _get_context_assembly_service(self) -> ContextAssemblyService:
        if self.context_assembly_service is None:
            repo_root = self.repo_root or Path.cwd()
            self.context_assembly_service = ContextAssemblyService.build_default(repo_root=repo_root)
        return self.context_assembly_service
