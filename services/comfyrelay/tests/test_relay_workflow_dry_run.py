"""workflow_validate's dry run (#215): ComfyUI's own /prompt check through the core image's opt-in validate-only
route, against a fake ComfyUI. The real-ComfyUI counterpart is test_relay_dry_run_live.py."""

from __future__ import annotations

import asyncio
import json

import comfyrelay.tools_workflow as tw
import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import SYSTEM_STATS, WORKFLOW_OBJECT_INFO, settings

pytestmark = pytest.mark.anyio

ROUTE = "/comfyrelay/validate_only"


def graph() -> dict:
    return {
        "1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "x"}},
    }


REJECTED = {
    "error": {
        "type": "prompt_outputs_failed_validation",
        "message": "Prompt outputs failed validation",
        "details": "Required input is missing: filename_prefix",
        "extra_info": {},
    },
    "node_errors": {
        "1": {
            "errors": [
                {
                    "type": "invalid_input_type",
                    "message": "Failed to convert an input value to a INT value",
                    "details": "width, abc, invalid literal for int() with base 10: 'abc'",
                    "extra_info": {
                        "input_name": "width",
                        "input_config": ["INT", {"default": 512, "min": 1, "max": 16384}],
                        "received_value": "abc",
                    },
                }
            ],
            "dependent_outputs": ["2"],
            "class_type": "EmptyImage",
        },
        "2": {
            "errors": [
                {
                    "type": "required_input_missing",
                    "message": "Required input is missing",
                    "details": "filename_prefix",
                    "extra_info": {"input_name": "filename_prefix"},
                }
            ],
            "dependent_outputs": ["2"],
            "class_type": "SaveImage",
        },
    },
}


class Fake:
    """ComfyUI v0.38.0's /object_info, /prompt and, with `shim`, the validate-only route, which answers as /prompt
    does and queues nothing. `answer` is the route's (status, body) for a POST; `fail`, a path's status."""

    def __init__(self, shim: bool = True) -> None:
        self.shim = shim
        self.calls: list[tuple[str, str, object]] = []
        self.answer: tuple[int, dict] | None = None
        self.fail: dict[str, int] = {}
        self.delays: dict[str, float] = {}

    def client(self) -> ComfyUIClient:
        return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(self.handle))

    def count(self, method: str, path: str) -> int:
        return sum(1 for m, p, _ in self.calls if (m, p) == (method, path))

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))
        await asyncio.sleep(self.delays.get(path, 0))
        if path in self.fail:
            return httpx2.Response(self.fail[path])
        if path == "/system_stats":
            return httpx2.Response(200, json=SYSTEM_STATS)
        if path == "/object_info":
            return httpx2.Response(200, json=WORKFLOW_OBJECT_INFO)
        if path == ROUTE and self.shim:
            if method == "GET":
                return httpx2.Response(200, json={"validate_only": True, "version": 1})
            if self.answer is not None:
                return httpx2.Response(self.answer[0], json=self.answer[1])
            return httpx2.Response(200, json={"prompt_id": "minted", "number": 0, "node_errors": {}})
        if path == ROUTE:  # aiohttp: the static route has no POST, and no such file for a GET
            return httpx2.Response(405 if method == "POST" else 404, text="404: Not Found")
        return httpx2.Response(404)


async def call(fake: Fake, workflow: dict | None = None, *, server=None) -> dict:
    if server is None:
        server, _ = build_server(settings(), comfyui=fake.client())
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("workflow_validate", {"workflow": workflow or graph()})
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_with_the_route_comfyui_checks_the_graph_and_nothing_is_queued():
    fake = Fake()
    got = await call(fake)
    assert got["dry_run"] == {"ran": True, "accepted": True}
    assert (got["valid"], got["runnable"]) == (True, True)
    # The body is exactly the graph: no prompt_id, client_id or extra_data, so nothing that could carry a credential.
    assert [b for m, p, b in fake.calls if (m, p) == ("POST", ROUTE)] == [{"prompt": graph()}]
    assert fake.count("POST", "/prompt") == 0


async def test_comfyuis_rejection_is_reported_in_workflow_runs_shape():
    fake = Fake()
    fake.answer = (400, REJECTED)
    got = await call(fake)
    assert got["dry_run"]["ran"] is True and got["dry_run"]["accepted"] is False
    assert got["dry_run"]["error"] == {
        "type": "prompt_outputs_failed_validation",
        "message": "Prompt outputs failed validation",
        "details": "Required input is missing: filename_prefix",
    }
    assert got["dry_run"]["errors"] == [
        {
            "type": "invalid_input_type",
            "message": "Failed to convert an input value to a INT value",
            "node_id": "1",
            "class_type": "EmptyImage",
            "input": "width",
            "details": "width, abc, invalid literal for int() with base 10: 'abc'",
            "expected": "INT",
            "got": "abc",
        },
        {
            "type": "required_input_missing",
            "message": "Required input is missing",
            "node_id": "2",
            "class_type": "SaveImage",
            "input": "filename_prefix",
            "details": "filename_prefix",
        },
    ]
    # Additive: the structural verdict is unchanged.
    assert (got["valid"], got["runnable"], got["errors"]) == (True, True, [])


