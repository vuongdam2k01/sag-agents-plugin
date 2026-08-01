"""Minimal MCP client over streamable-http/SSE — stdlib only, no SDK.

Exists for one reason: selftest S17 has to VERIFY that pointing the read MCP at
`?source_id=<id>` actually narrows what an agent can see, rather than the plugin
emitting scoped URLs and asserting isolation it never measured. Everything else in
this repo earns its claims through `sagctl selftest`; read scoping must too.

Transport facts come from selftest S15 on a real instance (docs/SPEC.md): the URL
form returned by `GET /sources/{id}/mcp` is `http://<host>/mcp/?source_id=<id>`,
responses are `text/event-stream`, and no `Mcp-Session-Id` is required — each request
stands alone. If an instance DOES return a session id header, it must be echoed on
later calls; that is handled here so the client does not silently break on one.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class McpClientError(RuntimeError):
    pass


class McpHttpClient:
    def __init__(self, url: str, token: str | None = None, timeout: float = 30.0):
        self.url = url
        self.token = token
        self.timeout = timeout
        self._id = 0
        self._session_id: str | None = None

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _post(self, payload: dict, *, expect_response: bool = True) -> dict | None:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            # Servers pick a transport from Accept; offering both means this client
            # works against a plain-JSON server and an SSE one alike.
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise McpClientError(f"MCP HTTP {e.code}: {detail[:400]}") from None
        except urllib.error.URLError as e:
            raise McpClientError(f"MCP unreachable: {e.reason}") from None
        except TimeoutError as e:
            raise McpClientError(f"MCP timeout: {e}") from None
        except ConnectionError as e:
            raise McpClientError(f"MCP connection error: {e}") from None

        if not expect_response:
            return None
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> dict:
        """Accept both a bare JSON body and an SSE stream of `data:` frames."""
        text = raw.strip()
        if not text:
            raise McpClientError("empty MCP response")
        if text.startswith("{"):
            return json.loads(text)
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:") :].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                parsed = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            # Skip notifications/progress frames — the caller wants the result.
            if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                return parsed
        raise McpClientError(f"no JSON-RPC result frame in MCP response: {text[:400]}")

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        resp = self._post(
            {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params or {}}
        )
        assert resp is not None
        if "error" in resp:
            raise McpClientError(f"{method} -> {resp['error']}")
        return resp.get("result", {})

    def initialize(self) -> dict:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "sagctl-selftest", "version": "1"},
            },
        )
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            expect_response=False,
        )
        return result

    def list_tools(self) -> list[dict]:
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> str:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        chunks = []
        for item in result.get("content", []) or []:
            if item.get("type") == "text":
                chunks.append(item.get("text", ""))
        return "\n".join(chunks)


def scoped_url(base_url: str, source_id: str | None) -> str:
    base = base_url.rstrip("/")
    if source_id:
        return f"{base}/mcp/?source_id={source_id}"
    return f"{base}/mcp/"
