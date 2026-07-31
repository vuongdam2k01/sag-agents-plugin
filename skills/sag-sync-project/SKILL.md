---
name: sag-sync-project
description: Batch-sync every file matching the SAG manifest's include patterns to the knowledge base. Only invoked explicitly by a human or the orchestrator profile — never triggered automatically by the model on its own judgement.
disable-model-invocation: true
---

# sag-sync-project — batch sync (manual trigger only)

This skill **does not load itself** — it only runs when the user types
`/sag-sync-project` or when the orchestrator explicitly assigns you the task of
running a sync. This is an action on an ENTIRE SET of documents (unlike
`sag-publish`, which acts on a single document you just created).

## Required process: always dry-run first

```bash
sagctl sync --manifest .sag-sync.json                 # default = dry-run, no --yes
```

Read the result, report to the user the list of what will be
published/queued/skipped. **Only run for real once the user confirms** the
dry-run list is what they intend:

```bash
SAGCTL_ALLOW_SYNC=1 sagctl sync --manifest .sag-sync.json --yes
```

(The `SAGCTL_ALLOW_SYNC` variable must be set explicitly — this is a signal
that the `sync` operation has been deliberately enabled, not a default.)

## Bootstrap / initial backfill

When setting up a new source or rebuilding SAG from Git after an incident, this
is the tool to use — still dry-run first, which is especially important since
the number of files can be large (check `max_files` in the manifest, increase
it explicitly if needed instead of letting it error out).

## Not for use with

Publishing a single document you just wrote — use the `sag-publish` skill (via
the `sag_publish` MCP tool), not batch sync. Sync is for: bootstrap, backfill,
or periodic syncing of a large set at a human's explicit request.
