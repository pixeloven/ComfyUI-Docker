"""HTTP, with the two behaviours this tool is actually correct about.

Both are httpx defaults or one argument away, which is the point: this module
was 86 lines of urllib implementing a custom redirect handler, and the handler's
entire job is something httpx does natively.

1. CREDENTIALS ARE STRIPPED ON A CROSS-ORIGIN REDIRECT. HuggingFace answers
   `/resolve/` with a 302 to `*.cdn.hf.co` -- a different host -- so forwarding
   `Authorization` would send the account token to a CDN on every gated
   download. The CDN URL is already signed and needs no credential. urllib
   forwards every header across a redirect including that one; httpx does not.

2. `head_headers` READS THE FIRST HOP ONLY. `x-linked-etag` is the file's
   sha256 -- but only there. Following the redirect returns the CDN's Xet
   content-address, a different and equally plausible-looking 64-hex value.
   Four wrong hashes were produced that way before someone downloaded a file
   and hashed it.

A THIRD THING THAT STOPS BEING POSSIBLE. Civitai returns 403 for the literal
`Python-urllib/3.12` and 200 for every other User-Agent tried, including a
lowercased one. That block silently failed 38 of 106 lookups in a downstream
audit and was misdiagnosed as "needs a bearer token" -- a wrong explanation of
a real symptom, which is worse than no explanation. A client that does not send
the stdlib's default UA cannot reproduce it.
"""

from __future__ import annotations

import importlib.metadata

import httpx

try:
    _VERSION = importlib.metadata.version("comfyfetch")
except importlib.metadata.PackageNotFoundError:  # running from a source tree
    _VERSION = "0"

USER_AGENT = f"comfyfetch/{_VERSION} (+https://github.com/pixeloven/ComfyUI-Docker)"


def _headers(token: str | None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class _Body:
    """A file-like view over a streaming httpx response.

    Callers do `json.load(resp)` and `resp.read(CHUNK)` in a loop, and httpx
    offers `iter_bytes()` rather than an incremental `read(n)`. Adapting here
    keeps every call site unchanged, which is what lets the existing suite prove
    the transport swap changed no behaviour.

    Buffered rather than accumulating: a multi-GiB model must stream to disk,
    so the whole body is never held.
    """

    def __init__(self, response: httpx.Response, client: httpx.Client) -> None:
        self._response = response
        self._client = client
        self._chunks = response.iter_bytes()
        self._buf = b""
        self.headers = {k.lower(): v for k, v in response.headers.items()}

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            rest = self._buf + b"".join(self._chunks)
            self._buf = b""
            return rest
        while len(self._buf) < size:
            try:
                self._buf += next(self._chunks)
            except StopIteration:
                break
        out, self._buf = self._buf[:size], self._buf[size:]
        return out

    def close(self) -> None:
        self._response.close()
        self._client.close()

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def request(
    url: str, *, token: str | None = None, method: str = "GET", timeout: int = 60
) -> _Body:
    """Open a URL, optionally authenticated. The caller closes it.

    Returned OPEN and streaming so a multi-GiB body never materialises in
    memory. `follow_redirects=True` is where httpx's cross-origin credential
    strip applies -- see `Client._redirect_headers`.
    """
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    try:
        response = client.send(
            client.build_request(method, url, headers=_headers(token)), stream=True
        )
        response.raise_for_status()
    except BaseException:
        client.close()
        raise
    return _Body(response, client)


def head_headers(url: str, *, token: str | None = None, timeout: int = 30) -> dict[str, str]:
    """Headers from the FIRST hop only, never following the redirect.

    `follow_redirects=False` is the whole implementation. A 3xx is a normal
    response here, not an error, so unlike the urllib version there is no
    except-branch reaching into an exception object for its headers.

    Lowercased because callers should not have to guess the case a server used.
    """
    with httpx.Client(follow_redirects=False, timeout=timeout) as client:
        response = client.head(url, headers=_headers(token))
    return {k.lower(): v for k, v in response.headers.items()}
