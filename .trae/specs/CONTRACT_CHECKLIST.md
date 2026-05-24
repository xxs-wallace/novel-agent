# Contract And Context Checklist

Use this before implementation to decide the smallest required spec set.

## Must Read Root Product Spec

Read [`spec.md`](spec.md) when a change touches:

- user-facing entry points, modes, pages, or commands;
- user-visible status text;
- artifact review, manual confirmation, accept/rewrite/continue behavior;
- whether CLI/TUI, Web, and GUI should share the same workflow semantics;
- one-shot MVP compatibility versus formal product entry points.

## Must Read Contracts

Read the relevant `contracts.md` before changing:

- JSON field names, field types, enum values, required fields, or default meaning;
- persisted artifact schema or API payload schema;
- cross-layer objects passed between orchestration, Memory, KB, Writer, Reviewer,
  Benchmark, CLI, or Web;
- adapter behavior that maps old objects into frozen contracts.

Known contract files:

- [`novel-continuation-mvp/contracts.md`](novel-continuation-mvp/contracts.md):
  shared cross-layer objects such as `FragmentCard`, `FragmentCluster`,
  `SceneBrief`, `ContextAssemblyPayload`, `RetrievalContext`,
  `CoarseRetrievalResult`, `RerankResult`, and `WriterInputBundle`.
- [`writer-agent-layered-generation/contracts.md`](writer-agent-layered-generation/contracts.md):
  Writer review/user-input objects such as `ArtifactReviewDecision`,
  `GenerationReviewDecision`, `OutlineResearchQuestionSet`, and
  `OutlineResearchAnswerSubmission`.
- [`reviewer-agent/contracts.md`](reviewer-agent/contracts.md): Reviewer objects
  such as `ReviewTarget`, `ReviewRequest`, `ReviewPlan`,
  `ReviewerToolCall`, `ReviewerToolResult`, `EvidenceRef`, `ReviewFinding`,
  `ReviewReport`, `ReviewSuiteReport`, and `ReviewerManifest`.

## Must Preserve Model Semantics

If production behavior needs model understanding of text, summaries, characters,
relationships, plot structure, planning, or review:

- do not replace model judgment with deterministic local heuristics;
- retry only within the bounded policy implemented by the owning module;
- after retry exhaustion, return or persist explicit failure semantics such as
  `failed`, `blocked`, `skipped`, or `needs_model`;
- only use local fallback in spec-authorized dry-run, test, migration, or safety
  paths, and mark outputs as `dry_run`, `fallback`, or `provisional`.

## Usually Enough To Read Module Context Only

For narrow refactors that do not change behavior, contracts, prompts, status
copy, persistence shape, model semantics, or product flow:

- read the module `AGENT_CONTEXT.md`;
- read the directly edited code;
- read tests that exercise the edited path.

Escalate to source specs as soon as implementation choices depend on a boundary,
field meaning, status text, failure state, or user confirmation point.
