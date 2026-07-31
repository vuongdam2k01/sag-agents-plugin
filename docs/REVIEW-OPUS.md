# Design review transcript — a two-way exchange with Claude Opus

> Conducted 2026-07-31 via Claude CLI (`claude -p --model opus`), 2 rounds of
> conversation (independent critique → author rebuttal → convergence). Subject:
> `docs/DESIGN.md` + `docs/AGENT-BEHAVIOR.md`. Cost: ~$2.52.
>
> **Reviewer's verdict: NEEDS MAJOR REVISION — but directed, not a rewrite.**
> The data-contract foundation (DESIGN.md section 1) and the "SAG = a read-model of
> Git" framing were assessed as sound assets; the broken parts are in the algorithm
> layer and the enforcement layer.

## 1. The biggest outcome: switching the architecture to HYBRID

Round 1 Opus pointed out (F2/F4/F7) and round 2 successfully defended against the
author's rebuttal:

- **A permission rule based on a Bash string pattern cannot be enforced**:
  `Bash(sagctl document publish*)` can be bypassed by
  `python scripts/sagctl.py ...`, flag reordering, aliases, `sh -c`. Whereas an MCP tool
  identifier (`mcp__sagw__sag_publish`) is atomic, cannot be quoted/aliased/reordered —
  and MCP is the real common denominator across all 3 tools (Codex has no skill system,
  but does have MCP).
- The "three overlapping layers" claim in AGENT-BEHAVIOR §4.1 is **wrong** relative to
  Q6 itself: the attack path `echo $SAG_TOKEN → curl` goes through no layer at all.
- The author's rebuttal (a write tool constantly present in context = a larger injection
  surface) was narrowed down to one real risk: **approval fatigue** — addressed by
  minimizing the number of tools + an approval prompt that shows a digest/diff, not by
  reverting to Bash. A mandatory condition: **`sag_publish` has no `content` parameter,
  only `path`** — the content must go through Write/Edit (already approved + the user
  sees the diff) and then be committed.

**The locked phase-1 architecture** — one codebase, three consumption surfaces:

- `sagctl.py` = the single engine (key encoding + assertion, commit check, secret scan,
  replace-by-key, polling, audit).
- **MCP `sag`** (upstream, 8 read tools, read token) — allow everything.
- **MCP `sagw`** (a thin ~200-line write server wrapping the engine) — exactly 5 tools,
  ask for everything: `sag_publish{path,source?}` · `sag_publish_status` (auto) ·
  `sag_reprocess{key}` · `sag_unpublish{key,reason}` (the remediation path, always
  enabled) · `sag_sync_preview` (auto, read-only). Split into 2 servers so permissions
  can be set at the server level — this also works on Codex, where approval is coarse.
- **CLI-only, never an MCP tool**: `sync`, `maintain`, `source *`, `api`, `login`,
  `selftest`, `eval`, `doctor`, `adapter emit`.
- Two modes, stated honestly: **G1 standard** (same OS user — guards against accidents
  and shallow injection, NOT a security boundary) and **G2 hardened** (optional, `sagw`
  runs under a separate OS user as a service, config out of the agent's reach — a real
  boundary; DPAPI/keychain under the same user is NOT a boundary). The agent is only
  ever granted a read token; the write token never lives in the agent's environment.

## 2. Points the author successfully rebutted (Opus withdrew/conceded)

- **C2 — the key wire format**: withdrew "encode `__` unconditionally". Locked: decide
  `/` vs `__` ONCE at source provisioning, record `key_format` in the manifest; plus
  Opus's 3 patches: (L1) **an assertion of `response.filename == key` after every
  upload**, on mismatch ⇒ abort with `KEY_FORMAT_DRIFT`; (L2) forbid `__` in the relpath
  (keeps the encoding bijective); (L3) an ancestor manifest is mandatory for every
  publish (resolving both `source_id` + `key_format`).
- **C3 — the dedupe tie-break**: accepted the ancestry approach instead of `created_at`,
  plus a fatal detail: `git cat-file -e <sha>` before `is-ancestor` (distinguishes
  "losing" from "commit unknown"); if both are ancestors ⇒ the smaller
  `rev-list --count` wins; UNKNOWN ⇒ **delete nothing, report to a human**; maintain must
  fetch first, a fetch failure ⇒ report only.
- **C4 — superseded**: Opus withdrew the proposal to rename the filename (it
  self-contradicted F20's durable citation). Locked: **keep the key**, `sagctl`
  automatically inserts a banner under every heading ≤3 on upload (the primary layer,
  independent of chunk boundaries); a frontmatter check is a secondary layer; an archive
  source is optional.
- **C5 — the eval harness**: accepted the reduced scope — ship the `sagctl eval` command
  + format + 5 sample questions running against the selftest corpus; a real golden set is
  a per-project onboarding task; `--save-baseline` is mandatory from v1.

## 3. Confirmed design flaws (the author accepted immediately)

The publish-algorithm group (a cascading chain of findings F10→F16): DELETE semantics
were unverified (could be async ⇒ delete-first loses its entire reason for existing);
publish needs delete but the default ops set has no delete (⇒ split out a `replace` op);
a single-file publish doesn't write a lock but maintain treats "outside the lock =
orphan = propose deletion" (⇒ define orphans by Git HEAD instead); `--unreviewed`
renaming the filename breaks reconcile on its own (⇒ keep the key, only change the
status); sync's crash-recovery produces duplicates (⇒ sync shares `publish_one()`,
tolerates 404, detects renames via sha).

