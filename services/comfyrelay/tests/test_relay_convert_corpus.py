"""D8's test bar for the mcp-convert image (#167), over every open template the pinned ComfyUI serves.

tests/relay/corpus.sh runs it: it boots a core-cpu with empty model and input folders mounted from the host and
tests/relay/validate_only.py loaded, starts the mcp-convert image beside it, and sets the environment below.
Skipped without COMFYRELAY_CORPUS_RELAY_URL.

The templates are those the index doesn't mark as partner templates (openSource false).

1. Placeholders, before anything converts. Every model a template declares becomes an empty file in its folder,
   and every file a loader names (LoadImage, LoadImageMask, LoadAudio, LoadVideo, muted ones included) a small
   real one: an image, the clip in tests/data for a video (so its preview loads, as a real input's would), a short
   WAV. The lists are the relay's own (tools_introspection), so ComfyUI's validation passes on names.
2. The relay converts each one: workflow_validate given the UI graph converts it with the instance's frontend
   and returns the API graph it checked, which must pass that check.
3. The oracle: the frontend's own Export (API) in a plain browser tab, a fresh context each, once every
   LoadVideo's `video-preview` widget exists (test_relay_convert_live.export with EXPORT_AFTER_PREVIEWS, not a
   network-quiet wait). The relay's graph must be the same, but for floats that differ only in rounding (the
   frontend's own run-to-run noise in a 3D camera position); the report lists those. A template the frontend
   itself fails to export must fail in the relay as conversion_failed, and nothing else may.
4. ComfyUI accepts the converted graph: /prompt answers 200 with no node errors. The prompt is marked
   validate-only, so validate_only.py keeps it off the queue and nothing runs. REFUSED_UPSTREAM lists the
   templates ComfyUI refuses even as the editor exports them; a listed one it accepts fails the run.

This checks our converter against the frontend, and what it returns against ComfyUI; the frontend and ComfyUI
are the reference, not under test. corpus.json in COMFYRELAY_CORPUS_OUT has every template's outcome.

    COMFYRELAY_CORPUS_RELAY_URL     the relay's MCP endpoint, http://127.0.0.1:<port>/mcp
    COMFYRELAY_CORPUS_TOKEN         its bearer token
    COMFYRELAY_LIVE_COMFYUI_URL     the ComfyUI it converts against
    COMFYRELAY_CORPUS_MODELS        the host folder mounted as that ComfyUI's /app/models
    COMFYRELAY_CORPUS_INPUT         the host folder mounted as its /app/input
    COMFYRELAY_CORPUS_OUT           where corpus.json goes
    COMFYRELAY_CORPUS_CALLS         relay calls at once (default 4)
    COMFYRELAY_CORPUS_TABS          oracle tabs at once (default 4)
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import struct
import time
import zlib
from pathlib import Path
from typing import Any

import httpx2
import pytest
from comfyrelay.tools_introspection import _declared_models, _loader_inputs
from test_relay_convert_live import EXPORT_AFTER_PREVIEWS, PREVIEW_CLIP, URL, export, templates

RELAY = os.environ.get("COMFYRELAY_CORPUS_RELAY_URL", "")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not (RELAY and URL), reason="COMFYRELAY_CORPUS_RELAY_URL is not set (tests/relay/corpus.sh)"),
]

# Open templates ComfyUI refuses as the editor itself exports them, at the pin (v0.38.0, templates 0.11.70). The
# relay must still match the editor's export of each. The subgraph instance's widgets_values (a legacy list, no
# proxyWidgets) land on the wrong promoted widgets, so the loaders get ckpt_name 'person' and unet_name 2.
REFUSED_UPSTREAM = {
    "utility_sdpose_multi_person": "the frontend puts subgraph 675's widget values on the wrong inputs",
    "utility_sdpose_multi_person_video": "the frontend puts subgraph 675's widget values on the wrong inputs",
    "video_minimax_h3_fun_controlnet_union": "the frontend puts subgraph 700's widget values on the wrong inputs",
}
VALIDATE_ONLY = "comfyrelay_validate_only"  # tests/relay/validate_only.py's MARK
VIDEO = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
AUDIO = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}
ANNOTATION = re.compile(r" \[(input|output|temp)\]$")


def _png() -> bytes:
    """An 8x8 grey PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\0" + b"\x80\x80\x80" * 8 for _ in range(8))
    ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _wav() -> bytes:
    """A tenth of a second of 8 kHz 16-bit mono silence."""
    data = b"\0\0" * 800
    fmt = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
    body = b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _input_bytes(name: str) -> bytes:
    suffix = Path(name).suffix.lower()
    if suffix in VIDEO:
        return Path(PREVIEW_CLIP).read_bytes()
    return _wav() if suffix in AUDIO else _png()


