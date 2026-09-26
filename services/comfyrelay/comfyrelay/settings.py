"""Configuration, from the environment. The names follow the `mcp` image.

    COMFYUI_MCP_HTTP_TOKEN  REQUIRED. Clients send it as `Authorization: Bearer
                            <token>` or `X-API-Key: <token>`. The server
                            refuses to start without one.
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
    COMFYUI_VERSION         the ComfyUI version the image was built for. The
                            image sets it from the bake pin, as the ComfyUI
                            images do; nobody else needs to.

The token and ComfyUI variables are the ones the `mcp` image already reads, so
a deployment keeps its environment when comfyrelay replaces the server in that
image (#136).
"""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

TOKEN_ENV = "COMFYUI_MCP_HTTP_TOKEN"
PROFILES_ENV = "COMFYUI_MCP_PROFILES"
INSTANCE_ID_ENV = "COMFYUI_MCP_INSTANCE_ID"
MAX_JOBS_ENV = "COMFYUI_MCP_MAX_JOBS"
DEFAULT_MAX_JOBS = 16
DEFAULT_COMFYUI_URL = "http://localhost:8188"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9000
MCP_PATH = "/mcp"
DEFAULT_PROBE_URL = f"http://127.0.0.1:{DEFAULT_PORT}{MCP_PATH}"

# Decision 6 of #103. Order is the order of trust: each one reaches further.
PROFILES = ("read", "run", "manage", "develop")
DEFAULT_PROFILES = ("read", "run")


class ConfigError(ValueError):
    """The configuration cannot work. The CLI reports it and exits 2."""


def redact_url(url: str) -> str:
    """`url` with any user:password replaced by `***`, for logs and messages.

    COMFYUI_URL may carry credentials for a proxy in front of ComfyUI. They
    are still sent; they are never rendered. Anything that does not parse is
    replaced whole, since it cannot be shown safely.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url if "@" not in url else "<unparseable URL>"
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc="***@" + parts.netloc.rpartition("@")[2]))


def check_comfyui_url(url: str) -> str:
    """An http(s) URL with a host and a valid port, or a ConfigError that says why."""
    try:
        parts = urlsplit(url)
        _ = parts.port  # raises ValueError on a bad port
    except ValueError as exc:
        raise ConfigError(f"COMFYUI_URL {redact_url(url)!r} is not a valid URL: {exc}") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError(
            f"COMFYUI_URL {redact_url(url)!r} must be an http:// or https:// URL with a host, "
            f"such as {DEFAULT_COMFYUI_URL}"
        )
    return url


def parse_profiles(value: str) -> tuple[str, ...]:
    """`read, run` -> ("read", "run"), in canonical order. Unknown names are an error."""
    names = {p.strip().lower() for p in value.split(",") if p.strip()}
    if not names:
        raise ConfigError(f"no profile selected; choose from {', '.join(PROFILES)}")
    unknown = sorted(names - set(PROFILES))
    if unknown:
        raise ConfigError(f"unknown profile {', '.join(unknown)}; choose from {', '.join(PROFILES)}")
    return tuple(p for p in PROFILES if p in names)


@dataclass(frozen=True)
class Settings:
    # Never in the repr: a traceback that shows locals must not show it.
    token: str = field(repr=False)
    comfyui_url: str = DEFAULT_COMFYUI_URL
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    profiles: tuple[str, ...] = DEFAULT_PROFILES
    instance_id: str = ""
    # "env" when COMFYUI_MCP_INSTANCE_ID set it, "hostname" when it defaulted.
    instance_id_source: Literal["env", "hostname"] = "env"
    comfyui_pin: str | None = None
    max_jobs: int = DEFAULT_MAX_JOBS

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
        if not 0 < port < 65536:
            raise ConfigError(f"port {port} is out of range")
        instance_id = env.get(INSTANCE_ID_ENV, "").strip()
        raw_max_jobs = env.get(MAX_JOBS_ENV, "").strip() or str(DEFAULT_MAX_JOBS)
        try:
            max_jobs = int(raw_max_jobs)
        except ValueError:
            max_jobs = 0
        if max_jobs < 1:
            raise ConfigError(f"{MAX_JOBS_ENV}={raw_max_jobs!r} must be a whole number of at least 1")
        return cls(
            token=token,
            comfyui_url=check_comfyui_url(comfyui_url),
            host=host,
            port=port,
            profiles=parse_profiles(profiles),
            instance_id=instance_id or socket.gethostname(),
            instance_id_source="env" if instance_id else "hostname",
            comfyui_pin=env.get("COMFYUI_VERSION", "").strip() or None,
            max_jobs=max_jobs,
        )
