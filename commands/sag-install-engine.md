---
description: Install the sagctl engine from this plugin's own copy — no git clone, no hunting for paths.
---

Install the `sagctl` engine that this plugin's write path depends on.

`claude plugin install` already downloaded the engine as part of the plugin; it just is
not on PATH yet. Cloning the repo a second time only creates a copy that
`claude plugin update` does not manage.

Run exactly this, and report the output verbatim — including the PATH instructions,
which the script deliberately prints rather than applying itself:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/install-shim.py"
```

If that fails because the file is not executable, fall back to invoking it with the
interpreter that is actually present — do not assume `python` exists, Ubuntu ships only
`python3`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install-shim.py" || python "${CLAUDE_PLUGIN_ROOT}/scripts/install-shim.py"
```

Then:

1. Tell the user to run the `setx` / `export` line the script printed, and to open a new
   terminal. The script does not edit PATH on its own — that is an account-level change
   the user makes and confirms.
2. If the script printed a **WARNING about a version-pinned plugin cache**, surface it
   prominently. It means the shim would keep running the old engine after
   `claude plugin update`, without any error. Re-run from the marketplace checkout it
   points at.
3. Verify, in a new shell:

```bash
sagctl version
```

That prints the engine path and the interpreter baked into the shim. If `sagctl` is not
found, PATH has not been applied yet — the shim exists, the shell just cannot see it.

Once `sagctl version` works, everything else in the plugin works: the `sagw` MCP server
and all four hooks invoke `sagctl` rather than naming an interpreter, so there is exactly
one thing that has to be on PATH, not three.

Next step after this is `/sag-setup`.
