# Agent Context: narrative-memory-context

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, or `tasks.md`.

## Owns

- Factual Memory and context assembly.
- Chapter boundary detection for ingest.
- Character profiles, world memory, chapter memory, story outline memory, and progress memory.
- Close-read outputs that later feed Narrative Indexer and Writer.
- Structured factual context used for continuation.

## Does Not Own

- Creative reference fragments, clusters, or rerank; read `../creative-knowledge-base/spec.md`.
- Product UI flow/status text; read `../spec.md`.
- Writer planning artifact generation; read `../writer-agent-layered-generation/spec.md`.
- SceneCard/SourceArcMap semantics; read `../narrative-indexer/spec.md`.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for memory layer boundaries and factual rules.
- `design.md` for current implementation, storage, prompt inputs, and refactor targets.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

Memory changes often cross into `../novel-continuation-mvp/contracts.md` when
they affect `ContextAssemblyPayload`, `RetrievalContext`, or `WriterInputBundle`.
Read that contract before changing cross-layer payload shape or meaning.

## Likely Code

- `novel_agent/app/services/chapter_boundary_detector.py`
- `novel_agent/app/services/document_ingest_service.py`
- `novel_agent/app/services/chapter_*_service.py`
- `novel_agent/app/services/character_*_service.py`
- `novel_agent/app/services/world_*_service.py`
- `novel_agent/app/services/context_assembly_service.py`
- `novel_agent/app/services/narrative_memory_query_service.py`
- `novel_agent/app/repos/documents_repo.py`
- `novel_agent/app/repos/chapters_repo.py`
- `novel_agent/app/repos/character_profiles_repo.py`
- `novel_agent/app/repos/narrative_memory_pages_repo.py`
- `novel_agent/app/schemas/narrative_memory_schema.py`
- `novel_agent/app/schemas/context_assembly_schema.py`

## Guardrails

- Original Canon First: factual, character, relationship, timeline, and world-rule claims must come from local documents, Memory, KB, or code evidence.
- Memory stores facts, states, relationships, and chronology; it is not a style imitation store.
- Local boundary heuristics may create candidates and confidence, but must not pretend to complete semantic understanding.
- Production model failures must surface explicit failure semantics rather than silent factual fallback.
