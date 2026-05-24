# Agent Context: web-interface

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, or `tasks.md`.

## Owns

- Browser-based author workbench.
- FastAPI/Pydantic/Uvicorn backend direction and React/Vite/TypeScript frontend direction.
- Task rail, conversation pane, result explorer, artifact tree/detail views, web action APIs, job stream, and web-specific view models.
- Web mapping from user actions to shared WorkflowFacade/Writer/action-adapter semantics.

## Does Not Own

- Product-level workflow/status semantics; read `../spec.md`.
- CLI/TUI command/status semantics; read `../cli-interface/design.md`.
- Writer workflow and review gates; read `../writer-agent-layered-generation/spec.md`.
- Memory/KB internals.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for Web product boundary, API contracts, view models, status vocabulary, and acceptance.
- `design.md` for backend/frontend module design, API design, state management, flows, and tests.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

Read `../writer-agent-layered-generation/contracts.md` before changing Web
actions that submit Writer review decisions, question answers, or draft
decisions. Read Web `spec.md` before changing API payloads or view models.

## Likely Code

- `novel_agent/app/web/main.py`
- `novel_agent/app/web/deps.py`
- `novel_agent/app/web/launcher.py`
- `novel_agent/app/web/routes/*.py`
- `novel_agent/app/web/services/*.py`
- `novel_agent/app/web/schemas.py`

## Guardrails

- Web must call shared WorkflowFacade/action-adapter semantics; it must not directly patch Writer state, prompt assembly, Memory rules, or workflow state.
- Do not present raw JSON, internal stage names, checkpoints, or artifact ids as the primary user experience.
- Artifact and Writer views should convert artifacts into user-readable views.
