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

    async def _get_json(self, path: str, *, expect: type[dict | list] = dict) -> Any:
        """The JSON at `path`: an object, or an array for the few endpoints that answer with one (`expect=list`)."""
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
        if not isinstance(data, expect):
            raise self._bad_shape(path, "an object" if expect is dict else "an array")
        return data

    # -- introspection (#133): model folders and workflow templates ------------
    #
    # Templates come from the running ComfyUI, not from a package in this
    # image: ComfyUI v0.37.0 serves the comfyui-workflow-templates package it
    # pins at /templates/{path} (server.py, FrontendManager.template_asset_handler),
    # and the frontend reads /templates/index.json from there.

    async def model_folders(self) -> list[str]:
        """GET /models: the model folder types ComfyUI knows (checkpoints, loras, vae, ...)."""
        return self._strings("/models", await self._get_json("/models", expect=list))

    async def model_files(self, folder: str) -> list[str]:
        """GET /models/<folder>: the files ComfyUI finds for one folder type. HTTP 404 for a folder it doesn't know."""
        path = f"/models/{quote(folder, safe='')}"
        return self._strings(path, await self._get_json(path, expect=list))

    async def templates_index(self) -> list[dict[str, Any]]:
        """GET /templates/index.json: the template categories, each with its `templates`, as the frontend reads them."""
        data = await self._get_json("/templates/index.json", expect=list)
        if not all(isinstance(c, dict) and isinstance(c.get("templates", []), list) for c in data):
            raise self._bad_shape("/templates/index.json", "an array of categories with a templates array")
        return data

    async def template(self, name: str) -> dict[str, Any]:
        """GET /templates/<name>.json: one template's workflow, in the frontend's (UI) format."""
        path = f"/templates/{quote(name, safe='')}.json"
        data = await self._get_json(path)
        if not isinstance(data.get("nodes"), list):
            raise self._bad_shape(path, 'a workflow with a "nodes" array')
        return data

    def _strings(self, path: str, data: list[Any]) -> list[str]:
        if not all(isinstance(x, str) for x in data):
            raise self._bad_shape(path, "an array of strings")
        return data
