# Claude Code Adapter

Generate the config from inside the repo you are wiring up:

```bash
sagctl adapter-emit claude-code --write .
```

That writes `.mcp.json` (wholly ours, so it is written directly) and prints the
`.claude/settings.json` permission block for you to merge — settings.json normally
holds unrelated editor configuration and is never clobbered without `--force`.

`source_id` is read from the repo's `.sag-sync.json`, so the emitted read MCP url is
scoped to the project the agent works in (`${SAG_URL}/mcp/?source_id=<id>`) and the id
is never typed into this config by hand — see [SPEC amendment A2](../../docs/SPEC.md).

## `settings-rules.json`

This file is the **source** the generator reads for the permission block, not a
snippet to copy by hand. Edit it here and the change flows into every generated
config; that is why there is no second copy inside `adapters_emit.py`.

Permissions are keyed by **MCP tool identifier** rather than a Bash string pattern, so
they cannot be bypassed with a command variant (SPEC §S8, REVIEW-OPUS F2). `Bash` is
allowed only for the explicit manual path (`/sag-publish`) and denied for every
dangerous operation.

Note that `deny` beats `allow` in Claude Code, which is why `Bash(sagctl publish*)` is
set to **ask** rather than deny — denying it would break the slash command. The real
gate for manual mode is the engine-side single-use token (SPEC §S7), not the
permission list.
