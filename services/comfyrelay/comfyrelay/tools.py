"""The tools, and the registry that gates them by capability profile.

Profile gating happens HERE, at registration: `register()` adds a tool to the
server only when one of its profiles is active. A tool outside the active
profiles is never registered, so it is absent from `tools/list` and a call to
it fails as an unknown tool. Nothing depends on a tool checking a flag.

Names are part of the interface (#103, commitment 3): renaming or removing one
is a major version. New tools take a namespace prefix: `workflow_*`, `node_*`,
`model_*`, `docs_*`, `dev_*`. `server_info` and the `job_*` group
(`job_status`, `job_cancel`) are the cross-cutting names.

A tool may belong to several profiles. The `job_*` tools belong to `run`
today, because workflow runs are the only jobs; they join `manage` and
`develop` when installs and dev reloads start producing jobs. Reading a job
and cancelling one are separate tools so that each carries honest
annotations: `job_status` is read-only, `job_cancel` is destructive.
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
from .tools_introspection import INTROSPECTION_TOOLS
from .tools_workflow import WORKFLOW_TOOLS, reattach_cancel, reattach_status

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
    instance_id_source: Literal["env", "hostname"] = Field(
        description="env: set by COMFYUI_MCP_INSTANCE_ID. hostname: defaulted, so it may change on a restart"
    )
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
            live = str(stats["system"].get("comfyui_version") or "") or None
        except ComfyUIError as exc:
            error = exc.as_dict()
        caps = ctx.client_capabilities
        return ServerInfo(
            name=SERVER_NAME,
            version=__version__,
            instance_id=s.instance_id,
            instance_id_source=s.instance_id_source,
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
                "jobs": {
                    "store": "memory",
                    "max_wait_seconds": MAX_WAIT_SECONDS,
                    "max_in_flight": relay.jobs.max_in_flight,
                },
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


# -- job_* ------------------------------------------------------------------


class JobView(BaseModel):
    job_id: str
    kind: str
    summary: str
    state: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    finished: bool
    created_at: float | None = Field(description="Unix seconds; null only if ComfyUI does not say (source comfyui)")
    started_at: float | None
    finished_at: float | None
    result: Any = None
    error: dict[str, Any] | None = None
    progress: dict[str, Any] | None = Field(
        default=None,
        description="What the job reports while it works. A workflow run: prompt_id, comfyui_state (submitting, "
        "queued, running, finished) and, while queued, queue_position (0 is next)",
    )
    source: Literal["relay", "comfyui"] = Field(
        default="relay",
        description="relay: a job this server holds. comfyui: a workflow run it does not hold (it restarted, or "
        "dropped the finished job), looked up on ComfyUI by its id, which is the run's prompt_id",
    )


def _job_status(relay: Relay) -> Callable[..., Any]:
    async def job_status(
        job_id: str,
        timeout_seconds: float = Field(
            default=0,
            ge=0,
            le=MAX_WAIT_SECONDS,
            description="0 answers at once. Otherwise wait up to this long for the job to finish; keep it under "
            "your own client's tool-call timeout (often about 60s).",
        ),
    ) -> JobView:
        """Check on a long-running job by its id, or wait for it to finish. Changes nothing.

        Tools that start work lasting longer than one call return a job_id; poll or wait on it here. A wait
        returns when the job finishes or after timeout_seconds (the job keeps running; call again). Keep each
        wait under your own client's tool-call timeout, often about 60s, and wait again rather than longer.
        A workflow run's job_id is its ComfyUI prompt_id: if this server no longer holds the job (it restarted),
        the run is looked up on ComfyUI and reported with source "comfyui". To stop a job, use job_cancel.
        """
        if relay.jobs.find(job_id) is None:  # not held here: a workflow run is looked up on ComfyUI (#146)
            return JobView(**await reattach_status(relay.comfyui, job_id, timeout_seconds))
        found = await relay.jobs.wait(job_id, timeout_seconds) if timeout_seconds > 0 else relay.jobs.get(job_id)
        return JobView(**found.snapshot())

    return job_status


def _job_cancel(relay: Relay) -> Callable[..., Any]:
    async def job_cancel(job_id: str) -> JobView:
        """Cancel a running job by its id, and report its state. Cancelling a finished job changes nothing.

        It waits briefly for the job to stop. A job that is still unwinding reports `cancelling`; follow it with
        job_status until it reports `cancelled`. A workflow run this server no longer holds (it restarted) is
        not cancelled: that is refused with job_not_owned, since the prompt could be another client's.
        """
        if relay.jobs.find(job_id) is None:  # not held here: see reattach_cancel (#146)
            return JobView(**await reattach_cancel(relay, job_id))
        return JobView(**(await relay.jobs.cancel(job_id)).snapshot())

    return job_cancel


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "server_info",
        frozenset(PROFILES),
        _server_info,
        ToolAnnotations(read_only_hint=True, open_world_hint=False),
    ),
    ToolSpec(
        "job_status",
        frozenset({"run"}),
        _job_status,
        ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
    ),
    ToolSpec(
        "job_cancel",
        frozenset({"run"}),
        _job_cancel,
        ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False),
    ),
)
# The read profile's introspection tools (#133) and the run profile's workflow
# tools (#132) live in their own modules, each as (name, profiles, make,
# annotations) entries.
TOOLS += tuple(ToolSpec(*spec) for spec in (*INTROSPECTION_TOOLS, *WORKFLOW_TOOLS))


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
