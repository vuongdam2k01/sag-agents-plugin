#!/usr/bin/env python3
"""sagw — a thin MCP write server wrapping the sagctl engine (SPEC S0/S8).

Talks to SAG PURELY THROUGH its public REST API, exactly the way SAG's own
frontend or a `curl` command would — no installing, no patching, no adding
routes to the SAG source code. This server is plugin code, running as a
separate process on the agent's machine (stdio transport).

Exactly 6 tools per SPEC S8, no more:
  sag_publish            {path, assessment}         allow — always requires an assessment
  sag_publish_status     {path}                      allow — read-only
  sag_sync_preview       {path}                       allow — read-only, dry-run
  sag_reprocess          {path}                      allow
  sag_publish_unreviewed {path, reason}              ask   — bypasses the require gate, does NOT bypass secret/deny
  sag_unpublish          {path, reason}              ask   — the remediation path, always available

Everything else (sync batch, source admin, queue approve, api escape hatch)
lives ONLY in the `sagctl` CLI — never as an MCP tool (SPEC S8).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# stdout carries the JSON-RPC protocol (mcp_protocol) so it MUST be UTF-8 —
# the default Windows console (cp1252/cp437) will crash when the text content
# contains Vietnamese characters.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sagctl import __version__, assessment as assessment_mod, publish as publish_mod, sync as sync_mod
from sagctl import manifest as manifest_mod
from sagctl.mcp_protocol import McpServer, Tool

AGENT_NAME = os.environ.get("SAGCTL_AGENT", "unknown-agent")


def _handle_sag_publish(args: dict) -> dict:
    path = args["path"]
    raw_assessment = args.get("assessment")
    if raw_assessment is None:
        raise ValueError("assessment is required — sag_publish always requires a self-assessment (SPEC S5)")
    errors = assessment_mod.validate_model_input(raw_assessment)
    if errors:
        raise ValueError("invalid assessment: " + "; ".join(errors))
    result = publish_mod.publish_one(
        Path(path),
        assessment=raw_assessment,
        agent=AGENT_NAME,
        trigger=args.get("trigger", "end-of-task"),
        wait=False,
    )
    return result.__dict__


def _handle_sag_publish_status(args: dict) -> dict:
    doc = publish_mod.status_by_path(args["path"])
    return doc or {"found": False}


def _handle_sag_sync_preview(args: dict) -> dict:
    path = args["path"]
    m = manifest_mod.load_for(Path(path))
    items = sync_mod.plan(Path(m["_path"]))
    return {"source_id": m["source_id"], "candidate_count": len(items), "candidates": [i.relpath for i in items]}


def _handle_sag_reprocess(args: dict) -> dict:
    return publish_mod.reprocess_by_path(args["path"], agent=AGENT_NAME)


def _handle_sag_publish_unreviewed(args: dict) -> dict:
    result = publish_mod.publish_unreviewed(
        Path(args["path"]), reason=args["reason"], agent=AGENT_NAME, trigger="user-command"
    )
    return result.__dict__


def _handle_sag_unpublish(args: dict) -> dict:
    ok = publish_mod.unpublish_by_path(args["path"], reason=args["reason"], agent=AGENT_NAME)
    return {"ok": ok}


def build_server() -> McpServer:
    server = McpServer("sagw", __version__)
    server.register(
        Tool(
            name="sag_publish",
            description=(
                "Publish a document (repo path) to the SAG knowledge base. "
                "Requires an 'assessment' — a self-assessment of whether 'this "
                "content is knowledge worth adding to the shared knowledge base'. "
                "The engine decides on its own whether to publish immediately or "
                "queue it, based on the verdict/confidence and the manifest's "
                "policy — it does not ask the user."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "file path within the repo (committed)"},
                    "assessment": {
                        "type": "object",
                        "description": "self-assessment — see docs/SPEC.md §S5",
                        "properties": {
                            "verdict": {"type": "string", "enum": ["knowledge", "not-knowledge", "unsure"]},
                            "durable": {"type": "object", "properties": {"pass": {"type": "boolean"}, "why": {"type": "string"}}},
                            "audience": {"type": "object", "properties": {"pass": {"type": "boolean"}, "why": {"type": "string"}}},
                            "retrieval_fit": {"type": "object", "properties": {"pass": {"type": "boolean"}, "why": {"type": "string"}}},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "rationale": {"type": "string"},
                            "criteria_ack": {"type": "array", "items": {"type": "string"}},
                            "source_id": {"type": "string"},
                            "commit": {"type": "string"},
                        },
                        "required": ["verdict", "durable", "audience", "retrieval_fit", "confidence", "rationale"],
                    },
                },
                "required": ["path", "assessment"],
            },
            handler=_handle_sag_publish,
        )
    )
    server.register(
        Tool(
            name="sag_publish_status",
            description="Check the publish status (pending/ready/failed) of a document by its repo path. Read-only.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            handler=_handle_sag_publish_status,
        )
    )
    server.register(
        Tool(
            name="sag_sync_preview",
            description="Preview (read-only, does not execute) the list of files that would be synced within this path's source.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            handler=_handle_sag_sync_preview,
        )
    )
    server.register(
        Tool(
            name="sag_reprocess",
            description="Ask SAG to re-run the processing pipeline (parse/chunk/extract) for a document that is in a failed state.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            handler=_handle_sag_reprocess,
        )
    )
    server.register(
        Tool(
            name="sag_publish_unreviewed",
            description=(
                "Emergency publish of content that has NOT gone through the usual "
                "commit/merge gate (a hotfix runbook during an incident, a draft "
                "that's needed right now). Still blocked by the secret scan and "
                "deny_paths. Keeps the same key, only changes the state — this "
                "creates reconcile debt that must be handled later. Use ONLY when "
                "it's truly urgent."
            ),
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["path", "reason"],
            },
            handler=_handle_sag_publish_unreviewed,
        )
    )
    server.register(
        Tool(
            name="sag_unpublish",
            description="Remove a document from SAG — the remediation path for when a document is found to be wrong, harmful, or leaking a secret. Always available.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["path", "reason"],
            },
            handler=_handle_sag_unpublish,
        )
    )
    return server


if __name__ == "__main__":
    build_server().serve_forever()
