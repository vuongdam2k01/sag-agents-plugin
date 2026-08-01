# LOCKED SPEC v1 — implementation contract for the sag-agents plugin

> Locked on 2026-07-31 after 2 rounds of two-way exchange with Claude Opus (round 1
> transcript: `REVIEW-OPUS.md`; round 2: final gate GO-WITH-CONDITIONS → this locked
> spec). **Any deviation from this spec requires a new decision from the project owner,
> not an engineer's judgment call.** When this spec conflicts with DESIGN.md /
> AGENT-BEHAVIOR.md, this spec wins (the other two files were meant to be
> merged/reconciled in phase P0).

## Selftest results on sag.home (2026-07-31)

Ran `sagctl selftest` + manual verification against a real SAG instance (self-hosted,
over Tailscale, `base_url = http://sag.home`, self-registered 2 test identities —
`POST /auth/register` is closed, but `POST /auth/login {name}` self-creates/identifies a
user). **All 16/16 cases have run — 7/7 BLOCKING PASS.** (S15 initially got stuck because
the deployment's reverse proxy wasn't forwarding the `/mcp` route to the backend — the
project owner fixed the proxy, and the retest PASSED.) No unverified assumption remains
in the original selftest set.

| Case | Result | Consequence |
|---|---|---|
| **S1** | **FAIL relative to the old assumption** — sent key `docs/adr/probe.md`, SAG returned `filename=probe.md` (truncated to basename) | **`key_format` default changed from `path` to `flat`** (fixed in `manifest.py`). This is SAG's real behavior, not an assumption. |
| **S4** | **PASS** — a GET-by-id right at t=0 after DELETE returns 404 immediately (re-confirmed twice with the GET-by-id method, not `search`) | **DELETE is fully synchronous.** `DEFAULT_REPLACE_STRATEGY = "delete_first"` is correct, kept as-is. |
| **S6** | **PASS** (after fixing a bug in `list_documents_all`) | SAG **completely ignores** `limit`/`offset` on `GET .../documents` — always returns the full list. No real pagination-truncation risk; the bug was in `sagctl`'s own detection heuristic (fixed, see "Self-discovered bugs" below). |
| **S7** | **PASS** (after switching to checking via `GET .../documents/{id}/parsed` instead of `search`) | Banner + frontmatter survive the parser intact. The superseded strategy (keep the key, insert a banner under every heading) is viable. |
| **S11** | **FAIL** — identity B immediately sees the source created by identity A | **No isolation between identities.** Matches SAG's own documented warning: "single-user product". |
| **S12** | Fully answered | `LoginRequest` only needs `name` (email/password optional); the JWT has an `exp`, a fixed **7-day** lifetime; **no logout/revoke/refresh endpoint** (tried `/auth/logout`, `/auth/revoke`, `/auth/refresh` — all 404). A leaked token **cannot be revoked**, only waited out. |
| **S15** | **PASS** (after the project owner added a `/mcp` route to the reverse proxy — pointing at the same backend as `/api/*`, previously it fell through to the frontend) | A real hand-written MCP client (streamable-http/SSE, no session id) calling `list_documents(source_id)` via the `sag` server — the returned filename matches REST exactly (`rest-mcp-check.md`, the `flat` form confirmed in S1). Path-based citation resolves correctly on both the REST and MCP paths. |
| **S16** | **PASS** | `grep` matches EXACTLY (`unique_marker_...`) and **is scoped by source**: found in the source containing the content, returns `（未匹配到内容）` (no match) when scoped to a different, empty source. Matches the recommendation in `skills/sag-knowledge/SKILL.md` (use `grep` for exact identifiers, not `search`). |

**Non-blocking cases, also with real results — ALL 16/16 cases have run:**
- **S2**: every variant (`docs__adr__x.md`, accented Unicode, spaces, `#`) gets truncated
  to its basename by SAG whenever it contains `/` — consistent with S1. A **`flat`-form
  key (no `/`) round-trips with perfect fidelity** because there's nothing for SAG to
  truncate — further confirming `key_format=flat` is the right choice, not just "good
  enough".
- **S3**: uploading twice with the same filename → 2 separate documents, SAG does not
  auto-dedupe (matches the assumption `publish.py` was designed around).
- **S8**: a file with only frontmatter still ends up with `chunk_count=1` (not 0) — the
  "ready but empty" condition is rarer than expected for valid text files; the
  `chunk_count > 0` check is still kept for binary/unparseable cases.
- **S9**: `document_id` stays the same after `reprocess` — matches the assumption.
- **S10**: `ingest_text(title=...)` → `filename = "<title>.md"` — quite different from the
  file-upload path (which takes the filename from the multipart field). Only relevant if
  `/ingest` is ever used as a publish path in the future (currently `publish_one()` only
  uses `upload_document`).
