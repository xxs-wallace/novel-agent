from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ChunkFileSpan:
    source_path: str
    source_file_name: str
    start_offset: int
    end_offset: int
    text: str


@dataclass(slots=True)
class TextBatch:
    batch_no: int
    chars: int
    spans: list[ChunkFileSpan] = field(default_factory=list)

    @property
    def content(self) -> str:
        return "".join(span.text for span in self.spans)


class ChunkReaderService:
    def __init__(
        self,
        *,
        target_min_chars: int,
        target_max_chars: int,
        stop_at_newline_after_limit: bool = True,
        max_total_chars: int | None = None,
    ) -> None:
        self.target_min_chars = target_min_chars
        self.target_max_chars = target_max_chars
        self.stop_at_newline_after_limit = stop_at_newline_after_limit
        self.max_total_chars = max_total_chars

    def iter_batches(self, ordered_paths: list[Path]) -> list[TextBatch]:
        return self.iter_batches_from_checkpoint(ordered_paths)

    def _resolve_chunk_end(self, text: str, *, start: int, preferred_end: int) -> int:
        # Favor ending on full-sentence boundaries so resumed reads do not split the same
        # paragraph into two unrelated prompt windows.
        sentence_markers = ("。\r\n", "。\n", "。")
        window_start = max(start, preferred_end - 400)
        for search_start in (window_start, start):
            for marker in sentence_markers:
                marker_index = text.rfind(marker, search_start, preferred_end)
                if marker_index != -1 and marker_index + len(marker) > start:
                    return marker_index + len(marker)
        if self.stop_at_newline_after_limit:
            for search_start in (window_start, start):
                newline_index = text.rfind("\n", search_start, preferred_end)
                if newline_index != -1 and newline_index + 1 > start:
                    return newline_index + 1
        return preferred_end

    def iter_batches_from_checkpoint(
        self,
        ordered_paths: list[Path],
        *,
        resume_source_path: str | None = None,
        resume_source_offset: int = 0,
        start_batch_no: int = 1,
    ) -> list[TextBatch]:
        batches: list[TextBatch] = []
        current_spans: list[ChunkFileSpan] = []
        current_chars = 0
        batch_no = start_batch_no
        total_chars_read = 0
        waiting_for_resume_path = bool(resume_source_path)
        for path in ordered_paths:
            if waiting_for_resume_path:
                if path.as_posix() != resume_source_path:
                    continue
                waiting_for_resume_path = False
            if self.max_total_chars is not None and total_chars_read >= self.max_total_chars:
                break
            text = path.read_text(encoding="utf-8", errors="replace")
            start = max(0, resume_source_offset) if resume_source_path and path.as_posix() == resume_source_path else 0
            resume_source_path = None
            resume_source_offset = 0
            while start < len(text):
                if self.max_total_chars is not None and total_chars_read >= self.max_total_chars:
                    break
                remaining = text[start:]
                allowed = max(1, self.target_max_chars - current_chars)
                if self.max_total_chars is not None:
                    remaining_budget = self.max_total_chars - total_chars_read
                    if remaining_budget <= 0:
                        break
                    allowed = min(allowed, remaining_budget)
                if len(remaining) <= allowed:
                    chunk_text = remaining
                    end = len(text)
                else:
                    end = self._resolve_chunk_end(text, start=start, preferred_end=start + allowed)
                    chunk_text = text[start:end]
                if not chunk_text:
                    break
                current_spans.append(
                    ChunkFileSpan(
                        source_path=path.as_posix(),
                        source_file_name=path.name,
                        start_offset=start,
                        end_offset=end,
                        text=chunk_text,
                    )
                )
                current_chars += len(chunk_text)
                total_chars_read += len(chunk_text)
                start = end
                if current_chars >= self.target_min_chars:
                    batches.append(TextBatch(batch_no=batch_no, chars=current_chars, spans=current_spans))
                    batch_no += 1
                    current_spans = []
                    current_chars = 0
            if self.max_total_chars is not None and total_chars_read >= self.max_total_chars:
                break
        if current_spans:
            batches.append(TextBatch(batch_no=batch_no, chars=current_chars, spans=current_spans))
        return batches
