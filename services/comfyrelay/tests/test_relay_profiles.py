"""Profile gating is enforced where tools register: a tool outside the active
profiles is absent from tools/list and cannot be called."""

from __future__ import annotations

import logging

import pytest
from comfyrelay.server import build_server
from comfyrelay.settings import DEFAULT_PROFILES, PROFILES, ConfigError, parse_profiles
from comfyrelay.tools import TOOLS
from mcp import Client
from relay_helpers import comfyui_answering, settings

pytestmark = pytest.mark.anyio


def test_the_v1_default_is_read_and_run():
    assert DEFAULT_PROFILES == ("read", "run")
    assert PROFILES == ("read", "run", "manage")


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("read,run", ("read", "run")),
        (" RUN , read ", ("read", "run")),
        ("manage,read,read", ("read", "manage")),
        ("manage", ("manage",)),
    ],
)
def test_parse_profiles(value, want):
    assert parse_profiles(value) == want


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("", "no profile"),
        (" , ", "no profile"),
        ("read,admin", "admin"),
        ("read, Develop", "profile develop isn't available in this image"),
    ],
)
def test_parse_profiles_refuses(value, why):
    with pytest.raises(ConfigError, match=why):
        parse_profiles(value)


def test_every_tool_names_known_profiles_and_a_unique_name():
    assert len({t.name for t in TOOLS}) == len(TOOLS)
    for spec in TOOLS:
        assert spec.profiles and spec.profiles <= set(PROFILES), spec.name


async def listed(profiles: tuple[str, ...]) -> tuple[set[str], Client]:
    server, _ = build_server(settings(profiles=profiles), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        names = {t.name for t in (await client.list_tools()).tools}
        missing = await client.call_tool("job_status", {"job_id": "x"})
    return names, missing


READ_TOOLS = {
    "node_search",
    "node_describe",
    "model_list",
    "template_search",
    "template_get",
    "docs_search",
    "docs_guide",
}
RUN_TOOLS = {
    "job_status",
    "job_cancel",
    "workflow_validate",
    "workflow_run",
    "workflow_outputs",
    "workflow_upload_input",
}


async def test_default_profiles_register_server_info_the_run_tools_and_introspection():
    names, _ = await listed(("read", "run"))
    assert names == {"server_info"} | RUN_TOOLS | READ_TOOLS


async def test_a_tool_in_a_disabled_profile_is_absent_and_uncallable():
    names, call = await listed(("read",))
    assert "job_status" not in names
    assert names == {"server_info"} | READ_TOOLS
    assert call.is_error
    assert "Unknown tool" in call.content[0].text


async def test_introspection_is_the_read_profile_only(caplog):
    caplog.set_level(logging.WARNING, logger="comfyrelay")
    await listed(("read",))
    assert "profile 'read' is enabled" not in caplog.text  # read has tools now
    run_only, _ = await listed(("run",))
    assert run_only == {"server_info"} | RUN_TOOLS


async def test_manage_is_recognised_but_logs_that_nothing_is_available(caplog):
    caplog.set_level(logging.WARNING, logger="comfyrelay")
    names, _ = await listed(("manage",))
    assert names == {"server_info"}
    assert "profile 'manage' is enabled" in caplog.text
    assert "nothing is available through it" in caplog.text
