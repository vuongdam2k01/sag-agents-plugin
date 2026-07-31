---
description: Manually publish a file/folder/glob to the SAG knowledge base, skipping the self-assessment step (you — the user — have already made the call).
---

The user just requested a manual publish: `$ARGUMENTS`

The plugin's `UserPromptSubmit` hook detected this `/sag-publish` command and (if
the syntax matches correctly) inserted a one-time-use token into the context just
above, in the form:

```
[sagctl manual-publish] token=<TOKEN> args=<ARGS> — use: sagctl publish "<ARGS>" --manual-token <TOKEN>
```

Your job:

1. Find that `[sagctl manual-publish]` line in the context. If it is NOT there
   (the hook didn't match — e.g. the user typed the command via another path),
   tell the user that the manual path requires calling the `/sag-publish <path>`
   slash command directly, and stop.
2. If it is there, run the exact suggested command via Bash:
   ```bash
   sagctl publish "$ARGUMENTS" --manual-token <TOKEN>
   ```
   If `$ARGUMENTS` is a glob/folder, iterate over each matching file and call
   publish for each one (each file needs its own token — if there is only one
   token for a whole glob, use a manual `sagctl sync`-style call instead of
   looping `publish`; ask the user if the scope is unclear).
3. Do NOT use the MCP `sag_publish` tool for this command — that tool always
   requires an assessment and has no way to accept a manual token. The manual
   path exists only in the CLI.
4. Report the result back (`status`, `document_id`, or the error reason) to the
   user.

The token can only be used once and expires after a few minutes — if the
command fails because the token is invalid, ask the user to run `/sag-publish`
again to mint a new token; don't retry multiple times on your own.
