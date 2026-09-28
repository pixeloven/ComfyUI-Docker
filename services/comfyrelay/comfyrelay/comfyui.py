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


# What GET /api/jobs/<id> answers, with HTTP 404, for an id it does not know (v0.37.0, server.py get_job_by_id).
JOB_NOT_FOUND = {"error": "Job not found"}


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
        response = await self._send("GET", path)
        self._raise_for_status(response, path)
        return self._json_object(response, path, expect=expect)

    # Every request goes through these three, whatever the method: one mapping
    # of what can go wrong to the codes in this module's docstring.

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        """One request. A transport failure becomes a ComfyUIError; the caller judges the status."""
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx2.RequestError as exc:
            raise self._transport_error(exc, path) from exc

    def _transport_error(self, exc: httpx2.RequestError, path: str) -> ComfyUIError:
        url = f"{self._shown_url}{path}"
        if isinstance(exc, httpx2.TimeoutException):
            return ComfyUIError("comfyui_timeout", f"ComfyUI did not answer {url} in time", retryable=True)
        if isinstance(exc, httpx2.TransportError):
            return ComfyUIError(
                "comfyui_unreachable", f"could not reach ComfyUI at {self._shown_url}: {exc}", retryable=True
            )
        # the rest: a body that will not decode, say
        return ComfyUIError("comfyui_bad_response", f"ComfyUI answered {url} with a body that could not be read: {exc}")

    def _raise_for_status(self, response: httpx2.Response, path: str) -> None:
        if response.status_code >= 400:
            raise ComfyUIError(
                "comfyui_http_error",
                f"ComfyUI answered {self._shown_url}{path} with HTTP {response.status_code}",
                retryable=response.status_code >= 500,
                status=response.status_code,
            )

    def _json_object(self, response: httpx2.Response, path: str, *, expect: type[dict | list] = dict) -> Any:
        """The response's JSON, which must be an object (or, with `expect=list`, an array)."""
        try:
            data = response.json()
        except ValueError as exc:
            raise ComfyUIError(
                "comfyui_bad_response", f"ComfyUI answered {self._shown_url}{path} with something that is not JSON"
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

    # -- workflow runs (#132) -------------------------------------------------
    #
    # The calls the `workflow_*` tools make, in their own block. Transport
    # failures map to the same codes as above, and every call goes to
    # COMFYUI_URL and nowhere else.

    # How long each call made while cancelling a job may take. The producer
    # contract gives the whole unwind 3s (jobs.py), and tools_workflow bounds
    # the calls it makes then together at 2.5s.
    CANCEL_TIMEOUT = httpx2.Timeout(1.0)

    async def queue_prompt(self, graph: dict[str, Any], prompt_id: str, client_id: str | None = None) -> dict[str, Any]:
        """POST /prompt with our own prompt_id, and `client_id` when given. Returns ComfyUI's answer: prompt_id,
        number, node_errors.

        ComfyUI keeps `client_id` in the prompt's extra_data, which /queue and
        (once it has finished) /api/jobs/<id> and /history show: how a relay
        recognises its own prompt after a restart (tools_workflow.py). Never
        extra_data itself, which is how ComfyUI hands credentials to nodes.

        A 400 is ComfyUI refusing the graph: `workflow_rejected`, carrying
        ComfyUI's own error and its per-node errors.
        """
        body: dict[str, Any] = {"prompt": graph, "prompt_id": prompt_id}
        if client_id is not None:
            body["client_id"] = client_id
        response = await self._send("POST", "/prompt", json=body)
        if response.status_code == 400:
            body = self._json_object(response, "/prompt")
            error = body.get("error")
            error = error if isinstance(error, dict) else {"message": str(error)}
            details = f" ({error['details']})" if error.get("details") else ""
            raise ComfyUIError(
                "workflow_rejected",
                f"ComfyUI rejected the workflow: {error.get('message')}{details}",
                comfyui_error={k: error.get(k) for k in ("type", "message", "details")},
                node_errors=body.get("node_errors") or {},
            )
        self._raise_for_status(response, "/prompt")
        data = self._json_object(response, "/prompt")
        if not isinstance(data.get("prompt_id"), str):
            raise self._bad_shape("/prompt", 'an object with a "prompt_id" string')
        return data

    async def queue(self, *, cancelling: bool = False) -> dict[str, Any]:
        """GET /queue: {"queue_running": [...], "queue_pending": [...]}; each item starts [number, prompt_id].

        `cancelling` uses the short CANCEL_TIMEOUT.
        """
        response = await self._send("GET", "/queue", **({"timeout": self.CANCEL_TIMEOUT} if cancelling else {}))
        self._raise_for_status(response, "/queue")
        data = self._json_object(response, "/queue")
        if not all(isinstance(data.get(k), list) for k in ("queue_running", "queue_pending")):
            raise self._bad_shape("/queue", 'an object with "queue_running" and "queue_pending" lists')
        return data

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        """GET /history/<prompt_id>: that prompt's entry, or None while it has none."""
        path = f"/history/{quote(prompt_id, safe='')}"
        entry = (await self._get_json(path)).get(prompt_id)
        if entry is not None and not isinstance(entry, dict):
            raise self._bad_shape(path, "an object of history entries")
        return entry

    async def delete_queued(self, prompt_id: str) -> None:
        """POST /queue {"delete": [prompt_id]}: drop it if it is still waiting. A no-op otherwise."""
        response = await self._send("POST", "/queue", json={"delete": [prompt_id]}, timeout=self.CANCEL_TIMEOUT)
        self._raise_for_status(response, "/queue")

    async def cancel_job(self, prompt_id: str) -> bool | None:
        """POST /api/jobs/<id>/cancel: ComfyUI's atomic cancel. It dequeues the prompt if it is waiting and
        interrupts it if, and only if, it is the prompt running, under ComfyUI's queue lock.

        Returns whether ComfyUI dispatched a cancel (false: already finished,
        or unknown), or None when this ComfyUI has no jobs API. There is
        deliberately no /interrupt here: at v0.37.0 it checks the running
        prompt and interrupts outside the lock, and without a prompt id it
        stops whatever is running.
        """
        path = f"/api/jobs/{quote(prompt_id, safe='')}/cancel"
        response = await self._send("POST", path, timeout=self.CANCEL_TIMEOUT)
        if self._no_route(response):
            return None
        self._raise_for_status(response, path)
        return bool(self._json_object(response, path).get("cancelled"))

    async def job(self, prompt_id: str, *, cancelling: bool = False) -> dict[str, Any] | None:
        """GET /api/jobs/<id>: a small {"id", "status", ...} while the prompt is pending or in_progress (and
        the full entry once it is completed, failed or cancelled). None when ComfyUI does not know the id.

        Raises `jobs_api_unavailable` when this ComfyUI has no jobs API.
        """
        path = f"/api/jobs/{quote(prompt_id, safe='')}"
        response = await self._send("GET", path, **({"timeout": self.CANCEL_TIMEOUT} if cancelling else {}))
        if self._no_route(response):
            raise ComfyUIError("jobs_api_unavailable", f"ComfyUI at {self._shown_url} has no /api/jobs")
        if response.status_code == 404:
            if self._json_or_none(response) == JOB_NOT_FOUND:
                return None
            # A JSON 404 that is not ComfyUI's: a proxy, a gateway, something else answering for it.
            raise ComfyUIError(
                "comfyui_http_error",
                f"{self._shown_url}{path} answered HTTP 404 with a body that is not ComfyUI's job-not-found",
                status=404,
            )
        self._raise_for_status(response, path)
        data = self._json_object(response, path)
        if not isinstance(data.get("status"), str):
            raise self._bad_shape(path, 'an object with a "status" string')
        return data

    @staticmethod
    def _json_or_none(response: httpx2.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _no_route(response: httpx2.Response) -> bool:
        """ComfyUI (aiohttp) has no such route: a 405, or a 404 that is not ComfyUI's JSON "not found"."""
        if response.status_code == 405:
            return True
        return response.status_code == 404 and not response.headers.get("content-type", "").startswith(
            "application/json"
        )

    async def upload_input(self, filename: str, content: bytes, content_type: str) -> dict[str, Any]:
        """POST /upload/image into ComfyUI's input directory, never overwriting. Returns name, subfolder, type.

        With a name already taken ComfyUI stores the file as `name (1).ext`,
        unless the bytes are identical, when it keeps the one it has.
        """
        response = await self._send(
            "POST",
            "/upload/image",
            files={"image": (filename, content, content_type)},
            data={"type": "input", "overwrite": "false"},
        )
        self._raise_for_status(response, "/upload/image")
        data = self._json_object(response, "/upload/image")
        if not isinstance(data.get("name"), str):
            raise self._bad_shape("/upload/image", 'an object with a "name" string')
        return data

    async def view_size(self, ref: dict[str, str]) -> int | None:
        """HEAD /view for one file: its size in bytes, or None if ComfyUI does not say."""
        response = await self._send("HEAD", "/view", params=ref)
        self._raise_for_status(response, "/view")
        length = response.headers.get("content-length", "")
        return int(length) if length.isdigit() else None

    async def view_bytes(self, ref: dict[str, str], limit: int) -> tuple[bytes, str]:
        """GET /view for one file, reading no more than `limit` bytes. Returns (bytes, content type)."""
        try:
            async with self._http.stream("GET", "/view", params=ref) as response:
                self._raise_for_status(response, "/view")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ComfyUIError(
                            "output_too_large",
                            f"{ref.get('filename')} is larger than {limit} bytes, the most returned inline",
                            limit=limit,
                        )
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type", "application/octet-stream")
        except httpx2.RequestError as exc:
            raise self._transport_error(exc, "/view") from exc
