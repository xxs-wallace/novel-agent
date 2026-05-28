from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from math import ceil
from typing import Any, Sequence

from ..llm import JsonModelClient
from ..repos.documents_repo import DocumentRow
from ..schemas.creative_kb_schema import SemanticAlias


@dataclass(slots=True)
class SemanticAliasExtractionResult:
    aliases: list[SemanticAlias] = field(default_factory=list)
    sampled_doc_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SemanticAliasExtractorService:
    def __init__(
        self,
        *,
        model_client: JsonModelClient,
        edge_document_count: int = 2,
        middle_sample_ratio: float = 0.05,
    ) -> None:
        self.model_client = model_client
        self.edge_document_count = max(1, int(edge_document_count))
        self.middle_sample_ratio = max(0.0, float(middle_sample_ratio))

    def extract_aliases(self, *, book_id: str, documents: Sequence[DocumentRow]) -> SemanticAliasExtractionResult:
        sampled_documents = self.sample_documents(book_id=book_id, documents=documents)
        if not sampled_documents:
            return SemanticAliasExtractionResult()
        extraction_run_id = f"semantic-alias-{uuid.uuid4().hex[:12]}"
        system_prompt, user_prompt = self._build_prompt(book_id=book_id, documents=sampled_documents)
        payload, _raw_text = self.model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=lambda: self._fallback_payload(book_id=book_id, documents=sampled_documents),
            use_fallback_on_error=False,
        )
        warnings: list[str] = []
        return SemanticAliasExtractionResult(
            aliases=self._payload_to_aliases(
                book_id=book_id,
                payload=payload,
                sampled_documents=sampled_documents,
                extraction_run_id=extraction_run_id,
            ),
            sampled_doc_ids=[str(document.doc_id) for document in sampled_documents],
            warnings=warnings,
        )

    def sample_documents(self, *, book_id: str, documents: Sequence[DocumentRow]) -> list[DocumentRow]:
        ordered_documents = [document for document in documents if document.book_id == book_id and document.content.strip()]
        if not ordered_documents:
            return []
        edge_count = min(self.edge_document_count, len(ordered_documents))
        selected: dict[int, DocumentRow] = {}
        for document in ordered_documents[:edge_count]:
            selected[document.doc_id] = document
        for document in ordered_documents[-edge_count:]:
            selected[document.doc_id] = document
        edge_ids = set(selected)
        middle_documents = [document for document in ordered_documents if document.doc_id not in edge_ids]
        sample_count = min(len(middle_documents), max(0, ceil(len(middle_documents) * self.middle_sample_ratio)))
        if sample_count:
            rng = random.Random(book_id)
            for document in rng.sample(middle_documents, sample_count):
                selected[document.doc_id] = document
        return sorted(selected.values(), key=lambda document: document.doc_id)

    def _build_prompt(self, *, book_id: str, documents: Sequence[DocumentRow]) -> tuple[str, str]:
        doc_payload = [
            {
                "doc_id": document.doc_id,
                "document_title": document.document_title,
                "document_title_index": document.document_title_index,
                "content_excerpt": document.content[:3000],
            }
            for document in documents
        ]
        system_prompt = (
            "你是小说阅读/创作知识库 Agent。任务是从抽样原文中抽取语义等价词、指代词和表达变体。"
            "只输出 JSON，不要解释。不要发明没有文本依据的专有名词。"
        )
        user_prompt = json.dumps(
            {
                "book_id": book_id,
                "task": "extract_semantic_aliases_for_requirement_coverage",
                "output_schema": {
                    "aliases": [
                        {
                            "canonical_key": "规范关键词",
                            "aliases": ["等价词/指代词/表达变体"],
                            "category": "requirement_coverage",
                            "confidence": 0.0,
                            "evidence_doc_ids": ["doc_id"],
                        }
                    ]
                },
                "sampling_policy": "使用开头、结尾和中间 5% 抽样文档；只基于这些文档抽取。",
                "documents": doc_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        return system_prompt, user_prompt

    def _fallback_payload(self, *, book_id: str, documents: Sequence[DocumentRow]) -> dict[str, Any]:
        _ = book_id, documents
        return {"aliases": []}

    def _payload_to_aliases(
        self,
        *,
        book_id: str,
        payload: dict[str, Any] | list[Any],
        sampled_documents: Sequence[DocumentRow],
        extraction_run_id: str,
    ) -> list[SemanticAlias]:
        if not isinstance(payload, dict):
            return []
        sampled_doc_ids = {str(document.doc_id) for document in sampled_documents}
        aliases: list[SemanticAlias] = []
        for item in payload.get("aliases") or []:
            if not isinstance(item, dict):
                continue
            canonical_key = str(item.get("canonical_key") or "").strip()
            alias_values = [str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip()]
            if not canonical_key or not alias_values:
                continue
            evidence_doc_ids = [
                str(doc_id).strip()
                for doc_id in (item.get("evidence_doc_ids") or [])
                if str(doc_id).strip() in sampled_doc_ids
            ]
            aliases.append(
                SemanticAlias(
                    book_id=book_id,
                    canonical_key=canonical_key,
                    aliases=alias_values,
                    category=str(item.get("category") or "requirement_coverage"),
                    source="model_extraction",
                    evidence_doc_ids=evidence_doc_ids,
                    confidence=float(item.get("confidence") or 0.0),
                    extraction_run_id=extraction_run_id,
                )
            )
        return aliases
