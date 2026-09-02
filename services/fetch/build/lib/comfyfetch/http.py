"""HTTP with the redirect behaviour this tool needs.

`urllib` forwards every header except content-length and content-type across a
redirect, INCLUDING `Authorization`, and including a redirect to a different
host. curl strips credentials on a cross-host redirect and offers
`--location-trusted` to opt back in; this restores that behaviour.

It is not academic. HuggingFace answers `/resolve/` with a 302 to
`*.cdn.hf.co` — a different host — so a gated download would otherwise send the
account token to the CDN on every request. The CDN URL is already signed and
needs no credential.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "comfyfetch/1.0 (+https://github.com/pixeloven/ComfyUI-Docker)"


def _origin(url: str) -> tuple[str, str, int | None]:
    """Scheme, host and port — what curl compares before forwarding a credential.

    Host alone is not enough: a redirect to a different PORT on the same host is
    a different origin, and treating it as the same is how a token reaches a
    service that should not see it.
    """
    parts = urllib.parse.urlsplit(url)
    default = {"http": 80, "https": 443}.get(parts.scheme)
    return (parts.scheme, (parts.hostname or "").lower(), parts.port or default)


class _StripAuthOnCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if _origin(req.full_url) != _origin(newurl):
            new.headers = {
                k: v for k, v in new.headers.items() if k.lower() != "authorization"
            }
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_opener = urllib.request.build_opener(_StripAuthOnCrossHostRedirect)


def request(url: str, *, token: str | None = None, method: str = "GET",
            timeout: int = 60):
    """Open a URL, optionally authenticated. Caller closes the response."""
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _opener.open(
        urllib.request.Request(url, headers=headers, method=method), timeout=timeout
    )


def head_headers(url: str, *, token: str | None = None, timeout: int = 30) -> dict[str, str]:
    """Headers from the FIRST hop only, never following the redirect.

    `x-linked-etag` is the file's sha256 — but only here. Following the redirect
    returns the CDN's Xet content-address, a different and equally
    plausible-looking 64-hex value. Four wrong hashes were produced that way
    before it was caught by downloading a file and hashing it.
    """
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="HEAD")
    # A bare opener: no redirect handler at all, so a 3xx surfaces as an error
    # carrying the headers we want rather than being followed.
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        return {k.lower(): v for k, v in exc.headers.items()}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None
