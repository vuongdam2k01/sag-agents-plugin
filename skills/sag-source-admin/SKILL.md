---
name: sag-source-admin
description: Create, update, or delete a SAG source (the top-level container documents belong to). Destructive and rarely needed — only invoked explicitly by a human, never by model judgement.
disable-model-invocation: true
---

# sag-source-admin — source administration (manual trigger only)

This skill **does not load itself** — it only runs when the user types
`/sag-source-admin` or gives a direct, explicit order to create/update/delete a
source. Do not infer that some other request ("clean up the knowledge base")
implies permission to run this skill.

## Commands

```bash
sagctl source list
sagctl source get <source_id>
sagctl source create "<source name>"
sagctl source update <source_id> --fields '{"name": "..."}'
sagctl source delete <source_id> --yes    # DESTRUCTIVE — deletes all documents in the source
```

## Before `delete`

Reconfirm with the user using the source name and the current document count
(`sagctl document list <source_id>` to count) — this operation cannot be undone
on SAG's side (even though the content still exists in Git, it would have to be
synced again from scratch). Never infer on your own that a source "seems
unused" — only delete when the user clearly states which source to delete.

## Relationship to the manifest

A canonical source should correspond to exactly one `.sag-sync.json` in exactly
one repo. If the user creates a new source, remind them to create the
corresponding `.sag-sync.json` and commit it — without a manifest, no document
can be published to that source.
