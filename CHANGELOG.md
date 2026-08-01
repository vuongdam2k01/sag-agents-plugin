# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Because [docs/SPEC.md](docs/SPEC.md) is the canonical contract, entries that change
behavior cite the spec section they touch (S1–S12).

## [Unreleased]

### Added

- Open-source project scaffolding: `LICENSE` (MIT), `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, this changelog, GitHub issue and pull-request
  templates, and a CI workflow running the unit suite on Ubuntu and Windows across
  Python 3.11–3.13.
- Full English and Vietnamese READMEs covering architecture, the manifest, the publish
  pipeline, the MCP tool surface, the CLI, the security model, and the design principles.

## [0.1.0] — 2026-07-31

First working implementation of the locked spec (SPEC v1).

### Added

- **Engine** (`scripts/sagctl/`) — stdlib-only Python 3.11+, no pip dependencies.
  - Manifest parsing and validation for `.sag-sync.json`, with ancestor resolution (S1).
  - Key encoding with `flat`/`path` formats and post-upload `filename == key` assertion
    (S2, `KEY_FORMAT_DRIFT`).
  - Provenance injection into upload bytes only, merged into existing YAML frontmatter,
    never touching the file on disk (S3).
  - Deterministic safety floor: include/exclude, `deny_paths`, git-state `require`, secret
    scanning (regex + entropy, plus `gitleaks` when on PATH), dedupe-by-key, cost cap (S4).
  - Typed self-assessment contract with validation at the MCP layer (S5).
  - Routing — verdict first, confidence second, with `criteria_ack` enforcement (S6).
  - Manual-mode tokens: bound to `sha256(args)`, single-use, 5-minute TTL; `initiator`
    derived by the engine, never accepted from the model (S7).
  - Publish path: `publish_one()` shared by single publish and batch sync, non-blocking by
    default, `delete_first` replacement, success defined as `ready ∧ chunk_count > 0` (S9).
  - Review queue (`list`/`approve`/`reject`), ancestry-based dedupe, HEAD-relative orphan
    detection, stale-branch detection, self-gate post-hoc review, and `doctor` (S10).
  - Batch `sync` with rename detection via blob sha, `max_files`, and a concurrency cap.
  - `selftest` (16 probe cases) and `eval` with baseline saving.
  - Local audit JSONL with cost counters under `~/.sagctl/<sha256(source_id)[:12]>/`;
    the engine aborts if runtime state is found inside a working tree (S1).
- **`sagw` MCP write server** (`scripts/sagw_server.py`) — 6 tools over hand-rolled
  JSON-RPC on stdio, no SDK dependency: `sag_publish`, `sag_publish_status`,
  `sag_sync_preview`, `sag_reprocess`, `sag_publish_unreviewed`, `sag_unpublish` (S8).
- **Skills** — `sag-knowledge`, `sag-publish`, `sag-maintain`, plus `sag-sync-project` and
  `sag-source-admin` with `disable-model-invocation: true`.
- **Hooks** — `Stop`/`SessionEnd` unassessed-file backstop, `PostToolUse(Write|Edit)`
  nudge, and `UserPromptSubmit` exact-match manual-token minting (S11).
- **Adapters** — Claude Code permission rules, Hermes config example, Codex `adapter-emit`
  with a drift-detection version marker.
- **Tests** — 87 offline unit tests covering key encoding, manifest validation, routing,
  secret scanning, provenance, `**` glob matching, manual tokens, REST pagination, network
  error handling, and repo-leak detection.

### Verified

- Selftest run against a real SAG instance: **16/16 cases, 7/7 blocking PASS**. Results
  recorded in [docs/SPEC.md](docs/SPEC.md).
- `key_format` default **locked to `flat`** — S1 confirmed SAG truncates an uploaded
  filename to its basename, making `path` unusable as a default.
- Replace strategy **locked to `delete_first`** — S4 confirmed DELETE is fully synchronous
  (GET-by-id returns 404 immediately).
- Per-agent identity **dropped from the design** — S11 confirmed no isolation between
  identities and S13 confirmed no server-side attribution, so a second token would buy
  neither (S12).
- MCP read path verified with a hand-written streamable-http/SSE client; path-based
  citation resolves identically over REST and MCP (S15), and `grep` matches exactly and is
  scoped by source (S16).

### Fixed

- `restclient.py` — a timeout occurring mid-response-read surfaces as a raw
  `TimeoutError`/`ConnectionError` that `urllib` does not wrap, crashing the process on a
  single transient network blip. Now wrapped consistently as `SagApiError`; polling loops
  in `publish.py::_wait_for_ready` and `selftest.py` tolerate `status=0` and keep polling
  until the deadline, while real HTTP errors still raise immediately. Covered by 3
  regression tests.
- `list_documents_all` — misread "the server ignores `limit`" as "the server truncates
  pages" on a boundary coincidence. Now detects `len(first) > page_size` directly.
- `maintain.py` — `dedupe_source` and `find_stale_branch` assumed `get_document()` returns
  a content field; `DocumentOut` has none. Now calls `GET .../documents/{id}/parsed` via a
  new `get_document_parsed` (which required a separate raw-text request path, since the
  default `json.loads` crashes on that endpoint).
- `selftest.py` — S4 and S7 used semantic `search` to check content existence, which can
  miss a marker string that genuinely exists. Switched to GET-by-id and `/parsed` for
  unambiguous evidence.

[Unreleased]: https://github.com/vuongdam2k01/sag-agents-plugin/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vuongdam2k01/sag-agents-plugin/releases/tag/v0.1.0
