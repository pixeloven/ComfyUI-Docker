"""Consent plumbing. v1's policy refuses everything, and asks nobody.

No shipped tool needs consent yet, so these tests register their own on the
server `build_server` returns. That is the test hook: nothing here ships.
Each case runs over both protocol generations the SDK speaks, because they
carry elicitation differently (a server-to-client request up to 2025-11-25, an
InputRequiredResult round from 2026-07-28).

No `from __future__ import annotations`: the gated tool's annotation refers to
local variables, which the SDK must be able to evaluate.
"""

import json
from typing import Annotated

import mcp_types as types
import pytest
from comfyrelay.consent import Consent, ConsentRequest, PolicyDecision, RefuseAll, Verdict
from comfyrelay.server import build_server
from comfyrelay.tools import TOOLS
from mcp import Client
from relay_helpers import comfyui_answering, settings

pytestmark = pytest.mark.anyio
MODES = ["legacy", "auto"]


class AskAlways:
    name = "ask-always"

    def evaluate(self, request):
        return PolicyDecision(Verdict.ask, "test")


class GrantAll:
    name = "grant-all"

    def evaluate(self, request):
        return PolicyDecision(Verdict.grant, "test")


def with_gated_tool(policy=None):
    server, relay = build_server(settings(), comfyui=comfyui_answering())
    if policy is not None:
        relay.consent.policy = policy

    def describe(pack: str) -> ConsentRequest:
        return ConsentRequest(action="node.install", summary=f"Install node pack {pack}")

    async def gated_install(pack: str, consent: Annotated[Consent, relay.consent.required(describe)]) -> dict:
        return {"did_install": consent.granted, **consent.model_dump()}

    server.add_tool(gated_install)
    return server


class Human:
    """An elicitation callback that records what it was asked."""

    def __init__(self, action: str, approve: bool | None = None) -> None:
        self.action, self.approve, self.asked = action, approve, []

    async def __call__(self, context, params):
        self.asked.append(params.message)
        content = None if self.approve is None else {"approve": self.approve}
        return types.ElicitResult(action=self.action, content=content)


async def call(server, mode, human=None) -> dict:
    async with Client(server, mode=mode, elicitation_callback=human) as client:
        result = await client.call_tool("gated_install", {"pack": "ComfyUI-Custom-Scripts"})
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


def test_v1_policy_is_refuse_all():
    server, relay = build_server(settings(), comfyui=comfyui_answering())
    assert isinstance(relay.consent.policy, RefuseAll)
    verdict = relay.consent.policy.evaluate(ConsentRequest(action="node.install", summary="x"))
    assert verdict.verdict is Verdict.refuse


def test_no_shipped_tool_is_the_consent_test_hook():
    assert "gated_install" not in {t.name for t in TOOLS}


@pytest.mark.parametrize("mode", MODES)
async def test_v1_refuses_and_never_asks_even_a_willing_human(mode):
    human = Human("accept", approve=True)
    out = await call(with_gated_tool(), mode, human)
    assert out["did_install"] is False
    assert out["decided_by"] == "policy"
    assert "refused by policy refuse-all" in out["reason"]
    assert "comfy.yaml" in out["reason"]
    assert human.asked == []


@pytest.mark.parametrize("mode", MODES)
async def test_v1_refuses_a_headless_client(mode):
    out = await call(with_gated_tool(), mode)
    assert (out["did_install"], out["decided_by"]) == (False, "policy")


@pytest.mark.parametrize("mode", MODES)
async def test_ask_policy_grants_on_explicit_approval(mode):
    human = Human("accept", approve=True)
    out = await call(with_gated_tool(AskAlways()), mode, human)
    assert (out["did_install"], out["decided_by"]) == (True, "human")
    assert human.asked == ["Install node pack ComfyUI-Custom-Scripts\n\nAllow this?"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("human", "said"),
    [(Human("accept", approve=False), "answered no"), (Human("decline"), "declined"), (Human("cancel"), "cancelled")],
    ids=["no", "decline", "cancel"],
)
async def test_ask_policy_refuses_anything_but_approval(mode, human, said):
    out = await call(with_gated_tool(AskAlways()), mode, human)
    assert (out["did_install"], out["decided_by"]) == (False, "human")
    assert out["reason"] == f"refused: the user {said}"


@pytest.mark.parametrize("mode", MODES)
async def test_ask_policy_without_elicitation_falls_back_to_refusing(mode):
    out = await call(with_gated_tool(AskAlways()), mode, human=None)
    assert (out["did_install"], out["decided_by"]) == (False, "no_human")
    assert "elicitation capability" in out["reason"]


@pytest.mark.parametrize("mode", MODES)
async def test_grant_policy_needs_no_human(mode):
    human = Human("decline")
    out = await call(with_gated_tool(GrantAll()), mode, human)
    assert (out["did_install"], out["decided_by"]) == (True, "policy")
    assert human.asked == []
