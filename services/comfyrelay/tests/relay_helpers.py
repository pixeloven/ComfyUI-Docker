"""Helpers the tests import. Uniquely named, because `import conftest` would be
ambiguous: services/fetch/tests has a conftest.py too, and one pytest run
collects both."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx2
from comfyrelay.comfyui import ComfyUIClient
from comfyrelay.jobs import SHUTDOWN_WAIT_SECONDS, JobState, JobStore
from comfyrelay.settings import Settings

TOKEN = "test-token-0123456789"
SYSTEM_STATS = {
    "system": {"os": "posix", "comfyui_version": "0.37.0", "python_version": "3.12.3"},
    "devices": [{"name": "cpu", "type": "cpu"}],
}


def comfyui_answering(routes: dict[str, httpx2.Response] | None = None) -> ComfyUIClient:
    """A ComfyUIClient whose ComfyUI answers from `routes` (path -> response), 404 otherwise."""
    routes = {"/system_stats": httpx2.Response(200, json=SYSTEM_STATS), **(routes or {})}

    def handler(request: httpx2.Request) -> httpx2.Response:
        return routes.get(request.url.raw_path.decode(), routes.get(request.url.path, httpx2.Response(404)))

    return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(handler))


def comfyui_raising(exc: Callable[[httpx2.Request], Exception]) -> ComfyUIClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise exc(request)

    return ComfyUIClient("http://comfyui.test:8188", transport=httpx2.MockTransport(handler))


def settings(**overrides) -> Settings:
    base = dict(
        token=TOKEN,
        comfyui_url="http://comfyui.test:8188",
        host="127.0.0.1",
        port=9000,
        profiles=("read", "run"),
        instance_id="test-instance",
        comfyui_pin="v0.37.0",
        corpus_path="/nonexistent/corpus.sqlite",
    )
    return Settings(**{**base, **overrides})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def serve_nothing(self, sockets=None) -> None:
    """Stands in for uvicorn.Server.serve: `serve()` runs everything but the listening."""


async def assert_producer_honours_cancel(
    work: Callable[[], Awaitable[Any]], *, started: asyncio.Event | None = None, within: float = SHUTDOWN_WAIT_SECONDS
) -> None:
    """The producer contract (comfyrelay/jobs.py): cancelled, a producer stops within
    SHUTDOWN_WAIT_SECONDS (3s, its budget when the server stops) by letting
    CancelledError propagate. Every job producer's tests call this with its real
    work, and with `started` if it has a point where it is well under way (set it
    there), so the cancel lands mid-work, not before it began. It cannot see into
    threads: work handed to one must be interruptible on its own (the contract's
    second rule).
    """
    store = JobStore(cancel_wait=within)
    job = store.submit("contract.check", work)
    if started is not None:
        await asyncio.wait_for(started.wait(), 10)
    else:
        await asyncio.sleep(0.05)
    assert not job.task.done(), "the producer finished before it could be cancelled; set `started` mid-work"
    await store.cancel(job.id)
    assert job.task.done(), f"the producer did not stop within {within}s of being cancelled"
    assert job.task.cancelled(), "the producer swallowed CancelledError; it must re-raise it"
    assert job.state is JobState.cancelled


def node_spec(outputs: tuple[str, ...] = (), *, output_node: bool = False, **fields: object) -> dict:
    """An /object_info entry with only what the workflow checks read: outputs, output_node, partner signals."""
    return {"input": {"required": {}}, "output": list(outputs), "output_node": output_node, **fields}


CREDENTIAL_INPUTS = {"auth_token_comfy_org": ["AUTH_TOKEN_COMFY_ORG"], "api_key_comfy_org": ["API_KEY_COMFY_ORG"]}

# The classes the workflow tests use, as v0.37.0's /object_info shapes them (output lists and the partner-API
# signals are copied from a real one; input specs are left out, since ComfyUI checks inputs, not the relay).
WORKFLOW_OBJECT_INFO = {
    "LoadImage": node_spec(("IMAGE", "MASK")),
    "ImageScale": node_spec(("IMAGE",)),
    "ImageInvert": node_spec(("IMAGE",)),
    "ImageToMask": node_spec(("MASK",)),
    "EmptyImage": node_spec(("IMAGE",)),
    "CustomCombo": node_spec(("STRING", "INT")),
    "SaveImage": node_spec(("IMAGE",), output_node=True),
    "PreviewImage": node_spec(("IMAGE",), output_node=True),
    "PreviewAny": node_spec(("STRING",), output_node=True),
    "ClaudeNode": node_spec(
        ("STRING",),
        api_node=True,
        python_module="comfy_api_nodes.nodes_anthropic",
        category="partner/text/Anthropic",
        input={"required": {}, "hidden": CREDENTIAL_INPUTS},
    ),
    "ByteDanceCreateImageAsset": node_spec(
        ("STRING", "STRING"),
        api_node=False,
        python_module="comfy_api_nodes.nodes_bytedance",
        category="partner/image/ByteDance",
        input={"required": {}, "hidden": CREDENTIAL_INPUTS},
    ),
}


DOCS_SHA = "0123456789abcdef0123456789abcdef01234567"
# A docs checkout in Comfy-Org/docs' shape: docs.json's English navigation (groups within tabs, an OpenAPI
# operation, a file name with a space), a page that imports a snippet that imports another, a page the
# navigation doesn't list, and a translation.
DOCS_FILES = {
    "docs.json": json.dumps(
        {
            "navigation": {
                "languages": [
                    {
                        "language": "en",
                        "tabs": [
                            {
                                "tab": "Development",
                                "pages": [
                                    {"group": "Server", "pages": ["development/server/messages", "GET /nodes"]},
                                    "built-in-nodes/Video Slice",
                                ],
                            }
                        ],
                    },
                    {"language": "zh", "tabs": [{"tab": "Dev", "pages": ["zh/development/server/messages"]}]},
                ]
            }
        }
    ),
    "LICENSE": "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n",
    "development/server/messages.mdx": """---
