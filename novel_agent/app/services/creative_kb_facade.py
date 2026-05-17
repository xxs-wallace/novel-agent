from __future__ import annotations

import sqlite3
from typing import Any, Callable, Sequence

from ..repos.documents_repo import DocumentRow
from ..repos.fragment_cards_repo import FragmentCardsRepo
from ..repos.fragment_clusters_repo import FragmentClustersRepo
from ..repos.semantic_aliases_repo import SemanticAliasesRepo
from ..schemas.creative_kb_schema import CreativeKBBuildResult, FragmentCard
from .fragment_card_builder_service import FragmentCardBuilderService
from .fragment_cluster_service import FragmentClusterService
from .semantic_alias_extractor_service import SemanticAliasExtractorService


CREATIVE_KB_COMMIT_BATCH_SIZE = 1024

CreativeKBProgressCallback = Callable[[dict[str, Any]], None]


class CreativeKnowledgeBaseFacade:
    def __init__(
        self,
        *,
        fragment_card_builder_service: FragmentCardBuilderService,
        fragment_cluster_service: FragmentClusterService | None = None,
        fragment_cards_repo: FragmentCardsRepo | None = None,
        fragment_clusters_repo: FragmentClustersRepo | None = None,
        semantic_alias_extractor_service: SemanticAliasExtractorService | None = None,
        semantic_aliases_repo: SemanticAliasesRepo | None = None,
    ) -> None:
        self.fragment_card_builder_service = fragment_card_builder_service
        self.fragment_cards_repo = fragment_cards_repo or fragment_card_builder_service.fragment_cards_repo
        self.fragment_clusters_repo = fragment_clusters_repo or FragmentClustersRepo()
        self.fragment_cluster_service = fragment_cluster_service or FragmentClusterService(
            fragment_cards_repo=self.fragment_cards_repo,
            fragment_clusters_repo=self.fragment_clusters_repo,
        )
        self.semantic_alias_extractor_service = semantic_alias_extractor_service or SemanticAliasExtractorService(
            model_client=fragment_card_builder_service.model_client
        )
        self.semantic_aliases_repo = semantic_aliases_repo or SemanticAliasesRepo()

    def build_creative_kb(
        self,
        conn: sqlite3.Connection,
        *,
        documents: Sequence[DocumentRow],
        commit_batch_size: int = CREATIVE_KB_COMMIT_BATCH_SIZE,
        progress_callback: CreativeKBProgressCallback | None = None,
    ) -> CreativeKBBuildResult:
        normalized_documents = list(documents)
        skipped_doc_ids = self._collect_skipped_doc_ids(conn, normalized_documents)
        buildable_documents = [
            document
            for document in normalized_documents
            if str(document.doc_id) not in skipped_doc_ids
        ]
        total_documents = len(normalized_documents)
        total_buildable = len(buildable_documents)
        semantic_alias_count = 0
        semantic_alias_sampled_doc_ids: list[str] = []
        semantic_alias_warnings: list[str] = []

        if not buildable_documents:
            scoped_cards = self.fragment_cards_repo.list_by_doc_ids(
                conn,
                doc_ids=[str(document.doc_id) for document in normalized_documents],
            )
            clustering_result = self.fragment_cluster_service.cluster_and_persist(conn, fragment_cards=scoped_cards)
            conn.commit()
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "creative_kb_complete",
                        "total_documents": total_documents,
                        "attempted_docs": 0,
                        "built_cards": 0,
                        "skipped_existing_or_empty_docs": len(skipped_doc_ids),
                        "remaining_docs": 0,
                        "cluster_count": len(clustering_result.fragment_clusters),
                    }
            )
            semantic_alias_count, semantic_alias_sampled_doc_ids, semantic_alias_warnings = self._extract_and_persist_aliases(
                conn,
                documents=normalized_documents,
                progress_callback=progress_callback,
            )
            return CreativeKBBuildResult(
                built_cluster_count=len(clustering_result.fragment_clusters),
                representative_count=sum(1 for card in clustering_result.fragment_cards if card.is_cluster_representative),
                cluster_ids=[cluster.cluster_id for cluster in clustering_result.fragment_clusters],
                skipped_doc_ids=sorted(skipped_doc_ids),
                semantic_alias_count=semantic_alias_count,
                semantic_alias_sampled_doc_ids=semantic_alias_sampled_doc_ids,
                warnings=["no buildable documents for creative kb", *semantic_alias_warnings],
            )

        build_results = []
        persisted_cards: list[FragmentCard] = []
        failed_doc_ids: list[str] = []
        attempted_docs = 0
        batch_size = max(1, int(commit_batch_size))
        for start in range(0, len(buildable_documents), batch_size):
            batch_documents = buildable_documents[start : start + batch_size]
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "fragment_cards_batch_start",
                        "total_documents": total_documents,
                        "total_buildable_documents": total_buildable,
                        "attempted_docs": attempted_docs,
                        "built_cards": len(persisted_cards),
                        "failed_docs": len(failed_doc_ids),
                        "skipped_existing_or_empty_docs": len(skipped_doc_ids),
                        "remaining_docs": max(0, total_buildable - attempted_docs),
                        "batch_document_count": len(batch_documents),
                        "first_doc_id": str(batch_documents[0].doc_id) if batch_documents else "",
                        "last_doc_id": str(batch_documents[-1].doc_id) if batch_documents else "",
                    }
                )
            batch_results = []
            for document in batch_documents:
                if progress_callback is not None:
                    progress_callback(
                        {
                            "phase": "fragment_card_document_start",
                            "total_documents": total_documents,
                            "total_buildable_documents": total_buildable,
                            "attempted_docs": attempted_docs,
                            "built_cards": len(persisted_cards),
                            "failed_docs": len(failed_doc_ids),
                            "skipped_existing_or_empty_docs": len(skipped_doc_ids),
                            "remaining_docs": max(0, total_buildable - attempted_docs),
                            "current_doc_id": str(document.doc_id),
                            "current_document_chars": document.content_chars,
                        }
                    )
                result = self.fragment_card_builder_service.build_card_result(document)
                batch_results.append(result)
                attempted_docs += 1
                if result.fragment_card is not None:
                    persisted_cards.append(result.fragment_card)
                if result.status == "failed":
                    failed_doc_ids.append(str(document.doc_id))
                if progress_callback is not None:
                    progress_callback(
                        {
                            "phase": "fragment_card_document_done",
                            "total_documents": total_documents,
                            "total_buildable_documents": total_buildable,
                            "attempted_docs": attempted_docs,
                            "built_cards": len(persisted_cards),
                            "failed_docs": len(failed_doc_ids),
                            "skipped_existing_or_empty_docs": len(skipped_doc_ids),
                            "remaining_docs": max(0, total_buildable - attempted_docs),
                            "current_doc_id": str(document.doc_id),
                            "status": result.status,
                            "used_fallback": result.used_fallback,
                        }
                    )
            self.fragment_cards_repo.upsert_cards(
                conn,
                [result.fragment_card for result in batch_results if result.fragment_card is not None],
            )
            conn.commit()
            build_results.extend(batch_results)
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "fragment_cards",
                        "total_documents": total_documents,
                        "total_buildable_documents": total_buildable,
                        "attempted_docs": attempted_docs,
                        "built_cards": len(persisted_cards),
                        "failed_docs": len(failed_doc_ids),
                        "skipped_existing_or_empty_docs": len(skipped_doc_ids),
                        "remaining_docs": max(0, total_buildable - attempted_docs),
                        "current_doc_id": str(batch_documents[-1].doc_id) if batch_documents else "",
                        "committed": True,
                    }
                )

        scoped_cards = self.fragment_cards_repo.list_by_doc_ids(
            conn,
            doc_ids=[str(document.doc_id) for document in normalized_documents],
        )
        clustering_result = self.fragment_cluster_service.cluster_and_persist(conn, fragment_cards=scoped_cards)
        conn.commit()
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "creative_kb_complete",
                    "total_documents": total_documents,
                    "attempted_docs": attempted_docs,
                    "built_cards": len(persisted_cards),
                    "failed_docs": len(failed_doc_ids),
                    "skipped_existing_or_empty_docs": len(skipped_doc_ids),
                    "remaining_docs": 0,
                    "cluster_count": len(clustering_result.fragment_clusters),
                    "representative_count": sum(
                        1 for card in clustering_result.fragment_cards if card.is_cluster_representative
                    ),
                }
            )
        semantic_alias_count, semantic_alias_sampled_doc_ids, semantic_alias_warnings = self._extract_and_persist_aliases(
            conn,
            documents=normalized_documents,
            progress_callback=progress_callback,
        )
        warnings = self._collect_warnings(build_results=build_results, skipped_doc_ids=skipped_doc_ids)
        warnings.extend(warning for warning in semantic_alias_warnings if warning not in warnings)
        representative_count = sum(1 for card in clustering_result.fragment_cards if card.is_cluster_representative)

        return CreativeKBBuildResult(
            built_fragment_count=len(persisted_cards),
            built_cluster_count=len(clustering_result.fragment_clusters),
            representative_count=representative_count,
            fragment_ids=[card.fragment_id for card in persisted_cards],
            cluster_ids=[cluster.cluster_id for cluster in clustering_result.fragment_clusters],
            failed_doc_ids=failed_doc_ids,
            skipped_doc_ids=sorted(skipped_doc_ids),
            semantic_alias_count=semantic_alias_count,
            semantic_alias_sampled_doc_ids=semantic_alias_sampled_doc_ids,
            warnings=warnings,
        )

    def _extract_and_persist_aliases(
        self,
        conn: sqlite3.Connection,
        *,
        documents: Sequence[DocumentRow],
        progress_callback: CreativeKBProgressCallback | None,
    ) -> tuple[int, list[str], list[str]]:
        if not documents:
            return 0, [], []
        book_id = documents[0].book_id
        try:
            result = self.semantic_alias_extractor_service.extract_aliases(book_id=book_id, documents=documents)
            count = self.semantic_aliases_repo.upsert_aliases(conn, result.aliases)
        except Exception as exc:
            warning = f"semantic alias extraction failed: {exc}"
            return 0, [], [warning]
        conn.commit()
        return count, result.sampled_doc_ids, result.warnings

    def _collect_skipped_doc_ids(
        self,
        conn: sqlite3.Connection,
        documents: Sequence[DocumentRow],
    ) -> set[str]:
        skipped_doc_ids = {
            str(document.doc_id)
            for document in documents
            if not document.content.strip()
        }
        existing_doc_ids = self.fragment_cards_repo.list_existing_doc_ids(
            conn,
            doc_ids=[str(document.doc_id) for document in documents],
        )
        skipped_doc_ids.update(existing_doc_ids)
        return skipped_doc_ids

    def _collect_warnings(
        self,
        *,
        build_results: Sequence,
        skipped_doc_ids: set[str],
    ) -> list[str]:
        warnings: list[str] = []
        seen: set[str] = set()
        if skipped_doc_ids:
            warning = f"skipped existing or empty documents: {', '.join(sorted(skipped_doc_ids))}"
            warnings.append(warning)
            seen.add(warning)
        for result in build_results:
            for warning in result.warnings:
                if warning in seen:
                    continue
                seen.add(warning)
                warnings.append(warning)
        return warnings
