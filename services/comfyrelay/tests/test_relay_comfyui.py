"""The ComfyUI client maps every way a request can go wrong to a stable code."""

from __future__ import annotations

import json

import httpx2
import pytest
from comfyrelay.comfyui import ComfyUIClient, ComfyUIError
from relay_helpers import SYSTEM_STATS, comfyui_answering, comfyui_raising

pytestmark = pytest.mark.anyio


async def test_system_stats():
    assert await comfyui_answering().system_stats() == SYSTEM_STATS


async def test_object_info_quotes_the_node_class():
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.raw_path.decode())
        return httpx2.Response(200, json={"ok": True})

    client = ComfyUIClient("http://comfyui.test:8188/", transport=httpx2.MockTransport(handler))
    await client.object_info()
    await client.object_info("MathExpression|pysssss")
    await client.object_info("../system_stats")
    assert seen == ["/object_info", "/object_info/MathExpression%7Cpysssss", "/object_info/..%2Fsystem_stats"]


@pytest.mark.parametrize(
    ("raise_", "code", "retryable"),
    [
        (lambda r: httpx2.ConnectError("refused", request=r), "comfyui_unreachable", True),
        (lambda r: httpx2.ReadTimeout("slow", request=r), "comfyui_timeout", True),
        (lambda r: httpx2.ConnectTimeout("slow", request=r), "comfyui_timeout", True),
        (lambda r: httpx2.RemoteProtocolError("reset", request=r), "comfyui_unreachable", True),
    ],
)
async def test_transport_failures(raise_, code, retryable):
    with pytest.raises(ComfyUIError) as info:
        await comfyui_raising(raise_).system_stats()
    assert (info.value.code, info.value.retryable) == (code, retryable)


@pytest.mark.parametrize(("status", "retryable"), [(500, True), (503, True), (404, False), (400, False)])
async def test_http_errors(status, retryable):
    client = comfyui_answering({"/system_stats": httpx2.Response(status)})
    with pytest.raises(ComfyUIError) as info:
        await client.system_stats()
    assert info.value.code == "comfyui_http_error"
    assert info.value.detail == {"status": status}
    assert info.value.retryable is retryable


async def test_a_non_json_answer():
    client = comfyui_answering({"/system_stats": httpx2.Response(200, text="<html>proxy login</html>")})
    with pytest.raises(ComfyUIError) as info:
        await client.system_stats()
    assert info.value.code == "comfyui_bad_response"


async def test_redirects_are_not_followed():
    client = comfyui_answering({"/system_stats": httpx2.Response(302, headers={"Location": "http://elsewhere/"})})
    with pytest.raises(ComfyUIError):  # a 3xx is not JSON from ComfyUI, and nothing else is contacted
        await client.system_stats()


def test_the_error_is_structured_json():
    err = ComfyUIError("comfyui_timeout", "slow", retryable=True)
    assert json.loads(str(err)) == {"error": {"code": "comfyui_timeout", "message": "slow", "retryable": True}}


@pytest.mark.parametrize("body", [[], {"system": None}, {"system": []}, {}, None], ids=repr)
async def test_system_stats_of_the_wrong_shape_is_a_bad_response(body):
    """Any JSON parses; only an object with a "system" object is /system_stats."""
    client = comfyui_answering({"/system_stats": httpx2.Response(200, text=json.dumps(body))})
    with pytest.raises(ComfyUIError) as info:
        await client.system_stats()
    assert (info.value.code, info.value.retryable) == ("comfyui_bad_response", False)
    assert "/system_stats with JSON that is not an object" in info.value.message


async def test_object_info_of_the_wrong_shape_is_a_bad_response():
    client = comfyui_answering({"/object_info": httpx2.Response(200, json=["KSampler"])})
    with pytest.raises(ComfyUIError) as info:
        await client.object_info()
    assert info.value.code == "comfyui_bad_response"


# -- credentials in COMFYUI_URL are sent, never shown -------------------------

CREDENTIALED = "http://admin:hunter2@127.0.0.1:9"


@pytest.mark.parametrize(
    "answer",
    [
        None,  # a real connection, refused: the transport's own message is included too
        httpx2.Response(500),
        httpx2.Response(200, text="<html>"),
        httpx2.Response(200, json=[]),
    ],
    ids=["refused", "http-error", "not-json", "wrong-shape"],
)
async def test_credentials_in_the_url_never_appear_in_an_error(answer):
    transport = None if answer is None else httpx2.MockTransport(lambda request: answer)
    client = ComfyUIClient(CREDENTIALED, transport=transport)
    with pytest.raises(ComfyUIError) as info:
        await client.system_stats()
    assert "hunter2" not in str(info.value) and "admin" not in str(info.value)
    assert "http://***@127.0.0.1:9" in info.value.message


async def test_credentials_in_the_url_are_still_sent():
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization"))
        return httpx2.Response(200, json={"system": {}})

    await ComfyUIClient(CREDENTIALED, transport=httpx2.MockTransport(handler)).system_stats()
    assert seen == ["Basic YWRtaW46aHVudGVyMg=="]
