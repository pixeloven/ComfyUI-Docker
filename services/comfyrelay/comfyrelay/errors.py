"""Structured tool errors.

A tool fails by raising `RelayError`. It is the SDK's `ToolError`, so the call
returns `isError: true` with our message, instead of the bare "Error executing
tool <name>" that any other exception becomes. The SDK puts that prefix before
a ToolError's text; `server.RelayMCPServer.call_tool` takes it off again (#217),
so the text a client sees is only JSON with stable keys, which an agent can
branch on (`code`) rather than parse prose, and the same object is the result's
structuredContent:

    {"error": {"code": "unknown_job", "message": "...", "retryable": false}}

`retryable` says whether the same call can succeed later unchanged (ComfyUI
restarting, a timeout), as opposed to a request that is wrong as sent.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError


class RelayError(ToolError):
    def __init__(self, code: str, message: str, *, retryable: bool = False, **detail: Any) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.detail = detail
        super().__init__(json.dumps({"error": self.as_dict()}, sort_keys=True))

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable, **self.detail}
