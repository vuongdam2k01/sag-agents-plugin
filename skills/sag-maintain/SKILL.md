---
name: sag-maintain
description: Use when asked to check the health of the SAG knowledge base, review documents stuck in failed status, find orphaned or duplicate documents, or run the periodic self-gate review of auto-published documents. Typically invoked on a schedule (orchestrator profile / scheduled task) rather than ad hoc.
---

# sag-maintain — periodic maintenance

This work is about **proposing, not taking destructive action on your own**
(exception: dedupe based on deterministic Git ancestry, which the engine
handles safely on its own — see below). You report; a human or reviewer
decides the next action.

## Commands (run via Bash, not MCP — this is CLI-only by design)

```bash
sagctl maintain dedupe --manifest .sag-sync.json        # dedupe by Git ancestry — AUTOMATICALLY removes the losing copy when determinable
sagctl maintain orphans --manifest .sag-sync.json       # documents in SAG whose path no longer exists on the canonical branch
sagctl maintain stale-branch --manifest .sag-sync.json  # publishes that are committed-only and have long not reached the canonical branch
sagctl maintain review-self-gate <source_id> --days 7   # list of recent route=auto publishes for quality post-hoc review
sagctl doctor --manifest .sag-sync.json --source-id <id> # files that match the manifest but were never assessed (the hook may have been missed)
```

## How to read and report results

- `dedupe`: each outcome has an `action`. `auto_removed_loser` is already done
  (the engine did it itself, with a deterministic ancestry tie-break) — just
  notify the user. `no_dup` can be skipped. `unknown_needs_human` — list it for
  the user, **don't decide yourself which copy to remove**, even if one copy
  "looks" newer.
- `orphans`/`stale-branch`: just list them, propose `sag_unpublish` for each
  one, and wait for user confirmation before calling it (this is a destructive
  operation — use the `ask` tool).
- `review-self-gate`: read through recent automated publishes, re-assess
  whether they truly deserve to be in the knowledge base (use the
  `sag-knowledge` skill to read the actual content via MCP `sag` if needed).
  For any you conclude were published incorrectly: propose `sag_unpublish` with
  a reason, don't remove it yourself.
- `doctor --manifest`: files in the `unassessed_files` list are a sign that the
  `sag-publish` process was skipped (for example, the file was created in a way
  that didn't go through the hook). Propose running an assessment for them;
  don't bulk-publish without assessing each file.

## When to run

Don't wait for the user to ask — if you're an orchestrator profile running on a
schedule, run regularly (suggested default: weekly). If the user asks "is the
knowledge base healthy", run all 4 commands above and compile a concise report.
