# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Because [docs/SPEC.md](docs/SPEC.md) is the canonical contract, entries that change
behavior cite the spec section they touch (S1–S12) or the amendment that revises it
(A1, A2, …).

## [Unreleased]

### Added

- **Knowledge is no longer welded to `.md` files inside a Git repo (SPEC amendment A3,
  amends S3/S4).** Two restrictions turn out to have been storage details enforced as if
  they were policy: provenance only fit inside YAML frontmatter, so only markdown could be
  published; publishing required a Git commit, so an agent whose working area was not a
  checkout — a Hermes profile, a research session — could not publish at all.
  - **Provenance's authoritative home is now the state store** (`state.provenance_put/get`,
    SPEC A1), written for every publish regardless of format. Frontmatter becomes a
    convenience copy for `.md`/`.markdown` (`provenance.can_carry_frontmatter`), not the
    only place provenance can live.
  - **The git clause in the floor is conditional, not mandatory.**
    `manifest.git_root(m)` returns `None` when there is no repo above the manifest;
    `check_floor(..., in_git_repo=False)` then skips `check_git_state` entirely — not
    bypassed as a favour, simply inapplicable. Every other floor clause (path policy,
    secret scan, cost cap) still runs unconditionally.
  - **`include` now defaults to `**/*`**, every extension SAG accepts, not just markdown.
    The old `.md`-only default was a side effect of the frontmatter weld, never a
    judgement that only markdown can be knowledge — narrowing `include` decides what
    counts as knowledge by glob, which is the assessment's job. Fixed the same drift in
    `gate.py`, `routing.py`, and `sync.py`, which each hardcoded their own fallback
    (`sync.py`'s was still the old `**/*.md`) — all three now reference
    `manifest.DEFAULTS["include"]` as the single source of truth.
  - **An undecodable file is `UNSCANNABLE`, not silently certified.** The previous secret
    scanner read every file with `errors="replace"`, so scanning a PDF examined
    replacement characters and reported "clean" for bytes it never actually read. Now: a
    file that will not decode as UTF-8 makes the floor return `UNSCANNABLE`; an
    `AUTO`-routed publish downgrades to `QUEUE` instead of erroring, so a human decides
    rather than the engine claiming a scan it never performed.
  - **The engine does not grow a PDF/DOCX parser.** That stays the agent's job — Claude
    Code and others already ship document skills for it. The intended path: read the
    artifact, distil it into markdown, publish the distillation (better chunking than a
    server-side parse, per AGENT-BEHAVIOR.md P6), cite the original via `derived_from`.
  - **New: `publish_content(relpath, text, ...)` and MCP tool `sag_publish_content`** — an
    agent hands text directly, no file, no repo. `relpath` is a path-shaped key the caller
    chooses; it is matched against `include`/`exclude`/`deny_paths`/`ask_paths` and encoded
    into the SAG key exactly like a real file's relpath — no new policy concepts, no new
    manifest fields. `derived_from[]` keeps the citation chain (repo paths, URLs, other SAG
    keys) when this is a distillation. Same self-assessment contract and routing as
    `sag_publish`; no manual-mode bypass (there is no file for a slash-command token to
    bind to). New CLI: `sagctl publish-content`.
  - **Manifest resolution no longer requires a file to walk up from.**
    `manifest.resolve()`: explicit path → named manifest
    (`~/.sagctl/manifests/<name>.json`) → `$SAGCTL_MANIFEST` → walk up from a start
    directory that does not itself have to be inside a Git repo. `publish_content` tries
    the current working directory as its walk-up start.
  - **`require: "none"` was removed before shipping.** An earlier draft of this amendment
    added it as a fourth `require` value; that was Mode A pretending to be Mode B —
    superseded outright by `git_root()` returning `None`. `VALID_REQUIRE` stays
    `{committed, pushed, merged}`; `canonical_branch` is required by manifest validation
    only when `require` is `pushed`/`merged` (previously required unconditionally despite
    being inert otherwise).
  - **`maintain` refuses to reconcile documents that were never in the repo.**
    `find_orphans`/`find_stale_branch` both asked "does this path still exist in the
    repo?" — meaningless, and actively dangerous, for a document whose key was never a
    real repo path (`path_exists_at_ref` is unconditionally `False` for such a key, so
    every authored document would be flagged orphaned). Both now consult the document's
    `sag_in_git` provenance field (`maintain._reconcilable`) and skip anything where it is
    `False`. A document with no state-store record predates A1/A3 and is treated as
    reconcilable, matching prior behavior.
  - **Queueing an authored document keeps its content, not just a path.**
    `queue.enqueue()` gains `content`/`derived_from`/`manifest_path`; `queue.approve()`
    dispatches to `publish_content()` for `mode: "content"` items and to the unchanged
    `publish_one()` otherwise — there is no file on disk to re-read at approval time, so
    the text has to live in the queue record itself.
  - `sag_publish_content` added to the Claude Code allow list (same trust tier as
    `sag_publish` — identical assessment + floor pipeline) and to every Hermes profile
    example alongside `sag_publish`.
  - What did **not** change: the deterministic floor still runs on every document, the
    model still cannot assert `secret_free`/`canonical`, `deny_paths` still blocks
    unconditionally, and mirrored Git publishing is untouched — commit + blob, full
    `maintain` reconciliation, exactly as before. Git stops being the *precondition* for
    knowledge and the only place provenance can live; it does not stop being the strongest
    guarantee available when it exists.
  - 46 new tests: `manifest.resolve()`/`git_root()` resolution order, the conditional git
    clause, `UNSCANNABLE` vs `SECRET_FOUND` vs clean, `publish_content()`'s reject/queue/
    floor-failure/auto-publish paths (queue and floor failures proven to never touch the
    network), `queue.approve()`'s mode-based dispatch, `maintain._reconcilable()`, and a
    regression lock proving `gate.py`/`routing.py`/`sync.py` agree on the `include`
    fallback.

- **Fleet-shared state backend (SPEC amendment A1, amends S1).** Audit, queue, and cost
  counters now resolve through `sagctl/state.py` instead of touching `~/.sagctl/` files
  directly. `SAGCTL_STATE_URL` unset keeps the existing local files byte-for-byte — no
  migration, no behaviour change for a single-machine install. Set it (plus
  `SAGCTL_STATE_TOKEN`) and the whole agent fleet shares one cost cap, one queue, and one
  audit log.
  - Rationale: S1 put that state on local disk to satisfy REVIEW-OPUS F5 ("config inside
    the workspace = the agent grants itself permissions"), which constrains *write reach*,
    not *storage medium*. With one agent per host, `max_publishes_per_day` silently became
    N × the manifest value, an item queued on host A could never be approved from host B,
    and `doctor`'s fail-rate by `agent × route` saw 1/N of the history.
  - `scripts/sagstate_server.py` — stdlib-only reference service, bearer-token auth,
    per-source locking, refuses a non-loopback bind without `SAGSTATE_TOKEN`.
  - Backend operations are atomic by contract (`cost_bump`, `queue_set_status`) rather
    than get/set pairs, so concurrent hosts cannot lose a counter update or double-approve
    a queue item.
  - The wire addresses sources by `sha256(source_id)[:12]`, so a real `source_id` never
    reaches a URL, an access log, or a proxy trace.
  - `sagctl doctor` reports the active backend and its reachability — the fastest way to
    catch one host still on `local` while the rest of the fleet is on `http`.
  - Trust boundary unchanged: the service is dumb storage holding no policy. The manifest,
    the deterministic floor, and routing all still run on the agent host. Still G1.
  - 27 new tests, including two hosts racing to approve the same queue item and four hosts
    concurrently bumping one counter, run against a real in-process server.
- **Generated agent config with a scoped read MCP (SPEC amendment A2, amends S8).**
  `sagctl adapter-emit <target>` now resolves `source_id` from the manifest and generates
  the full config for all three targets, instead of pointing at static snippets to copy by
  hand.
  - Rationale: S8 specified the write side precisely and said nothing about reads, so
    `.mcp.json` shipped an unscoped `${SAG_URL}/mcp/`. With S11 (no isolation between
    identities) and one shared read token, every agent could list and search every source
    on the instance regardless of which project it worked in. Invisible on one project;
    with N projects it means no read-side scope at all.
  - The generated read url carries `?source_id=<id>` (the form `GET /sources/{id}/mcp`
    returns, confirmed in S15). `source_id` stays declared exactly once, in Git — N
    projects × M hosts no longer means N×M hand-maintained copies across three file formats.
  - Emitting without a resolvable manifest still works but warns on stderr and marks the
    output unscoped. An unscoped config must be a visible choice, not a silent default.
  - `--write DIR` places the files; `settings.json` / `config.yaml` / `config.toml` are
    merge-targets and are printed rather than clobbered unless `--force`.
  - Worth stating plainly: this is defence in depth, not a boundary. The same read token
    still reaches an unscoped url. Read separation as a real boundary is still option C.
  - New selftest case **S17** measures the claim rather than asserting it — two sources, a
    marker document in one, `list_documents` through a client scoped to the other —
    automated via `mcp_client.py`, a minimal hand-rolled streamable-http/SSE MCP client.
    **S17 has not yet been run against a live instance**; until it has, the scoped url is
    an unverified mitigation.
  - 13 new tests covering url derivation, merge-target marking, agent identity tagging,
    and that no write token ever appears in a generated config (S12).
- **Fixed: `setup probe` suggested a narrower `include` than the engine's own default.**
  It proposed `docs/**/*.md` where `manifest.DEFAULTS` is `**/*.md`, which quietly decided
  "what counts as knowledge" by glob — the assessment's job (S5/S6). The failure mode is
  silent in both directions: `routing.decide()` rejects an out-of-include path before the
  model is ever asked for a verdict, and `doctor --unassessed` only scans within `include`,
  so those files are never published *and* never flagged. The suggestion now matches the
  engine default and puts mechanical noise (`node_modules`, `vendor`, `.venv`) in `exclude`
  where it belongs.
- **Fixed: the plugin assumed a command named `python` existed.** Confirmed broken on a
  stock Ubuntu 24.04 (2026-08-01), which ships `python3` and no `python`: `sagw` never
  started and all four hooks died — the hooks *silently*, so the agent kept working and
  simply never reported an unassessed file. There is no interpreter name that is correct
  everywhere (python.org on Windows ships only `python`), so no static config can name one.
  - New `sagctl serve-mcp` and `sagctl hook <name>`. `.mcp.json`, `hooks.json`, and every
    config `adapter-emit` generates now invoke `sagctl`, whose shim has `sys.executable`
    baked in at install time. One thing has to be on PATH instead of three, and a missing
    `sagctl` fails loudly rather than silently.
  - `commands/sag-install-engine.md` — installs the engine from the plugin's own copy via
    `${CLAUDE_PLUGIN_ROOT}`. Telling Claude Code users to clone the repo was only ever a
    workaround for having no way to find that path, and the clone is a second copy
    `claude plugin update` does not manage.
  - `install-shim.py` warns when run from a **version-pinned plugin cache**
    (`~/.claude/plugins/cache/<marketplace>/<plugin>/0.1.0/` — the real layout, read off a
    live install) and points at the stable `marketplaces/` checkout. A shim baked against a
    versioned path keeps running the old engine after an upgrade without a word. It now
    also prints the engine path and interpreter it resolved.
  - New `sagctl version` reports version, engine path, and interpreter — how that drift
    gets noticed.
  - `plugin_root` is no longer needed for Codex at all; for Hermes it only points at
    `skills/`.
  - 11 new tests, including a guard that no shipped or generated config may name an
    interpreter in a `command` position.
- **S17 measured on a live instance (2026-08-01, `sag.home`).** `?source_id=` **is**
  enforced by the server for document access — a client scoped to source B cannot reach
  source A's documents. `list_sources` however still returns every source on the instance,
  so an agent can enumerate other projects' names and ids: content is separated, metadata
  is not. SPEC A2 and both READMEs are corrected to state this precisely instead of the
  original "casual retrieval only" framing, which understated the content guarantee and
  said nothing about the metadata leak. The G1 ceiling is unchanged — one shared read token
  still reaches an unscoped url. Same run confirmed `key_format=flat` (S1) and synchronous
  DELETE (S4) on a second host.
- **Onboarding skills — `/sag-setup` and `sag-status`.** Setup is order-dependent and has
  a verification gate that documentation alone does not enforce.
  - `sag-setup` (`disable-model-invocation: true`, human-triggered only) branches into
    **bootstrap** (provision a new scope) or **join** (attach to a scope another agent or
    host already created — the user supplies a `source_id`, nothing is created, and the
    skill checks that `key_format` matches the existing manifest).
  - It **scaffolds** a manifest once and never edits policy afterwards: `deny_paths`,
    `ask_paths`, and `criteria` are left empty for the user to fill in a separate reviewed
    commit, per S1. This is the deliberate divergence from Honcho's `/honcho:config`
    interactive editor — here the config is policy in Git, not host preference.
  - `sag-status` is read-only diagnostics over `sagctl doctor`: which scope, whether state
    is shared with other hosts, whether the read url is scoped, which committed files were
    never assessed.
- `sagctl setup probe --url --token [--full]` — measures an instance and reports the
  manifest defaults *it* implies. `key_format` is a probe result (S1), not a constant: S2
  locks `flat` on the strength of one instance and says to re-verify before provisioning a
  new source. Skipping that check fails silently — keys stop matching,
  `find_existing_by_key` never finds the previous document, and every publish adds a
  duplicate instead of replacing. `--full` also measures S4 (replace strategy) and S17
  (MCP read scoping); without it both are reported as unmeasured rather than assumed.
- `sagctl login --print-token` — prints the token instead of saving it, for minting the
  read token into `SAG_READ_TOKEN`. The write token remains the only thing written to
  `~/.sagctl/credentials.json` (S12). Documented honestly: SAG's JWT has no role or scope,
  so this split limits the blast radius of an agent-side leak, not what a leaked token can
  do.
- `SagClient.capabilities()` — `GET /system/capabilities`, used by `setup probe` to
  describe an instance before anything is provisioned against it.
- `adapters/claude-code/README.md` and `adapters/hermes/README.md`, so all three adapter
  directories document the generator rather than shipping snippets to copy.
- Open-source project scaffolding: `LICENSE` (MIT), `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, this changelog, GitHub issue and pull-request
  templates, and a CI workflow running the unit suite on Ubuntu and Windows across
  Python 3.11–3.13.
- Full English and Vietnamese READMEs covering architecture, the manifest, the publish
  pipeline, the MCP tool surface, the CLI, the security model, and the design principles.

### Removed

- `adapters/hermes/config.example.yaml` — superseded by `sagctl adapter-emit hermes`.
  Keeping a static snippet beside a generator that produces the same content is the exact
  drift the generator exists to prevent (REVIEW-OPUS F3). `adapters/claude-code/settings-rules.json`
  stays: the generator *reads* it, so it is a source of truth rather than a second copy.

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
