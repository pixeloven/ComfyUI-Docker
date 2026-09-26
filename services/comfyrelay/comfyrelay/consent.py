"""Consent: the one path by which a tool asks to do something that needs a human.

A tool that needs consent takes a parameter

    consent: Annotated[Consent, relay.consent.required(describe)]

where `describe` takes some of the tool's own arguments by name and returns a
`ConsentRequest`. The SDK fills the parameter before the tool body runs, and
the body proceeds only if `consent.granted`. The decision is made in three
steps:

1. **The policy** grants, refuses, or says to ask. v1's policy refuses every
   request (#103: v1 installs nothing and restarts nothing). v2 applies the
   tiered rule of decision 2 (pinned in the manifest and lock: grant; anything
   else: ask) by swapping the policy, not the path.
2. **Ask a human**, through MCP elicitation, when the policy says to and the
   client declared the elicitation capability. The SDK carries the question
   whichever protocol revision the client negotiated: a server-to-client
   request up to 2025-11-25, an `InputRequiredResult` round from 2026-07-28.
3. **The fallback.** A client without elicitation is treated as headless:
   there is no human to ask, so the request is refused, and the reason says so.

Only an explicit "approve" from the human grants. Decline, cancel, or an
answer of false all refuse. Every decision is logged.

No `from __future__ import annotations` here: the resolver annotations below
refer to closure variables, so they must be evaluated where they are written.
"""

import enum
import logging
from collections.abc import Callable
from typing import Annotated, Literal, NamedTuple, Protocol

from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    Context,
    Elicit,
    ElicitationResult,
    Resolve,
)
from pydantic import BaseModel, Field

log = logging.getLogger("comfyrelay.consent")


class ConsentRequest(BaseModel):
    action: str = Field(description="A stable name for what is asked, such as node.install")
    summary: str = Field(description="What a human is asked to allow, in one or two sentences")


class Verdict(str, enum.Enum):
    grant = "grant"
    refuse = "refuse"
    ask = "ask"


class PolicyDecision(NamedTuple):
    verdict: Verdict
    reason: str


class ConsentPolicy(Protocol):
    name: str

    def evaluate(self, request: ConsentRequest) -> PolicyDecision: ...


class RefuseAll:
    """v1: nothing that needs consent is allowed, and no human is asked."""

    name = "refuse-all"

    def evaluate(self, request: ConsentRequest) -> PolicyDecision:
        return PolicyDecision(
            Verdict.refuse,
            "this server changes nothing on the ComfyUI instance: it installs, updates and "
            "restarts nothing. To change what is installed, propose an edit to the "
            "deployment's comfy.yaml and lock instead.",
        )


class Consent(BaseModel):
    """The outcome a gated tool receives."""

    action: str
    granted: bool
    decided_by: Literal["policy", "human", "no_human"]
    reason: str


class Approval(BaseModel):
    approve: bool = Field(description="true to allow this; false to refuse it")


class ConsentGate:
    def __init__(self, policy: ConsentPolicy | None = None) -> None:
        self.policy: ConsentPolicy = policy or RefuseAll()

    def required(self, describe: Callable[..., ConsentRequest]) -> Resolve:
        """The marker for a tool parameter annotated `Annotated[Consent, <this>]`."""
        request_of = Resolve(describe)

        def ask(request: Annotated[ConsentRequest, request_of], ctx: Context):
            if self.policy.evaluate(request).verdict is Verdict.ask and _can_elicit(ctx):
                return Elicit(f"{request.summary}\n\nAllow this?", Approval)
            # Not asked. `decide` does not read this placeholder.
            return CancelledElicitation()

        def decide(
            request: Annotated[ConsentRequest, request_of],
            answer: Annotated[ElicitationResult[Approval], Resolve(ask)],
            ctx: Context,
        ) -> Consent:
            policy = self.policy.evaluate(request)
            if policy.verdict is not Verdict.ask:
                consent = Consent(
                    action=request.action,
                    granted=policy.verdict is Verdict.grant,
                    decided_by="policy",
                    reason=f"{_PAST[policy.verdict.value]} by policy {self.policy.name}: {policy.reason}",
                )
            elif not _can_elicit(ctx):
                consent = Consent(
                    action=request.action,
                    granted=False,
                    decided_by="no_human",
                    reason="refused: this needs a human's consent, and the client cannot ask one "
                    "(it did not declare the MCP elicitation capability), so it is treated as headless",
                )
            elif isinstance(answer, AcceptedElicitation) and answer.data.approve:
                consent = Consent(
                    action=request.action, granted=True, decided_by="human", reason="approved by the user"
                )
            else:
                outcome = "answered no" if isinstance(answer, AcceptedElicitation) else _PAST[answer.action]
                consent = Consent(
                    action=request.action,
                    granted=False,
                    decided_by="human",
                    reason=f"refused: the user {outcome}",
                )
            log.info(
                "consent %s for %s (%s): %s",
                "granted" if consent.granted else "refused",
                consent.action,
                consent.decided_by,
                consent.reason,
            )
            return consent

        return Resolve(decide)


_PAST = {"grant": "granted", "refuse": "refused", "decline": "declined", "cancel": "cancelled"}


def _can_elicit(ctx: Context) -> bool:
    caps = ctx.client_capabilities
    return bool(caps and caps.elicitation)
