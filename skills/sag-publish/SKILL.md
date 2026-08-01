---
name: sag-publish
description: Use immediately after creating or editing a document (markdown, or anything else — requirement, ADR, design doc, research report, runbook, postmortem, API contract, PDF/DOCX you analyzed) — self-assess whether the content is durable, shared knowledge worth publishing to the SAG knowledge base, and call sag_publish or sag_publish_content if so. Also use when the user explicitly asks to publish a document to the knowledge base.
---

# sag-publish — awareness and self-publishing knowledge

You have real judgment authority: every time you **finish creating or editing**
a document, ask yourself *"is this content knowledge that another agent will
need?"* and act on that judgment — no need to wait to be prompted, no need to
ask before publishing if you're confident enough. The engine decides on its own
whether to publish immediately or queue it; you don't need to know that detail,
just assess honestly and call the tool.

## When to run this assessment

- Right after you finish `Write`/`Edit` on a document in the repo — not just
  `.md` (you'll be reminded by a hook if you forget, but don't wait to be
  reminded).
- At the end of a unit of work that produces a durable decision/contract/process
  (an ADR is finalized, an API contract changes, a runbook is confirmed correct,
  a postmortem is complete, research is accepted).
- When the user says a finalizing statement ("lock in this approach", "this is
  the final decision").
- When you discover that an existing SAG document is now incorrect relative to
  reality — draft a corrected version and assess that corrected version.
- When you read a PDF/DOCX/other binary with a document skill and it contains
  something durable and shared — distil it into markdown and assess *that*
  (see "Documents you didn't write as a file" below). Never try to publish the
  binary directly.
- When you produce a synthesis with no file behind it at all (a research
  summary from a Hermes session, a distillation across several sources) — same
  judgment call, via `sag_publish_content` instead of `sag_publish`.

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
4. **Committed** (only when the file is inside a Git repo) — sagctl checks
   this deterministically; you don't need to check it yourself. Outside a repo,
   or for `sag_publish_content` (no file at all), this clause does not apply —
   it is not a workaround, there is simply nothing to check it against.
5. **Free of secrets/PII** — sagctl scans deterministically before upload; you
   just need to avoid deliberately including secrets, no need to manually scan.
   If the content cannot be scanned at all (a binary the engine cannot decode),
   the tool queues it for a human instead of publishing — see below.

## User-specific criteria

If the source's `.sag-sync.json` (manifest) has a `criteria` array, **read and
apply them — they take precedence over the 5 default criteria**. For example:
"never include meeting notes", "pricing documents must ask first". When calling
`sag_publish`, list the exact `id`s of the criteria you actually applied in
`assessment.criteria_ack` — if the manifest has criteria but you don't list any
ids, the engine will not auto-publish (it will queue the item for human
review), because it cannot tell whether you read the criteria or not.

## Documents you didn't write as a file

Two situations `sag_publish` cannot handle, both real and both common:

**A PDF/DOCX/other binary you read with a document skill.** The engine does not parse
binary formats — it never will, that stays your job, since you already do it well. It
also cannot secret-scan bytes it cannot decode, so calling `sag_publish` on a binary
either fails outright or gets queued as `UNSCANNABLE`. The right move is upstream of
that: read it, decide whether it's durable/shared knowledge exactly as you would for
anything else, and if so **write a markdown distillation and publish that** with
`sag_publish`. Record the original in `derived_from` (see next). The distillation
chunks better than a server-side parse would, because you write the headings.

**A synthesis you produced with no file at all** — a research summary from a session,
something distilled across several sources, a working directory that isn't even a Git
repo. Use `sag_publish_content` instead:

```json
{
  "relpath": "research/2026-08-01-pricing-competitors.md",
  "content": "# Pricing competitors\n\n...",
  "derived_from": ["docs/vendor-report.pdf@a1b2c3d", "https://example.com/pricing"],
  "assessment": { "...": "same shape as sag_publish's assessment" }
}
```

`relpath` is a path-shaped key you choose — pick one that reads sensibly next to real
file paths (`research/<date>-<topic>.md` is a reasonable convention), since it is
matched against the manifest's `include`/`exclude`/`deny_paths`/`ask_paths` exactly like
a real file's path would be. `derived_from` is how the citation chain survives when the
original artifact (a PDF, a URL, another SAG document) is not itself being published —
list what this was built from. Same self-assessment rubric, same routing, same floor as
`sag_publish` — the only thing not checked is a Git commit, because there may be none.

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
  approve it through the queue. This also happens when the engine could not
  secret-scan the content at all (an undecodable binary slipped through as a
  `path`) — same outcome, a human decides instead of the engine certifying
  something it never actually inspected.
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
