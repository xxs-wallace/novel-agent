# Agent Context: narrative-indexer

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, or `tasks.md`.

## Owns

- Unified `IndexCard` family model after close-read and before Analyzer/Writer/Outline Research.
- Factual, scene, character-state, world-concept, mystery/foreshadow, theme, creative-reference, and arc-pattern card families.
- Narrative scene indexing and `SourceArcMap` as derived structure.
- Card query model and source traceability.

## Does Not Own

- Original import/chapter segmentation source of truth; read `../narrative-memory-context/spec.md`.
- Creative KB fragment/rerank source of truth; read `../creative-knowledge-base/spec.md`.
- Analyzer literary judgment; read `../outline-analyzer/spec.md`.
- Writer artifact generation; read `../writer-agent-layered-generation/spec.md`.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for card family semantics, common card fields, and query model.
- `design.md` for implementation roles, storage, prompt impact, and SourceArcMap flow.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

Read owning contracts when index output becomes a cross-layer payload or public
API object. Creative reference compatibility may require
`../novel-continuation-mvp/contracts.md`; Writer review paths may require
Writer contracts.

## Likely Code

- `novel_agent/app/run_narrative_scene_index.py`
- `novel_agent/app/build_source_arc_map.py`
- `novel_agent/app/services/narrative_index_facade.py`
- `novel_agent/app/services/narrative_scene_indexer_service.py`
- `novel_agent/app/services/source_arc_mapping_service.py`
- `novel_agent/app/services/narrative_inquiry_broker.py`
- `novel_agent/app/prompts/narrative_scene_index_prompt.py`
- `novel_agent/app/prompts/source_arc_prompt.py`
- `novel_agent/app/schemas/narrative_index_schema.py`
- `novel_agent/app/schemas/narrative_inquiry_schema.py`
- `novel_agent/app/schemas/source_arc_schema.py`

## Guardrails

- `documents` are the common leaf source for cards.
- Creative reference cards are writing/style/structure references, not factual evidence.
- Cards must preserve source traceability.
- Online query should start from compact cards and escalate to raw excerpts only when needed.
