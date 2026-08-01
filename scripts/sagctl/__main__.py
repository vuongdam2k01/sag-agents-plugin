"""CLI entry point. `python -m sagctl <command>` or via the `sagctl` shim on PATH.

Every write command (publish, unpublish, reprocess, sync, source, queue approve, api)
reads the write token from ~/.sagctl/credentials.json (config.py) — NEVER accepts
the token via a command-line argument (it would leak into shell history / process list).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Force UTF-8 on stdout/stderr (Windows' default console is cp1252/cp437, which
# cannot encode Vietnamese) — applied when running `python -m sagctl` directly.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from . import __version__
from . import audit, config, doctor, evalcmd, gitutil, keys
from . import manifest as manifest_mod
from . import maintain, manual
from . import publish as publish_mod
from . import queue as queue_mod
from . import routing, secrets_scan, selftest, sync
from .restclient import SagApiError, SagClient


def _agent_name() -> str:
    return os.environ.get("SAGCTL_AGENT", "cli-user")


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _read_assessment_arg(raw: str | None, from_file: str | None) -> dict | None:
    if from_file:
        return json.loads(Path(from_file).read_text(encoding="utf-8"))
    if raw:
        return json.loads(raw)
    return None


# -- subcommands --------------------------------------------------------------


def cmd_login(args):
    client = SagClient(base_url=args.url, token="")
    resp = client.login(name=args.name, email=args.email, password=args.password)
    token = resp.get("access_token") or resp.get("token")
    if not token:
        print("Error: login response has no access_token/token", file=sys.stderr)
        return 1
    config.Credentials(args.profile).set(url=args.url, write_token=token)
    print(f"Saved credentials for profile '{args.profile}' at {config.credentials_path()}")
    return 0


def _client(profile: str) -> SagClient:
    cred = config.Credentials(profile).require()
    return SagClient(base_url=cred["url"], token=cred["write_token"])


def cmd_whoami(args):
    _print_json(_client(args.profile).whoami())
    return 0


def cmd_health(args):
    _print_json(_client(args.profile).health())
    return 0


def cmd_publish(args):
    assessment = _read_assessment_arg(args.assessment, args.assessment_file)
    try:
        result = publish_mod.publish_one(
            Path(args.path),
            assessment=assessment,
            manual_token=args.manual_token,
            manual_args_str=args.path if args.manual_token else None,
            agent=args.agent or _agent_name(),
            trigger=args.trigger,
            wait=args.wait,
            wait_timeout=args.wait_timeout,
            dry_run=args.dry_run,
            profile=args.profile,
        )
    except publish_mod.PublishError as e:
        print(f"PUBLISH_ERROR {e.code}: {e}", file=sys.stderr)
        return 1
    _print_json(result.__dict__)
    if result.status == "failed_or_empty":
        return 2
    return 0


def cmd_publish_status(args):
    doc = publish_mod.publish_status(args.source_id, args.key, profile=args.profile)
    if doc is None:
        print("document not found", file=sys.stderr)
        return 1
    _print_json(doc)
    return 0


def cmd_unpublish(args):
    ok = publish_mod.unpublish_one(args.source_id, args.key, reason=args.reason, agent=args.agent or _agent_name(), profile=args.profile)
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


def cmd_reprocess(args):
    job = publish_mod.reprocess_one(args.source_id, args.key, agent=args.agent or _agent_name(), profile=args.profile)
    _print_json(job)
    return 0


def cmd_source_list(args):
    _print_json(_client(args.profile).list_sources())
    return 0


def cmd_source_get(args):
    _print_json(_client(args.profile).get_source(args.source_id))
    return 0


def cmd_source_create(args):
    _print_json(_client(args.profile).create_source(args.name))
    return 0


def cmd_source_update(args):
    fields = json.loads(args.fields)
    _print_json(_client(args.profile).update_source(args.source_id, **fields))
    return 0


def cmd_source_delete(args):
    if not args.yes:
        print("--yes is required to delete a source (destructive operation)", file=sys.stderr)
        return 1
    _client(args.profile).delete_source(args.source_id)
    print("OK")
    return 0


def cmd_document_list(args):
    docs, truncated = _client(args.profile).list_documents_all(args.source_id)
    if truncated:
        print("WARNING: list_documents shows signs of pagination/truncation (not yet confirmed by selftest S6)", file=sys.stderr)
    _print_json(docs)
    return 0


def cmd_queue_list(args):
    _print_json(queue_mod.list_pending(args.source_id))
    return 0


def cmd_queue_approve(args):
    if not os.environ.get("SAGCTL_ALLOW_QUEUE_REVIEW"):
        print("op 'queue-review' is not enabled — set SAGCTL_ALLOW_QUEUE_REVIEW=1 (reviewer/orchestrator only)", file=sys.stderr)
        return 1
    item = queue_mod.approve(args.source_id, args.queue_id, reviewer=args.reviewer or _agent_name(), wait=args.wait)
    _print_json(item)
    return 0


def cmd_queue_reject(args):
    if not os.environ.get("SAGCTL_ALLOW_QUEUE_REVIEW"):
        print("op 'queue-review' is not enabled — set SAGCTL_ALLOW_QUEUE_REVIEW=1 (reviewer/orchestrator only)", file=sys.stderr)
        return 1
    item = queue_mod.reject(args.source_id, args.queue_id, reviewer=args.reviewer or _agent_name(), reason=args.reason)
    _print_json(item)
    return 0


def cmd_sync(args):
    if not os.environ.get("SAGCTL_ALLOW_SYNC"):
        print("op 'sync' is not enabled — set SAGCTL_ALLOW_SYNC=1 (orchestrator/scheduled only)", file=sys.stderr)
        return 1
    manifest_path = Path(args.manifest)
    result = sync.run(manifest_path, dry_run=not args.yes, agent=args.agent or _agent_name(), wait=args.wait)
    _print_json(result.__dict__)
    if result.errors:
        return 1
    return 0


def cmd_maintain_dedupe(args):
    m = manifest_mod.load(Path(args.manifest))
    client = _client(args.profile)
    outcomes = maintain.dedupe_source(client, m["source_id"], manifest_mod.repo_root(m), m["canonical_branch"])
    _print_json([o.__dict__ for o in outcomes])
    return 0


def cmd_maintain_orphans(args):
    m = manifest_mod.load(Path(args.manifest))
    client = _client(args.profile)
    orphans = maintain.find_orphans(client, m["source_id"], manifest_mod.repo_root(m), m["canonical_branch"])
    _print_json(orphans)
    return 0


def cmd_maintain_stale(args):
    m = manifest_mod.load(Path(args.manifest))
    client = _client(args.profile)
    stale = maintain.find_stale_branch(client, m["source_id"], manifest_mod.repo_root(m), m)
    _print_json(stale)
    return 0


def cmd_maintain_review_self_gate(args):
    report = maintain.review_self_gate(args.source_id, days=args.days)
    _print_json(report)
    return 0


def cmd_doctor(args):
    # Always reported: "is this host sharing state with the rest of the fleet?"
    # is a host-level question and must not require a --source-id to answer.
    out = {"state": doctor.state_report()}
    if args.manifest:
        out["unassessed_files"] = doctor.unassessed_files(Path(args.manifest))
    if args.source_id:
        out["health"] = doctor.health_report(args.source_id)
    _print_json(out)
    return 0


def cmd_eval(args):
    m = manifest_mod.load(Path(args.manifest)) if args.manifest else None
    source_id = args.source_id or (m and m["source_id"])
    client = _client(args.profile)
    cases = evalcmd.load_cases(Path(args.questions))
    results = evalcmd.run(client, source_id, cases)
    summary = evalcmd.summarize(results)
    _print_json({"summary": summary, "results": [r.__dict__ for r in results]})
    if args.save_baseline:
        path = evalcmd.save_baseline(source_id, summary, sag_version=args.sag_version, key_format=(m or {}).get("key_format", "unknown"))
        print(f"baseline saved at: {path}", file=sys.stderr)
    return 0


def cmd_selftest(args):
    client = SagClient(base_url=args.url, token=args.token)
    client_b = SagClient(base_url=args.url, token=args.token_b) if args.token_b else None
    case_ids = args.case.split(",") if args.case else list(selftest.ALL_CASES) + list(selftest.NEEDS_SECOND_IDENTITY)
    results = selftest.run_cases(client, case_ids, client_b=client_b)
    for r in results:
        mark = "BLOCKING" if r.blocking else "        "
        status = "?" if r.passed is None else ("PASS" if r.passed else "FAIL")
        print(f"[{mark}] {r.case} {status}: {r.detail}")
        if r.decision_hint:
            print(f"           -> {r.decision_hint}")
    missing_blocking = selftest.BLOCKING - {r.case for r in results}
    if missing_blocking:
        print(f"\nBLOCKING cases NOT YET RUN: {sorted(missing_blocking)} — should not proceed with P2 coding until results are in.", file=sys.stderr)
    return 0


def cmd_criteria_add(args):
    manifest_mod.add_criterion(Path(args.manifest), args.id, args.text)
    print(f"Added criterion '{args.id}' to {args.manifest} — remember to commit + review this change.")
    return 0


def cmd_gitleaks_scan(args):
    findings = secrets_scan.scan_file(Path(args.path))
    for f in findings:
        print(f"L{f.line} [{f.kind}]: {f.snippet}")
    return 1 if findings else 0


def cmd_api(args):
    if not os.environ.get("SAGCTL_ALLOW_API"):
        print("op 'api' (escape hatch) is not enabled — set SAGCTL_ALLOW_API=1. This command bypasses all policy/routing/gate checks.", file=sys.stderr)
        return 1
    client = _client(args.profile)
    body = json.loads(args.body) if args.body else None
    status, data = client._request(args.method.upper(), args.path, json_body=body)
    audit.append("api-escape-hatch", {"event": "api_call", "method": args.method, "path": args.path, "status": status})
    _print_json({"status": status, "data": data})
    return 0


def _resolve_source_id(args) -> str | None:
    """source_id is declared once, in the manifest, in Git — never typed into an
    agent-side config by hand. --source-id is the escape hatch for emitting a config
    from outside any repo."""
    if getattr(args, "no_scope", False):
        return None
    if getattr(args, "source_id", None):
        return args.source_id
    try:
        if getattr(args, "manifest", None):
            m = manifest_mod.load(Path(args.manifest))
        else:
            m = manifest_mod.load_for(Path.cwd())
        return m["source_id"]
    except manifest_mod.ManifestError:
        return None


def cmd_adapter_emit(args):
    from . import adapters_emit

    source_id = _resolve_source_id(args)
    if source_id is None and not args.no_scope:
        print(
            "WARNING: no manifest found and no --source-id given — emitting an UNSCOPED "
            "read MCP url. This agent will be able to list and search EVERY source on the "
            "SAG instance, not just its own (SAG has no isolation between identities, "
            "selftest S11). Run from a directory with a .sag-sync.json, or pass --source-id.",
            file=sys.stderr,
        )

    files = adapters_emit.emit_files(
        args.target, source_id=source_id, plugin_root=args.plugin_root
    )

    if not args.write:
        if args.out:  # kept for compatibility with the previous single-file behaviour
            Path(args.out).write_text(adapters_emit.emit(
                args.target, source_id=source_id, plugin_root=args.plugin_root), encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(adapters_emit.emit(
                args.target, source_id=source_id, plugin_root=args.plugin_root))
        return 0

    dest_root = Path(args.write)
    written, skipped = [], []
    for f in files:
        dest = dest_root / f.path
        # A file that normally already holds unrelated content (settings.json,
        # config.yaml) is never written blind — clobbering a user's editor settings
        # is not this command's job.
        if f.merge and not args.force:
            skipped.append((dest, "merge-target: print and merge by hand, or pass --force"))
            continue
        if dest.exists() and not args.force:
            skipped.append((dest, "already exists: pass --force to overwrite"))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.content, encoding="utf-8")
        written.append(dest)

    for d in written:
        print(f"wrote {d}")
    for d, why in skipped:
        print(f"skipped {d} — {why}", file=sys.stderr)
    if skipped:
        print("\n--- content of the skipped files ---\n", file=sys.stderr)
        for f in files:
            if any(str(dest_root / f.path) == str(d) for d, _ in skipped):
                print(f"# ===== {f.path} =====\n{f.content}", file=sys.stderr)
    return 0


# -- argparse wiring ------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sagctl", description="Write-side engine for the SAG knowledge base")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_profile(sp):
        sp.add_argument("--profile", default="default")

    sp = sub.add_parser("login")
    sp.add_argument("--url", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--email", default=None)
    sp.add_argument("--password", default=None)
    add_profile(sp)
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("whoami"); add_profile(sp); sp.set_defaults(func=cmd_whoami)
    sp = sub.add_parser("health"); add_profile(sp); sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("publish")
    sp.add_argument("path")
    sp.add_argument("--assessment", default=None, help="JSON string")
    sp.add_argument("--assessment-file", default=None)
    sp.add_argument("--manual-token", default=None)
    sp.add_argument("--agent", default=None)
    sp.add_argument("--trigger", default="user-command")
    sp.add_argument("--wait", action="store_true")
    sp.add_argument("--wait-timeout", type=float, default=90.0)
    sp.add_argument("--dry-run", action="store_true")
    add_profile(sp)
    sp.set_defaults(func=cmd_publish)

    sp = sub.add_parser("publish-status")
    sp.add_argument("source_id"); sp.add_argument("key"); add_profile(sp)
    sp.set_defaults(func=cmd_publish_status)

    sp = sub.add_parser("unpublish")
    sp.add_argument("source_id"); sp.add_argument("key"); sp.add_argument("--reason", required=True)
    sp.add_argument("--agent", default=None); add_profile(sp)
    sp.set_defaults(func=cmd_unpublish)

    sp = sub.add_parser("reprocess")
    sp.add_argument("source_id"); sp.add_argument("key"); sp.add_argument("--agent", default=None); add_profile(sp)
    sp.set_defaults(func=cmd_reprocess)

    source_sub = sub.add_parser("source").add_subparsers(dest="source_command", required=True)
    sp = source_sub.add_parser("list"); add_profile(sp); sp.set_defaults(func=cmd_source_list)
    sp = source_sub.add_parser("get"); sp.add_argument("source_id"); add_profile(sp); sp.set_defaults(func=cmd_source_get)
    sp = source_sub.add_parser("create"); sp.add_argument("name"); add_profile(sp); sp.set_defaults(func=cmd_source_create)
    sp = source_sub.add_parser("update"); sp.add_argument("source_id"); sp.add_argument("--fields", required=True, help="JSON object"); add_profile(sp); sp.set_defaults(func=cmd_source_update)
    sp = source_sub.add_parser("delete"); sp.add_argument("source_id"); sp.add_argument("--yes", action="store_true"); add_profile(sp); sp.set_defaults(func=cmd_source_delete)

    document_sub = sub.add_parser("document").add_subparsers(dest="document_command", required=True)
    sp = document_sub.add_parser("list"); sp.add_argument("source_id"); add_profile(sp); sp.set_defaults(func=cmd_document_list)

    queue_sub = sub.add_parser("queue").add_subparsers(dest="queue_command", required=True)
    sp = queue_sub.add_parser("list"); sp.add_argument("source_id"); sp.set_defaults(func=cmd_queue_list)
    sp = queue_sub.add_parser("approve"); sp.add_argument("source_id"); sp.add_argument("queue_id"); sp.add_argument("--reviewer", default=None); sp.add_argument("--wait", action="store_true"); sp.set_defaults(func=cmd_queue_approve)
    sp = queue_sub.add_parser("reject"); sp.add_argument("source_id"); sp.add_argument("queue_id"); sp.add_argument("--reviewer", default=None); sp.add_argument("--reason", required=True); sp.set_defaults(func=cmd_queue_reject)

    sp = sub.add_parser("sync")
    sp.add_argument("--manifest", required=True)
    sp.add_argument("--yes", action="store_true", help="actually execute; without this flag it's dry-run only")
    sp.add_argument("--wait", action="store_true")
    sp.add_argument("--agent", default=None)
    sp.set_defaults(func=cmd_sync)

    maintain_sub = sub.add_parser("maintain").add_subparsers(dest="maintain_command", required=True)
    sp = maintain_sub.add_parser("dedupe"); sp.add_argument("--manifest", required=True); add_profile(sp); sp.set_defaults(func=cmd_maintain_dedupe)
    sp = maintain_sub.add_parser("orphans"); sp.add_argument("--manifest", required=True); add_profile(sp); sp.set_defaults(func=cmd_maintain_orphans)
    sp = maintain_sub.add_parser("stale-branch"); sp.add_argument("--manifest", required=True); add_profile(sp); sp.set_defaults(func=cmd_maintain_stale)
    sp = maintain_sub.add_parser("review-self-gate"); sp.add_argument("source_id"); sp.add_argument("--days", type=int, default=7); sp.set_defaults(func=cmd_maintain_review_self_gate)

    sp = sub.add_parser("doctor")
    sp.add_argument("--manifest", default=None)
    sp.add_argument("--source-id", default=None)
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("eval")
    sp.add_argument("--questions", required=True)
    sp.add_argument("--manifest", default=None)
    sp.add_argument("--source-id", default=None)
    sp.add_argument("--save-baseline", action="store_true")
    sp.add_argument("--sag-version", default=None)
    add_profile(sp)
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("selftest")
    sp.add_argument("--url", required=True)
    sp.add_argument("--token", required=True)
    sp.add_argument("--token-b", default=None, help="second identity token, required for S11/S13")
    sp.add_argument("--case", default=None, help="e.g.: S1,S4,S6 — defaults to running all")
    sp.set_defaults(func=cmd_selftest)

    sp = sub.add_parser("criteria-add")
    sp.add_argument("--manifest", required=True)
    sp.add_argument("id")
    sp.add_argument("text")
    sp.set_defaults(func=cmd_criteria_add)

    sp = sub.add_parser("scan")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_gitleaks_scan)

    sp = sub.add_parser("api")
    sp.add_argument("method")
    sp.add_argument("path")
    sp.add_argument("--body", default=None, help="JSON string")
    add_profile(sp)
    sp.set_defaults(func=cmd_api)

    sp = sub.add_parser(
        "adapter-emit",
        help="generate agent-tool config from the manifest (read MCP scoped to source_id)",
    )
    sp.add_argument("target", choices=["claude-code", "hermes", "codex"])
    sp.add_argument("--manifest", default=None, help="manifest to read source_id from (default: found from cwd)")
    sp.add_argument("--source-id", default=None, help="override source_id (use outside a repo)")
    sp.add_argument(
        "--no-scope",
        action="store_true",
        help="emit an unscoped read MCP url — the agent can read every source on the instance",
    )
    sp.add_argument("--plugin-root", default="/opt/agent-skills/sag-agents-plugin",
                    help="path to the plugin checkout on the target host (hermes/codex)")
    sp.add_argument("--write", default=None, metavar="DIR", help="write the generated files under DIR")
    sp.add_argument("--force", action="store_true", help="with --write: overwrite existing / merge-target files")
    sp.add_argument("--out", default=None, help="write the whole rendering to one file")
    sp.set_defaults(func=cmd_adapter_emit)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except SagApiError as e:
        print(f"SAG_API_ERROR: {e}", file=sys.stderr)
        return 3
    except manifest_mod.ManifestError as e:
        print(f"MANIFEST_ERROR: {e}", file=sys.stderr)
        return 4
    except config.RepoStateLeakError as e:
        print(f"REPO_STATE_LEAK: {e}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
