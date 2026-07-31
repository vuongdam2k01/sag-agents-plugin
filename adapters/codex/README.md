# Codex Adapter

Codex has no directly compatible skill/plugin format — the configuration is
**generated** (not a static file copied by hand like Claude Code/Hermes) so it
can embed a version marker, letting `sagctl doctor` detect when Codex is
running a config block that has fallen out of date with the plugin.

```bash
sagctl adapter-emit codex --out /tmp/sag-codex-block.txt
```

The command prints two parts, separated by `---`:

1. The block to insert into Codex's `config.toml` — `[mcp_servers.sag]` (read,
   auto-approve) and `[mcp_servers.sagw]` (write, on-request).
2. The block to insert into the repo's `AGENTS.md` — describing the read
   funnel, the self-assessment obligation before publishing, and the
   anti-prompt-injection rules. Equivalent to the content of the
   `sag-publish`/`sag-knowledge` skill on the Claude Code side, rewritten as
   AGENTS.md content since Codex does not load SKILL.md.

Both blocks are wrapped in a `<!-- sag-agents-plugin v<version> BEGIN/END -->`
marker — when upgrading the plugin, rerun the command above and replace the
old block with the new one (no automatic merging — Codex has no
external_dirs-style mechanism like Hermes does).

Codex only receives the read + reviewed-publish role (T0/T1 per
docs/SPEC.md §S8) — no batch sync, no source-admin. Those operations are never
exposed via MCP to any tool, so there is nothing extra to grant to Codex even
if desired.
