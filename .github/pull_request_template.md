## What changed

<!-- One or two sentences. What does this PR do? -->

## Why

<!-- The problem being solved. Link the issue if there is one: Fixes #123 -->

## Spec

<!-- Which docs/SPEC.md section does this touch (S1–S12)? Write "none" if it touches none. -->

- Section:
- [ ] This change **implements** the spec as written.
- [ ] This change **modifies** the spec — the spec change was agreed in an issue first, and `docs/SPEC.md` is updated in this PR.

## How it was tested

- [ ] `python -m unittest discover -s tests` passes locally
- [ ] New or updated unit tests cover the change (offline, no SAG instance needed)
- [ ] Tested against a real SAG instance — which cases: <!-- e.g. sagctl selftest --case S1 -->
- [ ] Not applicable, because: <!-- docs-only, etc. -->

## Non-negotiables

- [ ] Requires **no** modification to SAG's source code
- [ ] Adds **no** runtime dependency outside the Python standard library
- [ ] No token is ever accepted as a command-line argument, logged, or written into the repo
- [ ] `sag_publish_unreviewed` still bypasses **only** the `require` gate — never the secret scan or `deny_paths`

## Docs

- [ ] `README.md` updated
- [ ] `README.vi.md` updated to match
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] No doc change needed

## Anything a reviewer should look at closely

<!-- Especially if you touched secrets_scan.py, manual.py, config.py, routing.py, or the
     UserPromptSubmit hook — those are the files where a regression silently removes a gate. -->