- **S13**: `DocumentOut` **has no owner/created_by/user_id field** — no server-side
  attribution.
- **S14**: a 500KB upload succeeded, taking only **0.5s** (well under the
  `max_upload_mb=25` reported by capabilities) — size is not the bottleneck. Ingestion
  ended in `failed` after **129.7s** (likely the same LLM rate-limit cause noted under
  "Operational note" below, not a file-size limit).
- **Capabilities** (`GET /system/capabilities`, no token needed): `max_upload_mb: 25`,
  `.md` support along with many other formats, `search_strategy` defaults to `"multi"`.

**Network-resilience bug discovered and fixed while running S14 (not SAG behavior, a
real vulnerability in `sagctl` itself when the network has transient latency/timeouts —
observed repeatedly over Tailscale to sag.home, even with plain `curl`, not specific to
the Python code):** `_request`/`_request_raw_text` in `restclient.py` only caught
`urllib.error.URLError`, but a timeout occurring MID-response-read (after the connection
was already established) can surface as a raw `TimeoutError`/`ConnectionError` that
`urllib` does not wrap — crashing the entire process (`publish --wait`, every polling
loop in `selftest.py`) over a single transient network blip. Fixed by also catching
`TimeoutError`/`ConnectionError` and wrapping them consistently as `SagApiError`;
`publish.py::_wait_for_ready` and the polling loops in `selftest.py` (S4/S7/S8/S9/S14)
now tolerate network errors (status=0) and keep polling until the deadline instead of
crashing — real HTTP errors (401/404/...) are still raised immediately as before. Added
3 regression tests (`tests/test_restclient_network_errors.py`, mocking
`TimeoutError`/`ConnectionError`).

**MCP `sag` (read) — confirmed with a hand-written client, no SDK used:**
- Transport: **streamable-http/SSE** (`Content-Type: text/event-stream`), the correct URL
  form from `GET /sources/{id}/mcp` returns: `http://<host>/mcp/?source_id=<id>`. **No
  session id needed** — every request is independent on this instance, no need to hold
  onto an `Mcp-Session-Id` between calls (unlike some other stateful MCP servers — check
  again if a different instance returns an `Mcp-Session-Id` header, in which case it must
  be resent on subsequent requests).
- `tools/list` correctly returns the 8 documented tools: `list_sources, search,
  get_entity, list_documents, outline, grep, read, get_chunk`. The server identifies
  itself as `"sag-knowledge"` version `1.29.0`, with `instructions` describing the funnel
  in Chinese — matching the content already written in `skills/sag-knowledge/SKILL.md`
  before this test.
