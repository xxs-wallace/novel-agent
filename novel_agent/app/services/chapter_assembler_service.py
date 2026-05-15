from __future__ import annotations

from dataclasses import dataclass, field

from ..repos.documents_repo import DocumentRow, DocumentsRepo
from ..repos.reading_progress_repo import ReadingProgressRepo


SPLIT_REASON_FULL_CHAPTER = "full_chapter"
SPLIT_REASON_OVER_BUDGET = "over_budget"


@dataclass(slots=True)
class ChapterBatch:
    document_title_index: int
    chapter_title: str
    documents: list[DocumentRow] = field(default_factory=list)
    is_complete_chapter: bool = True
    chapter_doc_count: int = 0
    chapter_total_chars: int = 0
    batch_doc_start_index: int = 1
    split_reason: str = SPLIT_REASON_FULL_CHAPTER

    @property
    def total_chars(self) -> int:
        return sum(doc.content_chars for doc in self.documents)

    @property
    def batch_doc_count(self) -> int:
        return len(self.documents)

    @property
    def title_indexes(self) -> list[int]:
        indexes: list[int] = []
        for doc in self.documents:
            if doc.document_title_index not in indexes:
                indexes.append(doc.document_title_index)
        return indexes

    @property
    def is_multi_chapter(self) -> bool:
        return len(self.title_indexes) > 1

    @property
    def is_split_batch(self) -> bool:
        return self.split_reason == SPLIT_REASON_OVER_BUDGET or not self.is_complete_chapter

    @property
    def batch_label(self) -> str:
        if self.is_multi_chapter:
            return f"多章-{self.title_indexes[0]}-{self.title_indexes[-1]}"
        if not self.is_split_batch:
            return "整章"
        return f"拆批-{self.batch_doc_start_index}-{self.batch_doc_start_index + self.batch_doc_count - 1}"

    def documents_for_title_index(self, document_title_index: int) -> list[DocumentRow]:
        return [doc for doc in self.documents if doc.document_title_index == document_title_index]

    def as_single_title_batch(self, document_title_index: int) -> "ChapterBatch":
        docs = self.documents_for_title_index(document_title_index)
        if not docs:
            raise ValueError(f"No documents for title index {document_title_index}")
        return ChapterBatch(
            document_title_index=document_title_index,
            chapter_title=docs[0].document_title,
            documents=docs,
            is_complete_chapter=self.is_complete_chapter,
            chapter_doc_count=len(docs),
            chapter_total_chars=sum(doc.content_chars for doc in docs),
            batch_doc_start_index=1,
            split_reason=SPLIT_REASON_FULL_CHAPTER if self.is_complete_chapter else self.split_reason,
        )


class ChapterAssemblerService:
    def __init__(
        self,
        *,
        documents_repo: DocumentsRepo,
        progress_repo: ReadingProgressRepo,
        document_chars_budget: int,
        progress_stage: str,
    ) -> None:
        self.documents_repo = documents_repo
        self.progress_repo = progress_repo
        self.document_chars_budget = document_chars_budget
        self.progress_stage = progress_stage

    def load_next_batch(self, conn, *, book_id: str) -> ChapterBatch | None:
        last_completed = self.progress_repo.resolve_resume_doc_id(
            conn,
            book_id=book_id,
            agent_stage=self.progress_stage,
        )
        remaining = self.documents_repo.fetch_after_doc_id(conn, book_id=book_id, doc_id=last_completed)
        if not remaining:
            return None
        return self._build_batch(conn, book_id=book_id, remaining=remaining)

    def load_next_batches(self, conn, *, book_id: str, limit: int) -> list[ChapterBatch]:
        last_completed = self.progress_repo.resolve_resume_doc_id(
            conn,
            book_id=book_id,
            agent_stage=self.progress_stage,
        )
        remaining = self.documents_repo.fetch_after_doc_id(conn, book_id=book_id, doc_id=last_completed)
        batches: list[ChapterBatch] = []
        cursor = 0
        batch_limit = max(1, int(limit))
        while cursor < len(remaining) and len(batches) < batch_limit:
            batch = self._build_batch(conn, book_id=book_id, remaining=remaining[cursor:])
            if not batch.documents:
                break
            batches.append(batch)
            cursor += len(batch.documents)
        return batches

    def _build_batch(self, conn, *, book_id: str, remaining: list[DocumentRow]) -> ChapterBatch:
        first = remaining[0]
        return self._build_single_chapter_batch(
            conn,
            book_id=book_id,
            first=first,
            same_chapter=[doc for doc in remaining if doc.document_title_index == first.document_title_index],
        )

    def _build_single_chapter_batch(
        self,
        conn,
        *,
        book_id: str,
        first: DocumentRow,
        same_chapter: list[DocumentRow],
    ) -> ChapterBatch:
        all_chapter_docs = self.documents_repo.fetch_by_title_index(
            conn,
            book_id=book_id,
            document_title_index=first.document_title_index,
        )
        chapter_total_chars = sum(doc.content_chars for doc in all_chapter_docs)
        batch_doc_start_index = self._compute_batch_doc_start_index(
            all_chapter_docs=all_chapter_docs,
            first_batch_doc_id=first.doc_id,
        )
        if self._should_keep_whole_chapter(chapter_total_chars):
            return ChapterBatch(
                document_title_index=first.document_title_index,
                chapter_title=first.document_title,
                documents=same_chapter,
                is_complete_chapter=True,
                chapter_doc_count=len(all_chapter_docs),
                chapter_total_chars=chapter_total_chars,
                batch_doc_start_index=batch_doc_start_index,
                split_reason=SPLIT_REASON_FULL_CHAPTER,
            )
        selected: list[DocumentRow] = []
        current_chars = 0
        for doc in same_chapter:
            if selected and current_chars + doc.content_chars > self.document_chars_budget:
                return ChapterBatch(
                    document_title_index=first.document_title_index,
                    chapter_title=first.document_title,
                    documents=selected,
                    is_complete_chapter=False,
                    chapter_doc_count=len(all_chapter_docs),
                    chapter_total_chars=chapter_total_chars,
                    batch_doc_start_index=batch_doc_start_index,
                    split_reason=SPLIT_REASON_OVER_BUDGET,
                )
            selected.append(doc)
            current_chars += doc.content_chars
        return ChapterBatch(
            document_title_index=first.document_title_index,
            chapter_title=first.document_title,
            documents=selected,
            is_complete_chapter=True,
            chapter_doc_count=len(all_chapter_docs),
            chapter_total_chars=chapter_total_chars,
            batch_doc_start_index=batch_doc_start_index,
            split_reason=SPLIT_REASON_OVER_BUDGET if len(selected) < len(all_chapter_docs) or batch_doc_start_index > 1 else SPLIT_REASON_FULL_CHAPTER,
        )

    def _should_keep_whole_chapter(self, chapter_total_chars: int) -> bool:
        return chapter_total_chars <= self.document_chars_budget

    def _compute_batch_doc_start_index(
        self,
        *,
        all_chapter_docs: list[DocumentRow],
        first_batch_doc_id: int,
    ) -> int:
        for index, doc in enumerate(all_chapter_docs, start=1):
            if doc.doc_id == first_batch_doc_id:
                return index
        return 1
