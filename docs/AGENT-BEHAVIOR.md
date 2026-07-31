# Agent behavior with the SAG Knowledge Center

> A supplement to `DESIGN.md` (the technical layer). This document answers the behavior
> layer: what the knowledge center is, what gets into it, who decides, when it's
> automatic, when it's manual, and what rules an agent reads/writes/maintains it by.
>
> **This file is a design log.** A few details below (the JSON example with `doc_type`/
> `canonical`/`secret_free` in the assessment, `manifest.rules`/`gate: self`/`autonomy`,
> the `.sag/queue.jsonl` location, the `created_at` dedupe tie-break, the `--unreviewed`
> filename-renaming behavior) were **changed or removed** in the final model — marked
> `[FIXED]` in place. **`docs/SPEC.md` (LOCKED SPEC v1) wins on any conflict.**

---

## 1. What this knowledge center IS — an accurate framing

Within a three-tier memory system, SAG is **not the agent's "memory"**. The correct
definition:

> **SAG = a read-model of the canonical documents in Git, optimized for an agent's
> retrieval and citation.**

Which means:

- **Git is the original, SAG is a projection** (a structured projection/cache). SAG can
  be deleted and rebuilt entirely from Git without losing anything. The reverse is not
  true — so *no information is allowed to exist only in SAG*.
- **Honcho is memory, SAG is a library.** Honcho writes are cheap, automatic, and
  session/personal-scoped (episodic). SAG writes are expensive, approved, and
  collective/citable (canonical).
- SAG answers the question *"what has the project decided/know, where's the evidence?"*
  — it does not answer *"what am I doing right now, what does the user prefer, what
  happened in the previous session?"* (Honcho), and it does not answer *"what does the
  code currently look like?"* (Git/direct grep).

The foundational consequence: **every upload rule boils down to a single question — "is
this already canonical in Git?"** If not, it has no way into SAG.

---

## 2. SAG's real-world characteristics → behavioral consequences

From verified source code, SAG has the following operational characteristics, each of
which forces a behavioral rule:

| # | SAG characteristic (verified) | Behavioral consequence for the agent |
|---|---|---|
| P1 | Ingestion runs an LLM pipeline (parse → chunk → embed → **event/entity extraction**), with a `token_usage` field tracking cost | Writing to SAG is **expensive and slow (minutes)**. SAG is a *write-light, read-heavy* store. Never use it for high-frequency logging |
| P2 | No update API; a content change = delete + re-upload, `document_id` changes | Only **already-stable** documents deserve to go in. A document edited daily will burn repeated ingest cost and churn citations |
| P3 | `pending → loading → extracting → ready` takes a noticeable amount of time | The agent **must not be designed around a "write then immediately read" workflow**. Publishing and consuming are two separate phases |
| P4 | Retrieval is strongest at event-entity multi-hop: complete events + named entities | Documents going into SAG should be **rich in named entities and complete propositions** (decisions, API contracts, procedures). Vague, chat-context-dependent content extracts poorly |
| P5 | `grep` exact-match exists alongside semantic search | Keep technical identifiers (function names, ticket IDs, error codes, endpoint names) **verbatim** in documents — don't paraphrase them |
| P6 | The original chunk is the evidence boundary; citations point to a chunk | Documents need **clear headings, each section standing on its own** — chunking follows the structure; a section that depends on another becomes a meaningless chunk |
| P7 | Single-user, no RBAC | The rule for "who gets to write what" must live in the **process (Git review) + sagctl policy**, not something expected from SAG |
| P8 | `source_id` is the MCP scoping unit; multi-hop entity joins operate within a query's scope | How **sources are split determines the quality of cross-document reasoning** (see section 6) |

---

## 3. What goes into SAG — criteria and a classification table

### 3.1 Five criteria (ALL FIVE must be met)

An artifact is only published when:

1. **Durable** — still correct and still referenced weeks/months later (not a temporary
   state of the current task).
2. **Approved** — merged into the canonical branch via review (Git is the approval
   boundary).
3. **Shared** — at least two different roles/agents will need to look it up (if only one
   agent needs it → Honcho or a file in the repo is enough).
4. **Fits SAG's retrieval model** — text with entities, decisions, events (P4/P5/P6).
   Code, raw data tables, binaries → don't fit.
