from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from ...runs.writer import RunWriter
from ..repos.character_profiles_repo import CharacterProfilesRepo
from ..schemas.narrative_inquiry_schema import AnalyzerBudget, NarrativeInquiryRequest
from ..schemas.narrative_index_schema import IndexQueryBudget, IndexQueryIntent
from ..schemas.narrative_memory_schema import MemoryCandidateSelection, MemoryQueryBudget, MemoryQueryState
from ..schemas.orchestration_schema import DraftResearchDecision, DraftRewritePlan, OutlineResearchQuestion, OutlineResearchQuestionSet
from .narrative_inquiry_broker import NarrativeInquiryBroker
from .narrative_index_facade import NarrativeIndexFacade
from .narrative_memory_query_service import NarrativeMemoryQueryService


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, *, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", _text(text))
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _safe_tail_excerpt(text: str, *, limit: int) -> str:
    normalized = _text(text)
    if len(normalized) <= limit:
        return normalized
    return "..." + normalized[-limit:].lstrip()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _int_list(value: object) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: set[int] = set()
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.add(number)
    return sorted(result)


def _data_path(run_writer: RunWriter, run_id: str, name: str) -> str:
    return str(run_writer.layout.run_dir(run_id) / name)


class DraftResearchService:
    """Model-led research loop that prepares compact context before prose execution."""

    def __init__(
        self,
        *,
        repo_root: Path,
        run_writer: RunWriter,
        model_client: Any,
        memory_query_service: NarrativeMemoryQueryService | None = None,
        narrative_index_facade: NarrativeIndexFacade | None = None,
        character_profiles_repo: CharacterProfilesRepo | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.run_writer = run_writer
        self.model_client = model_client
        self.memory_query_service = memory_query_service or NarrativeMemoryQueryService(repo_root=self.repo_root)
        self.narrative_index_facade = narrative_index_facade or NarrativeIndexFacade(repo_root=self.repo_root)
        self.character_profiles_repo = character_profiles_repo or CharacterProfilesRepo()

    def run(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        execution_input: Mapping[str, Any],
        rewrite_feedback: Mapping[str, Any] | None = None,
        previous_draft_md: str = "",
        max_rounds: int = 3,
    ) -> tuple[DraftResearchDecision, dict[str, Any]]:
        if self.model_client is None:
            raise RuntimeError("Draft Research Loop requires an available model_client")
        seed_packet = self._build_seed_packet(
            conn,
            run_id=run_id,
            book_id=book_id,
            execution_input=execution_input,
            rewrite_feedback=rewrite_feedback,
            previous_draft_md=previous_draft_md,
        )
        self.run_writer.write_json(run_id, "draft_seed_packet.json", seed_packet)
        notebook = self._empty_notebook(run_id=run_id, execution_input=execution_input)
        trace: list[dict[str, Any]] = []
        status = "ready_for_draft"
        question_set_id = ""
        replan_target = ""
        blocked_reason = ""
        for round_index in range(1, max(1, int(max_rounds or 1)) + 1):
            step = self._model_research_step(
                seed_packet=seed_packet,
                notebook=notebook,
                trace=trace,
                round_index=round_index,
            )
            trace.append({"operation": "draft_research_step", "round": round_index, "model_step": step})
            self._merge_notebook_updates(notebook, step.get("notebook_updates"))
            requests = [dict(item) for item in (step.get("requests") or []) if isinstance(item, Mapping)]
            status = _text(step.get("status")) or ("continue_research" if requests else "ready_for_draft")
            if status in {"needs_user_input", "replan_requested", "blocked"}:
                question_set_id, replan_target, blocked_reason = self._handle_non_ready_status(
                    run_id=run_id,
                    status=status,
                    step=step,
                    trace=trace,
                )
                break
            if requests:
                results = [
                    self._execute_request(conn, book_id=book_id, request=request)
                    for request in requests[:6]
                ]
                trace.append({"operation": "draft_research_requests", "round": round_index, "results": results})
                extraction = self._model_extract_notebook_notes(
                    seed_packet=seed_packet,
                    notebook=notebook,
                    request_results=results,
                    rewrite_feedback=rewrite_feedback or {},
                )
                self._merge_notebook_updates(notebook, extraction.get("notebook_updates") or extraction)
                if extraction.get("status") in {"needs_user_input", "replan_requested", "blocked"}:
                    status = _text(extraction.get("status"))
                    question_set_id, replan_target, blocked_reason = self._handle_non_ready_status(
                        run_id=run_id,
                        status=status,
                        step=extraction,
                        trace=trace,
                    )
                    break
                continue
            status = "ready_for_draft"
            break
        else:
            status = "ready_for_draft"

        rewrite_plan: DraftRewritePlan | None = None
        if status == "ready_for_draft" and rewrite_feedback:
            rewrite_plan = self._model_rewrite_plan(
                run_id=run_id,
                execution_input=execution_input,
                notebook=notebook,
                rewrite_feedback=rewrite_feedback,
                previous_draft_md=previous_draft_md,
            )
            self.run_writer.write_json(run_id, "draft_rewrite_plan.json", rewrite_plan)
            notebook["rewrite"] = rewrite_plan.to_dict()
            if rewrite_plan.requires_replan:
                status = "replan_requested"
                replan_target = rewrite_plan.replan_target or "chapter_brief"

        self.run_writer.write_json(run_id, "draft_context_notebook.json", notebook)
        self.run_writer.write_json(run_id, "draft_research_trace.json", {"trace": trace})
        next_action = {
            "ready_for_draft": "run_draft_prose_executor",
            "needs_user_input": "ask_user",
            "replan_requested": "return_to_artifact_review",
            "blocked": "halted",
        }[status]
        if status == "blocked" and not blocked_reason:
            blocked_reason = "Draft Research Loop could not confirm enough context for prose generation."
        decision = DraftResearchDecision(
            draft_research_id=f"draft-research-{run_id}-{_text(execution_input.get('chapter_id')) or 'chapter'}",
            run_id=run_id,
            chapter_id=_text(execution_input.get("chapter_id")) or _text(dict(execution_input.get("chapter_brief") or {}).get("chapter_id")),
            draft_id=_text((rewrite_feedback or {}).get("draft_id")),
            status=cast(Any, status),
            seed_packet_path=_data_path(self.run_writer, run_id, "draft_seed_packet.json"),
            notebook_path=_data_path(self.run_writer, run_id, "draft_context_notebook.json"),
            trace_path=_data_path(self.run_writer, run_id, "draft_research_trace.json"),
            question_set_id=question_set_id,
            replan_target=replan_target,
            blocked_reason=blocked_reason,
            next_action=cast(Any, next_action),
        )
        self.run_writer.write_json(run_id, "draft_research_decision.json", decision)
        return decision, notebook

    def _build_seed_packet(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        book_id: str,
        execution_input: Mapping[str, Any],
        rewrite_feedback: Mapping[str, Any] | None,
        previous_draft_md: str,
    ) -> dict[str, Any]:
        chapter_brief = dict(execution_input.get("chapter_brief") or {})
        fact_inputs = dict(execution_input.get("fact_inputs") or {})
        root_map = self.memory_query_service.root_map(conn, book_id=book_id, budget=MemoryQueryBudget(max_root_candidates=24))
        return {
            "schema_version": "1.0",
            "run_id": run_id,
            "book_id": book_id,
            "chapter_id": _text(execution_input.get("chapter_id")) or _text(chapter_brief.get("chapter_id")),
            "chapter_title": execution_input.get("chapter_title") or chapter_brief.get("title"),
            "chapter_brief": chapter_brief,
            "user_supplement": execution_input.get("user_supplement") or {},
            "planning_summary": {
                "book_continuation_plan": self._compact_mapping(fact_inputs.get("book_continuation_plan"), limit=1600),
                "batch_plan": self._compact_mapping(fact_inputs.get("batch_plan"), limit=1600),
                "length_budget": execution_input.get("length_budget") or {},
            },
            "recent_story_synopses": fact_inputs.get("recent_story_synopses") or [],
            "current_continuation_anchor": self._current_anchor(conn, book_id=book_id),
            "character_index": self._character_index(conn, book_id=book_id, execution_input=execution_input),
            "relationship_gate": execution_input.get("relation_state_gate") or {},
            "forbidden_inputs": execution_input.get("forbidden_inputs") or [],
            "planned_character_constraints": execution_input.get("planned_character_constraints") or [],
            "queryable_resources": {
                "text_search": "grep-like 词面定位；按 terms/match_mode/scopes 在 root summary、人物档案、outline segment、章节摘要、index card 中找关键词交集。",
                "character_profile": "按 character_id / name 查询人物档案与关键经历索引；可用 metadata.story_events_offset/story_events_char_budget 分页读取经历。",
                "character_experience": "按 experience_id / outline_segment_id / source_doc_ids 展开人物关键经历；也可用 metadata.story_events_offset 分页浏览人物经历。",
                "story_detail": "通过 segment_group / outline_root -> outline_segment -> chapter -> document 查询历史剧情。",
                "chapter_excerpt": "按 doc_id / source_doc_range 请求原始正文摘录。",
                "scene_card": "查询 Narrative SceneCard / SourceArcMap / Creative KB 卡片。",
                "world_concept": "查询世界观规则、限制和禁止突破点。",
                "structure_pattern": "查询结构和风格参考。",
                "WriterQuestionSet": "本地资料不足或需要用户授权时提出问题。",
            },
            "outline_root_map": root_map,
            "rewrite_feedback": dict(rewrite_feedback or {}),
            "previous_draft_excerpt": _safe_excerpt(previous_draft_md, limit=2400),
        }

    def _model_research_step(
        self,
        *,
        seed_packet: Mapping[str, Any],
        notebook: Mapping[str, Any],
        trace: Sequence[Mapping[str, Any]],
        round_index: int,
    ) -> dict[str, Any]:
        fallback = {
            "status": "continue_research" if round_index == 1 else "ready_for_draft",
            "requests": self._fallback_initial_requests(seed_packet) if round_index == 1 else [],
            "notebook_updates": {},
            "reason": "fallback_for_tests_only",
        }
        payload, _raw = self.model_client.generate_json(
            system_prompt=(
                "你是 Draft Research Loop。只返回 JSON。"
                "你不能直接写正文；你要判断正文前还需要查哪些事实，并把已确认材料摘取进 notebook。"
                "如果需要先定位历史剧情或关键词交集，优先请求 text_search；定位失败的分支不要写成事实。"
                "如果当前章节依赖人物当前状态、关系债务、共同经历、声音/行为边界或连续性约束，"
                "应通过 character_profile/character_experience 的 metadata.story_events_offset 分页翻阅经历；"
                "metadata.story_events_char_budget 不得超过 4096，并根据 story_events_page.next_offset 继续。"
                "剧情查询入口只能使用 segment_group / outline_root、outline_segment、chapter、document；"
                "不要使用 event_summary/event 作为 Memory 主路径。"
            ),
            user_prompt=json.dumps(
                {
                    "seed_packet": seed_packet,
                    "draft_context_notebook": notebook,
                    "recent_trace": list(trace)[-8:],
                    "output_schema": {
                        "status": "continue_research | ready_for_draft | needs_user_input | replan_requested | blocked",
                        "requests": [
                            {
                                "type": "text_search | character_profile | character_experience | story_detail | chapter_excerpt | scene_card | world_concept | structure_pattern",
                                "query": "...",
                                "purpose": "...",
                                "priority": "high | medium | low",
                                "metadata": {
                                    "terms": ["关键词A", "关键词B"],
                                    "match_mode": "all",
                                    "story_events_offset": 0,
                                    "story_events_char_budget": 4096,
                                },
                            }
                        ],
                        "notebook_updates": {
                            "character_notes": [],
                            "story_continuity_notes": [],
                            "scene_notes": [],
                            "world_notes": [],
                            "style_notes": [],
                            "unresolved_risks": [],
                        },
                        "user_questions": [],
                        "replan_target": "",
                        "blocked_reason": "",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            fallback_factory=lambda: fallback,
        )
        return dict(payload) if isinstance(payload, Mapping) else fallback

    def _model_extract_notebook_notes(
        self,
        *,
        seed_packet: Mapping[str, Any],
        notebook: Mapping[str, Any],
        request_results: Sequence[Mapping[str, Any]],
        rewrite_feedback: Mapping[str, Any],
    ) -> dict[str, Any]:
        fallback = {"status": "ready_for_draft", "notebook_updates": self._fallback_notebook_updates(request_results)}
        payload, _raw = self.model_client.generate_json(
            system_prompt=(
                "你是 Draft Research Loop 的证据摘取器。只返回 JSON。"
                "请从查询结果中摘取写正文必需的精炼事实、人物约束、剧情连续性和风险。"
                "不要把完整检索上下文搬进 notebook；每条笔记必须保留来源 id 或 source_doc_range。"
            ),
            user_prompt=json.dumps(
                {
                    "seed_packet": seed_packet,
                    "current_notebook": notebook,
                    "request_results": list(request_results),
                    "rewrite_feedback": dict(rewrite_feedback),
                    "output_schema": {
                        "status": "ready_for_draft | needs_user_input | replan_requested | blocked",
                        "notebook_updates": {
                            "character_notes": [],
                            "story_continuity_notes": [],
                            "scene_notes": [],
                            "world_notes": [],
                            "style_notes": [],
                            "unresolved_risks": [],
                            "evidence_trace": [],
                        },
                        "user_questions": [],
                        "replan_target": "",
                        "blocked_reason": "",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            fallback_factory=lambda: fallback,
        )
        return dict(payload) if isinstance(payload, Mapping) else fallback

    def _model_rewrite_plan(
        self,
        *,
        run_id: str,
        execution_input: Mapping[str, Any],
        notebook: Mapping[str, Any],
        rewrite_feedback: Mapping[str, Any],
        previous_draft_md: str,
    ) -> DraftRewritePlan:
        chapter_id = _text(execution_input.get("chapter_id")) or "chapter"
        fallback = {
            "schema_version": "1.0",
            "rewrite_plan_id": f"draft-rewrite-{run_id}-{chapter_id}",
            "run_id": run_id,
            "chapter_id": chapter_id,
            "source_decision_id": _text(rewrite_feedback.get("decision_id")),
            "source_draft_id": _text(rewrite_feedback.get("draft_id")),
            "rewrite_mode": "full_rewrite",
            "feedback_classification": "other",
            "feedback_text": _text(rewrite_feedback.get("feedback_text")),
            "preserve": [],
            "remove_or_change": [_text(rewrite_feedback.get("feedback_text"))],
            "new_memory_notes": [],
            "character_constraints": [],
            "style_constraints": [],
            "must_not_change": [],
            "requires_replan": False,
            "replan_target": "",
        }
        payload, _raw = self.model_client.generate_json(
            system_prompt=(
                "你是 Draft Research Loop 的重写计划器。只返回 JSON。"
                "你要把用户草稿反馈转成 Draft Prose Executor 可执行的 preserve/change/must_not_change 约束。"
                "如果反馈证明当前 ChapterBrief 不可执行，必须 requires_replan=true。"
            ),
            user_prompt=json.dumps(
                {
                    "chapter_brief": execution_input.get("chapter_brief") or {},
                    "draft_context_notebook": notebook,
                    "rewrite_feedback": dict(rewrite_feedback),
                    "previous_draft_excerpt": _safe_excerpt(previous_draft_md, limit=4000),
                    "output_schema": fallback,
                },
                ensure_ascii=False,
                indent=2,
            ),
            fallback_factory=lambda: fallback,
        )
        return DraftRewritePlan.from_dict(dict(payload) if isinstance(payload, Mapping) else fallback)

    def _execute_request(self, conn: sqlite3.Connection, *, book_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        request_type = _text(request.get("type") or request.get("request_type"))
        if request_type == "text_search":
            return self._query_text_search(conn, book_id=book_id, request=request)
        if request_type == "character_profile":
            return self._query_character_profile(conn, book_id=book_id, request=request)
        if request_type == "character_experience":
            return self._query_character_experience(conn, book_id=book_id, request=request)
        if request_type == "story_detail":
            return self._query_story_detail(conn, book_id=book_id, request=request)
        if request_type == "chapter_excerpt":
            return self._query_chapter_excerpt(conn, book_id=book_id, request=request)
        if request_type in {"scene_card", "structure_pattern", "world_concept"}:
            return self._query_index_cards(conn, book_id=book_id, request=request, request_type=request_type)
        return {"type": request_type or "unknown", "status": "skipped", "request": dict(request), "reason": "unsupported_request_type"}

    def _query_text_search(self, conn: sqlite3.Connection, *, book_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        metadata = dict(request.get("metadata") or {}) if isinstance(request.get("metadata"), Mapping) else {}
        if not metadata.get("terms"):
            metadata["terms"] = self._query_tokens(_text(request.get("query") or request.get("purpose")))[:6]
        metadata.setdefault("match_mode", "all")
        metadata.setdefault(
            "scopes",
            ["memory_roots", "outline_segments", "chapter_summaries", "character_profiles", "index_cards"],
        )
        inquiry_request = NarrativeInquiryRequest(
            request_id=str(request.get("request_id") or request.get("id") or "draft-text-search"),
            request_type="text_search",
            query=_text(request.get("query") or request.get("purpose")),
            purpose=_text(request.get("purpose")),
            priority=cast(Any, _text(request.get("priority")) or "medium"),
            expected_depth="locator",
            source_doc_ids=_int_list(request.get("source_doc_ids") or request.get("doc_ids")),
            document_ids=_int_list(request.get("document_ids")),
            metadata=metadata,
        )
        broker = NarrativeInquiryBroker(
            repo_root=self.repo_root,
            memory_query_service=self.memory_query_service,
            character_profiles_repo=self.character_profiles_repo,
            narrative_index_facade=self.narrative_index_facade,
        )
        bundle = broker.resolve_one(
            conn,
            book_id=book_id,
            request=inquiry_request,
            budget=AnalyzerBudget(max_total_requests=1, max_requests_per_round=1, max_evidence_chars_per_request=1800),
        )
        return {
            "type": "text_search",
            "status": "answered" if bundle.status == "found" else "missing",
            "request": dict(request),
            "evidence": bundle.to_dict(),
        }

    def _query_story_detail(self, conn: sqlite3.Connection, *, book_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        query = _text(request.get("query") or request.get("purpose"))
        state = self.memory_query_service.root_scan(conn, book_id=book_id, query=query, budget=MemoryQueryBudget())
        memory_trace = [*state.trace]
        selected_ids: list[str] = []
        for _ in range(4):
            if not state.current_candidates:
                break
            selection = self._model_select_memory_candidates(state=state, request=request)
            selected_ids = list(selection.selected_ids)
            memory_trace.append({"operation": "model_select_memory_candidates", "selection": selection.to_dict(), "level": state.current_level})
            if not selection.need_drill_down or state.current_level == "document":
                break
            next_state = self.memory_query_service.drill_down(
                conn,
                book_id=book_id,
                state=state,
                selected_ids=selection.selected_ids,
                query_suffix=selection.query_suffix,
                selection_reason=selection.reason,
                confidence=selection.confidence,
                need_sibling_scan=selection.need_sibling_scan,
            )
            memory_trace.extend(next_state.trace[len(state.trace):])
            state = next_state
        bundle = self._resolve_memory_selection(
            conn,
            book_id=book_id,
            state=state,
            selected_ids=selected_ids,
        )
        return {
            "type": "story_detail",
            "status": "answered" if bundle.get("evidence_items") else "missing",
            "request": dict(request),
            "memory_state": state.to_dict(),
            "evidence": bundle,
            "trace": memory_trace,
        }

    def _model_select_memory_candidates(self, *, state: MemoryQueryState, request: Mapping[str, Any]) -> MemoryCandidateSelection:
        candidates = state.current_candidates[:8]
        fallback = {
            "need_drill_down": state.current_level != "document",
            "selected_ids": [str(item.get("id") or item.get("page_id")) for item in candidates[:2] if item.get("id") or item.get("page_id")],
            "query_suffix": _safe_excerpt(_text(request.get("query")), limit=120),
            "reason": "fallback_for_tests_only",
            "confidence": 0.6,
            "need_sibling_scan": False,
        }
        payload, _raw = self.model_client.generate_json(
            system_prompt=(
                "你是 Draft Research Loop 的 Memory candidate selector。只返回 JSON。"
                "只能从 current_candidates 里选择 selected_ids，必要时给 query_suffix。"
            ),
            user_prompt=json.dumps(
                {
                    "original_query": state.original_query,
                    "request": dict(request),
                    "query_suffix_chain": list(state.query_suffix_chain),
                    "path_context": [item.to_dict() for item in state.path_context],
                    "current_level": state.current_level,
                    "current_candidates": candidates,
                    "output_schema": fallback,
                },
                ensure_ascii=False,
                indent=2,
            ),
            fallback_factory=lambda: fallback,
        )
        return MemoryCandidateSelection.from_mapping(dict(payload) if isinstance(payload, Mapping) else fallback)

    def _resolve_memory_selection(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        state: MemoryQueryState,
        selected_ids: Sequence[str],
    ) -> dict[str, Any]:
        ids = [item for item in selected_ids if item]
        if not ids:
            ids = [str(item.get("id") or item.get("page_id")) for item in state.current_candidates[:2] if item.get("id") or item.get("page_id")]
        if state.current_level == "outline_root":
            state = self.memory_query_service.drill_down(conn, book_id=book_id, state=state, selected_ids=ids)
            ids = [str(item.get("id") or item.get("page_id")) for item in state.current_candidates[:3]]
        if state.current_level == "outline_segment":
            return self.memory_query_service.resolve_outline_segment_refs(conn, book_id=book_id, segment_ids=ids).to_dict()
        if state.current_level == "chapter":
            return self.memory_query_service.resolve_chapter_refs(conn, book_id=book_id, chapter_refs=ids).to_dict()
        doc_ids = self._doc_ids_from_candidates(state.current_candidates, ids)
        return self.memory_query_service.resolve_document_refs(conn, book_id=book_id, doc_ids=doc_ids, excerpt_budget=1800).to_dict()

    def _query_character_profile(self, conn: sqlite3.Connection, *, book_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        metadata = dict(request.get("metadata") or {}) if isinstance(request.get("metadata"), Mapping) else {}
        if "story_events_offset" in metadata or "experience_offset" in metadata:
            inquiry_request = NarrativeInquiryRequest(
                request_id=str(request.get("request_id") or request.get("id") or "draft-character-profile"),
                request_type="character_profile",
                query=_text(request.get("query") or request.get("name") or request.get("character_id")),
                purpose=_text(request.get("purpose")),
                priority=cast(Any, _text(request.get("priority")) or "medium"),
                name=_text(request.get("name") or request.get("character_id")),
                metadata=metadata,
            )
            broker = NarrativeInquiryBroker(
                repo_root=self.repo_root,
                memory_query_service=self.memory_query_service,
                character_profiles_repo=self.character_profiles_repo,
                narrative_index_facade=self.narrative_index_facade,
            )
            bundle = broker.resolve_one(
                conn,
                book_id=book_id,
                request=inquiry_request,
                budget=AnalyzerBudget(max_total_requests=1, max_requests_per_round=1, max_evidence_chars_per_request=2400),
            )
            return {
                "type": "character_profile",
                "status": "answered" if bundle.status == "found" else "missing",
                "request": dict(request),
                "profiles": [dict(item) for item in bundle.evidence_items],
                "evidence": bundle.to_dict(),
            }
        query = _text(request.get("query") or request.get("name") or request.get("character_id"))
        rows = self.character_profiles_repo.list_by_book(conn, book_id=book_id)
        profiles = [self._profile_from_row(row) for row in rows]
        matches = self._rank_profiles(profiles, query=query, limit=6)
        return {"type": "character_profile", "status": "answered" if matches else "missing", "request": dict(request), "profiles": matches}

    def _query_character_experience(self, conn: sqlite3.Connection, *, book_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        metadata = dict(request.get("metadata") or {}) if isinstance(request.get("metadata"), Mapping) else {}
        if "story_events_offset" in metadata or "experience_offset" in metadata:
            paged = self._query_character_profile(
                conn,
                book_id=book_id,
                request={
                    **dict(request),
                    "type": "character_profile",
                    "request_type": "character_profile",
                    "name": request.get("name") or request.get("character_id") or request.get("query"),
                    "metadata": metadata,
                },
            )
            experiences: list[dict[str, Any]] = []
            for profile in paged.get("profiles") or []:
                if not isinstance(profile, Mapping):
                    continue
                for event in profile.get("story_events") or []:
                    experiences.append(
                        {
                            "canonical_name": profile.get("canonical_name"),
                            "summary": event,
                            "story_events_page": profile.get("story_events_page") or {},
                        }
                    )
            return {
                "type": "character_experience",
                "status": "answered" if experiences else "missing",
                "request": dict(request),
                "experiences": experiences,
                "profile_pages": paged.get("profiles") or [],
                "evidence": paged.get("evidence") or {},
            }
        query = json.dumps(request, ensure_ascii=False)
        profiles = [self._profile_from_row(row) for row in self.character_profiles_repo.list_by_book(conn, book_id=book_id)]
        experiences: list[dict[str, Any]] = []
        for profile in profiles:
            for item in profile.get("story_events") or []:
                if not isinstance(item, Mapping):
                    continue
                rendered = json.dumps(item, ensure_ascii=False)
                if any(token and token in rendered for token in self._query_tokens(query)):
                    payload = dict(item)
                    payload["canonical_name"] = profile.get("canonical_name")
                    experiences.append(payload)
        segment_ids = [str(item.get("outline_segment_id") or "") for item in experiences if str(item.get("outline_segment_id") or "")]
        evidence = {}
        if segment_ids:
            evidence = self.memory_query_service.resolve_outline_segment_refs(conn, book_id=book_id, segment_ids=segment_ids[:6]).to_dict()
        return {
            "type": "character_experience",
            "status": "answered" if experiences else "missing",
            "request": dict(request),
            "experiences": experiences[:8],
            "expanded_evidence": evidence,
        }

    def _query_chapter_excerpt(self, conn: sqlite3.Connection, *, book_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        doc_ids = _int_list(request.get("doc_ids") or request.get("source_doc_ids"))
        if not doc_ids:
            doc_ids = self._doc_ids_from_range(request.get("source_doc_range"))
        if not doc_ids and _text(request.get("doc_id")).isdigit():
            doc_ids = [int(_text(request.get("doc_id")))]
        query_text = self._request_query_text(request)
        if not doc_ids:
            doc_ids = self._doc_ids_from_request_query(conn, book_id=book_id, query_text=query_text)
        tail_budget = self._tail_excerpt_budget_from_query(query_text)
        if tail_budget is not None:
            evidence = self._resolve_document_tail_refs(conn, book_id=book_id, doc_ids=doc_ids[:8], excerpt_budget=tail_budget)
            return {"type": "chapter_excerpt", "status": "answered" if evidence.get("excerpts") else "missing", "request": dict(request), "evidence": evidence}
        bundle = self.memory_query_service.resolve_document_refs(conn, book_id=book_id, doc_ids=doc_ids[:8], excerpt_budget=2400)
        return {"type": "chapter_excerpt", "status": "answered" if bundle.excerpts else "missing", "request": dict(request), "evidence": bundle.to_dict()}

    def _query_index_cards(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        request: Mapping[str, Any],
        request_type: str,
    ) -> dict[str, Any]:
        target_types = {
            "scene_card": ["narrative_scene", "factual_event", "mystery_foreshadow"],
            "world_concept": ["world_concept"],
            "structure_pattern": ["creative_reference", "arc_pattern"],
        }.get(request_type, [])
        result = self.narrative_index_facade.search_cards(
            conn,
            book_id=book_id,
            intent=IndexQueryIntent(
                original_query=_text(request.get("query") or request.get("purpose")),
                consumer="writer",
                target_card_types=cast(Any, target_types),
                raw_read_policy="avoid_unless_needed",
            ),
            budget=IndexQueryBudget(max_candidate_cards=12, max_card_summary_chars=520),
        )
        return {"type": request_type, "status": "answered" if result.candidate_cards else "missing", "request": dict(request), "result": result.to_dict()}

    def _handle_non_ready_status(
        self,
        *,
        run_id: str,
        status: str,
        step: Mapping[str, Any],
        trace: list[dict[str, Any]],
    ) -> tuple[str, str, str]:
        if status == "needs_user_input":
            questions = _string_list(step.get("user_questions") or step.get("questions"))
            if not questions:
                questions = ["请补充当前章节正文扩写所需的关键事实或授权边界。"]
            question_set = OutlineResearchQuestionSet(
                question_set_id=f"draft-research-{run_id}-questions",
                run_id=run_id,
                stage="draft_research_user_input",
                source_artifact_id=f"writer:{run_id}:draft-research",
                artifact_path=_data_path(self.run_writer, run_id, "draft_research_question_set.json"),
                actions={
                    "submit": "submit_draft_research_answers",
                    "defer": "defer_draft_research_answers",
                },
                questions=[
                    OutlineResearchQuestion(
                        question_id=f"q{index}",
                        prompt=question,
                        required=True,
                        risk_level="high",
                    )
                    for index, question in enumerate(questions[:3], start=1)
                ],
            )
            self.run_writer.write_json(run_id, "draft_research_question_set.json", question_set)
            trace.append({"operation": "draft_research_needs_user_input", "question_set_id": question_set.question_set_id})
            return question_set.question_set_id, "", ""
        if status == "replan_requested":
            return "", _text(step.get("replan_target")) or "chapter_brief", ""
        if status == "blocked":
            return "", "", _text(step.get("blocked_reason")) or "Draft Research Loop blocked."
        return "", "", ""

    def _empty_notebook(self, *, run_id: str, execution_input: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "notebook_id": f"draft-context-{run_id}-{_text(execution_input.get('chapter_id')) or 'chapter'}",
            "run_id": run_id,
            "chapter_id": _text(execution_input.get("chapter_id")),
            "character_notes": [],
            "story_continuity_notes": [],
            "scene_notes": [],
            "world_notes": [],
            "style_notes": [],
            "unresolved_risks": [],
            "evidence_trace": [],
            "created_at": _utc_now(),
        }

    def _merge_notebook_updates(self, notebook: dict[str, Any], updates: object) -> None:
        if not isinstance(updates, Mapping):
            return
        for key in ("character_notes", "story_continuity_notes", "scene_notes", "world_notes", "style_notes", "unresolved_risks", "evidence_trace"):
            incoming = updates.get(key)
            if not isinstance(incoming, list):
                continue
            existing = [item for item in notebook.get(key, []) if isinstance(item, (Mapping, str))]
            rendered = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in existing}
            for item in incoming:
                if not isinstance(item, (Mapping, str)):
                    continue
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if marker in rendered:
                    continue
                rendered.add(marker)
                existing.append(dict(item) if isinstance(item, Mapping) else str(item))
            notebook[key] = existing[-80:]

    def _fallback_initial_requests(self, seed_packet: Mapping[str, Any]) -> list[dict[str, Any]]:
        chapter_brief = dict(seed_packet.get("chapter_brief") or {})
        query = " ".join(
            _text(value)
            for value in (
                chapter_brief.get("title"),
                chapter_brief.get("goal"),
                chapter_brief.get("plot_function"),
                chapter_brief.get("combined_synopsis"),
            )
            if _text(value)
        )
        requests = [{"type": "story_detail", "query": query or "当前章节历史承接", "purpose": "确认正文扩写连续性", "priority": "high"}]
        character_index = [item for item in seed_packet.get("character_index") or [] if isinstance(item, Mapping)]
        if character_index:
            requests.append(
                {
                    "type": "character_profile",
                    "name": character_index[0].get("canonical_name") or character_index[0].get("character_id"),
                    "query": character_index[0].get("canonical_name") or "",
                    "purpose": "确认本章人物声音与关系边界",
                    "priority": "high",
                }
            )
        return requests

    def _fallback_notebook_updates(self, request_results: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        updates = {
            "character_notes": [],
            "story_continuity_notes": [],
            "scene_notes": [],
            "world_notes": [],
            "style_notes": [],
            "unresolved_risks": [],
            "evidence_trace": [],
        }
        for result in request_results:
            request_type = _text(result.get("type"))
            target = "story_continuity_notes"
            if request_type in {"character_profile", "character_experience"}:
                target = "character_notes"
            elif request_type == "scene_card":
                target = "scene_notes"
            elif request_type == "world_concept":
                target = "world_notes"
            elif request_type == "structure_pattern":
                target = "style_notes"
            updates[target].append(
                {
                    "summary": _safe_excerpt(json.dumps(result, ensure_ascii=False), limit=520),
                    "source_type": request_type,
                    "status": result.get("status") or "candidate",
                }
            )
            updates["evidence_trace"].append({"request_type": request_type, "status": result.get("status")})
        return updates

    def _character_index(self, conn: sqlite3.Connection, *, book_id: str, execution_input: Mapping[str, Any]) -> list[dict[str, Any]]:
        matcher_text = json.dumps(execution_input, ensure_ascii=False)
        profiles = [self._profile_from_row(row) for row in self.character_profiles_repo.list_by_book(conn, book_id=book_id)]
        selected = self._rank_profiles(profiles, query=matcher_text, limit=12)
        return [
            {
                "character_id": str(item.get("character_id") or ""),
                "canonical_name": item.get("canonical_name") or "",
                "aliases": item.get("aliases") or [],
                "summary": _safe_excerpt(_text(item.get("profile_summary_md")), limit=260),
                **self._character_experience_index(item, matcher_text=matcher_text, limit=6),
            }
            for item in selected
        ]

    def _character_experience_index(
        self,
        profile: Mapping[str, Any],
        *,
        matcher_text: str,
        limit: int,
    ) -> dict[str, Any]:
        events = [item for item in (profile.get("story_events") or []) if isinstance(item, Mapping)]
        selected = self._select_profile_events_for_prompt(events, matcher_text=matcher_text, limit=limit)
        return {
            "key_experience_index": [self._prompt_experience_index_item(event) for event in selected],
            "story_events_page": {
                "mode": "relevance_and_recent_index",
                "offset": 0,
                "next_offset": len(selected) if len(selected) < len(events) else None,
                "total": len(events),
                "has_more": len(selected) < len(events),
                "returned": len(selected),
                "page_read_instruction": (
                    "Use character_profile or character_experience with metadata.story_events_offset "
                    "and metadata.story_events_char_budget <= 4096 to page through this character's chronology."
                ),
            },
        }

    def _select_profile_events_for_prompt(
        self,
        events: Sequence[Mapping[str, Any]],
        *,
        matcher_text: str,
        limit: int,
    ) -> list[Mapping[str, Any]]:
        if not events or limit <= 0:
            return []
        tokens = self._query_tokens(matcher_text)
        scored: list[tuple[int, int, Mapping[str, Any]]] = []
        for index, event in enumerate(events):
            rendered = json.dumps(event, ensure_ascii=False)
            score = sum(4 for token in tokens if token and token in rendered)
            if event.get("source_doc_ids") or event.get("source_doc_range") or event.get("outline_segment_id"):
                score += 1
            if index >= max(0, len(events) - limit):
                score += 2
            scored.append((score, index, event))
        selected: list[Mapping[str, Any]] = []
        seen: set[int] = set()
        for _score, index, event in sorted(scored, key=lambda item: (-item[0], item[1])):
            if index in seen:
                continue
            seen.add(index)
            selected.append(event)
            if len(selected) >= limit:
                break
        return selected

    def _prompt_experience_index_item(self, event: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "experience_id": event.get("experience_id") or event.get("event_id") or "",
            "outline_segment_id": event.get("outline_segment_id") or "",
            "label": event.get("label") or "",
            "summary": _safe_excerpt(_text(event.get("summary")), limit=180),
            "source_doc_ids": event.get("source_doc_ids") or [],
            "source_doc_range": event.get("source_doc_range") or "",
        }

    def _profile_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        json_fields = {
            "aliases_json": "aliases",
            "personality_json": "personality",
            "occupations_json": "occupations",
            "age_timeline_json": "age_timeline",
            "abilities_json": "abilities",
            "recent_activity_json": "recent_activity",
            "relationships_json": "relationships",
            "story_events_json": "story_events",
            "chapter_indexes_json": "chapter_indexes",
            "mentioned_doc_ids_json": "mentioned_doc_ids",
            "speaking_doc_ids_json": "speaking_doc_ids",
        }
        payload: dict[str, Any] = {}
        for key in row.keys():
            value = row[key]
            payload[json_fields.get(key, key)] = _json_list(value) if key in json_fields else value
        return payload

    def _rank_profiles(self, profiles: Sequence[Mapping[str, Any]], *, query: str, limit: int) -> list[dict[str, Any]]:
        tokens = self._query_tokens(query)
        scored: list[tuple[int, int, Mapping[str, Any]]] = []
        for index, profile in enumerate(profiles):
            haystack = json.dumps(profile, ensure_ascii=False)
            names = [_text(profile.get("canonical_name")), *_string_list(profile.get("aliases"))]
            score = sum(4 for name in names if name and name in query)
            score += sum(1 for token in tokens if token in haystack)
            if score > 0:
                scored.append((score, -index, profile))
        scored.sort(reverse=True)
        return [dict(item[2]) for item in scored[:limit]]

    def _current_anchor(self, conn: sqlite3.Connection, *, book_id: str) -> str:
        row = conn.execute(
            """
            SELECT document_title_index, chapter_title, summary_short
            FROM chapters
            WHERE book_id = ?
            ORDER BY document_title_index DESC
            LIMIT 1
            """,
            (book_id,),
        ).fetchone()
        if row is None:
            return ""
        return f"最近已建模章节 {int(row['document_title_index'] or 0)}《{row['chapter_title'] or ''}》：{_safe_excerpt(str(row['summary_short'] or ''), limit=260)}"

    def _doc_ids_from_candidates(self, candidates: Sequence[Mapping[str, Any]], selected_ids: Sequence[str]) -> list[int]:
        selected = {str(item) for item in selected_ids if str(item)}
        doc_ids: set[int] = set()
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or candidate.get("page_id") or "")
            if selected and candidate_id not in selected:
                continue
            for doc_id in _int_list(candidate.get("source_doc_ids")):
                doc_ids.add(doc_id)
            if str(candidate.get("doc_id") or "").isdigit():
                doc_ids.add(int(str(candidate.get("doc_id"))))
        return sorted(doc_ids)

    def _doc_ids_from_range(self, value: object) -> list[int]:
        text = _text(value)
        if not text:
            return []
        if "-" not in text:
            return [int(text)] if text.isdigit() else []
        left, right = text.split("-", 1)
        if not left.strip().isdigit() or not right.strip().isdigit():
            return []
        start, end = int(left), int(right)
        if end < start:
            return [start]
        if end - start > 24:
            return [start, end]
        return list(range(start, end + 1))

    def _request_query_text(self, request: Mapping[str, Any]) -> str:
        fields = (
            "query",
            "purpose",
            "range",
            "note",
            "doc_id",
            "doc_ids",
            "source_doc_ids",
            "source_doc_range",
            "chapter",
            "chapter_id",
            "document_title_index",
        )
        return " ".join(_text(request.get(field)) for field in fields if _text(request.get(field)))

    def _doc_ids_from_request_query(self, conn: sqlite3.Connection, *, book_id: str, query_text: str) -> list[int]:
        text = _text(query_text)
        if not text:
            return []
        doc_ids: set[int] = set()
        for pattern in (
            r"\bdoc(?:ument)?_?ids?\s*[:=]\s*([0-9,\-\s]+)",
            r"\bsource_doc_ids?\s*[:=]\s*([0-9,\-\s]+)",
            r"\bsource_doc_range\s*[:=]\s*([0-9,\-\s]+)",
        ):
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                for item in self._doc_ids_from_number_list(match.group(1)):
                    doc_ids.add(item)

        title_indexes: set[int] = set()
        for pattern in (
            r"\bdocument_title_index\s*[:=]\s*(\d+)",
            r"\bchapter\s*[:=]\s*chapter[-_\s]?(\d+)\b",
            r"\bchapter[-_\s](\d+)\b",
            r"\bchapter\s+(\d+)\b",
            r"第\s*(\d+)\s*[章节回]",
        ):
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                number = int(match.group(1))
                if number > 0:
                    title_indexes.add(number)

        for title_index in sorted(title_indexes):
            for item in self._doc_ids_for_document_title_index(conn, book_id=book_id, document_title_index=title_index):
                doc_ids.add(item)
        return sorted(doc_ids)

    def _doc_ids_from_number_list(self, text: str) -> list[int]:
        doc_ids: set[int] = set()
        for chunk in re.split(r"[,，\s]+", _text(text)):
            if not chunk:
                continue
            for item in self._doc_ids_from_range(chunk):
                doc_ids.add(item)
        return sorted(doc_ids)

    def _doc_ids_for_document_title_index(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        document_title_index: int,
    ) -> list[int]:
        if document_title_index <= 0:
            return []
        chapter = conn.execute(
            """
            SELECT source_doc_start_id, source_doc_end_id
            FROM chapters
            WHERE book_id = ? AND document_title_index = ?
            LIMIT 1
            """,
            (book_id, int(document_title_index)),
        ).fetchone()
        if chapter is not None:
            start = int(chapter["source_doc_start_id"] or 0)
            end = int(chapter["source_doc_end_id"] or 0)
            if start > 0 and end >= start:
                rows = conn.execute(
                    """
                    SELECT doc_id FROM documents
                    WHERE book_id = ? AND doc_id BETWEEN ? AND ?
                    ORDER BY doc_id
                    """,
                    (book_id, start, end),
                ).fetchall()
                ids = [int(row["doc_id"]) for row in rows]
                if ids:
                    return ids
                return list(range(start, min(end, start + 7) + 1))
        rows = conn.execute(
            """
            SELECT doc_id FROM documents
            WHERE book_id = ? AND document_title_index = ?
            ORDER BY doc_id
            """,
            (book_id, int(document_title_index)),
        ).fetchall()
        return [int(row["doc_id"]) for row in rows]

    def _tail_excerpt_budget_from_query(self, query_text: str) -> int | None:
        text = _text(query_text)
        if not text:
            return None
        tail_marker = r"(?:last|ending|end|tail|末尾|尾部|结尾|最后)"
        if not re.search(tail_marker, text, flags=re.IGNORECASE):
            return None
        for pattern in (
            rf"{tail_marker}\D{{0,16}}(\d{{2,5}})",
            rf"(\d{{2,5}})\s*(?:chars?|characters?|字|字符)\D{{0,16}}{tail_marker}",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return max(200, min(4000, int(match.group(1))))
        return 1200

    def _resolve_document_tail_refs(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        doc_ids: Sequence[int],
        excerpt_budget: int,
    ) -> dict[str, Any]:
        clean_ids = sorted({int(item) for item in doc_ids if int(item) > 0})
        if not clean_ids:
            return {"status": "provisional", "source_doc_ids": [], "chapter_refs": [], "evidence_items": [], "sources": [], "excerpts": []}
        placeholders = ",".join("?" for _ in clean_ids)
        rows = conn.execute(
            f"""
            SELECT * FROM documents
            WHERE book_id = ? AND doc_id IN ({placeholders})
            ORDER BY doc_id
            """,
            (book_id, *clean_ids),
        ).fetchall()
        per_doc_budget = max(80, int(excerpt_budget or 80) // max(1, len(rows)))
        evidence_items: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        excerpts: list[dict[str, Any]] = []
        for row in rows:
            content = str(row["content"] or "")
            excerpt = _safe_tail_excerpt(content, limit=per_doc_budget)
            item = {
                "doc_id": int(row["doc_id"]),
                "summary": excerpt,
                "source_doc_range": str(row["doc_id"]),
                "document_title_index": int(row["document_title_index"] or 0),
                "excerpt_scope": "tail",
                "status": "provisional",
            }
            evidence_items.append(item)
            excerpts.append(
                {
                    "doc_id": int(row["doc_id"]),
                    "text": excerpt,
                    "excerpt_scope": "tail",
                    "source_start_offset": int(row["source_start_offset"] or 0),
                    "source_end_offset": int(row["source_end_offset"] or 0),
                }
            )
            sources.append(
                {
                    "type": "document",
                    "path": f"sqlite:documents:{row['doc_id']}",
                    "doc_id": int(row["doc_id"]),
                    "status": "provisional",
                    "excerpt_scope": "tail",
                }
            )
        return {
            "evidence_items": evidence_items,
            "sources": sources,
            "status": "provisional",
            "source_doc_ids": [int(row["doc_id"]) for row in rows],
            "chapter_refs": [],
            "excerpts": excerpts,
            "trace": [
                {
                    "operation": "resolve_document_tail_refs",
                    "doc_ids": clean_ids,
                    "resolved_doc_ids": [int(row["doc_id"]) for row in rows],
                    "excerpt_budget": int(excerpt_budget or 0),
                    "source_scope": "tail_documents",
                }
            ],
        }

    def _query_tokens(self, text: str) -> list[str]:
        return [
            token
            for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}", _text(text))
            if token
        ][:40]

    def _compact_mapping(self, value: object, *, limit: int) -> dict[str, Any] | str:
        if not isinstance(value, Mapping):
            return _safe_excerpt(str(value or ""), limit=limit)
        rendered = json.dumps(value, ensure_ascii=False)
        if len(rendered) <= limit:
            return dict(value)
        return _safe_excerpt(rendered, limit=limit)
