# Agent Context: outline-analyzer

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, `prompts.md`, or `tasks.md`.

## Owns

- Read-only literary/outline analysis chat mode.
- Analyzer seed packets, research requests, research loop state, notebook, and response requirements.
- Model-guided exploration over Memory, Narrative Indexer, SourceArc, Creative KB, and raw excerpts through controlled brokers.
- Analyzer benchmark design.

## Does Not Own

- Writer planning artifacts or automatic Writer continuation.
- Memory/KB writes.
- Formal Reviewer evaluation of generated drafts.
- Product-level visible workflow/status text outside Analyzer mode.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for product boundary, read policy, response requirements, and degraded modes.
- `design.md` for loop algorithm, components, prompt inputs, web/CLI integration, and benchmark.
- `prompts.md` before changing Analyzer prompt behavior.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

If Analyzer payloads become shared API or persisted contracts, check the
consuming module and add/read an explicit contract before freezing field
semantics.

## Likely Code

- `novel_agent/app/services/outline_analyzer_service.py`
- `novel_agent/app/services/outline_analyzer_benchmark_service.py`
- `novel_agent/app/run_outline_analyzer_benchmark.py`
- `novel_agent/app/services/narrative_inquiry_broker.py`

## Guardrails

- Analyzer is read-only: no Memory, KB, Writer run state, workflow state, or formal artifact writes.
- It must distinguish confirmed fact, reasonable inference, uncertain gap, user preference, and speculative option.
- It must not feed an entire book into one prompt.
- Missing model or JSON failure must not be replaced by local semantic heuristics.
