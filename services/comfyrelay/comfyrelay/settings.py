"""Configuration, from the environment. The names follow the `mcp` image.

    COMFYUI_MCP_HTTP_TOKEN  REQUIRED, at least 32 characters. Clients send it as
                            `Authorization: Bearer <token>` or `X-API-Key:
                            <token>`. The server refuses to start without one,
                            or with a shorter one.
    COMFYUI_URL             where ComfyUI answers, from this container
                            (default http://localhost:8188)
    MCP_HOST, MCP_PORT      the listen address (default 0.0.0.0:9000); the
                            endpoint is always /mcp
    COMFYUI_MCP_PROFILES    comma-separated capability profiles (default
                            read,run)
    COMFYUI_MCP_INSTANCE_ID how server_info names this sidecar (default: the
                            hostname, which is the container or pod name;
                            server_info says which, and startup warns)
    COMFYUI_MCP_MAX_JOBS    how many jobs may be in flight at once (default
                            16); a submission past it is refused
    COMFYUI_MCP_MAX_LARGE_REQUESTS
                            how many POST requests with a body over 1 MiB are
                            handled at once (default 2); the rest wait
                            briefly, then get a retryable 503 (server.py)
    COMFYUI_VERSION         the ComfyUI version the image was built for. The
                            image sets it from the bake pin, as the ComfyUI
                            images do; nobody else needs to.
    COMFYUI_MCP_DOCS        the docs index docs_search and docs_guide read
                            (default /opt/docs/docs.sqlite, where the image
                            builds it); without one those tools say so

The token, ComfyUI and listen variables are the ones the `mcp` image read
before 5.0.0, when it packaged artokun/comfyui-mcp, so a deployment keeps them
across the switch to comfyrelay (#136).
"""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

TOKEN_ENV = "COMFYUI_MCP_HTTP_TOKEN"
PROFILES_ENV = "COMFYUI_MCP_PROFILES"
INSTANCE_ID_ENV = "COMFYUI_MCP_INSTANCE_ID"
MAX_JOBS_ENV = "COMFYUI_MCP_MAX_JOBS"
MAX_LARGE_REQUESTS_ENV = "COMFYUI_MCP_MAX_LARGE_REQUESTS"
DOCS_ENV = "COMFYUI_MCP_DOCS"
DEFAULT_DOCS = "/opt/docs/docs.sqlite"
DEFAULT_MAX_JOBS = 16
DEFAULT_MAX_LARGE_REQUESTS = 2
# The shortest token the server starts with (owner decision on #136): 32
# characters is 128 bits as hex, and `openssl rand -hex 32` gives 64.
MIN_TOKEN_CHARS = 32
DEFAULT_COMFYUI_URL = "http://localhost:8188"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9000
MCP_PATH = "/mcp"
DEFAULT_PROBE_URL = f"http://127.0.0.1:{DEFAULT_PORT}{MCP_PATH}"

# Decision 6 of #103. Order is the order of trust: each one reaches further.
PROFILES = ("read", "run", "manage")
DEFAULT_PROFILES = ("read", "run")


class ConfigError(ValueError):
    """The configuration cannot work. The CLI reports it and exits 2."""


