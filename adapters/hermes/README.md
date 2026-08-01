# Hermes Adapter

The configuration is **generated**, not copied from a static file here:

```bash
sagctl adapter-emit hermes --plugin-root /opt/agent-skills/sag-agents-plugin
```

Run it from inside the repo you are wiring up. `source_id` is read from that repo's
`.sag-sync.json`, so the emitted read MCP url is scoped to the project the agent
actually works in (`${SAG_URL}/mcp/?source_id=<id>`) and the id is never typed into
this config by hand — see [SPEC amendment A2](../../docs/SPEC.md).

A static `config.example.yaml` used to live here. It was removed once the generator
covered the same ground: two sources for one piece of configuration is exactly the
drift the generator exists to prevent (REVIEW-OPUS F3).

The output covers:

- `mcp_servers.sag` — read, allow-all (the server has only 8 read tools), scoped url.
- `mcp_servers.sagw` — write, no default `tools.include`, so a profile that declares
  nothing gets no write permissions at all.
- `skills.external_dirs` — mount **read-only at the filesystem level**. Hermes'
  `skill_manage` tool can rewrite skills if the directory is writable
  (`docs/AGENT-BEHAVIOR.md` R6).
- Four example profiles (`product_researcher`, `developer`, `delivery_engineer`,
  `orchestrator`) showing the per-role `tools.include` split. Only `orchestrator`
  carries `SAGCTL_ALLOW_SYNC` / `SAGCTL_ALLOW_QUEUE_REVIEW`, and those ops are
  CLI-only (SPEC §S8) — granted by env, not by an MCP tool.

`config.yaml` is a merge target: the command prints the block rather than writing it,
so it cannot clobber a config that already holds unrelated settings.

Secrets (`SAG_URL`, `SAG_READ_TOKEN`, `SAGCTL_STATE_TOKEN`, `HERMES_PROFILE_NAME`)
belong in each profile's `.env`. The SAG **write** token appears nowhere in this
config — `sagw` reads it from `~/.sagctl/credentials.json` on the host running the
process (`sagctl login` once per host, SPEC §S12).
