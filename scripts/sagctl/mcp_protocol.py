"""Minimal MCP (Model Context Protocol), hand-written on stdlib — NOT dependent
on the pip `mcp` package, to keep the zero-dependency constraint (SPEC S0).

Implements only the `stdio` transport parts needed for an internal write
server: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`,
`ping`. Does not implement resources/prompts/sampling — sagw does not need
them.
"""
from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from typing import Callable

PROTOCOL_VERSION = "2024-11-05"


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], dict]  # takes arguments -> returns a dict that gets JSON-encoded into content


class McpServer:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def _write(self, obj: dict) -> None:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def _ok(self, id_, result: dict) -> None:
        self._write({"jsonrpc": "2.0", "id": id_, "result": result})

    def _err(self, id_, code: int, message: str) -> None:
        self._write({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})

    def _handle_initialize(self, id_, params):
        self._ok(
            id_,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": self.version},
            },
        )

    def _handle_tools_list(self, id_, params):
        tools = [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in self._tools.values()
        ]
        self._ok(id_, {"tools": tools})

    def _handle_tools_call(self, id_, params):
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = self._tools.get(name)
        if tool is None:
            self._err(id_, -32602, f"unknown tool: {name}")
            return
        try:
            result = tool.handler(arguments)
            text = json.dumps(result, ensure_ascii=False, default=str)
            self._ok(id_, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:  # noqa: BLE001 - return the error for the model to read, don't crash the server
            self._ok(
                id_,
                {
                    "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                    "isError": True,
                },
            )

    def _handle_ping(self, id_, params):
        self._ok(id_, {})

    def serve_forever(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            method = msg.get("method")
            id_ = msg.get("id")
            params = msg.get("params") or {}
            if method == "initialize":
                self._handle_initialize(id_, params)
            elif method == "notifications/initialized":
                continue  # notification, no response is returned
            elif method == "tools/list":
                self._handle_tools_list(id_, params)
            elif method == "tools/call":
                self._handle_tools_call(id_, params)
            elif method == "ping":
                self._handle_ping(id_, params)
            elif id_ is not None:
                self._err(id_, -32601, f"method not found: {method}")
