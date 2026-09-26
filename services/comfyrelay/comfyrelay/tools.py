"""The tools, and the registry that gates them by capability profile.

Profile gating happens HERE, at registration: `register()` adds a tool to the
server only when one of its profiles is active. A tool outside the active
profiles is never registered, so it is absent from `tools/list` and a call to
it fails as an unknown tool. Nothing depends on a tool checking a flag.

Names are part of the interface (#103, commitment 3): renaming or removing one
is a major version. New tools take a namespace prefix: `workflow_*`, `node_*`,
`model_*`, `docs_*`, `dev_*`. `server_info` and `job` are the two
cross-cutting names, and each is also its namespace.

A tool may belong to several profiles. `job` belongs to `run` today, because
workflow runs are the only jobs; it joins `manage` and `develop` when installs
and dev reloads start producing jobs.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from . import __version__
from .comfyui import ComfyUIClient, ComfyUIError
from .consent import ConsentGate
from .jobs import MAX_WAIT_SECONDS, JobStore
from .settings import PROFILES, Settings

log = logging.getLogger("comfyrelay")

SERVER_NAME = "comfyrelay"


@dataclass
class Relay:
    """Everything the tools share. One per server process, not per MCP session:
    a job started in one session can be followed from another."""

    settings: Settings
    comfyui: ComfyUIClient
    jobs: JobStore = field(default_factory=JobStore)
    consent: ConsentGate = field(default_factory=ConsentGate)
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    profiles: frozenset[str]
    make: Callable[[Relay], Callable[..., Any]]
    annotations: ToolAnnotations


# -- server_info ------------------------------------------------------------


class ComfyUIStatus(BaseModel):
    reachable: bool
    live_version: str | None = Field(description="What the connected ComfyUI reports, from /system_stats")
    pinned_version: str | None = Field(description="What this image was built for (null outside the image)")
    matches_pin: bool | None = Field(description="null when either side is unknown or the pin is a commit")
    error: dict[str, Any] | None = None


class ProfileStatus(BaseModel):
    active: list[str]
    available: list[str]
    without_tools: list[str] = Field(description="Active profiles this version has no tools for yet")


class ServerInfo(BaseModel):
    name: str
    version: str
    instance_id: str
    profiles: ProfileStatus
    capabilities: dict[str, Any]
    comfyui: ComfyUIStatus
    corpus: dict[str, Any]


def _same_version(live: str | None, pinned: str | None) -> bool | None:
    semver = re.compile(r"^v?\d+\.\d+\.\d+$")
    if not live or not pinned or not semver.match(pinned) or not semver.match(live):
        return None
    return live.lstrip("v") == pinned.lstrip("v")


def _server_info(relay: Relay) -> Callable[..., Any]:
    async def server_info(ctx: Context) -> ServerInfo:
        """Identify this ComfyUI sidecar: its id, active capability profiles, tools, and the ComfyUI version it serves.

        Call it first. It reports the live ComfyUI version next to the version this server was built for, and
        whether ComfyUI is reachable right now. It never fails because ComfyUI is down; `comfyui.error` says why.
        """
        s = relay.settings
        live, error = None, None
        try:
            stats = await relay.comfyui.system_stats()
            live = str(stats.get("system", {}).get("comfyui_version") or "") or None
        except ComfyUIError as exc:
            error = exc.as_dict()
        caps = ctx.client_capabilities
        return ServerInfo(
            name=SERVER_NAME,
            version=__version__,
            instance_id=s.instance_id,
            profiles=ProfileStatus(
                active=list(s.profiles),
                available=list(PROFILES),
                without_tools=profiles_without_tools(s.profiles),
            ),
            capabilities={
                "tools": sorted(relay.tools),
                "consent": {
                    "policy": relay.consent.policy.name,
                    "client_can_elicit": bool(caps and caps.elicitation),
                },
                "jobs": {"store": "memory", "max_wait_seconds": MAX_WAIT_SECONDS},
            },
            comfyui=ComfyUIStatus(
                reachable=error is None,
                live_version=live,
                pinned_version=s.comfyui_pin,
                matches_pin=_same_version(live, s.comfyui_pin),
                error=error,
            ),
            # Filled by the docs corpus (#134): each source with its license.
            corpus={"status": "absent", "sources": []},
        )

    return server_info


# -- job --------------------------------------------------------------------


class JobView(BaseModel):
    job_id: str
    kind: str
    summary: str
    state: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    finished: bool
    created_at: float
    started_at: float | None
    finished_at: float | None
    result: Any = None
    error: dict[str, Any] | None = None


def _job(relay: Relay) -> Callable[..., Any]:
    async def job(
        job_id: str,
        action: Literal["status", "wait", "cancel"] = "status",
        timeout_seconds: float = Field(
            default=30.0, ge=0, le=MAX_WAIT_SECONDS, description="For wait: how long to wait at most"
        ),
    ) -> JobView:
        """Follow a long-running job by its id: check its status, wait for it to finish, or cancel it.

        Tools that start work lasting longer than one call return a job_id; poll it here. `wait` returns when the
        job finishes or after timeout_seconds (the job keeps running; wait again). `cancel` stops it.
        """
        if action == "wait":
            found = await relay.jobs.wait(job_id, timeout_seconds)
        elif action == "cancel":
            found = await relay.jobs.cancel(job_id)
        else:
            found = relay.jobs.get(job_id)
        return JobView(**found.snapshot())

    return job


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "server_info",
        frozenset(PROFILES),
        _server_info,
        ToolAnnotations(read_only_hint=True, open_world_hint=False),
    ),
    ToolSpec(
        "job",
        frozenset({"run"}),
        _job,
        ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False),
    ),
)


def profiles_without_tools(active: tuple[str, ...], specs: tuple[ToolSpec, ...] = TOOLS) -> list[str]:
    """Active profiles that add nothing: no tool of theirs beyond those every profile has."""
    everywhere = frozenset(PROFILES)
    return [p for p in active if not any(p in s.profiles and s.profiles != everywhere for s in specs)]


def register(server: MCPServer, relay: Relay, specs: tuple[ToolSpec, ...] = TOOLS) -> list[str]:
    """Add every tool whose profiles intersect the active ones. The only place tools are added."""
    active = set(relay.settings.profiles)
    for spec in specs:
        if spec.profiles & active:
            server.add_tool(spec.make(relay), name=spec.name, annotations=spec.annotations)
            relay.tools.append(spec.name)
    for profile in profiles_without_tools(relay.settings.profiles, specs):
        log.warning(
            "profile %r is enabled, but comfyrelay %s has no tools for it: nothing is available through it",
            profile,
            __version__,
        )
    return relay.tools
