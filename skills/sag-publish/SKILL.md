---
name: sag-publish
description: Use immediately after creating or editing a markdown document (requirement, ADR, design doc, research report, runbook, postmortem, API contract) — self-assess whether the content is durable, shared knowledge worth publishing to the SAG knowledge base, and call sag_publish if so. Also use when the user explicitly asks to publish a document to the knowledge base.
---

# sag-publish — awareness and self-publishing knowledge

You have real judgment authority: every time you **finish creating or editing**
a document, ask yourself *"is this content knowledge that another agent will
need?"* and act on that judgment — no need to wait to be prompted, no need to
ask before publishing if you're confident enough. The engine decides on its own
whether to publish immediately or queue it; you don't need to know that detail,
just assess honestly and call the tool.

## When to run this assessment

- Right after you finish `Write`/`Edit` on a `.md` file in the repo (you'll be
  reminded by a hook if you forget, but don't wait to be reminded).
- At the end of a unit of work that produces a durable decision/contract/process
  (an ADR is finalized, an API contract changes, a runbook is confirmed correct,
  a postmortem is complete, research is accepted).
- When the user says a finalizing statement ("lock in this approach", "this is
  the final decision").
- When you discover that an existing SAG document is now incorrect relative to
  reality — draft a corrected version and assess that corrected version.

**Do not assess** (skip, don't call the tool): mid-task notes, debug logs,
unfinalized intermediate conclusions, anything that belongs to Honcho or to task
status in GitLab/issue trackers, and anything **not yet committed** (assessment
only makes sense after you've already `git commit`ed the file — sagctl will
reject it if the file is still dirty).

## Thinking framework (5 criteria — not a rigid form to fill out)

1. **Durable** — still correct and still needed weeks/months from now, not a
   temporary state of the current task.
2. **Shared** — at least one other agent/role besides you will need to look it
   up.
3. **Fits SAG's retrieval model** — written as a complete, self-contained
   proposition, with a clear subject/timeframe, using consistent entity names,
   with each heading standing on its own. Keep technical identifiers (function
   names, endpoints, error codes) verbatim.
4. **Committed** — sagctl checks this deterministically; you don't need to
   check it yourself.
5. **Free of secrets/PII** — sagctl scans deterministically before upload; you
   just need to avoid deliberately including secrets, no need to manually scan.

## User-specific criteria

If the source's `.sag-sync.json` (manifest) has a `criteria` array, **read and
apply them — they take precedence over the 5 default criteria**. For example:
"never include meeting notes", "pricing documents must ask first". When calling
`sag_publish`, list the exact `id`s of the criteria you actually applied in
`assessment.criteria_ack` — if the manifest has criteria but you don't list any
ids, the engine will not auto-publish (it will queue the item for human
review), because it cannot tell whether you read the criteria or not.

## Calling the `sag_publish` tool

```json
{
  "path": "docs/adr/adr-0013.md",
  "assessment": {
    "verdict": "knowledge",
    "durable": {"pass": true, "why": "API contract, referenced across multiple sprints"},
    "audience": {"pass": true, "why": "needed by both developers and QA"},
    "retrieval_fit": {"pass": true, "why": "complete, self-contained propositions, named entities"},
    "confidence": 0.86,
    "rationale": "User confirmed this approach was finalized in this session",
    "criteria_ack": ["c1"]
  }
}
```

`verdict` is the most important judgment — `"knowledge"` if it belongs in the
knowledge base, `"not-knowledge"` if not (the tool won't publish anything, just
records it), `"unsure"` if you're uncertain (it will go into the queue for a
human to review). Don't inflate `confidence` to "clear the threshold" —
periodic post-hoc review re-grades automated publishes, and repeated bad
assessments will get your self-publish privilege downgraded.

## After calling the tool

- A `status: "pending"` result means it has been sent to SAG and is being
  processed — **don't wait around** (ingestion can take a few minutes).
  Continue with other work.
- At the end of the session, or when you need certainty, verify with
  `sag_publish_status` or with `grep`/`search` via the `sag-knowledge` skill —
  report the citation path back to the user (`source + file path`), not
  `document_id`.
- A `status: "queued"` result means there wasn't enough confidence to
  auto-publish — tell the user the reason (`reason`); they or a reviewer will
  approve it through the queue.
- If the tool reports a `DENIED_PATH` or `SECRET_FOUND` error, don't try to
  work around it (don't use Bash to call `sagctl` directly to bypass it) —
  report it back to the user.

## The user's manual path (not yours to initiate on your own)

If the user gives a direct order like "put the entire docs/specs folder into
the knowledge base", that's a manual command — direct them to use
`/sag-publish <path|glob>` (see the slash command), not you calling
`sag_publish` yourself with a fabricated assessment. The `sag_publish` tool has
no way for you to declare "the user ordered it" — every call you make always
goes through a real assessment.
