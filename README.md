<div align="center">

# sag-agents-plugin

**Turn [SAG](https://github.com/Zleap-AI/SAG) into a shared, writable knowledge base for your AI coding agents — without touching a single line of SAG's source code.**

[![CI](https://github.com/vuongdam2k01/sag-agents-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/vuongdam2k01/sag-agents-plugin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Dependencies: none](https://img.shields.io/badge/dependencies-stdlib%20only-green.svg)](#design-principles)

*[English](README.md) · [Tiếng Việt](README.vi.md)*

</div>

---

## What this is

SAG ships an excellent **read-only** MCP server: 8 retrieval tools over an indexed
document corpus. What it does not ship is the other half of the loop — a safe way for an
agent to *contribute* to that corpus.

`sag-agents-plugin` is that other half. It installs into **Claude Code**, **Hermes
Agent**, and **Codex**, and gives your agents:

- **Read** — SAG's own upstream MCP server (`sag`), untouched, 8 tools.
- **Write** — a local MCP server (`sagw`, 6 tools) plus a CLI (`sagctl`), both backed by
  one engine that talks to SAG exclusively through its **public REST API**.
- **Judgment** — 5 skills that teach the agent *when* a document is durable, shared
  knowledge worth publishing, and a typed self-assessment contract it must fill in before
  anything is written.
- **A safety floor** — a deterministic, LLM-free set of checks (git state, path
  allow/deny rules, secret scanning, cost caps) that runs before *every* upload and cannot
  be talked out of by a model.

> **The behavioral and technical contract lives in [docs/SPEC.md](docs/SPEC.md)** — that
> file is canonical. `docs/DESIGN.md` and `docs/AGENT-BEHAVIOR.md` are the design log
> explaining *why*; SPEC.md wins on any conflict.

### Why "no source modification" matters

Every operation goes over SAG's documented REST API and its built-in MCP server. You can
upgrade SAG, or point the plugin at somebody else's SAG instance, without a fork, a patch
queue, or a migration. The trade-off is that the plugin has to discover SAG's real
behavior empirically — which is exactly what `sagctl selftest` does (16 probe cases,
results recorded in [docs/SPEC.md](docs/SPEC.md)).

---

## Table of contents

- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Installation](#installation)
- [Configuration: the manifest](#configuration-the-manifest)
- [How a publish actually happens](#how-a-publish-actually-happens)
- [MCP tools](#mcp-tools)
- [CLI reference](#cli-reference)
- [Skills](#skills)
- [Security model](#security-model)
- [Development](#development)
- [Project layout](#project-layout)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│  Agent host  (Claude Code · Hermes Agent · Codex)           │
│                                                             │
│   skills/  ── judgment: is this durable knowledge?          │
│   hooks/   ── awareness nudges + single-use manual tokens   │
└──────────┬─────────────────────────────────┬────────────────┘
           │ READ                            │ WRITE
           │                                 │
   ┌───────▼────────┐              ┌─────────▼──────────┐
   │  MCP  `sag`    │              │  MCP  `sagw`       │
   │  SAG upstream  │              │  scripts/          │
   │  8 read tools  │              │  sagw_server.py    │
   │  read token    │              │  6 write tools     │
   └───────┬────────┘              └─────────┬──────────┘
           │                                 │
           │                       ┌─────────▼──────────┐
           │                       │  sagctl engine     │
           │                       │  safety floor ·    │
           │                       │  routing · audit   │
           │                       │  (also a CLI)      │
           │                       └─────────┬──────────┘
           │                                 │ write token
           │                                 │ (~/.sagctl/, never in agent env)
   ┌───────▼─────────────────────────────────▼──────────┐
   │                  SAG  (unmodified)                 │
   │            REST API  +  built-in MCP               │
   └────────────────────────────────────────────────────┘
```

One engine, three consumption surfaces. The read path and the write path use **different
tokens**, and the write token never enters the agent's environment.

---

## Quick start

```bash
git clone https://github.com/vuongdam2k01/sag-agents-plugin.git
cd sag-agents-plugin

# 1. Install the engine (puts `sagctl` on PATH, creates ~/.sagctl/)
python scripts/install-shim.py

# 2. Authenticate — stores a write token at ~/.sagctl/credentials.json (0600)
sagctl login --url http://<sag-host>:8000 --name <your-name>

# 3. Verify the plugin's assumptions hold on *your* SAG instance
sagctl selftest --url http://<sag-host>:8000 --token <token>

# 4. Create a source and wire up a project
sagctl source create "my-project-knowledge"
cp examples/sag-sync.example.json /path/to/your/repo/.sag-sync.json
#   → edit source_id in that file

# 5. Preview what would be published, then do it
sagctl sync --manifest .sag-sync.json          # dry-run by default
sagctl sync --manifest .sag-sync.json --yes
```

**Requirements:** Python 3.11+, Git, a reachable SAG instance. No pip packages.

---

## Installation

### Claude Code

```bash
claude plugin marketplace add https://github.com/vuongdam2k01/sag-agents-plugin
claude plugin install sag-agents
```

Set the read-side environment variables before use:

```bash
export SAG_URL="http://<sag-host>:8000"
export SAG_READ_TOKEN="<read-only token>"
```

The **write token is deliberately not in the agent's environment** — it lives in
`~/.sagctl/credentials.json` and is read by `sagw`/`sagctl` at call time. See
[Security model](#security-model).

The plugin registers both MCP servers ([.mcp.json](.mcp.json)), four hooks
([hooks/hooks.json](hooks/hooks.json)), the `/sag-publish` slash command, and 5 skills.
Generate the project-scoped MCP config and the permission block from inside the repo:

```bash
sagctl adapter-emit claude-code --write .
```

See [adapters/claude-code/](adapters/claude-code/).

### Hermes Agent

```bash
sagctl adapter-emit hermes --plugin-root /opt/agent-skills/sag-agents-plugin
```

Emits `mcp_servers`, `skills.external_dirs`, and the per-role profile split. See
[adapters/hermes/](adapters/hermes/).

### Codex

```bash
sagctl adapter-emit codex --plugin-root /opt/agent-skills/sag-agents-plugin
```

This prints the config block for `config.toml` and the `AGENTS.md` section, each with a
version marker so drift is detectable. See [adapters/codex/](adapters/codex/).

### The engine (required for all three)

```bash
python scripts/install-shim.py
sagctl login --url <SAG_URL> --name <name>
```

`sagctl` is Python 3.11+, **stdlib-only**, and is the single implementation behind the
CLI, the `sagw` MCP server, and every hook.

---

## Configuration: the manifest

Each repo that publishes to SAG carries a `.sag-sync.json` at a directory that is an
**ancestor of the commit being published**:

```json
{
  "source_id": "...",
  "sandbox_source_id": "...",
  "key_format": "flat",
  "require": "committed",
  "canonical_branch": "main",
  "min_confidence": 0.8,
  "criteria": [
    { "id": "c1", "text": "Do not include meeting notes" }
  ],
  "deny_paths": ["docs/pricing/**"],
  "ask_paths": [],
  "include": ["**/*.md"],
  "exclude": [],
  "max_files": 50,
  "max_publishes_per_day": 30,
  "stale_branch_days": 14
}
```

| Field | Meaning |
|---|---|
| `key_format` | `flat` (default) or `path`. **Verify with `sagctl selftest --case S1`** — most SAG instances truncate an uploaded filename to its basename, which is why `flat` is the default. |
| `require` | Git state required before publishing: `committed` (default) · `pushed` · `merged`. |
| `min_confidence` | Below this, a `knowledge` verdict is queued for human review instead of auto-published. |
| `criteria` | Natural-language rules for the *model's* judgment. If criteria exist but the assessment acknowledges none, the publish is queued — not auto-approved. |
| `deny_paths` | Deterministic engine-side block. Blocks **manual mode too**. |
| `ask_paths` | Forces the human-review queue; can be satisfied by manual mode. |
| `max_publishes_per_day` | Cost cap, enforced by the engine. |

**Precedence:** `deny_paths` > `ask_paths` > `include`/`exclude` > `criteria` >
`confidence`.

Runtime state (config, audit log, queue, cost counters) lives under
`~/.sagctl/<sha256(source_id)[:12]>/` — **never in the repo**. The engine aborts if it
finds `sagctl.config.json`, `audit.jsonl`, or `queue.jsonl` inside a working tree. When
agents run on more than one machine, point them all at a shared state service instead —
see [Running agents on several machines](#running-agents-on-several-machines).

Start from [examples/sag-sync.example.json](examples/sag-sync.example.json).

---

## Running agents on several machines

A scope is a `source_id`, not a folder. Any number of agents, on any number of machines,
in any number of repos, share a scope by declaring the same `source_id` in their
`.sag-sync.json`. Publishing stays correct with no coordination at all: `publish_one()`
never trusts local state — it lists documents by key on SAG and replaces, so SAG is the
inventory and two hosts converge on their own.

Three things do **not** converge on their own, because they are per-host files:

| | Consequence on N hosts |
|---|---|
| `cost.json` | `max_publishes_per_day` becomes N × the manifest value |
| `queue.jsonl` | an item queued on host A cannot be approved from host B |
| `audit.jsonl` | `doctor` and post-hoc review each see 1/N of the history |

Run the state service once, anywhere the fleet can reach:

```bash
SAGSTATE_TOKEN=<shared-secret> python scripts/sagstate_server.py --host 0.0.0.0 --port 9000
```

Then on every agent host:

```bash
export SAGCTL_STATE_URL="http://<state-host>:9000"
```

```bash
export SAGCTL_STATE_TOKEN="<shared-secret>"
```

That is the whole configuration — one cost cap, one queue, one audit log for the fleet.
Leave both unset and the engine keeps the local files exactly as before; there is no
migration step and no behaviour change for a single-machine setup.

Verify it took effect:

```bash
sagctl doctor
```

The `state` block reports `backend: http` and whether the service is reachable. If one
host reports `local` while another reports `http`, they are **not** sharing state — even
though both publish into the same SAG source.

The service is dumb storage and holds no policy: the manifest still decides what may be
published, the deterministic floor still runs on the agent host. Compromising it lets an
attacker forge audit history and reset the cost counter, not publish something the floor
would have rejected. See [SPEC amendment A1](docs/SPEC.md#a1-state-location-is-pluggable--local-default--http-fleet-shared).

### Generating each host's config

`source_id` is declared once — in the manifest, in Git. Every agent-side config is
generated from it, so nothing is hand-copied between machines. Run this in the repo, on
the host being set up:

```bash
sagctl adapter-emit claude-code --write .
```

For the other targets:

```bash
sagctl adapter-emit hermes --plugin-root /opt/agent-skills/sag-agents-plugin
```

```bash
sagctl adapter-emit codex --plugin-root /opt/agent-skills/sag-agents-plugin
```

The generated read MCP url carries the scope — `${SAG_URL}/mcp/?source_id=<id>` — so an
agent working in project A does not casually retrieve project B's knowledge. Without a
resolvable manifest the command still emits, but prints a warning and marks the config
unscoped: that has to be a visible choice, not a silent default.

Files that normally already hold unrelated content (`settings.json`, `config.yaml`,
`config.toml`) are printed for you to merge rather than written over. Only `.mcp.json`,
which is wholly ours, is written directly.

**What the scoping is worth:** defence in depth, not a boundary. SAG has no isolation
between identities (selftest S11) and the fleet shares one read token, so the same token
still reaches an unscoped URL. It stops casual cross-project retrieval, not a determined
one. Selftest case `S17` measures this on your own instance rather than taking it on
trust — run it before relying on the claim:

```bash
sagctl selftest --url http://<sag-host>:8000 --token <token> --case S17
```

See [SPEC amendment A2](docs/SPEC.md#a2-agent-side-config-is-generated-from-the-manifest-read-mcp-is-scoped).

---

## How a publish actually happens

```text
  agent finishes writing docs/adr/0007-queue-choice.md
              │
              ▼
  ┌───────────────────────────────────────────┐
  │ 1. SELF-ASSESSMENT  (model, typed, S5)    │
  │    verdict: knowledge | not-knowledge |   │
  │             unsure                        │
  │    durable / audience / retrieval_fit     │
  │    criteria_ack[] · confidence · why      │
  └────────────────┬──────────────────────────┘
                   ▼
  ┌───────────────────────────────────────────┐
  │ 2. DETERMINISTIC FLOOR  (engine, no LLM)  │
  │    manifest ancestor resolvable           │
  │  ∧ include ∧ ¬exclude ∧ ¬deny_paths       │
  │  ∧ git state satisfies `require`          │
  │  ∧ secret scan (regex + entropy, gitleaks)│
  │  ∧ dedupe-by-key ∧ cost cap               │
  │    ── any red clause ⇒ hard reject ──     │
  └────────────────┬──────────────────────────┘
                   ▼
  ┌───────────────────────────────────────────┐
  │ 3. ROUTING  (verdict first, conf second)  │
  │  knowledge ∧ conf≥min ∧ criteria_ack ⇒ AUTO
  │  unsure | low conf | ask_paths      ⇒ QUEUE
  │  not-knowledge                      ⇒ DROP
  │  deny_paths                         ⇒ REJECT
  └────────────────┬──────────────────────────┘
                   ▼
  ┌───────────────────────────────────────────┐
  │ 4. UPLOAD                                 │
  │    provenance injected into the *bytes*   │
  │    only — the file on disk is untouched   │
  │    delete-then-upload for replacement     │
  │    assert response.filename == key        │
  │    full assessment → audit JSONL          │
  └───────────────────────────────────────────┘
```

The model supplies **judgment**. The engine supplies **facts** (`canonical`,
`secret_free`, `key`, `initiator`) — a model is never allowed to assert those about
itself.

### Citations are paths, not IDs

SAG has no document-update API (a change is delete + re-upload), so `document_id` and
`chunk_id` change on every republish. The only durable citation is
`source_id + repo path (+ heading)`. The skills enforce this.

---

## MCP tools

### `sag` — read (SAG upstream, unmodified)

`list_sources` · `list_documents` · `outline` · `search` · `grep` · `read` · `get_chunk` ·
`get_entity`

The [sag-knowledge](skills/sag-knowledge/SKILL.md) skill teaches the retrieval funnel and
a per-lookup budget, plus when to use `grep` (exact identifiers) over `search`
(semantic).

### `sagw` — write (this plugin)

| Tool | Args | Default permission |
|---|---|---|
| `sag_publish` | `{path, assessment}` | **allow** — assessment is always mandatory |
| `sag_publish_status` | `{path}` | **allow** — read-only |
| `sag_sync_preview` | `{}` | **allow** — read-only dry-run |
| `sag_reprocess` | `{path}` | **allow** |
| `sag_publish_unreviewed` | `{path, reason}` | **ask** — bypasses `require`, never bypasses secret scan or `deny_paths` |
| `sag_unpublish` | `{path, reason}` | **ask** — the remediation path, always available |

There is **no manual-mode flag on the MCP surface**. `sag_publish` always requires an
assessment; the only way to skip assessment is the `/sag-publish` slash command, which
mints a single-use token bound to `sha256(args)` with a 5-minute TTL.

---

## CLI reference

```bash
# auth & health
sagctl login --url <URL> --name <name>       # write token → ~/.sagctl/credentials.json
sagctl whoami
sagctl health

# publish path
sagctl publish <path> [--assessment-file f.json] [--wait] [--dry-run]
sagctl publish-status <source_id> <key>
sagctl unpublish <source_id> <key> --reason "..."
sagctl reprocess <source_id> <key>

# batch
sagctl sync --manifest .sag-sync.json        # dry-run by default; --yes to execute

# review queue
sagctl queue list <source_id>
sagctl queue approve <source_id> <queue_id> [--reviewer NAME]
sagctl queue reject  <source_id> <queue_id> --reason "..."

# maintenance
sagctl maintain dedupe        --manifest .sag-sync.json
sagctl maintain orphans       --manifest .sag-sync.json
sagctl maintain stale-branch  --manifest .sag-sync.json
sagctl maintain review-self-gate <source_id> --days 7

# sources & documents
sagctl source list | get <id> | create "<name>" | update <id> --fields '{...}' | delete <id> --yes
sagctl document list <source_id>

# diagnostics
sagctl doctor --manifest .sag-sync.json --source-id <id>   # files matched but never assessed
sagctl scan <path>                                          # secret scan on demand
sagctl selftest --url <URL> --token <tok> [--case S1,S4]    # probe a real SAG instance
sagctl eval --questions q.jsonl --source-id <id> [--save-baseline]
sagctl criteria-add --manifest .sag-sync.json <id> "<criterion text>"
sagctl adapter-emit codex|hermes|claude-code [--out FILE]
sagctl api GET /system/capabilities                         # escape hatch; denied to agents by default
```

**The write token is never accepted as a command-line argument** — it would leak into
shell history and the process list. It is only ever read from `~/.sagctl/`.

---

## Skills

| Skill | Auto-invoked | Purpose |
|---|---|---|
| [sag-knowledge](skills/sag-knowledge/SKILL.md) | yes | Search, browse, cite, read — the retrieval funnel and citation discipline. |
| [sag-publish](skills/sag-publish/SKILL.md) | yes | Self-assess a document you just wrote and publish it if it is durable shared knowledge. |
| [sag-maintain](skills/sag-maintain/SKILL.md) | yes | Health checks: failed documents, orphans, duplicates, self-gate review. Proposes, never destroys. |
| [sag-sync-project](skills/sag-sync-project/SKILL.md) | **no** | Batch sync an entire repo. Human-triggered only. |
| [sag-source-admin](skills/sag-source-admin/SKILL.md) | **no** | Create/update/delete a source. Destructive, human-triggered only. |

The two destructive skills set `disable-model-invocation: true` — a request like "clean up
the knowledge base" does not grant permission to run them.

### Awareness layer

- **`Stop` / `SessionEnd` hooks (primary)** — diff the session's changed files against the
  manifest's include globs, cross-check the audit log, and list anything never assessed.
  Notify-only, loop-guarded.
- **`PostToolUse(Write|Edit)` (secondary)** — a gentle nudge, deduped once per file per
  session.
- **`UserPromptSubmit`** — mints the single-use manual token, and *only* when the prompt
  matches the exact `/sag-publish <args>` form.
- **Hermes / Codex** — advisory only (profile prompt / `AGENTS.md`) plus a scheduled
  `sagctl doctor`. Stated honestly: machine enforcement exists on Claude Code alone.

---

## Security model

This is a **guardrail against accident and shallow prompt injection, not a security
boundary.** The agent and the engine run as the same OS user; a determined attacker with
code execution as that user can bypass any of it. Hardening (separate OS user, engine as a
service) is a documented future option, not what ships today.

What *is* enforced:

| Control | Enforcement |
|---|---|
| Write token isolation | Lives in `~/.sagctl/credentials.json` (`0600`), never in the agent env, never a CLI argument. Read token is separate and read-only. |
| Secret scanning | Regex + entropy on every upload, plus `gitleaks` if it is on PATH. **`sag_publish_unreviewed` does not bypass it.** |
| `deny_paths` | Blocks even manual mode — it is a rule the human wrote for themselves. |
| Manual tokens | Bound to `sha256(args)`, single-use (unlinked on consumption), 5-minute TTL. A token minted for path A cannot publish path B. |
| `initiator` | Derived by the engine from token presence. A model cannot claim `user-manual`. |
| Repo hygiene | The engine aborts if runtime state files are found inside a working tree. |
| Audit | Every assessment and route decision is appended to a local JSONL, queryable via `sagctl doctor`. |

**Known limitations, stated plainly:**

- SAG (as tested) has **no isolation between identities** and **no server-side
  attribution** — every agent in a fleet shares one read/write token pair by design, since
  a second identity would buy neither. Attribution exists only in the local audit log.
- SAG's JWT has a fixed **7-day lifetime with no revoke/refresh endpoint**. A leaked token
  cannot be revoked, only waited out — rotate on a cycle shorter than 7 days in sensitive
  environments.

Both findings are empirical (selftest cases S11/S12/S13 against a real instance), not
assumptions. Full detail in [docs/SPEC.md](docs/SPEC.md).

To report a vulnerability, see [SECURITY.md](SECURITY.md).

---

## Development

```bash
# unit tests — offline, no SAG instance needed
python -m unittest discover -s tests -v

# integration — probes a real SAG instance, 16 cases
sagctl selftest --url <SAG_URL> --token <token>
sagctl selftest --url <SAG_URL> --token <token> --case S1     # one case (comma-separated for several)
```

87 unit tests cover every pure function: key encoding, manifest validation, routing,
secret scanning, provenance injection, `**` glob matching, manual-token lifecycle,
REST-client pagination, network-error resilience, and detection of a `~/.sagctl/` leak
into a repo. They run offline in CI on Linux and Windows across Python 3.11–3.13.

`selftest` is different in kind: it verifies that **SAG itself** still behaves the way the
spec assumes. Run it before provisioning a new source or after a SAG upgrade — especially
case **S1** (`key_format`) and **S4** (delete synchrony), which decide two locked
defaults.

> ⚠️ `selftest` uploads real documents and consumes real LLM quota on the SAG host's
> provider account. Case S6 alone uploads 120 documents — lower `n` if you rerun it often
> against a tightly-limited account.

### Design principles

1. **Never modify SAG.** REST API and built-in MCP only.
2. **Stdlib only.** Python 3.11+, zero pip dependencies, so the engine vendors cleanly
   into any container or agent host.
3. **The model judges; the engine decides.** Verdicts are advisory input to a
   deterministic router — never a substitute for it.
4. **Verify, don't assume.** Every claim about SAG's behavior traces to a numbered
   selftest case with a recorded result.
5. **Propose over destroy.** Maintenance reports; humans act. The one exception is
   duplicate removal with provable Git ancestry.

---

## Project layout

```text
.claude-plugin/      plugin + marketplace manifests
scripts/sagctl/      the engine — write logic, safety floor, routing, audit
scripts/sagw_server.py   thin MCP write server wrapping the engine (6 tools)
scripts/install-shim.py  puts `sagctl` on PATH, creates ~/.sagctl/
skills/              5 skills teaching correct knowledge-base use
commands/            /sag-publish slash command
hooks/               awareness nudges + manual token minting
adapters/            per-agent-tool installation config (claude-code, hermes, codex)
examples/            sample manifest, doc templates, sample eval set
tests/               87 unit tests for pure functions — no server required
docs/                SPEC.md (canonical), design log, review transcript
```

---

## Documentation

| Document | What it is |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | **Canonical.** The locked implementation contract (S0–S12), selftest results against a real instance, and the phase plan. |
| [docs/DESIGN.md](docs/DESIGN.md) | Design log — the reasoning that produced the spec. |
| [docs/AGENT-BEHAVIOR.md](docs/AGENT-BEHAVIOR.md) | Intended agent behavior in detail. |
| [docs/REVIEW-OPUS.md](docs/REVIEW-OPUS.md) | Transcript of the adversarial design review that hardened the spec. |
| [examples/README.md](examples/README.md) | How to use the sample manifest, doc templates, and eval set. |

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first — in
particular the two rules that are not negotiable:

1. **No change may require modifying SAG's source code.**
2. **No change may add a runtime dependency outside the Python standard library.**

Anything that contradicts [docs/SPEC.md](docs/SPEC.md) needs a spec change first, agreed
in an issue — not an engineer's judgment call in a PR.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE) © 2026 vuongdam2k01

SAG itself is a separate project with its own license — see
[Zleap-AI/SAG](https://github.com/Zleap-AI/SAG).
