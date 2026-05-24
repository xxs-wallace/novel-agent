# Specs Index For Agents

This directory is the source of truth for the novel continuation system. Use this
index to route context before reading long specs. This file is a navigation aid;
it does not replace any `spec.md`, `design.md`, `contracts.md`, or `tasks.md`.

## Context Loading Policy

Do not read every spec for every task. Start with this file and, when available,
the relevant module's `AGENT_CONTEXT.md`.

Default reading rules:

- User-facing workflow, entry points, visible status text, or confirmation gates:
  read [`spec.md`](spec.md).
- Cross-layer JSON objects, field names, field types, or field semantics:
  read the relevant `contracts.md`.
- Module behavior, boundaries, or capabilities:
  read that module's `spec.md` and, when implementation details matter,
  `design.md`.
- Runtime state machines, rollback, persistence, recovery, or technical tradeoffs:
  read the relevant `design.md`.
- QA, acceptance, task breakdown, or verification work:
  read the relevant `tasks.md`.
- Small local code fixes that do not touch product flow, contracts, prompts,
  model semantics, or persisted objects may read only the relevant code plus the
  module `AGENT_CONTEXT.md`.

When in doubt, expand from context to source documents. `AGENT_CONTEXT.md` files
are summaries for routing and context reduction, not authority for changing
frozen behavior.

## Global Source Of Truth

- [`spec.md`](spec.md): product-level source of truth for the author-facing
  continuation workflow, supported product interfaces, user-visible status text,
  artifact review flow, and manual confirmation rules.
- [`context-map.yaml`](context-map.yaml): code/spec ownership map used to pick
  the smallest relevant document set.
- [`CONTRACT_CHECKLIST.md`](CONTRACT_CHECKLIST.md): quick checklist for deciding
  whether a change must inspect contracts or product flow docs.

## Modules

| Module | Owns | Start Here | Read Contracts When |
| --- | --- | --- | --- |
| [`novel-continuation-mvp`](novel-continuation-mvp/AGENT_CONTEXT.md) | Local run foundation, document baseline, main orchestration, shared cross-layer contracts | `novel-continuation-mvp/AGENT_CONTEXT.md` | Changing `FragmentCard`, `SceneBrief`, `ContextAssemblyPayload`, retrieval result, or `WriterInputBundle` semantics |
| [`narrative-memory-context`](narrative-memory-context/AGENT_CONTEXT.md) | Factual memory, chapter boundaries, close-read outputs, context assembly | `narrative-memory-context/AGENT_CONTEXT.md` | Usually via `novel-continuation-mvp/contracts.md` when crossing into Writer or retrieval |
| [`narrative-indexer`](narrative-indexer/AGENT_CONTEXT.md) | Unified index card families, scene cards, source arc mapping, card query model | `narrative-indexer/AGENT_CONTEXT.md` | When card objects become shared runtime payloads or persisted public contracts |
| [`creative-knowledge-base`](creative-knowledge-base/AGENT_CONTEXT.md) | Creative reference fragments, clusters, `SceneBrief -> coarse retrieval -> rerank` | `creative-knowledge-base/AGENT_CONTEXT.md` | Changing fragment, cluster, `SceneBrief`, coarse retrieval, rerank, or retrieval context fields |
| [`writer-agent-layered-generation`](writer-agent-layered-generation/AGENT_CONTEXT.md) | Writer agent loop, planning layers, artifact review gates, draft generation, writeback | `writer-agent-layered-generation/AGENT_CONTEXT.md` | Changing review decisions, outline research question/answer contracts, or writer-facing shared objects |
| [`outline-analyzer`](outline-analyzer/AGENT_CONTEXT.md) | Read-only literary analysis chat and research loop | `outline-analyzer/AGENT_CONTEXT.md` | When analysis request/response payloads become shared contracts |
| [`reviewer-agent`](reviewer-agent/AGENT_CONTEXT.md) | Model-only read-only review runtime, reviewer tools, report schema | `reviewer-agent/AGENT_CONTEXT.md` | Changing review target, request, plan, tool call/result, evidence, finding, report, suite, or manifest fields |
| [`agentic-benchmark`](agentic-benchmark/AGENT_CONTEXT.md) | Benchmark samples, authorized input boundaries, scoring, smoke runners | `agentic-benchmark/AGENT_CONTEXT.md` | Reusing or wrapping shared Writer, Memory, KB, or Reviewer contracts |
| [`cli-interface`](cli-interface/AGENT_CONTEXT.md) | Unified CLI/TUI product entry, command routing, status presentation, artifact editing | `cli-interface/AGENT_CONTEXT.md` | Mapping UI forms/actions to Writer review or shared JSON decisions |
| [`web-interface`](web-interface/AGENT_CONTEXT.md) | Browser-based author workbench, FastAPI/React split, artifact explorer, web action API | `web-interface/AGENT_CONTEXT.md` | Changing Web API payloads or mapping web actions to Writer contracts |

## Cross-Cutting Routes

- Prompt/model semantic behavior: read the owning module `spec.md` and `design.md`.
  If the path can fail due to missing model, failed model call, or JSON parse
  failure, preserve explicit failed/blocked/skipped/needs_model semantics unless
  a spec authorizes a dry-run/test fallback.
- User-visible status wording: read root [`spec.md`](spec.md), then
  [`cli-interface/design.md`](cli-interface/design.md) or
  [`web-interface/spec.md`](web-interface/spec.md) as appropriate.
- Artifact review and continuation decisions: read root [`spec.md`](spec.md),
  [`writer-agent-layered-generation/spec.md`](writer-agent-layered-generation/spec.md),
  and [`writer-agent-layered-generation/contracts.md`](writer-agent-layered-generation/contracts.md).
- Factual evidence, character/world/chapter/outline memory, or raw text recall:
  read [`narrative-memory-context/spec.md`](narrative-memory-context/spec.md).
- Creative reference, style, atmosphere, structure patterns, or rerank:
  read [`creative-knowledge-base/spec.md`](creative-knowledge-base/spec.md).
- Read-only analysis conversation: read
  [`outline-analyzer/spec.md`](outline-analyzer/spec.md).
- Formal review: read [`reviewer-agent/spec.md`](reviewer-agent/spec.md) and
  [`reviewer-agent/contracts.md`](reviewer-agent/contracts.md).
- Benchmark leakage or authorized future information: read
  [`agentic-benchmark/spec.md`](agentic-benchmark/spec.md).
