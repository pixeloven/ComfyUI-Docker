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
                            hostname, which is the container or pod name)
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
from dataclasses import dataclass

TOKEN_ENV = "COMFYUI_MCP_HTTP_TOKEN"
PROFILES_ENV = "COMFYUI_MCP_PROFILES"
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
    token: str
    comfyui_url: str = DEFAULT_COMFYUI_URL
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    profiles: tuple[str, ...] = DEFAULT_PROFILES
    instance_id: str = ""
    comfyui_pin: str | None = None

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
        return cls(
            token=token,
            comfyui_url=comfyui_url,
            host=host,
            port=port,
            profiles=parse_profiles(profiles),
            instance_id=env.get("COMFYUI_MCP_INSTANCE_ID", "").strip() or socket.gethostname(),
            comfyui_pin=env.get("COMFYUI_VERSION", "").strip() or None,
        )
