# Agent Context: cli-interface

This summary routes agents to the right source docs. It is not a replacement for
`design.md`, `tasks.md`, `prompts.md`, or `agent-prompts.md`.

## Owns

- Unified CLI/TUI author-facing interaction design.
- Command routing, modes, page layout, input buffer behavior, command palette, status sidebar, run event stream, artifact presentation, scoped artifact revision, and Textual milestones.
- CLI/TUI mapping from user actions/forms to shared Writer and artifact decision contracts.

## Does Not Own

- Product-level workflow/status semantics; read `../spec.md`.
- Writer workflow itself; read `../writer-agent-layered-generation/spec.md`.
- Web implementation; read `../web-interface/spec.md`.
- Benchmark smoke semantics; read `../agentic-benchmark/spec.md`.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `design.md` for CLI/TUI architecture and interaction mapping.
- `tasks.md` for implementation task groups and acceptance work.
- `prompts.md` or `agent-prompts.md` only when changing CLI-related prompt/delegation guidance.

## Contract Triggers

Read `../writer-agent-layered-generation/contracts.md` before changing:

- artifact review decisions;
- chapter draft decisions;
- Writer question/answer mapping;
- form-to-JSON mapping for review gates.

Read `../novel-continuation-mvp/contracts.md` before changing shared retrieval or Writer input objects.

## Likely Code

- `novel_agent/app/cli/app.py`
- `novel_agent/app/cli/artifacts.py`
- `novel_agent/app/cli/decisions.py`
- `novel_agent/app/cli/events.py`
- `novel_agent/app/cli/facade.py`
- `novel_agent/app/cli/forms.py`
- `novel_agent/app/cli/input.py`
- `novel_agent/app/cli/router.py`
- `novel_agent/app/cli/status.py`
- `novel_agent/app/cli/textual_app.py`
- `novel_agent/app/cli/textual_screens.py`
- `novel_agent/app/cli/textual_widgets.py`
- `novel_agent/app/cli_tui.py`

## Guardrails

- CLI/TUI must share product semantics with Web/GUI.
- Internal state names, checkpoints, and artifact ids can appear in technical details, logs, JSON, or developer views, but not as primary user status.
- Artifact edits must preserve review/continuation semantics and not silently confirm changes.
