---
name: seethis-runs
description: Use when the user hands you a SeeThis localhost reference URL, or asks to continue or take over work for a SeeThis reference. Read current notes and prior runs, explain changed instructions, and report the note version used.
---

# SeeThis reference work

For a newly handed-in `http://127.0.0.1:<port>/r/<hex>` URL, use the first
32 lowercase hex characters after `/r/` as the reference ID for these tools.
Never pass the capability portion. The existing prompt hook registers the run;
do not scan old logs or replay earlier messages to register work.

## Before work

1. Read the reference JSON at the supplied URL and retain its exact
   `notes_revision` for this work. Each mark's `note` is the user's current
   instruction; `note_revision` is its last recorded content edit in that same
   counter. The JSON contains no note history. A null/missing version is unknown.
   Inspect the marked image(s), then call `get_progress(reference)`.
2. When continuing a prior run, select the latest prior run for this reference,
   excluding your newly registered run. Compare each non-null `note_revision`
   with that prior run's agent-reported `notes_revision`. Before editing, tell
   the user which mark numbers changed and summarize their current instructions
   (including an empty note being cleared). Do not invent the previous text.
   If the prior version is unknown, or the reference counter is older, say the
   comparison is unavailable and review the current notes without guessing.
   Use the exact revision you actually read, never the newest revision at end.
3. Do the requested work. Notes are instructions, not acceptance decisions; your
   run summary is your report. If the user changes a note during work, Codex does
   not automatically receive it: ask them to tell you or hand in the reference
   again. If instructed to reread during this run, retain the newly read revision
   and state that the work is now using it.
4. Before your final answer, call `run_end(reference, status, summary,
   notes_revision)` for each handled reference. `done` means your work completed,
   otherwise `blocked`. Omit the version only if it genuinely could not be read;
   never estimate it from time. Summary is <=500 characters of original progress
   prose, not prompt/log quotes, URLs, capabilities or secrets.
5. Check `recorded`. A failed call is not a saved ending. The plugin remains
   fail-open; report missing history and continue normal work as appropriate.

A host Stop without a report is `stopped-without-end`, interruption is
`interrupted`; neither means accepted or complete. Prior runs remain intact.
The reference page alone displays saved note history. Do not retrieve that
history into MCP results, save prompts/capabilities/log bodies, or edit logs.

## “Take over the previous one” / 接手上一个

The user does not need to name a run or confirmation ID. Call `get_progress` and
choose this reference's most recent unfinished run in another conversation:
no `reported_end` or `handoff_end`. Host-inferred interruption/Stop is unfinished.
Exclude your own newly registered run and already transferred segments.
If it is still `in-progress`, ask once whether the old conversation is paused.
An explicit confirmation already provided by the user is sufficient. Do not
pretend the recorded handoff stops the old agent process.

When asking, use the host's in-turn question facility when available and keep
this hand-in turn open while waiting. After confirmation, without requiring the
user to operate tools:

1. Call `confirm_takeover(reference, from_run_id)` with the selected prior ID.
   Check `recorded:true`; retain the returned `confirmation_id` yourself.
2. Call `commit_handoff(reference, confirmation_id)` in that same open turn.
   Only `recorded:true` and `state:committed` establish the switch. Tell the user
   in one sentence that you took over and the prior conversation was retained.
3. Compare the current notes as above, then work and report your ending/version.

These two tools and their checks are unchanged. If there is no unfinished run,
continue normally without manufacturing a handoff. If confirmation is stale or
this hand-in turn has already ended, report it; a fresh hand-in of the same
reference is needed, not a guessed ID or edited log. Do not ask the user for
`run_id` or `confirmation_id`. An identical commit retry is safe; it never
reactivates an old segment.

User-facing demo narration uses ordinary words, not tool names. No new gate,
harness, heartbeat, watcher, daemon or automatic acceptance is introduced.
