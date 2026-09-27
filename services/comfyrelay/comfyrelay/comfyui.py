"""A small async client for the one ComfyUI this relay serves.

It is the only thing in comfyrelay that makes an outbound request, and it only
ever talks to `COMFYUI_URL`: no redirects are followed, so a response cannot
send it anywhere else.

Every failure is a `ComfyUIError` with a stable code, which a tool can let
propagate as a structured MCP error:

    comfyui_unreachable   nothing answered (connection refused, DNS, reset)
    comfyui_timeout       it answered too slowly
    comfyui_http_error    it answered with a 4xx or 5xx (`status` is included)
    comfyui_bad_response  it answered 2xx with a body that cannot be read
                          (corrupt compression), that is not JSON, or that is
                          JSON of the wrong shape for that endpoint

Messages name ComfyUI's URL with any user:password in it redacted.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx2

from .errors import RelayError
from .settings import redact_url

# /object_info is several MB on an install with many custom nodes, so reads get
# more time than connects. A connect that takes seconds means it is not there.
DEFAULT_TIMEOUT = httpx2.Timeout(30.0, connect=5.0)


class ComfyUIError(RelayError):
    pass


class ComfyUIClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx2.Timeout = DEFAULT_TIMEOUT,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._shown_url = redact_url(self.base_url)
        self._http = httpx2.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def system_stats(self) -> dict[str, Any]:
        """GET /system_stats: ComfyUI's version, Python, PyTorch and devices."""
        data = await self._get_json("/system_stats")
        if not isinstance(data.get("system"), dict):
            raise self._bad_shape("/system_stats", 'an object with a "system" object')
        return data

    async def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        """GET /object_info, or /object_info/<class> for one node class."""
        path = "/object_info" if node_class is None else f"/object_info/{quote(node_class, safe='')}"
        return await self._get_json(path)

    def _bad_shape(self, path: str, expected: str) -> ComfyUIError:
        return ComfyUIError(
            "comfyui_bad_response", f"ComfyUI answered {self._shown_url}{path} with JSON that is not {expected}"
        )

    async def _get_json(self, path: str) -> dict[str, Any]:
        """The JSON object at `path`. Every endpoint this client reads answers with an object."""
        url = f"{self._shown_url}{path}"
        try:
            response = await self._http.get(path)
        except httpx2.TimeoutException as exc:
            raise ComfyUIError("comfyui_timeout", f"ComfyUI did not answer {url} in time", retryable=True) from exc
        except httpx2.TransportError as exc:
            raise ComfyUIError(
                "comfyui_unreachable",
                f"could not reach ComfyUI at {self._shown_url}: {exc}",
                retryable=True,
            ) from exc
        except httpx2.RequestError as exc:  # the rest: a body that will not decode, say
            raise ComfyUIError(
                "comfyui_bad_response", f"ComfyUI answered {url} with a body that could not be read: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise ComfyUIError(
                "comfyui_http_error",
                f"ComfyUI answered {url} with HTTP {response.status_code}",
                retryable=response.status_code >= 500,
                status=response.status_code,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ComfyUIError(
                "comfyui_bad_response", f"ComfyUI answered {url} with something that is not JSON"
            ) from exc
        if not isinstance(data, dict):
            raise self._bad_shape(path, "an object")
        return data