- **`sagw_server.py` (built with the hand-rolled `mcp_protocol.py`) implements plain
  JSON-RPC over stdio ONLY, NOT streamable-http/SSE** — this is the correct choice since
  `sagw` runs locally (spawned as a subprocess by the agent tool), no HTTP transport
  needed; only the `sag` server (SAG's own upstream) uses streamable-http. No changes
  needed to `sagw`.

**Operational note discovered while testing — not a bug, but worth knowing:**
Some documents ended up in `status: failed` with the error
`litellm.RateLimitError: ... Token Plan usage limit reached` — a **quota/credit limit
on the project owner's LLM provider account (MiniMax-M3)**, not a SAG or plugin bug.
Important: the document still has `chunk_count=1` and **basic `grep`/`search` still
finds the content** despite `status=failed` — meaning chunking/embedding (no LLM needed)
had already completed before the event/entity-extraction step (LLM-dependent) failed.
`publish.py` treats `status=="ready"` as a STRICT success condition (no leniency for
`failed` even with chunks present) — this is the right choice, kept as-is: trust the
final status SAG itself reports, and `sag-maintain`/`sagctl reprocess` is already the
recovery path for `failed` documents. **Running the selftest (especially S6 — uploading
120 documents) consumes real LLM quota on the project owner's infrastructure** — consider
lowering `n` in `case_s6_pagination` if rerunning it repeatedly on the same
tightly-limited LLM account.

**Conclusion for S23/token model (DESIGN.md, REVIEW-OPUS F23):** S11 (no isolation) + S13
(no server-side attribution) + unstable `login` behavior when identifying by name
(observed: calling with the same `{name}` repeatedly did not always return the same user
id during the test session) → **per-agent identity is officially dropped** from the
design, no longer "conditional". Use the S12 model exactly (split read/write token, no
per-agent distinction) — see S12 below.

**Self-discovered bugs fixed while running the selftest (not SAG behavior):**
1. `list_documents_all` misread "the server ignores limit" as "the server truncates
   pages" when `len(page) == page_size` due to a boundary coincidence — fixed by directly
   detecting `len(first) > page_size` (direct evidence the server ignores the limit)
   before suspecting truncation.
2. `maintain.py` (`dedupe_source`, `find_stale_branch`) assumed `get_document()` returned
   a `content`/`text` field — **wrong**, `DocumentOut` has no such field (confirmed via
   S13). Must call `GET .../documents/{id}/parsed` separately (added a
   `get_document_parsed` method, returning plain text rather than JSON — also required
   adding a separate `_request_raw_text`, since `_request`'s default `json.loads` would
   crash on this endpoint).
3. `case_s4`/`case_s7` in `selftest.py` originally used `search` to check whether content
   existed — **unreliable**: search is semantic/vector-based and can fail to match a
   meaningless marker string even when the content genuinely exists (directly observed:
   the pre-delete search in S4 also missed it). Switched to GET-by-id (S4) and
   `GET .../parsed` (S7) — unambiguous binary evidence, independent of search quality.

## S0. Architecture

A single engine `scripts/sagctl.py` (Python 3.11+, stdlib-only). Three consumption
surfaces:
- MCP `sag` — SAG's own upstream, 8 read tools, read token, allow-all. Does not touch
  SAG's source.
- MCP `sagw` — the plugin's thin server wrapping the engine, 6 tools, talking to SAG
  purely over REST.
- CLI — everything else (sync, maintain, queue, source, selftest, eval, doctor, adapter).

G1 standard (same OS user): protects against accidents + shallow injection, **not** a
security boundary. G2 hardened (separate OS user, service): an optional later addition.

## S1. Configuration source

Manifest `.sag-sync.json` **in the repo, must be an ancestor of the commit being
published**:

```json
{
  "source_id": "...", "sandbox_source_id": "...",
  "key_format": "path | flat",
  "require": "committed",              // committed (default) | pushed | merged
  "canonical_branch": "main",
  "min_confidence": 0.8,
  "criteria": [ {"id": "c1", "text": "Do not include meeting notes"} ],
  "deny_paths": ["docs/pricing/**"],
  "ask_paths": [],
  "include": ["**/*.md"], "exclude": [],
  "max_files": 50, "max_publishes_per_day": 30, "stale_branch_days": 14
}
```

- Precedence: `deny_paths > ask_paths > include/exclude > criteria > confidence`.
- `deny_paths` blocks **manual mode too** (a rule the user themselves wrote); `ask_paths`
  can be satisfied by manual mode.
- `criteria` = natural language for the model's judgment; `deny/ask_paths` = deterministic
  rules for the engine. Editing criteria/deny/ask = a separate commit + separate audit
  entry + ask permission.
- Config/audit/queue/cost-counter: `~/.sagctl/<sha256(source_id)[:12]>/`. The engine
  **aborts** if it finds `sagctl.config.json|queue.jsonl|audit.jsonl` in the repo (the
  manifest itself belongs in the repo). **⇒ amended by A1 below** — the *location* is no
  longer pinned to the local filesystem; the "never in the repo" rule is unchanged.

## S2. Identity & hashing

- Key = POSIX relpath, encoded per `key_format` — **LOCKED: `flat` is the default**
  (selftest S1 on sag.home confirmed SAG truncates the multipart filename to its
  basename, so `path` is not viable as the default; `path` is still kept as an option for
  other SAG instances with different behavior — always verify with
  `sagctl selftest --case S1` before provisioning a new source); `__` is forbidden in the
  relpath when using `flat`.
- After every upload: assert `response.filename == key`; on mismatch ⇒ abort with
  `KEY_FORMAT_DRIFT`.
- Hash/dedupe/content-change detection: **`git hash-object` on the original file** (before
  provenance is inserted).
- Durable citation = `source + key(+heading)`; `document_id/chunk_id` are ephemeral.

## S3. Provenance

Inserted **only into the upload bytes**, never modifying the file on disk: `sag_key,
sag_source_commit, sag_source_blob, sag_published_at, sag_status, sag_route`. Merged
into existing YAML frontmatter if the file already has one (never creating a second
`---` block). Every SAG↔repo comparison strips provenance first. **⇒ amended by A3** —
the state store (A1) is now the authoritative home for provenance; in-band frontmatter is
a convenience copy written only for `.md`/`.markdown`.

## S4. Deterministic floor (before every upload, no LLM)

```text
manifest ancestor is resolvable
∧ path matches include ∧ does not match exclude ∧ does not match deny_paths
∧ (no Git repo above the manifest ∨ git state satisfies require)
∧ secret scan passes and the content was decodable (regex + entropy; gitleaks if present on PATH)
∧ dedupe-by-key ∧ cost cap not exceeded
```

If any clause is red ⇒ the engine deterministically rejects, with one exception: an
`AUTO`-routed document the scanner could not decode (`UNSCANNABLE`) is downgraded to
`QUEUE` rather than rejected — a human decides, the engine never claims to have scanned
what it could not read (A3). `sag_publish_unreviewed` bypasses `require` but **does not**
bypass the secret scan / `deny_paths`. **⇒ amended by A3** — the git clause applies only
where a repo exists above the manifest; outside one it is inapplicable, not skipped.

## S5. Assessment (the contract for the `sag_publish` tool + CLI `--assessment`)

The model supplies exactly these fields, mandatory and typed; missing/wrong type ⇒ fails
validation at the MCP layer:

```text
verdict        : knowledge | not-knowledge | unsure
durable{pass,why}, audience{pass,why}, retrieval_fit{pass,why},
criteria_ack[id], confidence, rationale
```

Everything else in the full record is filled in by the **ENGINE**, never taken from the
model — `schema_version, path, source_id, commit, assessed_at, key, criteria_available`,
plus `initiator` (agent-auto | user-manual | queue-approved), `trigger`
(post-write-hook | end-of-task | user-command | maintenance), `agent`
(claude-code | hermes:\<profile\> | codex).

- `canonical`/`secret_free` are **not** declared by the model — that's the engine floor's
  job.
- `path`/`source_id`/`commit` were briefly required from the model too (a drafting error,
  not the intent) — the MCP tool's own schema never actually offered them as properties,
  and the engine already has authoritative values for all three (the tool call's `path`
  argument, the resolved manifest, `gitutil`), so nothing a model supplied for them was
  ever read. A real agent hit exactly this mismatch live (2026-08-01): a schema-valid
  assessment got rejected for "missing required field: path", forcing an unnecessary
  `git rev-parse HEAD` to satisfy a check whose answer the engine already had. Fixed by
  dropping them from `_REQUIRED_TOP` and having `enrich()` set them from the engine's own
  values, overwriting anything the model provides — same treatment as `key`/`initiator`.
- The full record is written to the audit JSONL; the frontmatter only receives the
  minimal provenance (S3).

## S6. Routing (`verdict` first, `confidence` second)

```text
knowledge ∧ conf ≥ min_confidence ∧ (no criteria ∨ criteria_ack ≠ ∅) → AUTO publish
knowledge ∧ conf < threshold | unsure | criteria_ack empty when criteria exist
  | ask_paths matched                                                   → QUEUE
not-knowledge                                                           → do not publish
deny_paths matched                                                      → reject, manual mode included
manual mode (valid token)                                               → skip assessment, S4 still runs
```

`criteria_ack` has teeth: if the manifest has criteria but the ack is empty ∧ verdict is
knowledge ⇒ no auto-publish, push to queue (guards against assessment running when the
criteria have fallen out of context).

## S7. Manual mode

- MCP has **no** manual flag. `sag_publish` always requires an assessment.
- The only manual path: slash command `/sag-publish <path|glob>` → the `UserPromptSubmit`
  hook **only mints a token when the prompt matches that command's exact form**, the
  token is bound to `sha256(args)`, single-use (the engine unlinks it upon consumption) +
  5-minute TTL, stored at `~/.sagctl/session/`. `initiator: user-manual` is a
  **conclusion the engine draws from the token**, never a field the model sends.
- Hermes/Codex: a human types the CLI command outside the agent session.

## S8. Tools & permissions (keyed by MCP tool identifier)

- **allow**: `mcp__sag__*` · `mcp__sagw__sag_publish{path, assessment}` ·
  `sag_publish_status{key?}` · `sag_sync_preview{}` · `sag_reprocess{key}`
- **ask**: `sag_publish_unreviewed{path, reason}` (keeps the same key, only changes
  `sag_status`, creates a reconcile debt) · `sag_unpublish{key, reason}` ·
  `Bash(sagctl publish*)`
- **deny**: `Bash(sagctl unpublish*|queue*|api*|source*|sync*)` ·
  `curl|wget|python -c|Invoke-WebRequest`
  (note: deny beats allow in Claude Code ⇒ `publish` is set to ask, not deny, so the
  slash command still works; the real gate is the engine-side token)
- **Ops config**: default = `read, publish, replace, reprocess, unpublish`
  (unpublish is in the default set because it's the remediation path, already ask-gated);
  must be enabled explicitly = `queue-review, sync, source-admin, api`.
  `replace` is internal to the engine (only removes a document that duplicates the exact
  key being uploaded), separate from `delete`.

## S9. Publish semantics

- `publish_one()` is shared by both single-document publish and batch sync.
- **Non-blocking by default**; `--wait` is opt-in, ≤90s, timeout ⇒ exit 75 (tempfail).
- Success = `ready ∧ chunk_count > 0`.
- Replace ordering: **LOCKED to `delete_first`** — selftest S4 on sag.home confirmed
  DELETE is fully synchronous (a GET-by-id returns 404 immediately at t=0).
  `upload_then_delete` is still available in the code
  (`SAGCTL_REPLACE_STRATEGY=upload_then_delete`) for other SAG instances if their
  selftest gives a different result.
- Tolerates 404 on delete. Sync additionally: detects renames via blob sha, `max_files`,
  a concurrency cap.

## S10. Maintain / post-hoc review

- Default is to **propose**, never auto-delete. The one exception: a duplicate key with
  determinable ancestry ⇒ automatically remove the losing copy. Tie-break: `git cat-file
  -e` first → `is-ancestor` → if both are ancestors ⇒ the smaller `rev-list --count` wins
  → UNKNOWN ⇒ delete nothing, report to a human; fetch failure ⇒ report only.
- "Orphan" is defined relative to the **Git HEAD** of the mapped repo, not the lock file.
- Stale-branch (guards against squash/rebase erasing the SHA): `is-ancestor(commit)`
  **OR** (`path` exists at `origin/<canonical_branch>` ∧ its blob matches
  `sag_source_blob`); if both are false for longer than `stale_branch_days` ⇒ flag,
  propose unpublish.
- Self-gate post-hoc review + fail-rate by `agent × route` ⇒ `sagctl doctor`. Action
  (lowering the threshold/revoking privileges) is a human decision in phase 1.

## S11. Awareness-nudge layer

- **Primary**: the `Stop` + `SessionEnd` hooks — scan `git diff --name-only` since the
  start of the session ∩ include-globs, cross-check against the audit log, list files not
  yet assessed. Notify-only, checks `stop_hook_active` (guards against loops).
- **Secondary**: `PostToolUse(Write|Edit)` gives a gentle nudge, deduped once per
  file/session.
- **Hermes/Codex**: advisory (profile system prompt / AGENTS.md) + `sagctl doctor
  --unassessed`. Stated honestly: machine-enforcement only exists on Claude Code.

## S12. Token

Read/write are split. The agent only holds the read token (`.mcp.json` uses
`SAG_READ_TOKEN`). The write token is read from `~/.sagctl/` by `sagw`/the CLI.

**Per-agent identity: LOCKED — dropped entirely**, no longer "conditional". Selftest S11
(sag.home) confirmed there is no isolation between identities (user B immediately sees
user A's source); S13 confirmed there is no server-side attribution (`DocumentOut` has no
owner/user_id field). A second identity/token buys neither isolation nor attribution —
it only adds credential-management overhead. Use **exactly one read/write token pair for
the entire agent fleet** of a project; attribution only exists at the `audit.py` layer
(local, unauthenticated — good enough for internal forensics, not enough to stop an
agent deliberately lying about `agent`/`initiator`).

**Token lifecycle (S12 on sag.home)**: `LoginRequest` only needs `name`; the JWT has a
fixed **7-day** lifetime, no logout/revoke/refresh endpoint. A leaked token **cannot be
revoked early** — the direct consequence: write the token to exactly one place
(`~/.sagctl/credentials.json`, `0600` permissions), and treat rotation as re-login +
manual redistribution on a cycle shorter than 7 days for sensitive environments.

---

## Amendments to the locked spec

### A1. State location is pluggable — `local` (default) | `http` (fleet-shared)

**Amends S1.** Decided by the project owner after the single-machine assumption behind
S1 was found not to hold for the real deployment.

**What was wrong.** S1 placed audit/queue/cost at `~/.sagctl/<sha256(source_id)[:12]>/`.
The requirement that produced that location is REVIEW-OPUS F5 — *"config inside the
workspace = the agent grants itself permissions"* — which constrains **write reach**, not
**storage medium**. On one machine the two coincide, so the distinction never surfaced.
Across a fleet where each agent runs on its own host they diverge, and every guarantee
S1 attached to those three files silently degrades:

| File | What S1 promises | What actually happens across N hosts |
|---|---|---|
| `cost.json` | `max_publishes_per_day` is the budget | the budget becomes N × the manifest value |
| `queue.jsonl` | S6 routes low-confidence work to human review | an item queued on host A **cannot be approved from host B** |
| `audit.jsonl` | S10 post-hoc review + `doctor` fail-rate by `agent × route` | each host sees 1/N of the history; the statistic is meaningless |

Note this degrades *policy*, not *correctness of publishing*: `publish_one()` never trusts
local state — it lists documents by key on SAG and replaces (SAG is the inventory source
of truth), so dedupe and replace stay correct no matter how many hosts participate.

**The amendment.** All access to those three goes through `state.py`, which resolves a
backend from the environment:

```text
SAGCTL_STATE_URL unset  → LocalBackend  — the S1 files, byte-for-byte, no migration
SAGCTL_STATE_URL set    → HttpBackend   — one fleet-shared store (SAGCTL_STATE_TOKEN)
```

The "never in the repo" rule of S1 is **unchanged** — `assert_no_repo_state_leak` and
`FORBIDDEN_IN_REPO` are untouched, and a remote store satisfies the F5 requirement more
strictly than a local file the agent's own OS user can write.

**Atomicity is part of the contract, not an implementation detail.** The backend exposes
`cost_bump` and `queue_set_status` rather than get/set pairs: two hosts doing
read-then-write on a counter is a lost update, and two hosts reading `status == pending`
before either writes would double-approve the same queue item. Both operations resolve
inside the backend, under a lock.

**Reference implementation**: `scripts/sagstate_server.py` — stdlib-only, same zero-
dependency rule as the engine, bearer-token auth, per-source lock, and it refuses to bind
a non-loopback address without `SAGSTATE_TOKEN`.

**Trust boundary — unchanged, and this service does not move it.** The state service is
dumb storage holding no policy. The manifest still decides what may be published, `gate.py`
still runs the deterministic floor, `routing.py` still decides auto/queue/reject.
Compromising the state service lets an attacker forge audit history and reset the cost
counter; it does **not** let them publish anything the floor would have rejected. This is
still G1 (see S0) — a hard boundary is still option C, still out of phase 1.

**Addressing.** The wire uses `sha256(source_id)[:12]` — the same namespace key as the
local layout — so a real `source_id` never appears in a URL, an access log, or a proxy
trace.

**Diagnostics.** `sagctl doctor` reports the active backend. On a fleet, one host
reporting `local` while another reports `http` means they are **not** sharing state, even
though both point at the same SAG source.

### A2. Agent-side config is generated from the manifest; read MCP is scoped

**Amends S8** (adds the read side) and replaces the "static snippets, copy by hand"
half of Q7/DESIGN.

**What was wrong.** S8 specifies write permissions precisely — by MCP tool identifier,
ops taxonomy, default vs explicitly-enabled. It says nothing about the read side, and
`.mcp.json` shipped `${SAG_URL}/mcp/` with no `source_id`. Combined with S11 (no isolation
between identities) and S12 (one read token for the whole fleet), the consequence is that
**every agent can list and search every source on the instance**, regardless of which
project it works in. On a one-project instance that is invisible. On N projects it means
the plugin has no read-side scope at all.

The second half of the problem is mechanical: scoping requires a `source_id` in the agent
tool's own config — `.mcp.json`, `config.yaml`, `config.toml` — none of which reads
`.sag-sync.json`. With N projects × M agent hosts that is N×M hand-maintained copies in
three file formats. Hand-copying at that scale does not stay correct.

**The amendment.**

1. `source_id` remains declared **exactly once**, in the manifest, in Git.
2. `sagctl adapter-emit <target>` resolves it from the manifest found at cwd (or
   `--manifest` / `--source-id`) and **generates** the agent-side config for all three
   targets, with the read MCP pointed at `${SAG_URL}/mcp/?source_id=<id>` — the URL form
   `GET /sources/{id}/mcp` returns, confirmed in S15.
3. Emitting without a resolvable `source_id` still works but **says so loudly**, on stderr
   and in the file header. An unscoped config must be a visible choice, never a silent
   default.
4. `--write DIR` places the files. Artifacts that normally already hold unrelated content
   (`settings.json`, `config.yaml`, `config.toml`) are marked merge-targets and are never
   written blind — they are printed for a human to merge unless `--force`.

**What this is worth, stated honestly.** Defence in depth, not a boundary. The same read
token still reaches an unscoped URL, and S11 means the server enforces nothing. It stops
an agent working in project A from casually retrieving project B's knowledge; it does not
stop one that is trying to. Read-side separation as a real boundary remains option C, out
of phase 1 — unchanged by this amendment.

**Verification.** New non-blocking selftest case **S17** measures the claim instead of
asserting it: two temporary sources, a marker document in A only, then `list_documents`
through a client scoped to B. Automated via `mcp_client.py`, a minimal hand-rolled
streamable-http/SSE client (no SDK), same approach that produced the S15 result.

**S17 result on `sag.home` (2026-08-01, run from a second host):**

```text
probe visible via source-A-scoped url:                    True
A's document reachable through the source-B-scoped url:   False   <- no content leak
list_sources through the scoped url shows other sources:  True    <- metadata leaks
```

The mitigation is **stronger than claimed for content, incomplete for metadata**, and the
wording above is corrected accordingly rather than left generous:

- `?source_id=` **is** enforced by the server for document access. An agent scoped to A
  cannot pull A's documents through a url scoped to B. This is a real boundary for
  content, not merely a default — better than the "casual retrieval only" framing this
  amendment originally used.
- `list_sources` still returns **every** source on the instance. An agent scoped to
  project A can enumerate the names and ids of the other nine projects. Source names are
  frequently the project names, so treat them as disclosed to every agent on the instance.
- Neither result changes the G1 ceiling: the fleet shares one read token, so an agent that
  constructs an unscoped url reaches everything regardless. Scoping constrains the tools
  the agent is given, not what its credential can do.

Re-run `sagctl setup probe --url <URL> --token <TOKEN> --full` on any new instance — this
result describes `sag.home`, not SAG in general.

### A3. Knowledge is not welded to `.md` files inside a Git repo

**Amends S3** (provenance may live outside the upload bytes), **S4** (the git clause
applies only where a repo exists), and the `include` default carried in S1's example.

**What was wrong.** Provenance (S3) was inserted into the upload bytes as YAML
frontmatter, and only markdown can carry that without corruption. Publishing (S4) required
a Git commit, which only exists inside a repo. Neither restriction was a decision that
"only committed markdown can be knowledge" — both were storage details (frontmatter needs
text; a commit needs a repo) that leaked into the rules and were enforced as if they were
policy:

- SAG accepts `.pdf .docx .pptx .xlsx .csv .json` and more (`GET /system/capabilities`,
  `allowed_upload_exts`) — the engine accepted none of them. `publish_one()` read every
  file with `read_text(encoding="utf-8")`, so a PDF raised `UnicodeDecodeError` rather than
  being handled or cleanly refused.
- An agent whose working area was not a Git checkout — a Hermes profile, a research
  session with no repo behind it — could not publish at all: `manifest.load_for()` and
  `check_git_state()` both assumed one.
- The secret scanner made it worse, silently: it read every file with
  `errors="replace"`, so scanning a PDF examined replacement characters and reported
  "clean" for bytes it had never decoded. A floor check that certifies what it did not
  inspect is worse than no check, because S4 lets everything downstream trust it.

**The amendment — provenance moves to the state store, Git becomes optional evidence.**

1. **Provenance's authoritative home is the state store** (`state.provenance_put/get`,
   SPEC A1), keyed by `source_id + key`, written for every publish regardless of format.
   YAML frontmatter is now a *convenience copy* for markdown — written when
   `provenance.can_carry_frontmatter(path)` is true (`.md`/`.markdown`), skipped otherwise.
   A human reading a markdown document straight out of SAG still sees its provenance; a
   PDF's provenance lives where `maintain` and `doctor` actually look.
2. **The git clause in `check_floor` is conditional, not mandatory.** `manifest.git_root(m)`
   returns the Git toplevel above the manifest, or `None` when there is none.
   `in_git_repo=False` means `check_git_state` is not run at all — not skipped as a
   favour, simply inapplicable, because there is no commit to check. Every other floor
   clause (path policy, secret scan, cost cap) still runs unconditionally.
3. **`include` defaults to `**/*`**, not `**/*.md` — the old default was a consequence of
   the frontmatter weld, never a content judgement. What counts as knowledge is the
   assessment's job (S5/S6); `include` is a mechanical boundary, and narrowing it fails
   silently in both directions (`routing.decide()` rejects before the model is asked, and
   `doctor --unassessed` only scans within `include`).
4. **An undecodable file is `UNSCANNABLE`, not banned and not certified.** When a route
   would be `AUTO` and the floor returns `UNSCANNABLE`, the engine downgrades it to
   `QUEUE` instead of rejecting outright — a human decides, the engine never claims to
   have scanned something it could not read. The engine does **not** grow
   format-specific extraction to work around this: an agent that can read a PDF (Claude
   Code and others ship document skills for exactly this) should distil it into markdown
   and publish that instead. The distillation chunks better than a server-side parse
   (AGENT-BEHAVIOR.md P6) and is fully covered by the floor; the original stays cited via
   `derived_from`.
5. **New: `publish_content(relpath, text, ...)` / MCP tool `sag_publish_content`** — the
   agent hands text directly, no file, no repo. `relpath` is a path-shaped key the caller
   chooses (e.g. `research/2026-08-01-pricing-competitors.md`); it plays exactly the role
   a real file's relpath plays — matched against `include`/`exclude`/`deny_paths`/
   `ask_paths`, encoded into the SAG key by `key_format` — so no new policy concepts and
   no new manifest fields exist for this path. `derived_from[]` keeps the citation chain:
   repo paths (ideally `path@blobsha`), URLs, or other SAG keys. Same self-assessment
   contract (S5), same routing (S6), same floor (S4) minus the inapplicable git clause.
   There is no manual-mode bypass for this tool — there is no file for a slash command's
   token to bind to.
6. **Manifest resolution no longer requires a file to walk up from.**
   `manifest.resolve()`: explicit path → named manifest
   (`~/.sagctl/manifests/<name>.json`) → `$SAGCTL_MANIFEST` → walk up from a start
   directory (which itself does not have to be inside a Git repo — `find_manifest` walks
   to the filesystem root when no repo is found, not just to a repo boundary). `publish_content`
   additionally tries the current working directory as its walk-up start. Publishing still
   **requires** a manifest (S1, unchanged) — what changed is where one is allowed to live.
7. **`require: "none"` does not exist.** An earlier draft of this amendment added it as a
   fourth `require` value; that was Mode A pretending to be Mode B — a repo pretending not
   to need Git instead of the document honestly having none. Superseded by `git_root()`
   being allowed to return `None` outright. `VALID_REQUIRE` stays `{committed, pushed,
   merged}`; `canonical_branch` is required by the manifest schema only when `require` is
   `pushed` or `merged` (it is otherwise inert — consulted only there and by
   stale-branch detection).
8. **`maintain` refuses to reconcile what was never in the repo.** Orphan detection
   (`find_orphans`) and stale-branch detection (`find_stale_branch`) both ask "does this
   path still exist in the repo?" — meaningless, and actively dangerous, for a document
   whose key was never a real repo path: `path_exists_at_ref` is unconditionally `False`
   for such a key, so every authored document would be flagged as orphaned. Both functions
   now consult `sag_in_git` from the document's provenance record
   (`maintain._reconcilable`) and skip anything where it is `False`. A document with no
   state-store record at all predates A1/A3 and is treated as reconcilable, matching prior
   behavior.
9. **Queueing an authored document keeps its content, not just its path.**
   `queue.enqueue()` gains `content`/`derived_from`/`manifest_path`; an item is
   `mode: "content"` when `content` is set. There is no file on disk to re-read at
   approval time, so the text has to live in the queue record itself.
   `queue.approve()` dispatches to `publish_content()` for `mode: "content"` items and to
   the unchanged `publish_one()` otherwise.

**What did not change.** The deterministic floor still runs on every document. The model
still cannot assert `secret_free` or `canonical`. A document the engine cannot decode is
never certified as scanned. `deny_paths` still blocks unconditionally, git repo or not.
Git, where it exists, still gives the strongest guarantee SAG can offer — commit + blob,
full reconciliation via `maintain` — and nothing about mirrored publishing (Mode A, in an
earlier draft's terms) changed. What changed is that Git stops being the *precondition*
for a document being knowledge, and stops being the only place provenance can live.

---

## Phase plan

| Phase | Content | Depends on |
|---|---|---|
| **P0** | Reconcile the docs: merge DESIGN+AGENT-BEHAVIOR into a complete SPEC, apply the [fix-docs] conditions | blocks everything |
| **P0b** | Skeleton (parallel with P1, no server needed): repo structure + `sagw/` + `hooks/` + `commands/`, manifest parser+validator, JSON Schema assessment, audit writer + cost counter, `~/.sagctl/` layout, secret scan, provenance injector, git-blob hash + `--dry-run` planner, adapter/doc templates. 3 isolated functions waiting on the selftest: `encode_key()`, `replace_strategy()`, `list_all_documents()`. DoD: py_compile, every `--help`, dry-run gives the same plan on Windows/Linux, offline policy test, assessment-validation test | P0 |
| **P1** | ✅ **COMPLETED on sag.home (2026-07-31) — 16/16 cases, 7/7 BLOCKING PASS.** S1 flat, S4 delete_first, S6 no-truncation after fixing the bug, S7 banner survives, S11 no isolation, S12 7-day non-revocable token, S15+S16 PASS via a real MCP client. While running it, 2 additional network-resilience bugs (uncaught timeout/connection errors) were discovered and fixed. See "Selftest results" at the top of the file. | P0 |
| **P2** | Engine publish path: `publish_one()` (manifest ancestor → S4 floor → key+assertion → dedupe → replace → upload with provenance → non-blocking), `unpublish`, `reprocess`, `publish-status` | P1 (S1/S4/S6/S15) |
| **P3** | Consumption surfaces: `sagw` 6 tools + schema validation; the 3 adapter permission sets; the Stop/SessionEnd/PostToolUse/UserPromptSubmit hooks; the `/sag-publish` slash command. Bypass test: manual mode without a token ⇒ rejected; a token for path A cannot be used for path B | P2 |
| **P4** | Queue (`list\|approve\|reject`, `queue-review` op), ancestry-based dedupe, HEAD-based orphan detection, stale-branch, self-gate post-hoc review, `doctor` | P2, S7 |
| **P5** | Batch sync (using `publish_one()`, rename via blob, max_files, concurrency) + `eval --save-baseline` | P2 |
| **P6** | Write the selftest results back into SPEC, pin the SAG version | P1 |

Critical path: **P0 → P1(S4) → P2 → P3**. P0b runs in parallel from day one; P4/P5 don't
block each other.
