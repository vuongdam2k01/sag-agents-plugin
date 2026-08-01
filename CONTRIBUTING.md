# Contributing to sag-agents-plugin

Thanks for taking the time to contribute. This document covers what you need to know
before opening an issue or a pull request.

## Two rules that are not negotiable

1. **No change may require modifying SAG's source code.** Everything goes through SAG's
   public REST API and its built-in MCP server. If a feature seems to need a SAG patch,
   the feature needs a different design — open an issue and let's find it together.
2. **No change may add a runtime dependency outside the Python standard library.**
   `sagctl` is stdlib-only on purpose, so it vendors cleanly into any container or agent
   host without a `pip install`. Test-only helpers must also be stdlib (`unittest`, not
   `pytest`).

## The spec is canonical

[docs/SPEC.md](docs/SPEC.md) is the locked implementation contract. Every module in
`scripts/sagctl/` references its section numbers (S1–S12).

- A PR that **implements** the spec is normal work.
- A PR that **contradicts** the spec needs a spec change first — open an issue describing
  what the spec says, why it is wrong, and what it should say instead. The spec is changed
  by an explicit decision, not by an engineer's judgment call inside a PR.
- If you find that reality (SAG's actual behavior) disagrees with the spec, that is a
  **selftest finding** — add or update a `selftest` case that demonstrates it, and cite
  the case in your issue.

## Development setup

```bash
git clone https://github.com/vuongdam2k01/sag-agents-plugin.git
cd sag-agents-plugin
python --version          # must be 3.11 or newer
python -m unittest discover -s tests -v
```

No virtualenv, no install step, no dependencies. That is the point.

For work that touches the network layer you will also want a real SAG instance:

```bash
python scripts/install-shim.py
sagctl login --url http://<sag-host>:8000 --name <name>
sagctl selftest --url http://<sag-host>:8000 --token <token>
```

> ⚠️ `selftest` uploads real documents and consumes real LLM quota on the SAG host's
> provider account. Case S6 alone uploads 120 documents. Use a throwaway source, and lower
> `n` in `case_s6_pagination` if you are iterating.

## Testing expectations

| Change | Required tests |
|---|---|
| A pure function (key encoding, globbing, routing, validation, scanning, provenance) | A unit test in `tests/`. These must run **offline** — no network, no SAG instance. |
| REST client behavior (pagination, error handling, retries) | A unit test with a mocked transport. See `tests/test_restclient_network_errors.py` for the pattern. |
| Anything that depends on SAG's real behavior | A `selftest` case in `scripts/sagctl/selftest.py`, with the observed result recorded in `docs/SPEC.md`. |
| A safety-floor rule (S4) or routing rule (S6) | A unit test proving the rule **rejects** as well as one proving it accepts. Bypass tests matter more than happy-path tests here. |

Run the full suite before pushing:

```bash
python -m unittest discover -s tests -v
```

CI runs the same suite on Ubuntu and Windows across Python 3.11, 3.12, and 3.13. Path
handling and encoding differ between platforms — if you touch either, check both.

## Code style

The codebase follows a few local conventions; match them rather than importing your own:

- `from __future__ import annotations` at the top of every module.
- Type hints on public functions. No runtime type-checking library.
- Errors carry a machine-readable code (`PublishError(code=...)`, e.g.
  `KEY_FORMAT_DRIFT`) so callers can branch on the cause, not on message text.
- Comments explain **why**, and reference the spec section (`# S4: floor runs before
  every upload`) when they encode a contract.
- Windows compatibility is not optional: use `pathlib`, POSIX-normalize repo-relative
  paths, and never assume UTF-8 is the console default.
- Vietnamese and English both appear in docs; keep code, identifiers, and log messages in
  English.

## Security-sensitive areas

Extra care is expected in these files — changes here get a closer review:

- `scripts/sagctl/secrets_scan.py` — weakening a detector needs a stated reason.
- `scripts/sagctl/manual.py` — token binding, single use, TTL. A regression here silently
  removes the only gate on manual mode.
- `scripts/sagctl/config.py` — credential storage, file permissions, repo-leak detection.
- `scripts/sagctl/routing.py` — the `deny_paths` > `ask_paths` > … precedence order.
- `hooks/user_prompt_submit_mint_token.py` — the exact-match rule that decides when a
  token is minted at all.

Never add a code path that accepts a token as a command-line argument, and never widen
what `sag_publish_unreviewed` bypasses.

Please do not open a public issue for a vulnerability — see [SECURITY.md](SECURITY.md).

## Pull requests

1. Branch from `main`.
2. Keep the change focused. A behavior change plus a refactor in one PR is two PRs.
3. Update the relevant docs in the same PR — `docs/SPEC.md` for contract changes, the
   `README.md` **and** `README.vi.md` for user-facing changes, `CHANGELOG.md` under
   `[Unreleased]`.
4. Make sure `python -m unittest discover -s tests` passes.
5. Fill in the PR template: what changed, why, which spec section it touches, how it was
   tested (and whether against a real SAG instance).

## Reporting bugs

Open an issue with:

- What you expected, what happened, and the exact command or tool call.
- `sagctl --version`, your Python version, and your OS.
- Whether it reproduces with `--dry-run`.
- Relevant output — **redact tokens, URLs, and document contents first.**

If the bug involves SAG's behavior rather than the plugin's, please include the matching
`sagctl selftest --case <ID>` output; that usually settles which side the problem is on.

## Suggesting features

Say what problem you are solving and how you would know it is solved. A feature that
requires a SAG patch, a pip dependency, or a spec change will be discussed on those terms
first — that is not a rejection, it just means the design conversation comes before the
code.

## Code of Conduct

By participating you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).
