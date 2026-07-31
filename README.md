# sag-agents-plugin

*[English](README.md) | [Tiếng Việt](README.vi.md)*

A plugin that installs directly into Claude Code, Hermes Agent, and Codex to use SAG
(Zleap-AI/SAG) as a shared knowledge base — filling in the write operations that SAG's
read-only MCP does not provide, **without modifying a single line of SAG's source code**.
All communication with SAG goes through its public REST API and its built-in MCP server.

**Source of truth for behavior and the technical contract:
[docs/SPEC.md](docs/SPEC.md).** `docs/DESIGN.md` and `docs/AGENT-BEHAVIOR.md` are the
design log behind SPEC.md — useful for understanding *why*, but SPEC.md wins on any
conflict.

## Installation

### Claude Code

```bash
claude plugin marketplace add <path-or-url-to-this-repo>
claude plugin install sag-agents
```

Environment variables must be set before use:

```bash
export SAG_URL="http://<sag-host>:8000"
export SAG_READ_TOKEN="<read-only token>"
```

The write token is **not** placed in the agent's environment — see
[Installing sagctl](#installing-sagctl).

### Hermes Agent

Point `skills.external_dirs` at this repo's `skills/` directory — see
[adapters/hermes/config.example.yaml](adapters/hermes/config.example.yaml).

### Codex

Run `sagctl adapter emit codex` to generate the config block for `config.toml` and
`AGENTS.md` (with a version marker to detect drift) — see
[adapters/codex/](adapters/codex/).

## Installing sagctl (required for all 3 tools)

```bash
python scripts/install-shim.py    # puts `sagctl` on PATH, creates ~/.sagctl/
sagctl login                       # generates a write token, stores it under ~/.sagctl/
```

`sagctl` is the single engine (Python 3.11+, stdlib-only) behind the CLI, the write MCP
server `sagw`, and every hook. Architecture details: [docs/SPEC.md §S0](docs/SPEC.md).

## Repo layout

```text
scripts/sagctl/     engine — all write logic, safety floor, routing, audit
scripts/sagw_server.py   thin MCP write server wrapping the engine (6 tools)
skills/              5 skills that teach the agent how to use the knowledge base correctly
commands/             manual slash command (/sag-publish)
hooks/                awareness nudges + manual token minting
adapters/             per-agent-tool installation configuration
examples/             sample manifest, doc-templates, sample eval set
tests/                unit tests for pure functions (no real server needed)
docs/                 SPEC.md (canonical), design log, review transcript
```

## Running the tests

```bash
python -m unittest discover -s tests -v
```

Unit tests cover every pure function (key encoding, manifest validation, routing, secret
scanning, provenance, `**` globbing, manual tokens, detecting a `~/.sagctl/` leak into the
repo) — no real SAG server needed, runs offline in CI.

To verify against a real SAG instance:

```bash
sagctl selftest --url <SAG_URL> --token <token>
```

Results and any instance-specific defaults are recorded in
[docs/SPEC.md](docs/SPEC.md).