5. **Contains no secrets / PII / information not cleared for wide distribution** — SAG
   has no per-reader ACL (P7): everything in SAG is *readable by every agent*.

### 3.2 Destination classification table

| Artifact | Destination | Reason |
|---|---|---|
| PRD, approved ADR, system design, API contract | **SAG** (via Git) | Meets all 5 criteria, rich in entities |
| Runbook, confirmed postmortem, test strategy | **SAG** (via Git) | Looked up repeatedly by multiple roles |
| Accepted research report (with sources) | **SAG** (via Git) | Needs citations — exactly SAG's strength |
| Project entity glossary (canonical names) | **SAG** (via Git) | Amplifies entity-retrieval quality for every other document |
| A superseded ADR | SAG, **marked in the title + a banner at the top of the file** | Historical value; marked so search doesn't cause confusion |
| A draft in progress, an unapproved proposal | A Git branch/MR — **not yet in SAG** | Hasn't met criterion 2 |
| A hypothesis, an unfinished analysis, investigation notes | **Honcho** (or an MR comment) | Not durable, not shared |
| An agent's personal lesson, a user preference | **Honcho** | Episodic, doesn't need citing |
| Task status, assignments, progress | **GitLab issue/MR** | Changes constantly (violates P2) |
| Source code, config | **Git** — the agent greps it directly | SAG isn't a code index; code changes faster than a sync cycle |
| Logs, terminal output, chat transcripts | **Nowhere** (or attached to an issue) | Noisy, PII risk, worthless for event extraction |
| Secrets, credentials | **Strictly forbidden** | P7 — no read boundary |
| Live operational metrics (dashboards) | An observability tool | SAG is static knowledge, not live data |

### 3.3 Writing rules for SAG to "digest" well (mandatory in the publish skill)

- Write each decision as a **complete proposition, with a clear subject and timing**:
  *"On 2026-07-30, the team finalized storing the generated page as versioned JSON
  (ADR-0012)"* — not *"as discussed, we'll go with the second approach"*.
- Use **canonical glossary names** for every entity, consistent across documents — this
  is what feeds multi-hop joins.
- Clear heading hierarchy; each section stands on its own (P6). Minimum frontmatter:
  `title`, `status: approved|superseded`, `date`, `supersedes/superseded_by` if
  applicable.
- Keep technical identifiers verbatim (P5).

---

## 4. Automatic or manual — analysis and the chosen model

### 4.1 Three models

**(A) The agent decides on its own to publish whenever it "learns something"** —
REJECTED.
- The agent is the worst judge of how durable its own just-formed conclusion is (recency
  bias); the knowledge base would fill with intermediate conclusions.
- SAG doesn't dedupe (no upsert) → every "re-learning" is a duplicate document.
- Opens a prompt-injection path: a malicious document could trick an agent into "recording
  a conclusion" that's fake, into the shared store — poisoning knowledge for *every*
  other agent.
- Uncontrolled LLM ingest cost (P1).

**(B) Fully manual (a person runs the command for each document)** — REJECTED.
- People forget; the store always lags behind Git; it loses the very benefit of an agent
  system.
- Doesn't take advantage of the fact that the upload step is a **purely mechanical**
  operation once the decision has already been made.

**(C) THE CHOSEN MODEL: "the agent proposes — a human approves in-session — the agent
tool's permission system is the enforcement mechanism"**

The context for this decision: this plugin **installs directly into Claude Code, Hermes
Agent, and Codex** — the knowledge lifecycle must operate inside the agent's working
session, with no CI pipeline assumed. The only approval point that still exists in that
environment is **the human sitting in the session**, and the only real enforcement
mechanism is **each agent tool's own permission system**. So the "automatic or manual"
question splits into two:

