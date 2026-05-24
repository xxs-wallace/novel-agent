# Agent Context: novel-continuation-mvp

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, `contracts.md`, or `tasks.md`.

## Owns

- Local run foundation for `novel_agent/`.
- Original text import, `documents` baseline, local pre-segmentation, and smoke-compatible entry points.
- Main orchestration that assembles Memory, Creative KB, Writer, artifacts, and run outputs.
- Shared cross-layer contract draft in `contracts.md`.

## Does Not Own

- Product-level user workflow and visible status text; read `../spec.md`.
- Creative reference card/rerank behavior; read `../creative-knowledge-base/spec.md`.
- Factual Memory internals; read `../narrative-memory-context/spec.md`.
- Writer layer workflow; read `../writer-agent-layered-generation/spec.md`.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for local run boundaries and document baseline rules.
- `design.md` for orchestration flow, current run path, persisted run outputs, and compatibility notes.
- `contracts.md` before changing shared JSON objects.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

Read `contracts.md` before changing:

- `FragmentCard`
- `FragmentCluster`
- `SceneBrief`
- `ContextAssemblyPayload`
- `RetrievalContext`
- `CoarseRetrievalResult`
- `RerankResult`
- `WriterInputBundle`

## Likely Code

- `novel_agent/app/orchestrators/main_layer_orchestrator.py`
- `novel_agent/app/run_mvp.py`
- `novel_agent/app/run_interactive.py`
- `novel_agent/app/run_continue_scene.py`
- `novel_agent/app/schemas/orchestration_schema.py`

## Guardrails

- Formal user product entry points must follow `../spec.md`; legacy one-shot paths are only smoke, compatibility, or migration surfaces.
- User-confirmed or user-edited planning artifacts must become later workflow inputs.
- Do not change shared fields or semantics locally; route through contracts.
