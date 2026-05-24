# Agent Context: creative-knowledge-base

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, or `tasks.md`.

## Owns

- Creative reference cards/fragments, fragment clusters, near-duplicate handling, and representative selection.
- Online retrieval flow: `SceneBrief -> coarse retrieval -> rerank`.
- Style, atmosphere, emotional mechanism, scene structure, and transferable writing reference.
- Creative KB benchmark and Writer A/B diagnostic surfaces.

## Does Not Own

- Factual character/world/chapter memory; read `../narrative-memory-context/spec.md`.
- Product UI flow/status text; read `../spec.md`.
- Writer generation itself; read `../writer-agent-layered-generation/spec.md`.
- Factual Narrative Indexer card families; read `../narrative-indexer/spec.md`.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for fragment, cluster, retrieval, and rerank requirements.
- `design.md` for storage, schemas, prompts, services, migration, and benchmark flow.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

Read `../novel-continuation-mvp/contracts.md` before changing:

- `FragmentCard`
- `FragmentCluster`
- `SceneBrief`
- `RetrievalContext`
- `CoarseRetrievalResult`
- `RerankResult`

## Likely Code

- `novel_agent/app/services/creative_kb_facade.py`
- `novel_agent/app/services/fragment_card_builder_service.py`
- `novel_agent/app/services/fragment_cluster_service.py`
- `novel_agent/app/services/scene_brief_service.py`
- `novel_agent/app/services/coarse_retrieval_service.py`
- `novel_agent/app/services/rerank_service.py`
- `novel_agent/app/services/retrieval_context_adapter.py`
- `novel_agent/app/repos/creative_kb_storage.py`
- `novel_agent/app/repos/fragment_cards_repo.py`
- `novel_agent/app/repos/fragment_clusters_repo.py`
- `novel_agent/app/prompts/fragment_card_prompt.py`
- `novel_agent/app/prompts/scene_brief_prompt.py`
- `novel_agent/app/prompts/rerank_prompt.py`
- `novel_agent/app/schemas/creative_kb_schema.py`

## Guardrails

- Tags are coarse-filter aids, not the primary retrieval truth.
- Creative KB results must not be promoted into factual Memory.
- Final references should avoid duplicate fragments from the same cluster.
- Online retrieval should not re-analyze large amounts of original text.