| Question | Answer | Mechanism |
|---|---|---|
| *What* becomes shared knowledge? | **A human decides — ONCE** | The main path: approval happens at **Git merge** into the canonical branch. The ad-hoc path (content that hasn't gone through review): approved in-session via the tool's approval prompt |
| *How* does it get onto SAG? | **Automatic, deterministic** | For already-merged content: the engine checks the preconditions itself and publishes **without asking again** — re-asking about an already-approved decision is approval theater |

The authorization principle: **the level of automation isn't tied to the operation, it's
tied to the TRUST STATE of the content** — and that state must be machine-verifiable.
Since a tool's permission system is static (allow/ask/deny by tool identifier), the way
to encode this dynamic policy is to **split tools by trust tier**: an auto-allowed tool
only functions when every precondition is green (the engine deterministically rejects
otherwise), an ask tool is for content that hasn't gone through review.

**The automation rule (a deterministic predicate, no LLM involved):**

```text
AUTO-PUBLISH is permitted ⇔
     the file matches an include-glob in .sag-sync.json
  ∧  the commit containing the file is an ancestor of origin/<canonical_branch>   (already past the Git approval point)
  ∧  the secret scan passes
  ∧  it does not exceed the rate/cost cap (max-files, N times/24h/key)
If any clause fails ⇒ the engine REJECTS; the agent must switch to the ask path.
```

**Who judges? — The agent itself, on each piece of content.** There is no rigid
classification table, no gate by folder or by type. When an agent creates or edits a
piece of content, it answers a question for itself: **"is this knowledge that other
agents will need?"** — using the 5 criteria in §3.1 as a thinking framework, not a form
to fill out. Three outcomes:

```text
It's knowledge, confident enough  → commit → publish AUTOMATICALLY (through the deterministic floor)
Not sure                          → propose (in-session if a human is present; into the queue otherwise)
Not knowledge                     → nothing — Honcho if worth remembering personally, or nothing at all
The user gives a direct order     → carry it out (still goes through the deterministic floor)
```

**Automation is always on — the user cannot toggle it, only add their own criteria into
the judgment.** By default the agent judges using the 5 criteria in §3.1. If the user
declares `criteria` in the manifest, those criteria are fed directly into the agent's
judgment (a skill/hook loads them into context at assessment time) and **take priority
over the defaults**:

```json
{ "source_id": "...", "key_format": "flat",
  "min_confidence": 0.8,
  "criteria": [
    {"id": "c1", "text": "Never include meeting notes or investigation logs"},
    {"id": "c2", "text": "Always include every API contract change, even minor ones"}
  ],
  "ask_paths": ["docs/pricing/**"]
}
```

*(Changed from the original draft: `key_format` defaults to `flat` — confirmed via
selftest S1, SAG truncates filenames to their basename. `criteria` is an array of `{id,
text}` objects, not plain strings — the `id` is needed so the agent can confirm which
criteria it actually read (`criteria_ack`, see §4.3, fixed). The "pricing must ask first"
sentence maps to `ask_paths` — a DETERMINISTIC rule the engine enforces, not a line in
`criteria` whose observance depends on the model's own goodwill — see SPEC §S1.)*

No `criteria` present ⇒ the default stays fully automatic. Criteria are natural language
— they adjust the *judgment*, not a new rule engine.

**The manual path is a normal, always-available function:** the user gives a direct
order like "put the entire docs/specs folder into the knowledge base" ⇒ carried out
immediately, **no assessment needed**, because the human has already decided. Only the
deterministic floor still runs (secret scan, commit check, dedupe), because the floor
protects against accidents, not against the user's own intent. **`[FIXED]`** The
execution path is **not** calling `sag_publish` (MCP) directly, nor an uncontrolled CLI —
both are places where the model could infer on its own that "the user ordered it" with
no actual evidence. The real mechanism: only through the `/sag-publish` slash command
(typed by a human) + a one-time token minted by a hook — see the "The user's manual
command" row in §4.7 and SPEC §S7.

The judgment belongs to the model — the engine cannot verify "this is genuinely
knowledge". What the engine holds onto, deterministically: the floor (committed ∧ secret
scan ∧ cost cap ∧ dedupe), the confidence threshold, and a record of the judgment in the
audit log for post-hoc re-grading. An agent that judges poorly isn't blocked beforehand,
but doesn't get away with it afterward (§4.3).

| Tier | Content/operation | Mode | Mechanism (all 3 tools, keyed by MCP tool identifier) |
|---|---|---|---|
| T0 — read | 8 read tools | **Automatic** | `allow mcp__sag__*` |
| T1a — publish content **the agent has judged to be knowledge meeting the threshold** (or the user ordered it) | `sag_publish` (just path + assessment; the engine enforces the floor + threshold) | **Automatic — no asking** | `allow mcp__sagw__sag_publish` — safe because the engine deterministically rejects when the floor/threshold is red |
| T1b — publish **content that fails the floor** (not committed — an urgent hotfix, a draft) | `sag_publish_unreviewed` (a separate tool) | **Ask every time** | `ask` by tool name; Hermes: only granted to certain profiles; creates a reconcile debt |
| T2 — batch sync | merged-only, no prune: **can be automatic** (scheduled/orchestrator); `sag_sync_preview` is auto | Conditionally automatic | Batch = CLI, run by a schedule or a human; the same predicate as T1a |
| T3 — unpublish / prune / source-admin | A destructive operation or one outside Git | **Human + ask/deny** | `ask mcp__sagw__sag_unpublish`; prune/source is CLI-only + `--yes`; denied by default in the adapters |

Honesty about the strength of this boundary (replacing the old "three layers" claim): in
standard mode (G1, same OS user) this is a **guard against accidents and shallow
injection** — matched by MCP tool identifier so it can't be evaded by a command variant,
but it does not stop a determined agent from routing around the engine. A hard boundary
only exists in hardened mode (G2): the engine + write token run under a separate OS user,
with preconditions checked outside the agent's reach.

### 4.2 Where does Git stand once CI is no longer the gatekeeper

Git **is still the source of truth**, but its role changes from *approval pipeline* to
*evidence ledger*: `sagctl document publish` rejects an uncommitted file (checks that
`git status --porcelain` is clean for that file) unless `--unreviewed` is passed, and
records the commit SHA in the lock/audit. The mandatory in-session sequence:

```text
draft the doc → commit → present it for user approval → publish → verify
```

MR-based review still works for a team that has that process (the in-session approval
happens at publish time, after the merge); CI, if it exists, is only an **optional
hardening layer** (running `sagctl sync` as a drift-catching guard), not the backbone of
the design.

### 4.3 The agent's knowledge awareness — a self-assessment rubric and routing

**This awareness is injected into the agent right from the plugin, as part of its normal
workflow** — the `sag-publish` skill (always loaded) imposes an obligation: *every time
the agent CREATES or EDITS an artifact that could be durable knowledge (a requirement,
ADR, design doc, research, runbook...), it must run a publish judgment right then and
there — not waiting to be prompted, not waiting until the end of the session*.
**`[FIXED]`** It does not match against `manifest.rules` (this field doesn't exist — the
final model doesn't classify by path/file-type before judging, see the note in §4.1) —
the agent identifies which files deserve assessment based on CONTENT, not on whether the
path matches some pre-configured list. Triggering moments for the judgment:

- Right after finishing creating/editing a `.md` file in a repo that has a
  `.sag-sync.json` manifest (e.g. just finished writing
  `docs/requirements/req-checkout.md` ⇒ judge it right away — the `PostToolUse` hook
  reminds the agent if it forgets).
- At the end of a unit of work that produces a **durable decision/contract/process** (an
  ADR is finalized, an API contract changes, a runbook is confirmed correct, a
  postmortem is done, research is accepted).
- The user says a finalizing statement ("lock in this approach", "this is the final
  decision").
- Discovering that an existing SAG document is now out of sync with reality (judge the
  corrected version).

**A self-assessment rubric** — the judgment isn't a feeling, it's a structured
assessment the agent must produce, which the engine writes into the audit log +
frontmatter. **`[FIXED — see SPEC.md §S5]`** The example below (the original draft) had
`canonical`/`secret_free` self-declared by the model — the final model DROPS these two
fields from the assessment: "is it committed" and "is it secret-free" are the
deterministic floor's job (`gate.py`), not the model's judgment — don't let the model
"declare on the machine's behalf". There is also NO `doc_type` — the final model doesn't
classify by document type (see the note at the end of §4.3). The real schema (the agent
must fill this in — the engine fills in `initiator`, `trigger`, `agent`, `key`,
`criteria_available`, `schema_version`, `assessed_at` itself):

```json
{
  "verdict":      "knowledge",
  "durable":      {"pass": true,  "why": "API contract, referenced across multiple sprints"},
  "audience":     {"pass": true,  "why": "needed by both developers, QA, and delivery"},
  "retrieval_fit":{"pass": true,  "why": "complete propositions, named entities"},
  "confidence":   0.86,
  "rationale":    "The user confirmed this in the session, the content is stable",
  "criteria_ack": ["c1"]
}
```

**Routing — the agent's judgment decides the path:**

```text
judged "is knowledge" ∧ confidence ≥ min_confidence → commit → sag_publish AUTOMATICALLY
judged "is knowledge" ∧ confidence < threshold       → improve the doc, or propose/queue it
judged "not knowledge"                               → don't publish (Honcho if worth remembering)
the user's criteria touch this content               → follow that criterion (including "ask first")
the user gives a direct order (file/folder/glob)      → carry it out immediately, no assessment needed
```

The agent has **real judgment authority** and an **automatic execution path** with no
human needed; it also has **awareness of its own limits** — when unsure, it proposes
rather than gambles, and every judgment leaves a record for post-hoc review.

**Long-lived authorization goes through the manifest, not through chat**: when the user
says "from now on don't include X" or "auto-publish this type from now on", the agent
doesn't treat the chat message as permanent authorization — it proposes editing
`.sag-sync.json` (`sagctl criteria-add <id> "<text>"` for a new judgment criterion, or
editing `deny_paths`/`ask_paths` for a deterministic rule). Authorization becomes a Git
artifact: reviewable, revocable, with a history. **`[FIXED]`** The original draft used
the concept of `manifest.rules`/`gate: self` keyed by document TYPE (`doc_type`) — the
final model **drops the type-based gate concept entirely**: there is no rigid
classification table, the agent judges EACH piece of content on its own using the 5
criteria in §3.1 + `criteria` (not a fixed gate configuration by document type). See SPEC
§S1 — only `criteria` (natural language) and `deny_paths`/`ask_paths` (deterministic
rules) remain; there is no `rules[].gate` or `autonomy` field.

**Post-hoc review is automation's safety net**: every document published via the `auto`
route gets `sag_route: auto` written into its frontmatter (not `sag_gate: self` as in the
original draft); `sag-maintain` (or a reviewer agent) periodically reviews these — a
poor-quality or misplaced document gets proposed for unpublishing and counted in the
statistics; a high post-hoc-review failure rate by agent×route is a signal to lower
`min_confidence` or narrow `include`. Automatic first, checked after — instead of gating
everything up front.

Anti-triggers (never judge for publishing): mid-task intermediate conclusions, debug
notes, uncommitted content, anything section 3.2 already assigned to
Honcho/GitLab/nowhere-at-all.

### 4.4 Multiple concurrent agents — convergence instead of locking

With no CI acting as a serialization point, multiple sessions (a dev's Claude Code,
various Hermes profiles, Codex) can publish in parallel. The design chooses **natural
convergence** instead of a distributed lock:

- **A single-file publish needs no lock file**: the algorithm is *list documents by
  filename in the source → delete the duplicate → upload → wait for ready*. Idempotent
  by construction; SAG itself is the source of truth for "what currently exists", the
  lock file is only a cache to speed up sync batches and a place to store the commit SHA.
- The worst-case race (two agents publishing the same path at once) creates a document
  with a duplicate filename — `sag-maintain` periodically dedupes ⇒ the system
  **self-heals**, no coordination needed beforehand. **`[FIXED]`** The tie-break **does
  not use `created_at`** as in the original draft (REVIEW-OPUS F13: `created_at` is the
  moment the API was called, not the moment the knowledge was formed — a race between an
  agent on a newer commit and an agent on a stale branch could let the OLD version win,
  silently, permanently). The real tie-break uses **Git ancestry** (`git cat-file -e` →
  `merge-base --is-ancestor` → `rev-list --count` if both are ancestors → if UNKNOWN,
  delete NOTHING, report to a human) — see SPEC §S10.
- Batch-sync permission is only granted to one role (the orchestrator) via the permission
  config (the T2 table) — a single writer by configuration, not by a verbal convention.

### 4.5 So where is manual actually still necessary? — 5 situations

1. **Bootstrap / backfill**: loading the initial corpus, or rebuilding SAG from Git after
   an incident — a human types `/sag-sync-project`, always viewing the plan with
   `--dry-run` first.
2. **A hotfix during an incident**: a runbook is needed DURING an incident —
   `sag_publish_unreviewed` (MCP) or `sagctl publish --unreviewed` (CLI), **mandatory
   reconcile**: commit + get it properly approved right afterward. **`[FIXED]`** The
   original draft said "the title automatically gets `[UNREVIEWED]` prepended" and
   "delete-first by filename" when the approved version replaces the hotfix version —
   WRONG: renaming the filename means dedupe-by-key CANNOT find the old hotfix version
   (two different keys), leaving both versions existing at once — exactly the worst-case
   scenario for an incident runbook. The real behavior: **keep the SAME key**, only
   change `sag_status: unreviewed` in the provenance — see SPEC §S8.
3. **Remediation**: `failed`/orphaned/duplicate documents — the `sag-maintain` skill,
   triggered by a human or the tool's schedule (section 5.3).
4. **Prune**: removing knowledge that's been removed from Git — always manual + `--yes`;
   no tool is ever allowed to auto-prune.
5. **Preview**: seeing how a document will be chunked/extracted before approving it —
   publish into a separate sandbox source, look at it, then delete it.

### 4.6 A sample cycle (closed-loop, in-session) **`[FIXED — the old cycle required
user approval every single time, contradicting §4.1's "automatic, no asking". The
correct cycle:]`**

```text
The agent is working, forms a durable conclusion (e.g., an ADR is finalized)
  → writes docs/adr/adr-0013.md per the standard in section 3.3 → commits it
  → self-assesses (the §4.3 rubric): confident enough, meets the floor (committed/secret/cost cap)
  → calls sag_publish (allow, does NOT ask the user) → the engine: dedupes by key →
    replaces if a duplicate exists → uploads → returns immediately (non-blocking)
  → the agent verifies with grep (not search — it can false-negative on an
    unfamiliar marker/string, confirmed via selftest S4/S7), reports the citation path back to the user
  → (a side branch: if not confident enough / fails the floor → goes into the queue or
    sag_publish_unreviewed — ONLY THEN does it need to ask/be approved)
  → every agent reads it via the MCP funnel, citing by path
  → whichever agent discovers a document has drifted from reality → does NOT fix SAG itself —
    drafts a corrected version + proposes approval → the loop repeats
```

### 4.7 Execution mapping — where every concept maps to a real mechanism

No concept in section 4 is allowed to exist only as prose. The mandatory mapping table:

| Concept | The concrete real mechanism |
|---|---|
| "Awareness is injected, triggered when creating/editing a document" | **Claude Code:** a `PostToolUse` hook on `Write\|Edit` (shipped in the plugin's `hooks/`) — a deterministic script checks the just-written file: markdown + has frontmatter/a heading ⇒ injects a system message *"just created/edited a document — run the publish judgment (sag-publish skill)"*. This is a machine-enforced trigger, not dependent on the model remembering. Plus: the `sag-publish` skill's description (always shown in the skill index) states the trigger condition. **Hermes:** the profile's system prompt (adapter config) + the skill description. **Codex:** the AGENTS.md block (adapter emit). |
| "A mandatory self-assessment rubric, not a feeling" | **The `sag_publish` tool's JSON Schema**: the `assessment` parameter is a mandatory object with typed fields (`verdict`, `durable{pass,why}`, `audience`, `retrieval_fit`, `confidence: number`, `rationale`, `criteria_ack[]`) — **no `doc_type`** (the original draft was wrong, see the note in §4.3). Missing/wrong-typed ⇒ the tool call fails validation right at the MCP layer — the model is forced to produce a full assessment before it can even call the tool. CLI equivalent: `--assessment <json>`. |
| "The judgment of 'is this knowledge'" | Belongs to the model, during its reasoning turn — the plugin cannot do this for it, it can only guarantee it HAPPENS (the hook reminds) and LEAVES A TRACE (the assessment is mandatory in the tool call, recorded in the audit log + frontmatter). |
| "Threshold + routing" | Code inside the engine (`routing.py`): reads `min_confidence`, `deny_paths`, `ask_paths`, `criteria` from the manifest (**no `autonomy` field** — the original draft was wrong, it was dropped from the schema); compares `verdict` first, then `confidence`; the resulting path (auto / queue / reject) is the pure function `routing.decide()`, not a piece of text instruction. |
| "Automatic, no asking" (T1a) | A real config file: `adapters/claude-code/settings-rules.json` (`allow mcp__sagw__sag_publish`), `adapters/codex/config.toml` (auto-approval for the `sagw` server's `sag_publish` tool), Hermes's per-profile `tools.include`. |
| "Ask every time" (T1b) | `ask mcp__sagw__sag_publish_unreviewed` in the same files above. |
| "Propose when unsure / when no human is in the session" | A `queue.jsonl` at `~/.sagctl/<hash source_id>/` — **NOT in the repo** (the original draft's `.sag/queue.jsonl` was wrong: if the queue lived in the repo, an agent with `Write` permission could approve its own queue entries — REVIEW-OPUS §2c). A human or reviewer reads it with `sagctl queue list`, decides with `sagctl queue approve\|reject <id>` (requires the `queue-review` op, not in the default op set) — approving makes the engine publish, and the audit log records two signatures (author + reviewer). |
| "Self-gate post-hoc review" | A real command, `sagctl maintain --review-self-gate`, run by the tool's scheduler (a Claude Code scheduled task / Hermes cron), producing a report + proposed unpublishes; fail-rate statistics are recorded in the audit log, readable via `sagctl doctor`. |
| "The user's own criteria" | A `criteria` array (natural language) in `.sag-sync.json`; a hook/skill loads it verbatim into context at agent-assessment time; the engine records the criteria version in the audit log. The user says "from now on don't include X" ⇒ the agent edits `criteria` + commits — authorization/revocation is a Git artifact, not something remembered in chat. |
| "The user's manual command" | **`[FIXED — a real security hole, see SPEC.md §S7]`** The original draft let the model set a `manual_by_user` flag itself in a `sag_publish` call — this is EXACTLY the most serious bypass hole the review round pointed out: a malicious document only needs to trick the agent into "declaring" that flag to skip the entire assessment. The real mechanism: **`sag_publish` (MCP) NEVER has a manual parameter** — the manual path ONLY goes through the `/sag-publish <path>` slash command (typed by a human) → the `UserPromptSubmit` hook mints a one-time token, bound to hash(args), 5-minute TTL → `sagctl publish <path> --manual-token <token>` (CLI, not an MCP tool) → the engine draws its own conclusion about `initiator`, the model cannot self-declare it. |
| "A deterministic floor for every gate" | Code inside the engine, running before every upload: a git-state check (`git status --porcelain`, `merge-base --is-ancestor` when require=merged) · a secret scan (regex+entropy, `gitleaks` if present) · a cost cap (counted in the audit log) · dedupe-by-key + the `response.filename == key` assertion. |

---

## 5. Behavioral rules for READING and maintenance

### 5.1 When an agent must query SAG (mandatory touchpoints in the system prompt/skill)

- **Before a design or architecture decision**: search for related ADRs/PRDs — avoid
  re-deciding something already finalized or contradicting a prior decision.
- **When starting a new task**: read the outline of related domain documents to load
  context.
- **When a claim needs to be cited**: any claim of "the project has decided X" must come
  with a citation from SAG, not be stated off the top of the head from session memory.
- **When handling an incident**: grep error codes/service names in old runbooks +
  postmortems.

### 5.2 Priority order when sources conflict

```text
Current Code/Git  >  SAG  >  Honcho  >  session memory
```

SAG loses to code because SAG is a lagging projection. When an agent discovers SAG
contradicts the code: **do not silently ignore it, do not silently overwrite it** — the
agent's obligation is to *report the discrepancy* (open an MR to fix the doc, or flag it
to the orchestrator). This is the knowledge base's self-correction mechanism.

### 5.3 Periodic maintenance (`sag-maintain`, run on a schedule or triggered manually)

- Scan for `failed` documents → reprocess (at most once) → still failing, report to a
  human.
- **`[FIXED — see SPEC.md §S10]`** Cross-check SAG against **the canonical branch's Git
  HEAD** (NOT the lock file as in the original draft): an "orphan" = a document whose
  corresponding path no longer exists at HEAD → propose deletion. Reason for the change:
  a single-file publish (the main path, T1a) doesn't write to a lock — if orphans were
  defined against the lock, maintain would propose deleting almost EVERY document that
  was just auto-published (REVIEW-OPUS F14/F28). Plus "stale-branch": a document
  published with `require: committed` that has never reached the canonical branch after
  N days → propose unpublishing.
- Report documents with `status: superseded` past their retention period (e.g. 6 months)
  → propose pruning.
- Aggregate `token_usage` to track ingest cost.
- **Automated post-hoc review (self-review)**: scan recently published `sag_route: auto`
  documents (not `sag_gate: self` — that field no longer exists) — does it match the
  §3.3 standard? Does the assessment match the content? If poor ⇒ propose unpublishing;
  track fail rates by agent/tier to adjust `min_confidence` or revoke `gate: self`.

### 5.4 Writing to Honcho after reading SAG

Allowed and encouraged: saving a **short conclusion + citation path** (e.g., *"ADR-0012
finalized versioned JSON — docs/adr/adr-0012.md"*). Forbidden: copying an entire SAG
chunk verbatim into Honcho (creates a copy that drifts out of sync, losing version
control).

---

## 6. How to split sources

- **Default: one source per project** — combine PRD/ADR/design/runbook into a shared
  source so event-entity joins work across document types (P8): a question like *"which
  decision led to endpoint X and which runbook is related"* needs the documents to be
  within the same query scope.
- Split into separate sources only when: (1) a large raw research corpus (noisy,
  different lifecycle), (2) a sandbox preview (§4.5 item 5), (3) documents sensitive
  enough that only one group of agents should see them — remembering that scoping by
  `source_id` in the MCP URL is **a convenience isolation, not security** (P7, and now
  there's real evidence for it — selftest S11: different identities still see all the
  same sources, there is no isolation at the SAG layer).
- Every canonical source maps to exactly one `.sag-sync.json` manifest in exactly one
  Git repo. **`[FIXED]`** "A 1-1-1 relationship so there's never more than one write
  path" — this sentence contradicts itself against §4.4 (single-file publish + batch
  sync are TWO different write paths into the same source, which is exactly why §4.4
  needs to discuss races and convergence). More accurately: **one source = one
  manifest**, but a source CAN have multiple concurrent writers (many agents doing
  single-file publishes + a periodic batch sync) — safety doesn't come from "only one
  write path" but from dedupe-by-key + the ancestry tie-break when a race occurs (SPEC
  §S10).

---

## 7. Feedback into the technical design (a supplement to DESIGN.md)

1. `sagctl document publish` adds an `--unreviewed` flag (the hotfix situation, §4.5
   item 2): **`[FIXED]`** keeps the SAME key (does not rename the filename — see §4.5
   item 2, fixed), only changes `sag_status` in the provenance + records a separate audit
   entry — making the exception *visible* instead of forbidding it and having it get
   worked around anyway.
2. The `sag-publish` skill teaches the correct in-session sequence: *draft the doc to
   spec → commit → self-assess → publish (non-blocking, `--wait` is NOT the default) →
   verify with `grep` (not search) → report the citation path*. `sagctl` enforces the
   commit step (rejects a dirty file unless `--unreviewed` is passed).
3. The publish algorithm changed: **dedupe by filename via `list documents` before
   uploading** (SAG is the inventory source of truth; the lock file is downgraded to a
   cache for batch sync + a place to store the commit SHA) — a single-file publish
   doesn't depend on a lock file shared across machines.
4. Packaged as **core + 3 adapters**: the core (`sagctl` + the shared skill content);
   the Claude Code adapter (the plugin manifest, `.mcp.json`, an **allow/ask/deny
   permission-rules snippet** for settings.json); the Hermes adapter (a `config.yaml`
   snippet: `mcp_servers` + `skills.external_dirs` + per-profile command permissions);
   the Codex adapter (a `config.toml` snippet: `[mcp_servers]` + approval policy, an
   AGENTS.md block containing the SAG read/write rules). The permission snippets are a
   deliverable on par with the code.
5. Added to the phase-1 scope: document templates (`examples/doc-templates/`: ADR,
   runbook, research report with standard frontmatter) — since retrieval quality depends
   on how something is written (section 3.3), a template is cheaper than trying to teach
   it purely through the skill's prose.
6. The manifest gets a `sandbox_source_id` field (optional) to support previewing.
7. `sag-maintain` runs on a schedule **using the agent tool's own scheduler** (a Claude
   Code scheduled task / Hermes cron; Codex doesn't take this role) — assigned to the
   orchestrator, suggested frequency: weekly, also handling the dedupe work from section
   4.4.