The bite-you-on-day-one group: **F25** the hash doesn't normalize CRLF ⇒ every switch
between a Windows and a Linux machine becomes a full corpus re-ingest paid for with real
LLM money (⇒ hash with `git hash-object`, POSIX relpaths, a cross-platform DoD); **F26**
`--wait` defaulting to 10 minutes vs Claude Code's own 2-minute Bash timeout, and a
contradiction with P3 (⇒ non-blocking by default, `--wait` opt-in ≤90s, exit 75, success
= `ready ∧ chunk_count>0`).

The safety group: config/audit inside the workspace = an agent can edit it itself (⇒
`~/.sagctl/` is mandatory, config inside the repo is rejected); the `sagctl api` escape
hatch defeats every permission table (⇒ denied by default in all 3 adapters); no secret
scan (⇒ mandatory before upload, blocked by default); a per-agent token on single-user
SAG has ≈0 value until revocation/attribution are verified (⇒ reduced to 2 tokens,
read/write, pending selftest S11/S12).

## 4. Mandatory change-set before writing code (15 items, by priority)

1. Reconcile Q1/Q4/Q8 with AGENT-BEHAVIOR §7 (no more drift between the two files).
2. Add Q0 (CLI vs write-MCP, lock in the hybrid); §4.1 drop "three overlapping layers",
   replace with G1/G2.
3. Rewrite T0–T3 keyed by MCP tool identifier + an explicit deny list
   (`curl|wget|python -c|Invoke-WebRequest|sagctl api|source|sync`).
4. Key wire-format v1: locked at provisioning + an assertion on every upload + forbid
   `__` in relpaths.
5. Split the `replace` op from `delete`; add `unpublish`, always available at T1.
6. Frontmatter provenance inserted by sagctl; ancestry tie-break, UNKNOWN ⇒ delete
   nothing.
7. Define "orphan"/`--prune` by Git HEAD; publish writes a cache entry.
8. Publish non-blocking by default; success = `ready ∧ chunk_count>0`; fix §4.6 to match
   P3.
9. `--unreviewed` keeps the key; report the reconcile debt in maintain.
10. Sync shares `publish_one()`; tolerates 404; detects renames; batch =
    upload-then-delete + a concurrency cap + `--max-files 50`.
11. Hash by git-blob + POSIX relpath; DoD: the same plan on Windows and Linux.
12. A mandatory secret scan before upload.
13. Superseded keeps the key + a banner on every heading ≤3.
14. Config/audit moved to `~/.sagctl/`; an ancestor manifest is mandatory for every
    publish.
15. Token: split read/write; per-agent identity is conditional, pending S11/S12; fix R3.

## 5. 16 selftest cases — 7 BLOCKING cases must run before writing code

| # | Case | Blocking? |
|---|---|---|
| S1 | Does the filename keep the `/`? (compare `DocumentOut.filename` character by character) | **BLOCKING** — decides `key_format` |
| S2 | Key round-trip: `__`, Unicode, spaces, `#` | |
| S3 | Uploading twice with the same filename → 2 docs or a conflict | |
| S4 | **DELETE semantics**: a synchronous or async purge (search/grep/get_entity at t=0/5s/30s/5min) | **BLOCKING** — is delete-first still valid |
| S5 | Delete then immediately re-upload the same key (an async-purge race) | |
| S6 | Pagination of `list documents` (120 docs) | **BLOCKING** — a silent dedupe slip |
| S7 | Does the frontmatter + banner survive into a chunk (`get_chunk` on a middle chunk)? | **BLOCKING** — does the superseded strategy live or die |
| S8 | `ready` but `chunk_count=0` (an empty md, a scanned-image PDF) | |
| S9 | `reprocess`: does `document_id` stay? does `chunk_id` change? | |
| S10 | Does `IngestRequest.title` map to `filename`? | |
| S11 | Do multiple identities see the same data? | **BLOCKING** — keep or drop per-agent tokens |
| S12 | Token: which `login` fields are mandatory, `exp` in the JWT, is there revocation?, does a password change invalidate old JWTs? | **BLOCKING** |
| S13 | Does the server provide per-token attribution | |
| S14 | Max file size, rate limits, measuring t(pending→ready) for 5KB/500KB | |
| S15 | REST↔MCP consistency: does the filename via MCP `list_documents` match the key? | **BLOCKING** — resolving citations |
| S16 | `grep` exact-match + scoped; post-publish verification uses grep | |

Process: run the selftest against a real instance → write the results back into
DESIGN.md's Q1/Q2/Q6 and section 3 → if S4 shows DELETE is async, stop and rewrite Q2
before writing any code.

## 6. Three strengths the reviewer acknowledged

1. Section 1's data contract, verified from source code — "a rare foundation", and it's
   exactly what makes a deep critique possible in the first place.
2. The "SAG = a read-model of Git" framing — "the single most correct architectural
   decision in the entire document set"; the §3.2 classification table and the
   `Code > SAG > Honcho > memory` ordering can be used as-is.
3. The honesty about the soft boundary in Q6, and rejecting both extremes
   (automatic/manual) for a reason — "the thing that makes this design worth fixing
   instead of rewriting from scratch".