def redact_url(url: str) -> str:
    """`url` with any user:password replaced by `***`, for logs and messages.

    COMFYUI_URL may carry credentials for a proxy in front of ComfyUI. They
    are still sent; they are never rendered. Everything up to the LAST `@`
    after the scheme is replaced, without parsing: a password containing an
    unencoded `/`, `?` or `#` ends a parser's idea of the host early, which
    would leave the `@` and the password outside it. Over-redacting a URL
    whose path has an `@` is the safe way to be wrong.
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        scheme, rest = "", url
    if "@" not in rest:
        return url
    return f"{scheme}{sep}***@{rest.rpartition('@')[2]}"


def check_comfyui_url(url: str) -> str:
    """An http(s) URL with a host and a valid port, or a ConfigError that says why.

    Every message shows the URL redacted.
    """
    import httpx2  # here, not at the top: `comfyctl --help` imports this module

    shown = redact_url(url)

    def invalid(exc: Exception) -> ConfigError:
        # A parser's message can quote part of the URL; redact it the same way.
        return ConfigError(f"COMFYUI_URL {shown!r} is not a valid URL: {redact_url(str(exc))}")

    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise invalid(exc) from None
    # Before the port is parsed: with an '@' outside the netloc, the "port" is
    # part of the password, and its parse error would quote it.
    if url.count("@") != parts.netloc.count("@"):
        raise ConfigError(
            f"COMFYUI_URL {shown!r} has an '@' outside its host part. If it carries credentials, "
            "percent-encode any '/', '?', '#' or '@' in them (for example '/' as %2F)."
        )
    try:
        _ = parts.port  # raises ValueError on a bad port
        httpx2.URL(url)  # what the client will make of it: IDNA, and the rest of its rules
    except (ValueError, httpx2.InvalidURL) as exc:
        raise invalid(exc) from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError(
            f"COMFYUI_URL {shown!r} must be an http:// or https:// URL with a host, such as {DEFAULT_COMFYUI_URL}"
        )
    return url


def check_token(token: str) -> str:
    """The token, if it can be sent in an HTTP header: visible ASCII only.

    A space, a line break, a control or a non-ASCII character would make every
    client's request invalid, so no client could ever authenticate. The error
    never shows the value.
    """
    if not _TOKEN_CHARS.fullmatch(token):
        raise ConfigError(
            f"{TOKEN_ENV} contains a character that cannot be sent in an HTTP header (a space, a line "
            "break, a control or a non-ASCII character). Use visible ASCII only, for example the output "
            "of `openssl rand -hex 32`."
        )
    return token


_TOKEN_CHARS = re.compile(r"[\x21-\x7e]+")


def parse_profiles(value: str) -> tuple[str, ...]:
    """`read, run` -> ("read", "run"), in canonical order. Unknown names are an error."""
    names = {p.strip().lower() for p in value.split(",") if p.strip()}
    if not names:
        raise ConfigError(f"no profile selected; choose from {', '.join(PROFILES)}")
    if "develop" in names:  # declined (#107, D6): say so, rather than "unknown"
        raise ConfigError(
            f"profile develop isn't available in this image; choose from {', '.join(PROFILES)}. "
            "To develop custom nodes, see https://github.com/pixeloven/ComfyUI-Docker/issues/107"
        )
    unknown = sorted(names - set(PROFILES))
    if unknown:
        raise ConfigError(f"unknown profile {', '.join(unknown)}; choose from {', '.join(PROFILES)}")
    return tuple(p for p in PROFILES if p in names)


@dataclass(frozen=True)
class Settings:
    # Never in the repr: a traceback that shows locals must not show either.
    token: str = field(repr=False)
    comfyui_url: str = field(default=DEFAULT_COMFYUI_URL, repr=False)  # may carry credentials
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    profiles: tuple[str, ...] = DEFAULT_PROFILES
    instance_id: str = ""
    # "env" when COMFYUI_MCP_INSTANCE_ID set it, "hostname" when it defaulted.
    instance_id_source: Literal["env", "hostname"] = "env"
    comfyui_pin: str | None = None
    max_jobs: int = DEFAULT_MAX_JOBS
    max_large_requests: int = DEFAULT_MAX_LARGE_REQUESTS
    docs_path: str = DEFAULT_DOCS

    @classmethod
    def load(
        cls,
        *,
        comfyui_url: str,
        host: str,
        port: int,
        profiles: str,
        env: Mapping[str, str] = os.environ,
    ) -> Settings:
        """Settings from CLI options (which read their own env vars) plus the env-only ones."""
        token = env.get(TOKEN_ENV, "").strip()
        if not token:
            raise ConfigError(
                f"Refusing to start: {TOKEN_ENV} is not set. This server listens on the network, "
                "and without a token anyone who can reach it could use it. Set it to a long "
                "random secret (for example `openssl rand -hex 32`) from your secret store."
            )
        check_token(token)
        if len(token) < MIN_TOKEN_CHARS:
            # The length only, never the value.
            raise ConfigError(
                f"Refusing to start: {TOKEN_ENV} is {len(token)} characters, and it must be at least "
                f"{MIN_TOKEN_CHARS}. Generate one with `openssl rand -hex 32` and keep it in your secret store."
            )
        if not 0 < port < 65536:
            raise ConfigError(f"port {port} is out of range")
        instance_id = env.get(INSTANCE_ID_ENV, "").strip()
        return cls(
            token=token,
            comfyui_url=check_comfyui_url(comfyui_url),
            host=host,
            port=port,
            profiles=parse_profiles(profiles),
            instance_id=instance_id or socket.gethostname(),
            instance_id_source="env" if instance_id else "hostname",
            comfyui_pin=env.get("COMFYUI_VERSION", "").strip() or None,
            max_jobs=_at_least_one(env, MAX_JOBS_ENV, DEFAULT_MAX_JOBS),
            max_large_requests=_at_least_one(env, MAX_LARGE_REQUESTS_ENV, DEFAULT_MAX_LARGE_REQUESTS),
            docs_path=env.get(DOCS_ENV, "").strip() or DEFAULT_DOCS,
        )


def _at_least_one(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip() or str(default)
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ConfigError(f"{name}={raw!r} must be a whole number of at least 1")
    return value
