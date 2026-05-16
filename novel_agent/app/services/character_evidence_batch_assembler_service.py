from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..repos.documents_repo import DocumentRow
from ..utils.text_utils import clamp_text


@dataclass(slots=True)
class CharacterEvidenceBatch:
    character_evidence_batch_id: str
    book_id: str
    doc_ids: list[int]
    document_title_indexes: list[int]
    source_doc_start_id: int
    source_doc_end_id: int
    batch_text: str
    documents: list[dict[str, object]] = field(default_factory=list)
    document_separator_hint: str = "[DOC doc_id=<id> title_index=<index> title=<title>] ... [/DOC]"
    existing_context_summary: str = ""
    existing_character_roster: list[dict[str, object]] = field(default_factory=list)
    character_roster_scope: str = "recent_32"
    can_request_full_roster: bool = False

    @property
    def total_chars(self) -> int:
        return len(self.batch_text)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CharacterEvidenceBatchAssemblerService:
    """Builds batch-level inputs for the Character Evidence Agent.

    This service intentionally follows document reading order and does not bind batch
    boundaries to chapter title indexes. Chapter Summary Agent scheduling remains the
    responsibility of ChapterAssemblerService.
    """

    def __init__(self, *, document_chars_budget: int = 20_000) -> None:
        self.document_chars_budget = max(1, int(document_chars_budget))

    def build_batch(
        self,
        *,
        book_id: str,
        documents: list[DocumentRow],
        existing_context_summary: str = "",
        local_character_hints: dict[int, list[str]] | None = None,
        existing_character_roster: list[dict[str, object]] | None = None,
        character_roster_scope: str = "recent_32",
        can_request_full_roster: bool = False,
    ) -> CharacterEvidenceBatch:
        _ = local_character_hints
        selected = self._select_documents_within_budget(documents)
        if not selected:
            raise ValueError("Character evidence batch requires at least one document")
        doc_ids = [int(doc.doc_id) for doc in selected]
        title_indexes = self._ordered_unique(int(doc.document_title_index) for doc in selected)
        batch_text = self._join_documents(selected)
        return CharacterEvidenceBatch(
            character_evidence_batch_id=self._build_batch_id(book_id=book_id, doc_ids=doc_ids),
            book_id=book_id,
            doc_ids=doc_ids,
            document_title_indexes=title_indexes,
            source_doc_start_id=doc_ids[0],
            source_doc_end_id=doc_ids[-1],
            batch_text=batch_text,
            documents=[
                {
                    "doc_id": int(doc.doc_id),
                    "document_title_index": int(doc.document_title_index),
                    "document_title": str(doc.document_title),
                    "content_chars": int(doc.content_chars),
                }
                for doc in selected
            ],
            existing_context_summary=clamp_text(existing_context_summary, 1500),
            existing_character_roster=list(existing_character_roster or []),
            character_roster_scope=str(character_roster_scope or "recent_32"),
            can_request_full_roster=bool(can_request_full_roster),
        )

    def to_prompt_input(self, *, batch: CharacterEvidenceBatch) -> dict[str, object]:
        return {"character_evidence_batch": batch.to_dict()}

    def _select_documents_within_budget(self, documents: list[DocumentRow]) -> list[DocumentRow]:
        selected: list[DocumentRow] = []
        used_chars = 0
        for document in documents:
            doc_chars = max(0, int(document.content_chars))
            if selected and used_chars + doc_chars > self.document_chars_budget:
                break
            selected.append(document)
            used_chars += doc_chars
            if used_chars >= self.document_chars_budget:
                break
        return selected

    def _join_documents(self, documents: list[DocumentRow]) -> str:
        parts: list[str] = []
        for document in documents:
            parts.append(
                "\n".join(
                    [
                        (
                            f"[DOC doc_id={document.doc_id} "
                            f"title_index={document.document_title_index} "
                            f"title={document.document_title}]"
                        ),
                        str(document.content),
                        "[/DOC]",
                    ]
                )
            )
        return "\n\n".join(parts)

    def _build_batch_id(self, *, book_id: str, doc_ids: list[int]) -> str:
        if len(doc_ids) == 1:
            return f"{book_id}:character-evidence:{doc_ids[0]}"
        return f"{book_id}:character-evidence:{doc_ids[0]}-{doc_ids[-1]}"

    def _ordered_unique(self, values) -> list[int]:
        result: list[int] = []
        seen: set[int] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