title: "Server Messages"
description: "What the server sends over the websocket."
---
import Reminder from "/snippets/reminder.mdx";

<Reminder />

## Built in message types

The server sends `executing` when a node starts, over the websocket.

<Tip>
  A message with `node` set to null means the prompt finished.
</Tip>
""",
    "built-in-nodes/Video Slice.mdx": "---\ntitle: Video Slice\n---\nCuts a clip out of a video.\n",
    "unlisted.mdx": "---\ntitle: Unlisted\n---\nNot in the navigation: quasar.\n",
    "zh/development/server/messages.mdx": "---\ntitle: Messages (zh)\n---\nTranslated: quasar.\n",
    "snippets/reminder.mdx": 'import Inner from "/snippets/inner.mdx";\n\n<Note>Keep ComfyUI updated.</Note>\n'
    "<Inner/>\n",
    "snippets/inner.mdx": "Nested snippet text.\n",
    "snippets/unused.mdx": "Never imported.\n",
}
SKILL_FILES = {
    "comfyui-workflows/SKILL.md": """---
name: comfyui-workflows
description: Guides.
---

# Working with ComfyUI workflows

- [workflow-formats](references/workflow-formats.md): UI vs API.
- [comfy-manifest](../comfy-manifest/SKILL.md): the manifest.
""",
    "comfyui-workflows/references/workflow-formats.md": """# Workflow formats

The editor saves the UI format; /prompt takes the API format.

## The relay

template_get returns the UI format, which workflow_run refuses.
""",
    "comfy-manifest/SKILL.md": """---
name: comfy-manifest
description: Author comfy.yaml and generate locks.
---

# Authoring comfy.yaml

Profiles compose by set union.
""",
}


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def make_corpus(root: Path) -> Path:
    """Build a corpus from DOCS_FILES and SKILL_FILES under `root`, as `comfyctl relay corpus build` does once
    its fetch is done. Returns the corpus.sqlite path; the rest of the build is beside it."""
    from comfyrelay.corpus import build

    docs = write_tree(root / "docs", DOCS_FILES)
    skills = write_tree(root / "skills", SKILL_FILES)
    build(docs=docs, sha=DOCS_SHA, skills=skills, out=root / "out", version="9.9.9")
    return root / "out" / "corpus.sqlite"
