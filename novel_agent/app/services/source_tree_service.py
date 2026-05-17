from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..llm import JsonModelClient
from ..prompts.directory_analysis_prompt import build_directory_analysis_prompt
from ..schemas.prompt_io_schema import DirectoryAnalysisOutput, DirectoryBookPlan, DirectoryReadOrderItem


class SourceTreeService:
    def __init__(self, model_client: JsonModelClient | None = None) -> None:
        self.model_client = model_client

    def summarize_tree(self, root: Path, *, limit: int = 200) -> str:
        if root.is_file():
            return root.name
        entries: list[str] = []
        for index, path in enumerate(self._iter_source_files(root)):
            if index >= limit:
                entries.append("... truncated ...")
                break
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = path.as_posix()
            entries.append(rel)
        return "\n".join(entries)

    def heuristic_analysis(self, root: Path, *, book_id: str) -> DirectoryAnalysisOutput:
        files = self._iter_source_files(root)
        read_order = [
            DirectoryReadOrderItem(path=path.as_posix(), sort_key=index + 1, reason="按文件名排序读取")
            for index, path in enumerate(files)
        ]
        plan = DirectoryBookPlan(
            book_id=book_id,
            book_name=root.name,
            root_path=root.as_posix(),
            selected_paths=[path.as_posix() for path in files],
            ignored_paths=[],
            read_order=read_order,
            confidence=0.95,
        )
        return DirectoryAnalysisOutput(strategy_type="single_book_multi_file", books=[plan], global_notes="heuristic")

    def analyze(self, root: Path, *, book_id: str) -> DirectoryAnalysisOutput:
        fallback = self.heuristic_analysis(root, book_id=book_id)
        if self.model_client is None:
            raise RuntimeError("SourceTreeService requires an available model_client")
        if self.model_client.settings.dry_run:
            return fallback
        system_prompt, user_prompt = build_directory_analysis_prompt(
            tree_summary=self.summarize_tree(root),
            source_root=root.as_posix(),
            book_id_hint=book_id,
        )
        payload, _ = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=fallback.to_dict,
            use_fallback_on_error=False,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Directory analysis model returned a non-object JSON payload")
        raw_books = payload.get("books", [])
        if not isinstance(raw_books, list):
            raise RuntimeError("Directory analysis model returned invalid books field")
        books = []
        for book in raw_books:
            if not isinstance(book, dict):
                raise RuntimeError("Directory analysis model returned a non-object book item")
            read_order = []
            raw_read_order = book.get("read_order", [])
            if not isinstance(raw_read_order, list) or not raw_read_order:
                raise RuntimeError("Directory analysis model returned no usable read_order")
            for item in raw_read_order:
                if not isinstance(item, dict):
                    raise RuntimeError("Directory analysis model returned a non-object read_order item")
                path = str(item.get("path", "")).strip()
                if not path:
                    raise RuntimeError("Directory analysis model returned read_order item without path")
                try:
                    sort_key = int(item.get("sort_key", len(read_order) + 1))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Directory analysis model returned invalid read_order sort_key") from exc
                read_order.append(
                    DirectoryReadOrderItem(
                        path=path,
                        sort_key=sort_key,
                        reason=str(item.get("reason", "")),
                    )
                )
            raw_selected_paths = book.get("selected_paths", [])
            if not isinstance(raw_selected_paths, list):
                raise RuntimeError("Directory analysis model returned invalid selected_paths field")
            raw_ignored_paths = book.get("ignored_paths", [])
            if not isinstance(raw_ignored_paths, list):
                raise RuntimeError("Directory analysis model returned invalid ignored_paths field")
            books.append(
                DirectoryBookPlan(
                    book_id=str(book.get("book_id") or book_id),
                    book_name=str(book.get("book_name") or root.name),
                    root_path=str(book.get("root_path") or root.as_posix()),
                    selected_paths=[str(x) for x in raw_selected_paths],
                    ignored_paths=[str(x) for x in raw_ignored_paths],
                    read_order=read_order,
                    confidence=self._coerce_confidence(book.get("confidence", 1.0)),
                )
            )
        if not books:
            raise RuntimeError("Directory analysis model returned no usable books")
        return DirectoryAnalysisOutput(
            strategy_type=self._coerce_strategy_type(payload.get("strategy_type", fallback.strategy_type)),
            books=books,
            global_notes=str(payload.get("global_notes", "")),
        )

    def _coerce_confidence(self, value: object) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            mapping = {
                "high": 0.9,
                "medium": 0.6,
                "low": 0.3,
            }
            if lowered in mapping:
                return mapping[lowered]
            try:
                return float(lowered)
            except ValueError:
                return 0.5
        return 0.5

    def _iter_source_files(self, root: Path) -> list[Path]:
        if root.is_file():
            return [root] if root.suffix.lower() in {".md", ".txt"} else []
        return sorted([path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".md", ".txt"}])

    def _coerce_strategy_type(self, value: object) -> Literal["single_file", "single_book_multi_file", "multi_book_directory"]:
        if value == "single_file":
            return "single_file"
        if value == "multi_book_directory":
            return "multi_book_directory"
        if value == "single_book_multi_file":
            return "single_book_multi_file"
        if isinstance(value, str) and "file" in value:
            return "single_file"
        raise RuntimeError("Directory analysis model returned invalid strategy_type")
