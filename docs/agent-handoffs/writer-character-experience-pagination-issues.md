# Writer Character Experience Pagination Issues

This is a development handoff note for follow-up agents. It is not a source-of-truth spec. Normative rules remain in `.trae/specs/spec.md`, `.trae/specs/writer-agent-layered-generation/spec.md`, `.trae/specs/writer-agent-layered-generation/design.md`, and related contracts.

## Background

Analyzer recently exposed a retrieval failure mode: a character profile was technically read, but only a small query-relevant slice of `story_events_json` reached the model. A key relationship-changing experience existed in the SQLite character profile, but did not enter the prompt because the initial query was broad and the resolver returned only an early slice.

The same class of risk appears in writer-side flows. It is not identical in every path, but the shared failure pattern is:

- character profile exists and contains the needed `story_events_json` item;
- the model sees only a narrow or early subset of experiences;
- later planning or drafting proceeds with a false "missing evidence" assumption, or misses a relationship / continuity constraint.

## Affected Paths

### 1. Outline Writer / Outline Research Loop

Relevant code:

- `novel_agent/app/services/outline_research_service.py`
- `novel_agent/app/schemas/orchestration_schema.py`

Observed behavior:

- `ResearchRequestType` only allows `story_detail`, `character_profile`, `world_concept`, and `structure_pattern`.
- `OutlineResearchService._resolve_character_profile()` returns full `relationships_json`, `story_events_json`, and `recent_activity_json` for matching profiles.
- `OutlineResearchService.resolve_requests()` then computes `summary_size`; if it exceeds the per-request budget, it replaces the structured results with one `summary` field produced by truncating `json.dumps(result.results)`.

Risk:

- A key experience later in `story_events_json` can be lost by budget truncation.
- Outline Research has no `character_experience` request type and no offset / pagination metadata, so the model cannot intentionally page through a character's experience list.
- `ResearchRequest.dedupe_key` does not include metadata, so adding pagination later requires dedupe changes too.

Recommended fix:

- Add a `metadata` field to `ResearchRequest`.
- Include `metadata` in `ResearchRequest.dedupe_key`.
- Extend `character_profile` handling to support `metadata.story_events_offset` and `metadata.story_events_char_budget`, with a hard production cap of 4096 characters per page.
- Return a page descriptor such as `story_events_page: { offset, next_offset, total, has_more, chars_returned }`.
- Update Outline Research prompt to tell the model to page through `story_events_json` when outline planning depends on relationship turns, shared history, promises, injuries, betrayals, rescues, major state changes, or other character-continuity events.

### 2. Draft Research Loop

Relevant code:

- `novel_agent/app/services/draft_research_service.py`

Observed behavior:

- Draft Research already advertises `character_experience`.
- `_query_character_experience()` scans full `story_events` across profiles by query tokens and returns up to 8 matching experiences, then expands up to 6 `outline_segment_id` refs.
- `_character_index()` builds `key_experience_index` from `story_events[:6]`.
- `_query_character_profile()` returns matched full profiles, which may be large and later compressed by the model-side notebook extraction step.

Risk:

- Initial seed visibility is biased toward early experiences because `key_experience_index` uses `story_events[:6]`.
- If the model does not already know which keywords to query, it may never ask `character_experience` for later experiences.
- `character_experience` is keyword-scan based, not page based. This is useful when the model knows what to look for, but weaker when the model needs to browse a character's experience chronology.

Recommended fix:

- Keep `character_experience` for targeted lookup.
- Add offset pagination to `character_profile` or `character_experience`, using the same `story_events_offset` / `story_events_char_budget` metadata convention.
- Change `key_experience_index` from first-N events to a more balanced index:
  - include recent events;
  - include events with current chapter / planned character matches;
  - include high-impact relationship/state-change experiences when available;
  - expose total count and page-read instruction if the list is partial.
- Update Draft Research prompt to explicitly page through experiences when drafting depends on current character state, relationship debt, shared history, or voice/behavior boundary.

### 3. Writer Prompt Assembly / Draft Prose Executor Inputs

Relevant code:

- `novel_agent/app/orchestrators/writer_execution.py`

Observed behavior:

- `_relevant_character_profiles_for_prompt()` selects profiles by whether names/aliases appear in `matcher_text`.
- `_prompt_character_profile()` includes:
  - `profile_summary_md` truncated to 1200 characters;
  - relationship facts selected by local relation matching;
  - `recent_activity` via `_prompt_profile_items(..., limit=6)`;
  - `story_events` via `_prompt_profile_items(..., limit=6)`.
- `_prompt_profile_items()` takes the first N items and truncates fields such as `value`, `summary`, and `status_summary`.

Risk:

- The final draft prompt can miss later or more relevant experiences even when Draft Research found them, especially if the prompt assembly path is used as a direct factual safety net.
- First-six `story_events` is especially unsafe for long-running characters whose important relationship/state changes occur after early introduction.

Recommended fix:

- Do not feed first-N `story_events` into final prompt assembly.
- Prefer facts already selected into `draft_context_notebook.json`.
- When adding character profile context as a safety net, select events by relevance to current `chapter_brief`, `relation_state_gate`, `user_supplement`, and recent story anchor.
- If relevance is insufficient or ambiguous, include a compact experience index with `story_events_page` metadata instead of pretending the first-N list is representative.

### 4. Context Assembly

Relevant code:

- `novel_agent/app/services/context_assembly_service.py`

Observed behavior:

- `ContextAssemblyService._assemble_character_profiles()` includes `profile_summary_md` and a `recent_activity_summary` made from the last 3 recent activity items.
- It does not include `story_events_json`.

Risk:

- This is less like the Analyzer bug and more like a deliberately lightweight context path.
- It should not be used as the only source for relationship-specific continuity decisions.

Recommended fix:

- Leave this path lightweight unless product scope requires richer context assembly.
- If used for writing decisions that depend on relationship history, route through the Writer research loop or shared character experience resolver first.

## Shared Implementation Direction

Prefer a shared resolver utility rather than divergent per-agent copies:

```text
character_profile request
  metadata.story_events_offset: integer >= 0
  metadata.story_events_char_budget: integer <= 4096
  -> returns story_events page in original chronology
  -> returns story_events_page metadata
```

The resolver should preserve source refs such as:

- `experience_id` / `event_id`
- `outline_segment_id`
- `source_chapter_indexes`
- `source_doc_ids`
- `source_doc_range`

Do not add novel-specific keywords, role names, relationship types, or hardcoded plot concepts. The fix should be a generic ability to browse character experience chronology and then let the model decide which experiences matter.

## Suggested Tests

- Outline Research: a profile with 10 story events and a key event at index 8 can be retrieved via `metadata.story_events_offset=8`.
- Outline Research: two requests for the same character with different offsets are not deduped.
- Draft Research: `character_experience` or `character_profile` pagination can retrieve a later experience even when `key_experience_index` does not include it.
- Writer prompt assembly: final character profile context does not blindly return `story_events[:6]`; it either uses selected notebook facts or relevance-ranked / paginated experience context.

## Current Analyzer Reference

Analyzer now supports this pattern in:

- `novel_agent/app/services/narrative_inquiry_broker.py`
- `novel_agent/app/schemas/narrative_inquiry_schema.py`
- `novel_agent/app/services/outline_analyzer_service.py`

Use that implementation as a reference, but keep writer contracts aligned with `writer-agent-layered-generation` specs.
