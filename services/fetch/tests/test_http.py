"""The two HTTP behaviours this tool is actually correct about.

Both were implemented and NEITHER was tested, which is why they are written
here before the transport changes underneath them. They are not stylistic:
each one has already cost something real.
"""

import hashlib

import pytest
import respx
from httpx import Response

from comfyfetch import auth, http, resolve


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


@respx.mock
def test_non_lfs_file_is_hashed_not_trusted():
    """A small non-LFS file's `x-linked-etag` is the GIT BLOB SHA-1, not a sha256.

    HuggingFace serves LFS files and plain git files through the same URL, and
    only the LFS ones carry a content sha256 in the etag. A `config.json` or
    `tokenizer.json` comes back with 40 hex characters -- git's
    `sha1("blob <len>\\0" + content)`, which is not a hash of the content alone
    and is not 64 wide. Recording it as the sha256 produced locks whose every
    JSON entry failed `fetch` with "sha256 mismatch": fetch hashes what it
    downloaded, and rightly refused to match a sha1 against it.

    Every model in the store was pure-LFS, so this stayed invisible until a
    manifest needed a model directory rather than a single weights file.
    """
    body = b'{"model_type": "florence2"}'
    blob = hashlib.sha1(b"blob %d\x00" % len(body) + body).hexdigest()
    assert len(blob) == 40

    respx.head("https://huggingface.co/o/r/resolve/main/config.json").mock(
        return_value=Response(200, headers={
            "x-repo-commit": "c" * 40,
            "x-linked-etag": f'"{blob}"',
        })
    )
    pinned = respx.get(f"https://huggingface.co/o/r/resolve/{'c' * 40}/config.json").mock(
        return_value=Response(200, content=body)
    )

    url, sha = resolve._hf("o/r", "main", "config.json", auth.AuthMap({}))

    assert sha == hashlib.sha256(body).hexdigest(), "trusted the git sha1 as a sha256"
    assert url == f"https://huggingface.co/o/r/resolve/{'c' * 40}/config.json"
    assert pinned.called, "hashed something other than the commit-pinned URL"


@respx.mock
def test_lfs_file_still_trusts_the_etag_and_downloads_nothing():
    """The 64-hex case must stay a HEAD. Hashing every LFS file to re-derive a
    sha256 the server already gave us would turn a resolve into a full download
    of the store.
    """
    sha256 = "d" * 64
    respx.head("https://huggingface.co/o/r/resolve/main/m.safetensors").mock(
        return_value=Response(200, headers={
            "x-repo-commit": "e" * 40,
            "x-linked-etag": f'"{sha256}"',
        })
    )
    body = respx.get(f"https://huggingface.co/o/r/resolve/{'e' * 64}/m.safetensors").mock(
        return_value=Response(200, content=b"never read")
    )

    _, sha = resolve._hf("o/r", "main", "m.safetensors", auth.AuthMap({}))

    assert sha == sha256
    assert not body.called, "downloaded an LFS file whose sha256 the etag already carried"