async def test_outputs_comfyui_would_drop_are_listed_with_accepted_true():
    fake = Fake()
    fake.answer = (200, {"prompt_id": "minted", "number": 3, "node_errors": {"2": REJECTED["node_errors"]["2"]}})
    got = await call(fake)
    assert got["dry_run"]["accepted"] is True
    assert [(e["type"], e["node_id"]) for e in got["dry_run"]["errors"]] == [("required_input_missing", "2")]


async def test_without_the_route_the_result_says_so_and_nothing_else_changes():
    fake = Fake(shim=False)
    got = await call(fake)
    assert got["dry_run"] == {"ran": False, "reason": "unavailable", "detail": tw.NOT_RUN["unavailable"]}
    assert list(got)[-1] == "dry_run"  # the one new key comes last; every other is as before
    assert fake.count("GET", ROUTE) == 1 and fake.count("POST", ROUTE) == 0 and fake.count("POST", "/prompt") == 0


async def test_the_probe_is_shared_and_cached():
    fake = Fake()
    server, _ = build_server(settings(), comfyui=fake.client())
    for _ in range(3):
        assert (await call(fake, server=server))["dry_run"]["ran"] is True
    assert fake.count("GET", ROUTE) == 1 and fake.count("POST", ROUTE) == 3


async def test_a_route_gone_since_the_probe_is_unavailable_and_probed_again():
    fake = Fake()
    server, _ = build_server(settings(), comfyui=fake.client())
    assert (await call(fake, server=server))["dry_run"]["ran"] is True
    fake.shim = False  # ComfyUI restarted without the opt-in, within the probe's TTL
    assert (await call(fake, server=server))["dry_run"]["reason"] == "unavailable"
    assert (await call(fake, server=server))["dry_run"]["reason"] == "unavailable"
    assert fake.count("GET", ROUTE) == 2  # the stale yes was dropped; the next call asked again
    assert fake.count("POST", "/prompt") == 0


async def test_a_graph_with_structural_errors_is_not_sent():
    fake = Fake()
    bad = graph()
    bad["2"]["class_type"] = "SaveImagee"
    got = await call(fake, bad)
    assert got["dry_run"] == {"ran": False, "reason": "invalid_workflow", "detail": tw.NOT_RUN["invalid_workflow"]}
    assert fake.count("GET", ROUTE) == 0 and fake.count("POST", ROUTE) == 0


async def test_a_graph_with_partner_api_nodes_is_never_sent():
    fake = Fake()
    partner = graph()
    partner["3"] = {"class_type": "ClaudeNode", "inputs": {}}
    got = await call(fake, partner)
    assert got["dry_run"]["reason"] == "partner_api_nodes"
    assert fake.count("POST", ROUTE) == 0 and fake.count("POST", "/prompt") == 0


async def test_a_failure_is_a_reason_never_the_calls_failure():
    fake = Fake()
    fake.fail[ROUTE] = 500
    got = await call(fake)
    assert got["dry_run"]["ran"] is False and got["dry_run"]["reason"] == "comfyui_http_error"
    assert "workflow_run submits the graph" in got["dry_run"]["detail"]
    assert got["valid"] is True


async def test_a_slow_comfyui_times_the_dry_run_out(monkeypatch):
    monkeypatch.setattr(tw, "DRY_RUN_SECONDS", 0.2)
    fake = Fake()
    fake.delays[ROUTE] = 1.0
    got = await call(fake)
    assert got["dry_run"]["reason"] == "timeout"


async def test_comfyuis_data_is_capped():
    options = [f"model_{i:04d}.safetensors" for i in range(1000)]
    many = {
        str(n): {
            "errors": [
                {
                    "type": "value_not_in_list",
                    "message": "Value not in list",
                    "details": "x" * 5000,
                    "extra_info": {
                        "input_name": "ckpt_name",
                        "input_config": [options, {}],
                        "received_value": "y" * 5000,
                    },
                }
            ],
            "class_type": "CheckpointLoaderSimple",
        }
        for n in range(80)
    }
    fake = Fake()
    fake.answer = (400, {"error": {"type": "t", "message": "m" * 5000}, "node_errors": many})
    got = (await call(fake))["dry_run"]
    assert len(got["errors"]) == tw.DRY_RUN_MAX_ERRORS and got["errors_omitted"] == 80 - tw.DRY_RUN_MAX_ERRORS
    first = got["errors"][0]
    assert first["expected"] == options[: tw.DRY_RUN_MAX_OPTIONS] and first["expected_count"] == 1000
    assert len(first["details"]) == len(first["got"]) == len(got["error"]["message"]) == tw.DRY_RUN_TEXT_MAX_CHARS
