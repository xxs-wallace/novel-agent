# Agent Context: reviewer-agent

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, `contracts.md`, or `tasks.md`.

## Owns

- Independent, read-only, model-driven review runtime.
- Review target resolution, reviewer loop, reviewer registry/suite, reviewer tools, and persisted reports.
- Formal reviewer categories for outline, synopsis, local draft continuity, memory consistency, and KB style/atmosphere.
- Reviewer contracts and smoke tests.

## Does Not Own

- Writer artifact generation or workflow approval.
- Memory/KB writes.
- Benchmark pass/fail rules.
- Product UI flow unless Reviewer is surfaced through another module.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for module boundary, model-only requirement, agent loop, and report semantics.
- `design.md` for runtime components, state machine, Broker-backed Memory access, reviewer types, smoke design, and persistence.
- `contracts.md` before changing any Reviewer schema.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

Read `contracts.md` before changing:

- `ReviewTarget`
- `ReviewContextPolicy`
- `ReviewBudget`
- `ReviewRequest`
- `ResolvedReviewTarget`
- `ReviewPlan`
- `ReviewerToolCall`
- `ReviewerToolResult`
- `EvidenceRef`
- `ReviewFinding`
- `ReviewReport`
- `ReviewSuiteReport`
- `ReviewerManifest`

## Likely Code

- `novel_agent/app/reviewer/base.py`
- `novel_agent/app/reviewer/runtime.py`
- `novel_agent/app/reviewer/registry.py`
- `novel_agent/app/reviewer/suite.py`
- `novel_agent/app/reviewer/target_resolver.py`
- `novel_agent/app/reviewer/tools.py`
- `novel_agent/app/reviewer/reviewers/*.py`
- `novel_agent/app/prompts/reviewer/prompt_builder.py`
- `novel_agent/app/services/reviewer_smoke_service.py`
- `novel_agent/app/run_reviewer_smoke.py`
- `novel_agent/app/schemas/reviewer_schema.py`

## Guardrails

- Formal Reviewer must be model-based; deterministic fake/baseline implementations belong only in benchmark/test boundaries and must be labeled.
- Reviewer reads Memory/KB through controlled tools; Memory access routes through `ReviewerMemoryTool` and Broker-backed inquiry, and must not write facts or artifacts.
- Failed model calls or JSON parsing failures must produce failed reports, not successful fake reviews.
- Writer-assist review must not read benchmark held-out reference truth.
