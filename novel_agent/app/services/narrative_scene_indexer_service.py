from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..constants import DEFAULT_MEMORY_ROOT
from ..prompts.narrative_scene_index_prompt import build_narrative_scene_index_prompt
from ..repos.assets_repo import AssetsRepo
from ..repos.chapters_repo import ChaptersRepo
from ..repos.documents_repo import DocumentRow, DocumentsRepo
from ..schemas.narrative_index_schema import (
    NARRATIVE_SCENE_TYPES,
    IndexCard,
    NarrativeSceneBoundary,
    NarrativeScenePayload,
)
from ..utils.text_utils import clamp_text, normalize_whitespace


DEFAULT_SCENE_WINDOW_CHARS = 16_000
DEFAULT_SCENE_OVERLAP_DOCS = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_excerpt(text: str, *, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", _text(text))
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


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


def _range_text(values: Sequence[int]) -> str:
    cleaned = sorted({int(value) for value in values if int(value) > 0})
    if not cleaned:
        return ""
    return str(cleaned[0]) if len(cleaned) == 1 else f"{cleaned[0]}-{cleaned[-1]}"


@dataclass(slots=True)
class NarrativeSceneWindow:
    window_id: str
    documents: list[DocumentRow]
    overlap_doc_ids: list[int]
    previous_context_summary: str = ""
    next_context_summary: str = ""
    world_context: str = ""
    character_context: list[dict[str, Any]] | None = None

    @property
    def source_doc_ids(self) -> list[int]:
        return [int(doc.doc_id) for doc in self.documents]

    @property
    def source_title_indexes(self) -> list[int]:
        return sorted({int(doc.document_title_index) for doc in self.documents if int(doc.document_title_index) > 0})

    @property
    def total_chars(self) -> int:
        return sum(int(doc.content_chars) for doc in self.documents)

    def to_prompt_input(self, *, book_id: str) -> dict[str, Any]:
        return {
            "book_id": book_id,
            "window_id": self.window_id,
            "previous_context_summary": self.previous_context_summary,
            "raw_document_window": [
                {
                    "doc_id": int(doc.doc_id),
                    "document_title_index": int(doc.document_title_index),
                    "document_title": str(doc.document_title),
                    "content": str(doc.content),
                }
                for doc in self.documents
            ],
            "next_context_summary": self.next_context_summary,
            "character_context": list(self.character_context or []),
            "world_context": self.world_context,
            "source_doc_ids": self.source_doc_ids,
            "overlap_doc_ids": list(self.overlap_doc_ids),
        }


class NarrativeSceneIndexerService:
    """Builds NarrativeSceneCards from Memory handoff windows.

    The service requires a model for normal semantic scene extraction. Dry-run
    mode may emit explicit fallback cards so tests and local wiring can proceed
    without pretending that semantic judgment succeeded.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        documents_repo: DocumentsRepo | None = None,
        chapters_repo: ChaptersRepo | None = None,
        assets_repo: AssetsRepo | None = None,
        window_chars_budget: int = DEFAULT_SCENE_WINDOW_CHARS,
        overlap_docs: int = DEFAULT_SCENE_OVERLAP_DOCS,
        context_summary_chars: int = 1200,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.documents_repo = documents_repo or DocumentsRepo()
        self.chapters_repo = chapters_repo or ChaptersRepo()
        self.assets_repo = assets_repo or AssetsRepo()
        self.window_chars_budget = max(1, int(window_chars_budget or DEFAULT_SCENE_WINDOW_CHARS))
        self.overlap_docs = max(0, int(overlap_docs or 0))
        self.context_summary_chars = max(200, int(context_summary_chars or 1200))

    def artifact_path(self, book_id: str) -> Path:
        directory = self.repo_root / DEFAULT_MEMORY_ROOT / "index_cards"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{book_id}.scene_cards.json"

    def load_scene_cards(self, *, book_id: str) -> list[IndexCard]:
        path = self.artifact_path(book_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        raw_cards = payload.get("scene_cards") if isinstance(payload, Mapping) else payload
        if not isinstance(raw_cards, list):
            return []
        cards: list[IndexCard] = []
        for item in raw_cards:
            if not isinstance(item, Mapping):
                continue
            try:
                cards.append(IndexCard.from_mapping({**dict(item), "card_type": "narrative_scene"}))
            except (TypeError, ValueError):
                continue
        return cards

    def build_scene_cards(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: str,
        model_client: Any,
        persist: bool = True,
        progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> list[IndexCard]:
        if model_client is None:
            raise RuntimeError("NarrativeSceneIndexerService requires an available model_client")
        documents = self.documents_repo.fetch_after_doc_id(conn, book_id=book_id)
        if not documents:
            return []
        chapters = self.chapters_repo.list_by_book(conn, book_id=book_id)
        world_context = self._world_context(conn, book_id=book_id)
        windows = self._build_windows(documents=documents, chapters=chapters, world_context=world_context)
        self._emit_progress(
            progress_callback,
            phase="windows_ready",
            total_windows=len(windows),
            total_documents=len(documents),
        )
        cards: list[IndexCard] = []
        for index, window in enumerate(windows, start=1):
            self._emit_progress(
                progress_callback,
                phase="window_start",
                window_index=index,
                total_windows=len(windows),
                source_doc_ids=window.source_doc_ids,
                source_title_indexes=window.source_title_indexes,
            )
            window_cards = self._generate_window_cards(book_id=book_id, model_client=model_client, window=window)
            cards.extend(window_cards)
            self._emit_progress(
                progress_callback,
                phase="window_done",
                window_index=index,
                total_windows=len(windows),
                source_doc_ids=window.source_doc_ids,
                built_cards=len(window_cards),
                accumulated_cards=len(cards),
            )
        cards = self._dedupe_scene_cards(cards)
        if persist:
            self._emit_progress(
                progress_callback,
                phase="persist_start",
                total_windows=len(windows),
                built_cards=len(cards),
            )
            self.save_scene_cards(book_id=book_id, cards=cards)
            self._emit_progress(
                progress_callback,
                phase="persist_done",
                total_windows=len(windows),
                built_cards=len(cards),
            )
        return cards

    @staticmethod
    def _emit_progress(
        progress_callback: Callable[[Mapping[str, Any]], None] | None,
        **payload: Any,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback({"stage": "narrative_scene_index", **payload})

    def save_scene_cards(self, *, book_id: str, cards: Sequence[IndexCard]) -> Path:
        path = self.artifact_path(book_id)
        payload = {
            "book_id": book_id,
            "generated_at": _utc_now(),
            "generator": "NarrativeSceneIndexerService",
            "scene_cards": [card.to_dict() for card in cards],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _build_windows(
        self,
        *,
        documents: list[DocumentRow],
        chapters: Sequence[sqlite3.Row],
        world_context: str,
    ) -> list[NarrativeSceneWindow]:
        windows: list[NarrativeSceneWindow] = []
        start = 0
        previous_end = 0
        while start < len(documents):
            selected: list[DocumentRow] = []
            used_chars = 0
            index = start
            while index < len(documents):
                doc = documents[index]
                if selected and used_chars + int(doc.content_chars) > self.window_chars_budget:
                    break
                selected.append(doc)
                used_chars += int(doc.content_chars)
                index += 1
                if used_chars >= self.window_chars_budget:
                    break
            if not selected:
                selected = [documents[start]]
                index = start + 1
            overlap_doc_ids = [int(doc.doc_id) for doc in selected if int(doc.doc_id) < previous_end + 1]
            window_number = len(windows) + 1
            title_indexes = sorted({int(doc.document_title_index) for doc in selected})
            windows.append(
                NarrativeSceneWindow(
                    window_id=f"scene-window-{window_number:04d}",
                    documents=selected,
                    overlap_doc_ids=overlap_doc_ids,
                    previous_context_summary=self._context_before(chapters=chapters, min_title_index=min(title_indexes)),
                    next_context_summary=self._context_after(chapters=chapters, max_title_index=max(title_indexes)),
                    world_context=world_context,
                    character_context=self._character_context(selected),
                )
            )
            previous_end = max(int(doc.doc_id) for doc in selected)
            if index >= len(documents):
                break
            next_start = max(index - self.overlap_docs, start + 1)
            start = next_start
        return windows

    def _generate_window_cards(
        self,
        *,
        book_id: str,
        model_client: Any,
        window: NarrativeSceneWindow,
    ) -> list[IndexCard]:
        prompt_input = window.to_prompt_input(book_id=book_id)
        system_prompt, user_prompt = build_narrative_scene_index_prompt(prompt_input)
        payload, _raw = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._fallback_window_payload(book_id=book_id, window=window),
            use_fallback_on_error=bool(getattr(getattr(model_client, "settings", None), "dry_run", False)),
        )
        if not isinstance(payload, Mapping):
            raise RuntimeError("Narrative Scene Indexer model returned a non-object JSON payload")
        raw_cards = payload.get("scene_cards", [])
        if not isinstance(raw_cards, list):
            raise RuntimeError("Narrative Scene Indexer model returned invalid scene_cards")
        cards: list[IndexCard] = []
        for item in raw_cards:
            if not isinstance(item, Mapping):
                continue
            card = self._scene_card_from_payload(book_id=book_id, window=window, raw=item)
            if card is not None:
                cards.append(card)
        return cards

    def _scene_card_from_payload(
        self,
        *,
        book_id: str,
        window: NarrativeSceneWindow,
        raw: Mapping[str, Any],
    ) -> IndexCard | None:
        summary = normalize_whitespace(str(raw.get("summary") or ""))
        label = normalize_whitespace(str(raw.get("label") or ""))
        if not summary:
            return None
        window_doc_ids = set(window.source_doc_ids)
        source_doc_ids = [doc_id for doc_id in _int_list(raw.get("source_doc_ids")) if doc_id in window_doc_ids]
        if not source_doc_ids:
            source_doc_ids = window.source_doc_ids
        docs_by_id = {int(doc.doc_id): doc for doc in window.documents}
        title_indexes = _int_list(raw.get("source_title_indexes"))
        if not title_indexes:
            title_indexes = sorted({int(docs_by_id[doc_id].document_title_index) for doc_id in source_doc_ids if doc_id in docs_by_id})
        boundary_payload = _json_dict(raw.get("scene_boundary"))
        boundary = NarrativeSceneBoundary(
            start_doc_id=str(boundary_payload.get("start_doc_id") or source_doc_ids[0]),
            end_doc_id=str(boundary_payload.get("end_doc_id") or source_doc_ids[-1]),
            boundary_confidence=float(boundary_payload.get("boundary_confidence") or raw.get("confidence") or 0.0),
            overlap_window_id=str(boundary_payload.get("overlap_window_id") or window.window_id),
        )
        scene_payload = NarrativeScenePayload(
            scene_type=str(raw.get("scene_type") or "transition_bridge"),
            label=label,
            participants=_string_list(raw.get("participants")),
            scene_boundary=boundary,
            trigger=str(raw.get("trigger") or ""),
            turning_point=str(raw.get("turning_point") or ""),
            outcome=str(raw.get("outcome") or ""),
            character_pressure=_string_list(raw.get("character_pressure")),
            relationship_movements=_string_list(raw.get("relationship_movements")),
            world_or_mystery_signals=_string_list(raw.get("world_or_mystery_signals")),
            future_consequence=str(raw.get("future_consequence") or ""),
        )
        scene_type = scene_payload.scene_type if scene_payload.scene_type in NARRATIVE_SCENE_TYPES else "transition_bridge"
        facets = [
            label,
            scene_type,
            *_string_list(raw.get("query_facets")),
            *scene_payload.participants,
            *scene_payload.relationship_movements,
            *scene_payload.world_or_mystery_signals,
        ]
        importance_facets = _string_list(raw.get("importance_facets")) or [scene_type]
        source_doc_range = _range_text(source_doc_ids)
        card_id = self._scene_card_id(
            book_id=book_id,
            source_doc_range=source_doc_range,
            scene_type=scene_type,
            label=label,
            summary=summary,
        )
        return IndexCard(
            card_id=card_id,
            card_type="narrative_scene",
            book_id=book_id,
            summary=summary,
            source_doc_ids=[str(doc_id) for doc_id in source_doc_ids],
            source_title_indexes=title_indexes,
            source_doc_range=source_doc_range,
            query_facets=facets,
            importance_facets=importance_facets,
            consumer_hints=["analyzer", "writer", "outline_research", "reviewer"],
            summary_sufficiency=str(raw.get("summary_sufficiency") or "sufficient"),
            raw_read_reason=str(raw.get("raw_read_reason") or ""),
            status=str(raw.get("status") or "provisional"),
            confidence=float(raw.get("confidence") or boundary.boundary_confidence or 0.0),
            payload=scene_payload.to_dict()
            | {
                "window_id": window.window_id,
                "source": "narrative_scene_indexer",
            },
        )

    def _fallback_window_payload(self, *, book_id: str, window: NarrativeSceneWindow) -> dict[str, Any]:
        return {
            "scene_cards": [
                {
                    "label": f"{window.window_id} dry-run fallback",
                    "summary": "dry-run fallback: Narrative Scene Indexer 未调用真实模型，本卡片只能用于链路连通测试。",
                    "scene_type": "transition_bridge",
                    "participants": [],
                    "source_doc_ids": window.source_doc_ids,
                    "source_title_indexes": window.source_title_indexes,
                    "scene_boundary": {
                        "start_doc_id": str(window.source_doc_ids[0]),
                        "end_doc_id": str(window.source_doc_ids[-1]),
                        "boundary_confidence": 0.1,
                        "overlap_window_id": window.window_id,
                    },
                    "trigger": "",
                    "turning_point": "",
                    "outcome": "",
                    "character_pressure": [],
                    "relationship_movements": [],
                    "world_or_mystery_signals": [],
                    "future_consequence": "",
                    "query_facets": ["dry_run", book_id],
                    "importance_facets": ["fallback"],
                    "summary_sufficiency": "needs_model_review",
                    "raw_read_reason": "dry-run fallback has no semantic scene judgment",
                    "status": "fallback",
                    "confidence": 0.1,
                }
            ]
        }

    def _dedupe_scene_cards(self, cards: Sequence[IndexCard]) -> list[IndexCard]:
        merged: list[IndexCard] = []
        for card in sorted(cards, key=lambda item: (item.source_doc_range, item.card_id)):
            duplicate_index = self._find_duplicate_scene_index(merged, card)
            if duplicate_index is None:
                merged.append(card)
                continue
            merged[duplicate_index] = self._merge_scene_cards(merged[duplicate_index], card)
        return merged

    def _find_duplicate_scene_index(self, cards: Sequence[IndexCard], candidate: IndexCard) -> int | None:
        candidate_label = _text(candidate.payload.get("label")).lower()
        candidate_type = _text(candidate.payload.get("scene_type"))
        candidate_docs = {int(doc_id) for doc_id in _int_list(candidate.source_doc_ids)}
        for index, card in enumerate(cards):
            if _text(card.payload.get("scene_type")) != candidate_type:
                continue
            if _text(card.payload.get("label")).lower() != candidate_label:
                continue
            docs = {int(doc_id) for doc_id in _int_list(card.source_doc_ids)}
            if docs.intersection(candidate_docs):
                return index
        return None

    def _merge_scene_cards(self, left: IndexCard, right: IndexCard) -> IndexCard:
        source_doc_ids = sorted({*_int_list(left.source_doc_ids), *_int_list(right.source_doc_ids)})
        source_title_indexes = sorted({*left.source_title_indexes, *right.source_title_indexes})
        chosen = right if right.confidence > left.confidence or len(right.summary) > len(left.summary) else left
        payload = dict(chosen.payload)
        payload["merged_from_card_ids"] = sorted({left.card_id, right.card_id, *(_string_list(left.payload.get("merged_from_card_ids"))), *(_string_list(right.payload.get("merged_from_card_ids")))})
        return IndexCard(
            card_id=self._scene_card_id(
                book_id=chosen.book_id,
                source_doc_range=_range_text(source_doc_ids),
                scene_type=str(payload.get("scene_type") or "transition_bridge"),
                label=str(payload.get("label") or ""),
                summary=chosen.summary,
            ),
            card_type="narrative_scene",
            book_id=chosen.book_id,
            summary=chosen.summary,
            source_doc_ids=[str(doc_id) for doc_id in source_doc_ids],
            source_title_indexes=source_title_indexes,
            source_doc_range=_range_text(source_doc_ids),
            outline_segment_ids=sorted({*left.outline_segment_ids, *right.outline_segment_ids}),
            query_facets=sorted({*left.query_facets, *right.query_facets}),
            importance_facets=sorted({*left.importance_facets, *right.importance_facets}),
            consumer_hints=sorted({*left.consumer_hints, *right.consumer_hints}),
            summary_sufficiency=chosen.summary_sufficiency,
            raw_read_reason=chosen.raw_read_reason,
            status=chosen.status,
            confidence=max(left.confidence, right.confidence),
            payload=payload,
        )

    def _context_before(self, *, chapters: Sequence[sqlite3.Row], min_title_index: int) -> str:
        items = [self._chapter_context_text(row) for row in chapters if int(row["document_title_index"] or 0) < min_title_index]
        return clamp_text("\n".join(item for item in items[-4:] if item), self.context_summary_chars)

    def _context_after(self, *, chapters: Sequence[sqlite3.Row], max_title_index: int) -> str:
        items = [self._chapter_context_text(row) for row in chapters if int(row["document_title_index"] or 0) > max_title_index]
        return clamp_text("\n".join(item for item in items[:4] if item), self.context_summary_chars)

    def _chapter_context_text(self, row: sqlite3.Row) -> str:
        title_index = int(row["document_title_index"] or 0)
        chapter_title = str(row["chapter_title"] or "")
        outline = _json_dict(row["outline_update_json"])
        summary = _text(outline.get("outline_segment")) or _text(row["summary_short"]) or _safe_excerpt(str(row["summary_md"] or ""), limit=360)
        if not summary:
            return ""
        return f"[{title_index}] {chapter_title}: {summary}"

    def _world_context(self, conn: sqlite3.Connection, *, book_id: str) -> str:
        row = self.assets_repo.get(conn, book_id=book_id)
        if row is None:
            return ""
        summary_path = Path(str(row["world_summary_path"] or "")).expanduser()
        if not summary_path.is_absolute():
            summary_path = (self.repo_root / summary_path).resolve()
        if not summary_path.exists():
            return ""
        return clamp_text(summary_path.read_text(encoding="utf-8", errors="replace"), 1600)

    def _character_context(self, documents: Sequence[DocumentRow]) -> list[dict[str, Any]]:
        names = sorted({name for doc in documents for name in doc.character_keywords if _text(name)})
        return [{"canonical_name": name} for name in names[:24]]

    def _scene_card_id(
        self,
        *,
        book_id: str,
        source_doc_range: str,
        scene_type: str,
        label: str,
        summary: str,
    ) -> str:
        digest = hashlib.sha1(f"{book_id}|{source_doc_range}|{scene_type}|{label}|{summary}".encode("utf-8")).hexdigest()[:10]
        range_part = re.sub(r"[^0-9A-Za-z_-]+", "-", source_doc_range or "unknown").strip("-")
        return f"narrative-scene:{book_id}:{range_part}:{digest}"