def _place(root: Path, name: str, data: bytes) -> bool:
    """Write a placeholder at `name` under `root` unless one is there. A name is template data, so one that would
    land outside `root` fails the run."""
    path = (root / name).resolve()
    assert path.is_relative_to(root.resolve()), f"a template names a file outside its folder: {name!r}"
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def _all_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Every node, muted and bypassed ones too, at the top level and in every subgraph definition."""
    graphs = [workflow, *((workflow.get("definitions") or {}).get("subgraphs") or [])]
    return [n for g in graphs for n in g.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("type"), str)]


def _same(a: Any, b: Any) -> bool:
    """Equal as JSON, but for floats within 1e-9 of each other (relative): rounding, never a different value."""
    if isinstance(a, float) or isinstance(b, float):
        numbers = all(isinstance(x, int | float) and not isinstance(x, bool) for x in (a, b))
        return numbers and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_same, a, b))
    return type(a) is type(b) and a == b


def _difference(got: dict[str, Any], want: dict[str, Any]) -> str:
    """Where two API graphs first differ, briefly."""
    if got.keys() != want.keys():
        only_got, only_want = sorted(got.keys() - want.keys())[:5], sorted(want.keys() - got.keys())[:5]
        return f"node ids only in the relay's {only_got}, only in the oracle's {only_want}"
    for node_id in want:
        g, w = got[node_id], want[node_id]
        if _same(g, w):
            continue
        if g.get("class_type") != w.get("class_type"):
            return f"node {node_id}: class_type {g.get('class_type')!r}, the oracle's {w.get('class_type')!r}"
        gi, wi = g.get("inputs") or {}, w.get("inputs") or {}
        for key in sorted(gi.keys() | wi.keys()):
            gv, wv = gi.get(key, "<absent>"), wi.get(key, "<absent>")
            if not _same(gv, wv):
                return f"node {node_id} ({w.get('class_type')}) input {key!r}: {gv!r:.150}, the oracle's {wv!r:.150}"
        return f"node {node_id}: outside its inputs"
    return "no difference"


def _video_previews(graph: dict[str, Any]) -> int:
    return sum(
        n.get("class_type") == "LoadVideo" and "video-preview" in (n.get("inputs") or {}) for n in graph.values()
    )


async def test_every_open_template_converts_as_the_editor_exports_it_and_comfyui_accepts_it():
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    models = Path(os.environ["COMFYRELAY_CORPUS_MODELS"])
    inputs = Path(os.environ["COMFYRELAY_CORPUS_INPUT"])
    out = Path(os.environ.get("COMFYRELAY_CORPUS_OUT", "."))
    calls = int(os.environ.get("COMFYRELAY_CORPUS_CALLS", "4"))
    tabs = int(os.environ.get("COMFYRELAY_CORPUS_TABS", "4"))
    token = os.environ["COMFYRELAY_CORPUS_TOKEN"]
    timings: dict[str, float] = {}
    t0 = time.monotonic()

    corpus = dict(await templates(limit=None, max_chars=math.inf))
    assert corpus, "ComfyUI serves no open template"
    assert not REFUSED_UPSTREAM.keys() - corpus.keys(), f"no longer served: {REFUSED_UPSTREAM.keys() - corpus.keys()}"

    # 1. Placeholders.
    placed = {"models": 0, "inputs": 0}
    for workflow in corpus.values():
        nodes = _all_nodes(workflow)
        for m in _declared_models(nodes):
            placed["models"] += _place(models / m["directory"], m["name"], b"")
        for _, _, value in _loader_inputs(nodes):
            file = ANNOTATION.sub("", value)
            placed["inputs"] += _place(inputs, file, _input_bytes(file))
    timings["templates_and_placeholders"] = time.monotonic() - t0

    # 2. The relay's conversions, then 3. the oracle's exports: one after the other, so neither starves the other's
    # preview loads.
    report: dict[str, dict[str, Any]] = {name: {} for name in corpus}
    t = time.monotonic()
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=180) as http:
        transport = streamable_http_client(RELAY, http_client=http)
        async with Client(transport, mode="legacy", read_timeout_seconds=180) as mcp:
            slots = asyncio.Semaphore(calls)

            async def convert(name: str) -> None:
                async with slots:
                    result = await mcp.call_tool("workflow_validate", {"workflow": corpus[name]})
                if result.is_error:
                    text = result.content[0].text if result.content else ""
                    try:
                        report[name]["relay_error"] = json.loads(text[text.index("{") :])["error"]
                    except (ValueError, KeyError):
                        report[name]["relay_error"] = {"code": "unparsed", "message": text[:500]}
                else:
                    report[name]["relay"] = result.structured_content

            await asyncio.gather(*(convert(name) for name in corpus))
    timings["relay"] = time.monotonic() - t
    t = time.monotonic()
    oracle = dict(zip(corpus, await export(list(corpus.values()), EXPORT_AFTER_PREVIEWS, tabs=tabs), strict=True))
    timings["oracle"] = time.monotonic() - t

    # 4. Compare, and have ComfyUI validate what matched.
    t = time.monotonic()
    async with httpx2.AsyncClient(base_url=URL, timeout=120) as comfyui:
        for name, entry in report.items():
            relay, error, want = entry.pop("relay", None), entry.pop("relay_error", None), oracle[name]
            if isinstance(want, Exception):
                entry["oracle_error"] = str(want).splitlines()[0][:300]
                if error and error.get("code") == "conversion_failed":
                    entry["result"] = "frontend_fails_too"
                else:
                    did = f"failed with {error.get('code')}" if error else "converted it"
                    entry.update(result="fail", why=f"the frontend's own export fails, and the relay {did}")
                continue
            if error:
                entry.update(result="fail", why=f"the relay failed with {error.get('code')}: {error.get('message')}")
                continue
            if not relay.get("converted_from_ui"):
                entry.update(result="fail", why="workflow_validate did not convert it")
                continue
            if relay.get("workflow") is None:
                entry.update(result="too_large", why=relay.get("workflow_omitted"))
                continue
            got = relay["workflow"]
            if not _same(got, want):
                entry.update(result="fail", why="differs from the frontend's export: " + _difference(got, want))
                continue
            entry["rounding_only"] = got != want
            entry["video_previews"] = _video_previews(got)
            if not relay["valid"]:
                entry.update(result="fail", why=f"the relay's workflow_validate refused it: {relay['errors']}")
                continue
            answer = await comfyui.post("/prompt", json={"prompt": got, "extra_data": {VALIDATE_ONLY: True}})
            body = answer.json()
            refused = answer.status_code != 200 or bool(body.get("node_errors"))
            if refused != (name in REFUSED_UPSTREAM):
                why = (
                    f"ComfyUI refused it ({answer.status_code}): "
                    + json.dumps({"error": body.get("error"), "node_errors": body.get("node_errors")})[:2000]
                    if refused
                    else "ComfyUI accepts it now: remove it from REFUSED_UPSTREAM"
                )
                entry.update(result="fail", why=why)
                continue
            entry["result"] = "refused_upstream" if refused else "pass"
    timings["comfyui"] = time.monotonic() - t

    def named(result: str, key: str = "result") -> list[str]:
        return sorted(n for n, e in report.items() if e.get(key) == result)

    summary = {
        "open_templates": len(corpus),
        "identical_and_accepted": len(named("pass")),
        "of_those_equal_but_for_float_rounding": named(True, "rounding_only"),
        "refused_upstream": named("refused_upstream"),
        "frontend_fails_too": named("frontend_fails_too"),
        "too_large_to_return": named("too_large"),
        "failed": named("fail"),
        "carry_video_preview": sum(1 for e in report.values() if e.get("video_previews")),
        "placeholders_written": placed,
        "seconds": {k: round(v, 1) for k, v in timings.items()} | {"total": round(time.monotonic() - t0, 1)},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "corpus.json").write_text(json.dumps({"summary": summary, "templates": report}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    assert not summary["failed"], json.dumps({n: report[n]["why"] for n in summary["failed"]}, indent=1)
    # The settle wait is checked only on graphs whose preview loaded: if no placeholder video loaded, none did.
    assert summary["carry_video_preview"], "no conversion carries a LoadVideo video-preview input"
