# Agent Context: agentic-benchmark

This summary routes agents to the right source docs. It is not a replacement for
`spec.md`, `design.md`, or `tasks.md`.

## Owns

- Benchmark samples, modes, authorized planning boundaries, forward guidance, scoring, leakage audits, and smoke runners.
- Single sample smoke compatibility, longer cached Writer benchmarks, multi-chapter Writer benchmarks, layered Writer benchmark, and reviewer-assisted evaluation.
- Rule/Judge scoring structure and benchmark artifacts.

## Does Not Own

- Product main workflow or UI; read `../spec.md`.
- Writer canonical generation prompts or layer behavior; read `../writer-agent-layered-generation/spec.md`.
- Memory/KB contract definitions; read their owning specs/contracts.
- Formal Reviewer schema; read `../reviewer-agent/contracts.md`.

## Read This First

- `AGENT_CONTEXT.md` for routing.
- `spec.md` for authorized input rules, benchmark modes, scoring, and pass/fail semantics.
- `design.md` for runner structure, data models, runtime flow, and code targets.
- `tasks.md` only for task/QA/acceptance work.

## Contract Triggers

Benchmark may wrap but must not redefine frozen contracts. Read:

- `../novel-continuation-mvp/contracts.md` when driving Writer/Memory/KB payloads.
- `../writer-agent-layered-generation/contracts.md` when using Writer review/input decisions.
- `../reviewer-agent/contracts.md` when storing or invoking formal Reviewer reports.

## Likely Code

- `novel_agent/app/run_single_sample_smoke.py`
- `novel_agent/app/run_paragraph_benchmark.py`
- `novel_agent/app/services/smoke_*.py`
- `novel_agent/app/services/paragraph_benchmark_service.py`
- `novel_agent/app/runner/single_sample_smoke_runner.py`
- `novel_agent/app/schemas/smoke_schema.py`
- `novel_agent/app/schemas/paragraph_benchmark_schema.py`

## Guardrails

- First judge whether continuation is legal, then whether it resembles the original.
- Authorized future planning information is not leakage; unauthorized reference truth is.
- Benchmark should drive formal Writer interfaces, not maintain a parallel hidden Writer prompt path.
- Keep Memory and Creative KB contribution statistics separate.
