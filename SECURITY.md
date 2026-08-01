# Security Policy

## What this project's threat model actually is

Read this before filing a report — it determines whether a finding is a vulnerability or a
documented limitation.

`sag-agents-plugin` at its shipping configuration (**G1 standard** in
[docs/SPEC.md](docs/SPEC.md) §S0) is a **guardrail against accidents and shallow prompt
injection. It is not a security boundary.** The agent process and the `sagctl` engine run
as the **same OS user**. Anyone who can execute arbitrary code as that user can read
`~/.sagctl/credentials.json` and call SAG directly, with or without this plugin.

A hardened configuration (**G2**: separate OS user, engine as a privileged service) is a
documented future direction, not what ships today.

### In scope

Findings that let an agent or an untrusted input do something the engine is supposed to
prevent, *without* already having code execution as the user:

- Bypassing the deterministic floor (§S4): publishing despite `deny_paths`, despite a
  failing secret scan, despite the `require` git-state gate, or past the cost cap.
- Defeating the manual-token gate (§S7): reusing a consumed token, using a token minted
  for path A to publish path B, minting a token from a prompt that does not match the
  exact `/sag-publish` form, or extending the 5-minute TTL.
- Forging `initiator` — getting the engine to record `user-manual` for a model-initiated
  publish.
- Making `sag_publish_unreviewed` bypass the secret scan or `deny_paths` (it is only ever
  allowed to bypass `require`).
- Credential exposure: the write token reaching the agent's environment, a command line,
  a log, the audit JSONL, or the repository.
- Path traversal or key-encoding tricks that write outside the intended source, or that
  make `response.filename == key` assert falsely.
- Prompt injection **in document content pulled from SAG** that causes the engine to take
  a write action.
- Secret-scanner evasion for a class of credential the scanner claims to detect.

### Out of scope

- Anything requiring arbitrary code execution as the agent's OS user — that is above the
  G1 boundary by design.
- A model lying in its self-assessment (`verdict`, `confidence`, `criteria_ack`). This is
  expected and is precisely why the deterministic floor exists and why the model is never
  allowed to assert `canonical` or `secret_free`. A finding is only in scope if the lie
  gets past the **floor**.
- Vulnerabilities in SAG itself — report those to
  [Zleap-AI/SAG](https://github.com/Zleap-AI/SAG).
- The two documented SAG limitations below.

### Known and accepted limitations

These are empirical findings from `sagctl selftest` against a real instance, recorded in
[docs/SPEC.md](docs/SPEC.md). They are not bugs in this plugin, and reports about them
will be closed as documented:

- **No isolation between SAG identities** (selftest S11) and **no server-side attribution**
  (S13). A second token buys neither isolation nor attribution, so the whole agent fleet
  shares one read/write pair by design. Attribution exists only in the local audit log,
  which is unauthenticated and adequate for internal forensics — not for stopping an agent
  that deliberately lies about `agent`/`initiator`.
- **SAG's JWT has a fixed 7-day lifetime with no revoke, logout, or refresh endpoint**
  (S12). A leaked token cannot be revoked, only waited out. Mitigation is operational:
  store the token in exactly one place (`~/.sagctl/credentials.json`, `0600`) and rotate
  by re-login on a cycle shorter than 7 days in sensitive environments.

## Reporting a vulnerability

**Please do not open a public issue.**

Report privately via either:

- GitHub's [private vulnerability reporting](https://github.com/vuongdam2k01/sag-agents-plugin/security/advisories/new)
  (preferred), or
- email to **vuongdam2k01@gmail.com** with `[SECURITY]` in the subject.

Include:

- A description of the issue and which control it defeats (cite the spec section if you
  can — §S4, §S6, §S7, §S12).
- Reproduction steps, ideally as a failing test or a `--dry-run` transcript.
- Your assessment of impact.
- Plugin version / commit, Python version, OS.

**Redact tokens, hostnames, and document contents before sending.**

## What to expect

| Stage | Target |
|---|---|
| Acknowledgement of your report | within 3 business days |
| Initial assessment (in scope / out of scope, severity) | within 7 days |
| Fix or documented mitigation for a confirmed high-severity issue | within 30 days |

This is a small project maintained by one person — these are honest targets, not a
contractual SLA. You will be told if something is going to take longer.

Please give a reasonable window for a fix before public disclosure. Reporters are credited
in the release notes unless they ask not to be.

## Operational hardening checklist

Not vulnerabilities, but worth doing if you run this against anything that matters:

- [ ] Read and write tokens are genuinely different tokens; only the read token is in the
      agent's environment.
- [ ] `~/.sagctl/credentials.json` is `0600` and on a filesystem the agent's other tools
      do not sync or back up.
- [ ] `deny_paths` covers every directory holding secrets, customer data, or pricing.
- [ ] `gitleaks` is installed on PATH so the scanner runs its full ruleset.
- [ ] `max_publishes_per_day` is set to something you would actually notice being hit.
- [ ] Token rotation happens on a cycle shorter than SAG's 7-day JWT lifetime.
- [ ] `sagctl doctor` and `sagctl maintain review-self-gate` are run on a schedule and
      someone reads the output.
