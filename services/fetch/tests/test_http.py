"""The two HTTP behaviours this tool is actually correct about.

Both were implemented and NEITHER was tested, which is why they are written
here before the transport changes underneath them. They are not stylistic:
each one has already cost something real.
"""

import pytest
import respx
from httpx import Response

from comfyfetch import http


@respx.mock
def test_authorization_is_stripped_on_a_cross_host_redirect():
    """HuggingFace answers /resolve/ with a 302 to *.cdn.hf.co -- a DIFFERENT
    host -- so forwarding the header would send the account token to a CDN on
    every gated download. The CDN URL is already signed and needs no credential.

    curl strips credentials cross-host and offers --location-trusted to opt back
    in; this matches curl.
    """
    respx.get("https://huggingface.co/x/resolve/main/a.safetensors").mock(
        return_value=Response(302, headers={"location": "https://cas.cdn.hf.co/signed"})
    )
    cdn = respx.get("https://cas.cdn.hf.co/signed").mock(
        return_value=Response(200, content=b"weights")
    )

    with http.request(
        "https://huggingface.co/x/resolve/main/a.safetensors", token="secret"
    ) as resp:
        assert resp.read() == b"weights"

    assert "authorization" not in {k.lower() for k in cdn.calls[0].request.headers}


@respx.mock
def test_authorization_survives_a_same_host_redirect():
    """Stripping unconditionally would break every ordinary same-origin
    redirect on an authenticated host."""
    respx.get("https://huggingface.co/a").mock(
        return_value=Response(302, headers={"location": "https://huggingface.co/b"})
    )
    second = respx.get("https://huggingface.co/b").mock(
        return_value=Response(200, content=b"ok")
    )

    with http.request("https://huggingface.co/a", token="secret") as resp:
        assert resp.read() == b"ok"

    assert second.calls[0].request.headers["authorization"] == "Bearer secret"


@respx.mock
def test_head_headers_reads_the_first_hop_only():
    """`x-linked-etag` IS the file's sha256 -- but only on hop one. Following
    the redirect returns the CDN's Xet content-address: a different, equally
    plausible-looking 64-hex value. Four wrong hashes were produced that way
    before anyone downloaded a file and hashed it.
    """
    first = respx.head("https://huggingface.co/x/resolve/main/a.safetensors").mock(
        return_value=Response(
            302,
            headers={
                "location": "https://cas.cdn.hf.co/signed",
                "x-linked-etag": '"' + "a" * 64 + '"',
            },
        )
    )
    cdn = respx.head("https://cas.cdn.hf.co/signed").mock(
        return_value=Response(200, headers={"etag": '"' + "b" * 64 + '"'})
    )

    headers = http.head_headers("https://huggingface.co/x/resolve/main/a.safetensors")

    assert "a" * 64 in headers["x-linked-etag"]
    assert first.called
    assert not cdn.called, "followed the redirect; the CDN etag is NOT the sha256"


@respx.mock
def test_head_headers_are_lowercased_so_callers_need_not_guess_case():
    respx.head("https://example.com/a").mock(
        return_value=Response(200, headers={"X-Linked-Size": "123"})
    )
    assert http.head_headers("https://example.com/a")["x-linked-size"] == "123"


@respx.mock
def test_an_unauthenticated_request_sends_no_authorization_header():
    route = respx.get("https://example.com/a").mock(return_value=Response(200))
    with http.request("https://example.com/a"):
        pass
    assert "authorization" not in {k.lower() for k in route.calls[0].request.headers}


@respx.mock
def test_the_user_agent_is_ours_and_not_the_stdlib_default():
    """Civitai returns 403 for the literal `Python-urllib/3.12` and 200 for
    every other UA tried, including a lowercased one. That block silently failed
    38 of 106 lookups in a downstream audit and was misdiagnosed as needing a
    bearer token. An explicit UA makes the class of bug impossible.
    """
    route = respx.get("https://example.com/a").mock(return_value=Response(200))
    with http.request("https://example.com/a"):
        pass
    ua = route.calls[0].request.headers["user-agent"]
    assert ua.startswith("comfyfetch/")
    assert "urllib" not in ua.lower()
