# Agent Context: writer-agent-layered-generation

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, `contracts.md`, or `tasks.md`.

## Owns

- Writer Agent Loop and layered continuation generation.
- Modeling baseline checks, story scale/climax inputs, plan generation, world/character supplementation, batch planning, chapter synopsis, draft generation, review gates, rollback, and writeback.
- Artifact review gates and user confirmation/resume semantics.
- Outline Research Loop and runtime boundaries under this module's subdirectories.

## Does Not Own

- Product-level visible workflow/status wording; read `../spec.md`.
- Original import and document baseline; read `../novel-continuation-mvp/spec.md`.
- Factual Memory internals; read `../narrative-memory-context/spec.md`.
- Creative KB fields/rerank; read `../creative-knowledge-base/spec.md`.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for Writer layer requirements and agent-loop semantics.
- `design.md` for implementation flow, review gates, rollback, and artifacts.
- `contracts.md` before changing review/user-input JSON.
- `specs/runtime-boundaries.spec.md` for draft execution, recovery, and writeback boundaries.
- `designs/outline-research-loop.design.md` for Outline Research Loop details.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

Read `contracts.md` before changing:

- `ArtifactReviewDecision`
- `GenerationReviewDecision`
- `OutlineResearchQuestionSet`
- `OutlineResearchAnswerSubmission`

Also read `../novel-continuation-mvp/contracts.md` before changing shared
cross-layer inputs such as `WriterInputBundle`, `SceneBrief`, or
`ContextAssemblyPayload`.

## Likely Code

- `novel_agent/app/orchestrators/writer_layered_generation.py`
- `novel_agent/app/orchestrators/writer_execution.py`
- `novel_agent/app/orchestrators/writer_workflow.py`
- `novel_agent/app/orchestrators/writer_planning_types.py`
- `novel_agent/app/orchestrators/scoped_artifact_revision.py`
- `novel_agent/app/services/outline_research_service.py`
- `novel_agent/app/services/writer_memory_workspace_service.py`
- `novel_agent/app/services/continuation_generation_service.py`
- `novel_agent/app/prompts/writer_planning_prompt.py`
- `novel_agent/app/schemas/orchestration_schema.py`

## Guardrails

- New flow uses a small state machine and artifact review records, not old Freeze A/B/C/D/E as the primary user model.
- Technical artifact ids, checkpoints, stage names, and workflow actions are debug/log/action details, not main UI status text.
- User-approved or user-edited planning material becomes downstream input.
- Chapter synopsis approval should flow into draft preparation/generation; separate length confirmation is not a mandatory user gate unless the active spec says otherwise.
- Upstream edits must trigger appropriate downstream rollback/revision.
