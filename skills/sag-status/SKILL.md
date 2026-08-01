---
name: sag-status
description: Use when asked whether the SAG plugin is set up correctly on this machine, which scope it is pointed at, whether it shares state with other agent hosts, or whether committed files are missing from the knowledge base. Read-only diagnostics — changes nothing.
---

# sag-status — is this machine wired up correctly?

Read-only. Runs diagnostics and reports; never fixes anything on its own. If something is
wrong, say what and point at `/sag-setup`.

## Run

```bash
sagctl doctor
```

With a manifest in reach, this also lists committed files that match `include` but have no
publish/queue/skip event in the audit log:

```bash
sagctl doctor --manifest .sag-sync.json --source-id <source_id>
```

## Report four things

**1. Which scope.** `source_id` from `.sag-sync.json`. If no manifest resolves from the
current directory, nothing can be published from here at all — not even manually (§S1).

**2. State backend.** From the `state` block:

- `http` + `reachable: true` — this host shares the cost cap, queue, and audit log with
  the rest of the fleet.
- `http` + `reachable: false` — misconfigured or the service is down. Publishing still
  works; the cap and queue do not.
- `local` — state is private to this host. Correct for a single machine. On a fleet it
  means `max_publishes_per_day` is being enforced N times over, and any queued item can
  only ever be approved from the host that created it.

**3. Read scoping.** Check whether the `sag` server url in `.mcp.json` (or the Hermes /
Codex equivalent) carries `?source_id=`. Without it this agent can list and search every
source on the instance, not just its own — SAG has no isolation between identities
(selftest S11), so the url is the only separation there is.

Say plainly what it is worth: defence in depth, not a boundary. The same read token still
reaches an unscoped url.

**4. Unassessed files.** Committed, matching `include`, never run through `publish_one()`.
Usually a missed hook. List them; do not publish them — that is `sag-publish`'s job and it
requires an assessment.

## Do not

- Do not run `sagctl login`, `source create`, or `adapter-emit --write` from this skill.
  Those belong to `/sag-setup`, which is manual-trigger only.
- Do not edit `.sag-sync.json`. `deny_paths`, `ask_paths`, and `criteria` are policy: they
  change in a separate reviewed commit (§S1), never as a diagnostic side effect.
