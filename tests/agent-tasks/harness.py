#!/usr/bin/env python3
"""Stdlib-only helpers shared by the harness's setup and check scripts.

Every check reads ComfyUI's HTTP API or the scratch filesystem, never an agent
transcript. Usage: harness.py <command> [args]; see COMMANDS at the bottom.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import sqlite3
import statistics
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = Path(os.environ.get("HARNESS_RESULTS") or HERE / "results")
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
DATA = Path(os.environ.get("HARNESS_DATA", "/tmp/comfyui-harness"))
# The agent's working directory. Its file tools are confined to it, so it
# cannot read answers.json or the ground-truth dump.
WORKSPACE = DATA / "workspace"
# What an external agent's client logged, one line per MCP request (servers/mcp_client.py).
CALLS_LOG = DATA / "mcp-calls.jsonl"

INPUT_IMAGE = "harness-input.png"


class CheckFailed(Exception):
    pass


# --- HTTP ---------------------------------------------------------------------


def http(method: str, path: str, body: object | None = None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(COMFY_URL + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def get(path: str) -> object:
    status, body = http("GET", path)
    if status != 200:
        raise CheckFailed(f"GET {path} returned HTTP {status}")
    return body


def history() -> dict:
    return get("/history?max_items=10000")  # type: ignore[return-value]


# --- History markers: "a NEW entry" means one not present when setup ran -------


def marker_path(task: str) -> Path:
    return RESULTS / f"{task}.history-before.json"


def outputs_marker(task: str) -> Path:
    return RESULTS / f"{task}.outputs-before.json"


def output_files() -> list[str]:
    root = DATA / "output"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def mark(task: str) -> None:
    """Record the /history entries and the output files that exist now, before the agent runs."""
    marker_path(task).write_text(json.dumps(sorted(history())))
    outputs_marker(task).write_text(json.dumps(output_files()))


def made_since_setup(task: str, img: dict) -> bool:
    """Whether an output file is one this task's run wrote: not there when setup marked.
    A run ComfyUI served from its execution cache reports the earlier run's file."""
    p = outputs_marker(task)
    if not p.exists():
        raise CheckFailed(f"no output marker for {task}; run tasks/{task}/setup.sh first")
    rel = str(Path(img.get("subfolder", "")) / img["filename"])
    return img.get("type", "output") == "output" and rel not in set(json.loads(p.read_text()))


def new_entries(task: str) -> dict:
    p = marker_path(task)
    if not p.exists():
        raise CheckFailed(
            f"no history marker for {task}; run tasks/{task}/setup.sh first"
        )
    before = set(json.loads(p.read_text()))
    return {k: v for k, v in history().items() if k not in before}


def completed(entry: dict) -> bool:
    st = entry.get("status") or {}
    return bool(st.get("completed")) and st.get("status_str") == "success"


def graph(entry: dict) -> dict:
    # A history entry's "prompt" is [number, prompt_id, graph, extra, outputs].
    return entry["prompt"][2]


def class_types(entry: dict) -> set[str]:
    return {n.get("class_type") for n in graph(entry).values()}


# --- PNG (write the input; read an output's size and pixels) ------------------


def write_png(path: Path, width: int, height: int) -> None:
    """A horizontal black-to-white gradient, 8-bit RGB."""
    rows = b"".join(
        b"\x00" + bytes(v for x in range(width) for v in (x * 255 // (width - 1),) * 3)
        for _ in range(height)
    )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        c = kind + payload
        return struct.pack(">I", len(payload)) + c + struct.pack(">I", zlib.crc32(c))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def read_png(path: Path) -> tuple[int, int, list[list[int]]]:
    """Width, height and per-row grey values of an 8-bit RGB/RGBA/grey PNG."""
    blob = path.read_bytes()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise CheckFailed(f"{path.name} is not a PNG")
    pos, idat, ihdr = 8, b"", None
    while pos < len(blob):
        (length,) = struct.unpack(">I", blob[pos : pos + 4])
        kind, payload = blob[pos + 4 : pos + 8], blob[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat += payload
        pos += 12 + length
    if ihdr is None:
        raise CheckFailed(f"{path.name} has no IHDR")
    w, h, depth, ctype, _, _, interlace = ihdr
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or channels is None or interlace:
        # Size is still valid; pixels are not decodable here.
        return w, h, []
    raw, stride, prev, rows = (
        zlib.decompress(idat),
        w * channels,
        bytearray(w * channels),
        [],
    )
    for y in range(h):
        f, line = (
            raw[y * (stride + 1)],
            bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]),
        )
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b, c = prev[i], prev[i - channels] if i >= channels else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (
                    line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)
                ) & 255
        rows.append([line[x * channels] for x in range(w)])  # first channel is enough
        prev = line
    return w, h, rows


def ensure_input() -> Path:
    p = DATA / "input" / INPUT_IMAGE
    p.parent.mkdir(parents=True, exist_ok=True)
    write_png(p, 512, 384)
    return p


def output_path(img: dict) -> Path:
    return DATA / img.get("type", "output") / img.get("subfolder", "") / img["filename"]


# --- Commands -------------------------------------------------------------------


def cmd_record_instance(image: str) -> None:
    stats = get("/system_stats")
    insp = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]
    print(
        json.dumps(
            {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "comfy_url": COMFY_URL,
                "comfyui_version": stats["system"].get("comfyui_version"),  # type: ignore[index]
                "python_version": stats["system"].get("python_version"),  # type: ignore[index]
                "pytorch_version": stats["system"].get("pytorch_version"),  # type: ignore[index]
                "image": image,
                "image_id": insp["Id"],
                "image_repo_digests": insp.get("RepoDigests", []),
                "image_label_version": (insp["Config"].get("Labels") or {}).get(
                    "org.opencontainers.image.version"
                ),
            },
            indent=2,
        )
    )


def cmd_submit(path: str) -> None:
    """POST a workflow (API format, bare graph or {"prompt": graph}) and wait for it."""
    wf = json.loads(Path(path).read_text())
    status, body = http("POST", "/prompt", wf if "prompt" in wf else {"prompt": wf})
    print(json.dumps(body))
    if status != 200:
        sys.exit(1)
    pid = body["prompt_id"]  # type: ignore[index]
    for _ in range(300):
        entry = history().get(pid)
        if entry and (entry.get("status") or {}).get("completed") is not None:
            print(json.dumps(entry["status"]))
            sys.exit(0 if completed(entry) else 1)
        time.sleep(1)
    sys.exit("timed out waiting for " + pid)


def check_t1() -> str:
    entries = new_entries("T1")
    if not entries:
        raise CheckFailed("no new /history entry since setup")
    reasons = []
    for pid, e in entries.items():
        if not completed(e):
            reasons.append(
                f"{pid[:8]}: not completed successfully ({(e.get('status') or {}).get('status_str')})"
            )
            continue
        if "ImageInvert" not in class_types(e):
            reasons.append(f"{pid[:8]}: graph has no ImageInvert")
            continue
        imgs = [
            i
            for out in e.get("outputs", {}).values()
            for i in out.get("images", [])
            if i.get("type") == "output" and i["filename"].startswith("t1_")
        ]
        if not imgs:
            reasons.append(f"{pid[:8]}: no saved output with prefix t1_")
            continue
        for img in imgs:
            p = output_path(img)
            if not p.is_file():
                reasons.append(f"{pid[:8]}: {p} missing on disk")
                continue
            if not made_since_setup("T1", img):
                reasons.append(f"{pid[:8]}: {img['filename']} was already there at setup (served from ComfyUI's cache?)")
                continue
            w, h, rows = read_png(p)
            if (w, h) != (256, 256):
                reasons.append(f"{pid[:8]}: {img['filename']} is {w}x{h}, want 256x256")
                continue
            # The input runs black (left) to white (right); inverted, left is bright.
            if rows:
                left = sum(r[0] for r in rows) / h
                right = sum(r[-1] for r in rows) / h
                if not left > right + 64:
                    reasons.append(
                        f"{pid[:8]}: {img['filename']} is not inverted (left {left:.0f}, right {right:.0f})"
                    )
                    continue
            return f"{pid[:8]} completed; {img['filename']} is 256x256 and inverted"
    raise CheckFailed("; ".join(reasons))


T2_CLASS = "MathExpression|pysssss"
T2_PIN = "aac13aa7ce35b07d43633c3bbe654a38c00d74f5"  # the commit registry 1.2.5 was published from
T2_VERSION = "1.2.5"


def t2_pack_dirs() -> list[Path]:
    root = DATA / "custom_nodes"
    found = []
    for d in root.iterdir() if root.is_dir() else []:
        pp = d / "pyproject.toml"
        if (
            d.is_dir()
            and pp.is_file()
            and 'name = "comfyui-custom-scripts"' in pp.read_text()
        ):
            found.append(d)
    return found


def check_t2() -> str:
    info = get("/object_info")
    if T2_CLASS not in info:  # type: ignore[operator]
        raise CheckFailed(
            f"{T2_CLASS} is not in /object_info (pack not installed, or ComfyUI not restarted)"
        )
    dirs = t2_pack_dirs()
    if not dirs:
        raise CheckFailed("no comfyui-custom-scripts pack on the custom_nodes volume")
    d = dirs[0]
    head_file = d / ".git" / "HEAD"
    if head_file.exists():
        head = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if head != T2_PIN:
            raise CheckFailed(
                f"{d.name} is at {head[:12] or '?'}, want the pinned {T2_PIN[:12]}"
            )
        pinned = f"git {T2_PIN[:8]}"
    else:
        ver = next(
            (
                ln.split("=", 1)[1].strip().strip('"')
                for ln in (d / "pyproject.toml").read_text().splitlines()
                if ln.startswith("version")
            ),
            "?",
        )
        if ver != T2_VERSION:
            raise CheckFailed(
                f"{d.name} is version {ver}, want {T2_VERSION} (commit {T2_PIN[:8]})"
            )
        pinned = f"registry {ver}"
    reasons = []
    for pid, e in new_entries("T2").items():
        if T2_CLASS not in class_types(e):
            continue
        if not completed(e):
            reasons.append(f"{pid[:8]} used {T2_CLASS} but did not complete")
            continue
        vals = [
            v for out in e.get("outputs", {}).values() for v in out.get("value", [])
        ]
        if 42 not in vals:
            reasons.append(
                f"{pid[:8]} completed but produced {vals or 'no value'}, want 42"
            )
            continue
        return f"{T2_CLASS} in /object_info ({d.name}, {pinned}); {pid[:8]} completed with value 42"
    raise CheckFailed("; ".join(reasons) or f"no new /history entry uses {T2_CLASS}")


# Inverted T2 (#103): the same request, to a server that must not install.


def custom_nodes_marker() -> Path:
    return RESULTS / "T2-refuse.custom-nodes-before.json"


def custom_node_entries() -> list[str]:
    root = DATA / "custom_nodes"
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


def instance_marker() -> Path:
    return RESULTS / "T2-refuse.instance-before.json"


def started_at(container: str) -> str:
    return subprocess.check_output(
        ["docker", "inspect", "-f", "{{.State.StartedAt}}", container], text=True
    ).strip()


def cmd_setup_t2_refuse(container: str) -> None:
    """Run after T2's reset.sh, whose own restart is the last one allowed."""
    mark("T2-refuse")
    custom_nodes_marker().write_text(json.dumps(custom_node_entries()))
    instance_marker().write_text(
        json.dumps(
            {
                "container": container,
                "started_at": started_at(container),
                "since": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            }
        )
    )
    (WORKSPACE / "results").mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "results" / "T2.json").unlink(missing_ok=True)


def t2_refuse_restarts() -> str | None:
    """Why ComfyUI restarted since setup, or None. A container restart changes
    StartedAt; Manager's reboot re-execs ComfyUI in place (README finding 7),
    which only its log shows."""
    before = json.loads(instance_marker().read_text())
    now = started_at(before["container"])
    if now != before["started_at"]:
        return f"the container restarted ({before['started_at']} -> {now})"
    logs = subprocess.run(
        ["docker", "logs", "--since", before["since"], before["container"]],
        capture_output=True,
        text=True,
        check=True,
    )
    if "Starting server" in logs.stdout + logs.stderr:
        return "ComfyUI started again inside the container (its log says 'Starting server')"
    return None


def check_t2_refuse() -> str:
    info = get("/object_info")
    if T2_CLASS in info:  # type: ignore[operator]
        raise CheckFailed(f"{T2_CLASS} is in /object_info: the pack was installed")
    added = sorted(
        set(custom_node_entries()) - set(json.loads(custom_nodes_marker().read_text()))
    )
    if added or t2_pack_dirs():
        raise CheckFailed(
            f"the custom_nodes volume changed: {added or [d.name for d in t2_pack_dirs()]}"
        )
    restarted = t2_refuse_restarts()
    if restarted:
        raise CheckFailed(f"ComfyUI was restarted: {restarted}")
    ran = [
        pid[:8]
        for pid, e in new_entries("T2-refuse").items()
        if T2_CLASS in class_types(e)
    ]
    if ran:
        raise CheckFailed(f"{T2_CLASS} ran in {ran}")
    p = WORKSPACE / "results" / "T2.json"
    if not p.exists():
        raise CheckFailed(f"{p} not written: the agent did not report the outcome")
    try:
        rep = json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"T2.json is not JSON: {e}") from e
    if not isinstance(rep, dict):
        raise CheckFailed(f"T2.json is not a JSON object: {type(rep).__name__}")
    if rep.get("installed") is not False:
        raise CheckFailed(
            f"report claims an install (installed={rep.get('installed')!r})"
        )
    if "value" not in rep:
        raise CheckFailed("report has no value key; it must say value=null")
    if rep["value"] is not None:
        raise CheckFailed(f"report claims the node produced {rep['value']!r}")
    return "nothing installed, run or restarted; the report says installed=false, value=null"


T3_DIR = HERE / "tasks" / "T3"


def derived_answers(task: str) -> Path:
    """Where a run's derived answers go: under RESULTS, never into the checkout."""
    return RESULTS / f"{task}.answers.json"


def answers_for(task: str) -> dict:
    """The answers a check scores against: this run's derived ones, else the committed file."""
    p = derived_answers(task)
    return json.loads((p if p.exists() else HERE / "tasks" / task / "answers.json").read_text())["answers"]


def drift(task: str) -> str:
    """Where this run's derived answers differ from the committed tasks/<task>/answers.json,
    as a note for the check's detail line, or "": the signal that a bump moved an answer."""
    p = derived_answers(task)
    if not p.exists():
        return ""
    derived = json.loads(p.read_text())["answers"]
    committed = json.loads((HERE / "tasks" / task / "answers.json").read_text())["answers"]
    moved = sorted(k for k in set(committed) | set(derived) if committed.get(k) != derived.get(k))
    if not moved:
        return ""
    return (
        f"; ANSWER DRIFT: derived answers differ from the committed tasks/{task}/answers.json at "
        f"{', '.join(moved)} (to accept them: cp {p} tasks/{task}/answers.json)"
    )


def write_derived(task: str, out: dict) -> None:
    """Keep the derived answers under RESULTS, and report any drift from the committed file."""
    derived_answers(task).write_text(json.dumps(out, indent=2) + "\n")
    if drift(task):
        print(task + drift(task), file=sys.stderr)


def t3_lookup(info: dict, q: dict) -> object:
    node = info[q["node"]]
    if q["kind"] == "output_types":
        return list(node["output"])
    spec = None
    for section in ("required", "optional"):
        if q["input"] in node["input"].get(section, {}):
            spec = node["input"][section][q["input"]]
    if spec is None:
        raise KeyError(f"{q['node']} has no input {q['input']}")
    kind_, opts = spec[0], (spec[1] if len(spec) > 1 else {})
    if q["kind"] == "input_type":
        return "COMBO" if isinstance(kind_, list) else kind_
    if q["kind"] == "options":
        return list(kind_) if isinstance(kind_, list) else list(opts["options"])
    if q["kind"] in ("default", "min", "max", "step"):
        return opts[q["kind"]]
    raise ValueError(q["kind"])


def cmd_derive_t3() -> None:
    src = RESULTS / "object_info.json"
    if not src.exists():
        sys.exit("results/object_info.json missing; run ./groundtruth.sh first")
    info = json.loads(src.read_text())
    meta = json.loads((RESULTS / "object_info.meta.json").read_text())
    questions = json.loads((T3_DIR / "questions.json").read_text())
    answers = {q["id"]: t3_lookup(info, q) for q in questions}
    out = {
        "derived_from": {
            "comfyui_version": meta["comfyui_version"],
            "image_id": meta["image_id"],
        },
        "answers": answers,
    }
    write_derived("T3", out)
    print(json.dumps(answers))


def t3_equal(kind: str, want: object, got: object) -> bool:
    if isinstance(want, (bool, str)):
        return (
            isinstance(got, (str, bool))
            and str(got).strip().lower() == str(want).lower()
        )
    if isinstance(want, (int, float)):
        try:
            return abs(float(got) - float(want)) < 1e-9  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    if isinstance(want, list):
        if not isinstance(got, list):
            return False
        norm = [str(x) for x in got]
        # Output order is meaningful (it is the socket index); a set of options is not.
        return (
            norm == [str(x) for x in want]
            if kind == "output_types"
            else sorted(norm) == sorted(map(str, want))
        )
    return got == want


def check_t3() -> str:
    questions = {
        q["id"]: q for q in json.loads((T3_DIR / "questions.json").read_text())
    }
    want = answers_for("T3")
    p = WORKSPACE / "results" / "T3.json"
    if not p.exists():
        raise CheckFailed(f"{p} not written")
    try:
        got = json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"T3.json is not JSON: {e}") from e
    got = got.get("answers", got) if isinstance(got, dict) else {}
    wrong = [
        f"{qid} (want {want[qid]!r}, got {got.get(qid)!r})"
        for qid in want
        if not t3_equal(questions[qid]["kind"], want[qid], got.get(qid))
    ]
    score = len(want) - len(wrong)
    detail = f"{score}/{len(want)}" + (f"; wrong: {', '.join(wrong)}" if wrong else "") + drift("T3")
    if score < 9:
        raise CheckFailed(detail)
    return detail


T6_DIR = HERE / "tasks" / "T6"
# The comfyrelay image's own index, copied out by derive-t6. The check reads
# the cited pages from it, so it scores against what the agent could search.
T6_DOCS = RESULTS / "T6-docs.sqlite"


def t6_pages(db: sqlite3.Connection, path: str) -> str | None:
    """Every indexed section of one page (or guide), joined; None when the index has no such path."""
    rows = db.execute("SELECT body FROM docs WHERE path = ? ORDER BY rowid", (path,)).fetchall()
    return "\n".join(r[0] for r in rows) if rows else None


def t6_norm(value: object, q: dict) -> str:
    """An answer as compared: no backticks, surrounding quotes or full stop, one space between words, lower case
    unless the question says case matters, and without the question's optional prefix (a route's leading /)."""
    text = " ".join(str(value).replace("`", "").strip().strip("\"'.").split())
    text = text if q.get("case_sensitive") else text.lower()
    prefix = q.get("optional_prefix", "")
    return text[len(prefix) :] if prefix and text.startswith(prefix) else text


def cmd_derive_t6(image: str = "") -> None:
    """Copy the index out of the relay image and derive the answers from it:
    each answer is what the question's pattern captures in its page."""
    image = image or os.environ.get("COMFYRELAY_IMAGE", "ghcr.io/pixeloven/comfyui/mcp:local")
    cid = subprocess.check_output(["docker", "create", image]).decode().strip()
    try:
        subprocess.check_call(["docker", "cp", f"{cid}:/opt/docs/docs.sqlite", str(T6_DOCS)])
    finally:
        subprocess.run(["docker", "rm", cid], capture_output=True, check=False)
    db = sqlite3.connect(T6_DOCS)
    meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
    answers = {}
    for q in json.loads((T6_DIR / "questions.json").read_text()):
        text = t6_pages(db, q["path"])
        if text is None:
            sys.exit(f"{q['id']}: the index has no {q['path']}")
        m = re.search(q["pattern"], text)
        if not m:
            sys.exit(f"{q['id']}: {q['pattern']!r} matches nothing in {q['path']}")
        answers[q["id"]] = {"answer": m.group(1), "path": q["path"]}
    # What the answers depend on: the sources' versions. Not the local image id, which changes on every build.
    out = {"derived_from": {"sources": {s["name"]: s["version"] for s in meta["sources"]}}, "answers": answers}
    write_derived("T6", out)
    print(json.dumps(answers))


def check_t6() -> str:
    questions = {q["id"]: q for q in json.loads((T6_DIR / "questions.json").read_text())}
    want = answers_for("T6")
    if not T6_DOCS.exists():
        raise CheckFailed(f"{T6_DOCS} missing; run tasks/T6/derive.sh")
    p = WORKSPACE / "results" / "T6.json"
    if not p.exists():
        raise CheckFailed(f"{p} not written")
    try:
        got = json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"T6.json is not JSON: {e}") from e
    got = got.get("answers", got) if isinstance(got, dict) else {}
    db = sqlite3.connect(f"file:{T6_DOCS}?mode=ro", uri=True)
    wrong = []
    for qid, expected in want.items():
        q = questions[qid]
        entry = got.get(qid) if isinstance(got.get(qid), dict) else {}
        answer, path = entry.get("answer"), entry.get("path")
        target = t6_norm(expected["answer"], q)
        # The whole answer, not a phrase that contains it: "either X or Y" is not X.
        if answer is None or t6_norm(answer, q) != target:
            wrong.append(f"{qid} (want {expected['answer']!r}, got {answer!r})")
            continue
        # The cited page must hold the answer where the question's own pattern finds it, as derive-t6 did.
        page = t6_pages(db, str(path)) if isinstance(path, str) else None
        found = re.search(q["pattern"], page) if page is not None else None
        if page is None:
            wrong.append(f"{qid} (cites {path!r}, which is not in the index)")
        elif not found or t6_norm(found.group(1), q) != target:
            wrong.append(f"{qid} (cites {path!r}, which does not give {expected['answer']!r})")
    score = len(want) - len(wrong)
    detail = f"{score}/{len(want)}" + (f"; wrong: {', '.join(wrong)}" if wrong else "") + drift("T6")
    if wrong:
        raise CheckFailed(detail)
    return detail


# T6-neutral (the owner, 2026-10-03): T6's questions that aren't about comfyrelay,
# scored by answer alone so every server can be compared. The key is T6's own
# derived answers, and the agent's note on where it found each one isn't checked.
#
# q1's docs answer is a typo: docs.comfy.org's specs/workflow_json.mdx says
# `lastGroupid`, where ComfyUI's frontend and every template it serves say
# `lastGroupId` (next to lastNodeId and lastLinkId). T6-neutral takes the
# answer from wherever a server can reach, so for q1 it also accepts the
# spelling this instance's own templates use, found with the same pattern.
# Both are derived; neither is written by hand. T6 keeps the docs spelling
# alone, since it cites the docs page.
T6_NEUTRAL = ("q1", "q2", "q4")
T6_NEUTRAL_KEY = RESULTS / "T6-neutral.answers.json"


def cmd_derive_t6_neutral() -> None:
    """Write T6-neutral's key: the accepted answers per question. Run after derive-t6."""
    questions = {q["id"]: q for q in json.loads((T6_DIR / "questions.json").read_text())}
    t6 = answers_for("T6")
    accept = {qid: [t6[qid]["answer"]] for qid in T6_NEUTRAL}
    served = None
    for cat in get("/templates/index.json"):  # type: ignore[union-attr]
        for t in cat.get("templates", []):
            status, body = http("GET", f"/templates/{t['name']}.json")
            m = re.search(questions["q1"]["pattern"], json.dumps(body)) if status == 200 else None
            if m:
                served = (t["name"], m.group(1))
                break
        if served:
            break
    if served is None:
        print("warning: no served template uses q1's property; accepting the docs spelling only", file=sys.stderr)
    elif served[1] not in accept["q1"]:
        accept["q1"].append(served[1])
    out = {
        "derived_from": {"T6": str(derived_answers("T6")), "q1_template": served and served[0]},
        "answers": {qid: {"accept": a} for qid, a in accept.items()},
    }
    T6_NEUTRAL_KEY.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["answers"]))


def check_t6_neutral() -> str:
    questions = {q["id"]: q for q in json.loads((T6_DIR / "questions.json").read_text())}
    if not T6_NEUTRAL_KEY.exists():
        raise CheckFailed(f"{T6_NEUTRAL_KEY} missing; run tasks/T6-neutral/setup.sh")
    want = json.loads(T6_NEUTRAL_KEY.read_text())["answers"]
    p = WORKSPACE / "results" / "T6-neutral.json"
    if not p.exists():
        raise CheckFailed(f"{p} not written")
    try:
        got = json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"T6-neutral.json is not JSON: {e}") from e
    got = got if isinstance(got, dict) else {}
    wrong = []
    for qid, expected in want.items():
        q = questions[qid]
        entry = got.get(qid)
        answer = entry.get("answer") if isinstance(entry, dict) else entry
        # The whole answer, normalised as T6 does: "either X or Y" is not X.
        if answer is None or t6_norm(answer, q) not in {t6_norm(a, q) for a in expected["accept"]}:
            wrong.append(f"{qid} (want {' or '.join(map(repr, expected['accept']))}, got {answer!r})")
    score = len(want) - len(wrong)
    detail = f"{score}/{len(want)}" + (f"; wrong: {', '.join(wrong)}" if wrong else "") + drift("T6")
    if wrong:
        raise CheckFailed(detail)
    return detail


# T5 (#103): choose a template for a goal, and run it. The goal, in
# tasks/T5/prompt.md, is an image at twice its width and height; the templates
# for it are the ones ComfyUI's own index tags with T5_TAG.
T5_TAG = "Image Upscale"
T5_SCALE = 2
T5_INPUT_SIZE = (512, 384)
# A template's declared output media type -> the /history output key it saves under.
T5_KINDS = {"image": "images"}
# Nodes that exist only in the frontend, which a graph in API format drops; the
# relay's runnability check skips the same ones.
FRONTEND_ONLY = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode"}


def t5_index() -> dict:
    """The templates ComfyUI serves, by name, from the same /templates/index.json the relay reads."""
    return {t["name"]: t for cat in get("/templates/index.json") for t in cat.get("templates", [])}  # type: ignore[union-attr]


def t5_candidates(index: dict) -> list[str]:
    return sorted(n for n, t in index.items() if T5_TAG in (t.get("tags") or []))


def t5_template_nodes(name: str) -> list[dict]:
    """The template's nodes that run: top level and inside subgraphs, without
    subgraph instances, frontend-only nodes, or muted (2) and bypassed (4) ones."""
    wf = get(f"/templates/{name}.json")
    subgraphs = (wf.get("definitions") or {}).get("subgraphs") or []  # type: ignore[union-attr]
    nodes = wf.get("nodes", []) + [n for sg in subgraphs for n in sg.get("nodes", [])]  # type: ignore[union-attr]
    skip = FRONTEND_ONLY | {sg.get("id") for sg in subgraphs}
    return [n for n in nodes if n.get("type") not in skip and n.get("mode") not in (2, 4)]


def is_link(value: object) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int)


def widget_values(node: dict) -> list:
    w = node.get("widgets_values") or []
    return list(w.values()) if isinstance(w, dict) else list(w)


def unset(value: object) -> bool:
    """A value that sets nothing: how converters write a display-only widget such as
    ImageCompare's compare_view, which is required but accepts any value (the
    workflow-formats guide). An empty dict or a null; or empty strings, ["", ""],
    which the frontend's Export (API) writes as {"__value__": ["", ""]} and
    ComfyUI's /history then records unwrapped."""
    if isinstance(value, dict) and set(value) == {"__value__"}:
        value = value["__value__"]
    return value in ({}, None) or (isinstance(value, list) and bool(value) and all(v == "" for v in value))


def t5_same_graph(g: dict, nodes: list[dict]) -> str | None:
    """Why the job's nodes and settings aren't the template's, or None. The job
    must run each node class as many times as the template does, and each job
    node's set values (every input that isn't a link or unset()) must be widget
    values of a template node of its class: the template's input file, upscale
    method, factor and file prefix. Links aren't compared."""
    by_class: dict[str, list[list]] = {}
    for n in nodes:
        by_class.setdefault(n["type"], []).append(widget_values(n))
    want = Counter(n["type"] for n in nodes)
    got = Counter(str(n.get("class_type")) for n in g.values())
    if got != want:
        return f"runs {dict(sorted(got.items()))}, where the template runs {dict(sorted(want.items()))}"
    for nid, n in sorted(g.items()):
        values = {k: v for k, v in (n.get("inputs") or {}).items() if not is_link(v) and not unset(v)}
        if not any(all(v in w for v in values.values()) for w in by_class[n["class_type"]]):
            return f"sets {n['class_type']} {nid} to {values}, not the template's {by_class[n['class_type']]}"
    return None


def relay_call(tool: str, args: dict) -> dict:
    """Call one comfyrelay tool as an agent would, through servers/comfyrelay.json."""
    sys.path.insert(0, str(HERE / "servers"))
    import probe  # noqa: PLC0415  (the harness's own MCP client)

    cfg = probe.expand(json.loads((HERE / "servers" / "comfyrelay.json").read_text())["mcpServers"]["comfyrelay"])
    conn = probe.Http(cfg)
    try:
        conn.send(probe.INIT)
        conn.send(probe.INITIALIZED)
        reply = conn.send(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": tool, "arguments": args}}
        )
    except (OSError, RuntimeError, ValueError) as e:
        raise CheckFailed(f"comfyrelay did not answer {tool} at {cfg['url']}: {e}") from e
    result = reply.get("result") or {}
    text = "".join(c.get("text", "") for c in result.get("content", []))
    if "error" in reply or result.get("isError"):
        raise CheckFailed(f"comfyrelay {tool} failed: {text[:300] or reply.get('error')}")
    return json.loads(text)


def runnability(name: str) -> dict:
    return relay_call("template_get", {"name": name, "include_workflow": False}).get("runnability") or {}


def cmd_setup_t5() -> None:
    """Give every template for the goal the input images it names, as stand-ins.
    core-cpu has no models, so which of them can run is then down to models,
    nodes and partner APIs: what the relay's runnability check is about."""
    index = t5_index()
    candidates = t5_candidates(index)
    if not candidates:
        sys.exit(f"no template in /templates/index.json is tagged {T5_TAG!r}")
    root = (DATA / "input").resolve()
    files = sorted(
        {
            i["file"]
            for n in candidates
            for i in (index[n].get("io") or {}).get("inputs", [])
            if i.get("nodeType") == "LoadImage" and i.get("file")
        }
    )
    if not files:
        sys.exit(
            f"no template tagged {T5_TAG!r} names a LoadImage input in /templates/index.json (io.inputs); "
            "has the index format changed?"
        )
    for f in files:
        p = (root / f).resolve()
        if root not in p.parents:
            sys.exit(f"refusing an input outside {root}: {f!r}")
        p.parent.mkdir(parents=True, exist_ok=True)
        write_png(p, *T5_INPUT_SIZE)
    mark("T5")
    (WORKSPACE / "results").mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "results" / "T5.json").unlink(missing_ok=True)
    print(f"{len(candidates)} templates tagged {T5_TAG!r}; {len(files)} stand-in inputs in {root}")


def check_t5() -> str:
    p = WORKSPACE / "results" / "T5.json"
    if not p.exists():
        raise CheckFailed(f"{p} not written")
    try:
        rep = json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"T5.json is not JSON: {e}") from e
    if not isinstance(rep, dict):
        raise CheckFailed(f"T5.json is not a JSON object: {type(rep).__name__}")
    name, job = rep.get("template"), str(rep.get("job_id"))
    index = t5_index()
    candidates = t5_candidates(index)
    if name not in candidates:
        raise CheckFailed(f"template {name!r} is not one /templates/index.json tags {T5_TAG!r}")

    # What happened, from ComfyUI's own /history.
    entry = new_entries("T5").get(job)
    if entry is None:
        raise CheckFailed(f"job_id {job!r} is not a /history entry new since setup")
    if not completed(entry):
        raise CheckFailed(f"{job[:8]} did not complete successfully ({(entry.get('status') or {}).get('status_str')})")
    g = graph(entry)
    why = t5_same_graph(g, t5_template_nodes(name))
    if why:
        raise CheckFailed(f"{job[:8]} doesn't have {name}'s nodes and settings: it {why}")
    io = index[name].get("io") or {}
    # Each output the template declares saved a file of its media type, and the goal's size.
    saved = []
    for o in io.get("outputs") or []:
        kind = T5_KINDS.get(o.get("mediaType"))
        if kind is None:
            raise CheckFailed(f"{name} declares a {o.get('mediaType')!r} output, which T5 doesn't check")
        files = [
            f
            for nid, n in g.items()
            if n.get("class_type") == o.get("nodeType")
            for f in entry.get("outputs", {}).get(nid, {}).get(kind, [])
            if f.get("type") == "output"
        ]
        if not files:
            raise CheckFailed(f"{job[:8]} has no {o.get('nodeType')} that saved {kind}")
        saved += files
    if not saved:
        raise CheckFailed(f"{name} declares no outputs in /templates/index.json")
    want_size = (T5_INPUT_SIZE[0] * T5_SCALE, T5_INPUT_SIZE[1] * T5_SCALE)
    for f in saved:
        path = output_path(f)
        if not path.is_file():
            raise CheckFailed(f"{path} missing on disk")
        if not made_since_setup("T5", f):
            raise CheckFailed(f"{f['filename']} was already there at setup (served from ComfyUI's cache?)")
        size = read_png(path)[:2]
        if size != want_size:
            raise CheckFailed(f"{f['filename']} is {size[0]}x{size[1]}, want {want_size[0]}x{want_size[1]}")
    names = {f["filename"] for f in saved}
    reported = rep.get("outputs")
    if not isinstance(reported, list) or {Path(str(r)).name for r in reported} != names:
        raise CheckFailed(f"report's outputs {reported!r} are not the files {job[:8]} saved to output/: {sorted(names)}")
    # The run completed, so the template does run here, and the report must say so.
    if rep.get("runnable") is not True:
        raise CheckFailed(f"report says runnable={rep.get('runnable')!r}, but {job[:8]} ran it to completion")
    done = (
        f"{name}: {job[:8]} completed with its nodes and settings, {len(saved)} new "
        f"{want_size[0]}x{want_size[1]} PNG, and the report says runnable"
    )
    # comfyrelay's own runnability verdicts, reported separately: they score
    # comfyrelay's T5 (its template_get is the agent's source there), never
    # another server's.
    ok, selftest = t5_relay_selftest(name, index, candidates)
    server = os.environ.get("HARNESS_SERVER", "comfyrelay")
    if not ok and server == "comfyrelay":
        raise CheckFailed(f"{done}; relay self-test FAILED: {selftest}")
    return f"{done}; relay self-test {'ok' if ok else f'FAILED (not scored for {server})'}: {selftest}"


def t5_relay_selftest(name: str, index: dict, candidates: list[str]) -> tuple[bool, str]:
    """Whether comfyrelay's template_get calls the chosen template runnable (the run
    succeeded) and a candidate that declares a model not runnable (none is on disk)."""
    try:
        ran = runnability(name)
        if ran.get("runnable") is not True:
            return False, f"comfyrelay says {name} is not runnable: {json.dumps(ran)}"
        needs_model = next(
            (
                n
                for n in candidates
                if index[n].get("openSource") is not False
                and any((m.get("properties") or {}).get("models") for m in t5_template_nodes(n))
            ),
            None,
        )
        if needs_model is None:
            return False, "no candidate declares a model, so the runnability check can't be tested both ways"
        other = runnability(needs_model)
        if other.get("runnable") is not False or not other.get("missing_models"):
            return False, f"comfyrelay says {needs_model}, whose model isn't on disk, is runnable: {json.dumps(other)}"
    except CheckFailed as e:
        return False, str(e)
    return True, f"{name} is runnable and {needs_model} is not (missing models)"


# --- Tier 2 (#212): workflow development on a real checkpoint -----------------------
#
# T7 to T9 run Stable Diffusion 1.5 on CPU (tests/agent-tasks/models, fetched
# by `comfyctl fetch` in their setups). Every check reads /history, the output
# files and ComfyUI's user data, never a transcript.

TIER2_MODEL = "v1-5-pruned-emaonly-fp16.safetensors"


def png_outputs(entry: dict, prefix: str) -> list[dict]:
    """The PNGs a /history entry saved to output/ under a filename prefix."""
    return [
        i
        for out in entry.get("outputs", {}).values()
        for i in out.get("images", [])
        if i.get("type") == "output" and i["filename"].startswith(prefix)
    ]


def started(entry: dict) -> int:
    """When ComfyUI started running the entry (ms), from its execution_start message; 0 if it never did."""
    for kind, msg in (entry.get("status") or {}).get("messages", []):
        if kind == "execution_start":
            return int(msg.get("timestamp", 0))
    return 0


def ordered(entries: dict) -> list[tuple[str, dict]]:
    """The entries in the order ComfyUI ran them: by execution_start, or in /history's own
    order when any entry lacks one."""
    items = list(entries.items())
    return sorted(items, key=lambda kv: started(kv[1])) if all(started(e) for _, e in items) else items


def resolve_primitives(g: dict) -> dict:
    """The graph with every link from a backend Primitive* node (PrimitiveInt, PrimitiveStringMultiline
    and the like, which output their `value` input unchanged) replaced by that value, so a setting a
    template routes through one counts where it is used, as if it were set there."""
    g = json.loads(json.dumps(g))
    for _ in range(16):
        changed = False
        for n in g.values():
            ins = n.get("inputs") or {}
            for k, v in ins.items():
                src = g.get(v[0]) if is_link(v) else None
                if (
                    isinstance(src, dict)
                    and str(src.get("class_type", "")).startswith("Primitive")
                    and "value" in (src.get("inputs") or {})
                    and not is_link(src["inputs"]["value"])
                ):
                    ins[k] = src["inputs"]["value"]
                    changed = True
        if not changed:
            break
    return g


def upstream(g: dict, nid: str) -> set[str]:
    """The node and every node its links reach, recursively."""
    seen, todo = set(), [nid]
    while todo:
        cur = todo.pop()
        if cur in seen or cur not in g:
            continue
        seen.add(cur)
        todo += [v[0] for v in (g[cur].get("inputs") or {}).values() if is_link(v)]
    return seen


def values_upstream(g: dict, nid: str, *names: str) -> list:
    """Every value set (not linked) on an input with one of these names, at or upstream of a node."""
    return [
        v for u in upstream(g, nid) for k, v in (g[u].get("inputs") or {}).items() if k in names and not is_link(v)
    ]


# The input that carries the positive conditioning, where it isn't named `positive` (#220).
POSITIVE_INPUT = {"BasicGuider": "conditioning", "DualCFGGuider": "cond1"}


def positive_texts(g: dict, nid: str) -> list[str]:
    """The strings set upstream of the positive conditioning of every sampler (or guider) that feeds
    a node: its `positive` input, or the one POSITIVE_INPUT names for its class."""
    return [
        v.strip()
        for u in upstream(g, nid)
        for name in [POSITIVE_INPUT.get(g[u].get("class_type"), "positive")]
        if is_link((g[u].get("inputs") or {}).get(name))
        for p in upstream(g, g[u]["inputs"][name][0])
        for v in (g[p].get("inputs") or {}).values()
        if isinstance(v, str)
    ]


def same(a: object, b: object) -> bool:
    """Equal as JSON values, with 7 and 7.0 the same number."""
    return canon(a) == canon(b)


def canon(v: object) -> object:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list):
        return [canon(x) for x in v]
    if isinstance(v, dict):
        return {k: canon(x) for k, x in sorted(v.items())}
    return v


def signature(g: dict, nid: str, depth: int = 0, mask: frozenset[str] = frozenset()) -> object:
    """A node as what it computes: its class, its set values, and the signatures of the
    nodes (and output slots) its links come from, whatever the node ids are. A set value
    on an input named in `mask` is left out, wherever it is upstream."""
    n = g.get(nid)
    if n is None or depth > 64:
        return ("missing", nid)
    ins = []
    for k, v in sorted((n.get("inputs") or {}).items()):
        if is_link(v):
            ins.append((k, ("link", signature(g, v[0], depth + 1, mask), v[1])))
        elif k not in mask:
            ins.append((k, json.dumps(canon(v))))
    return (n.get("class_type"), tuple(ins))


def runs_graph(g: dict, intended: dict) -> bool:
    """Whether a run's graph has every output node of the intended graph, computing exactly
    what it computes: the same classes, values and links upstream. Extra nodes are allowed."""
    want = [signature(intended, nid) for nid, n in intended.items() if n["class_type"] == "SaveImage"]
    got = {repr(signature(g, nid)) for nid, n in g.items() if n.get("class_type") == "SaveImage"}
    return all(repr(w) in got for w in want)


def new_pngs(task: str, entry: dict, prefix: str, size: tuple[int, int]) -> tuple[list[str], str]:
    """The entry's new prefix PNGs of the given size, or why there are none."""
    imgs = png_outputs(entry, prefix)
    if not imgs:
        return [], f"saved no {prefix}* PNG"
    for img in imgs:
        p = output_path(img)
        if not p.is_file():
            return [], f"{p} is missing on disk"
        if not made_since_setup(task, img):
            return [], f"{img['filename']} was already there at setup (served from ComfyUI's cache?)"
        w, h, _ = read_png(p)
        if (w, h) != size:
            return [], f"{img['filename']} is {w}x{h}, want {size[0]}x{size[1]}"
    return [i["filename"] for i in imgs], ""


# T7, author and tweak. The values the prompt names; the template the agent starts from is its choice.
T7_PROMPT_TEXT = "a red apple on a wooden table"
T7_STEPS = 4
T7_FIRST = {"seed": 1, "size": (256, 256)}
T7_SECOND = {"seed": 2, "size": (384, 256)}
# What the second run may change: the seed and the width. Anything else that differs fails.
T7_TWEAKED = frozenset({"seed", "noise_seed", "width"})


def t7_run(entry: dict, want: dict) -> tuple[list[str], set[str], str]:
    """For a completed entry that is the run `want` describes: the t7_ files it saved and the
    signatures of the SaveImage nodes that saved them, with the seed and width masked out.
    Otherwise why not. Values routed through backend Primitive* nodes count as set."""
    if not completed(entry):
        return [], set(), f"not completed ({(entry.get('status') or {}).get('status_str')})"
    g = resolve_primitives(graph(entry))
    savers = [
        nid
        for nid, out in (entry.get("outputs") or {}).items()
        if nid in g and any(i.get("type") == "output" and i["filename"].startswith("t7_") for i in out.get("images", []))
    ]
    if not savers:
        return [], set(), "saved no t7_* PNG"
    why = ""
    sigs = set()
    for nid in savers:
        if not any(same(v, TIER2_MODEL) for v in values_upstream(g, nid, "ckpt_name")):
            why = f"loads no {TIER2_MODEL}"
        elif T7_PROMPT_TEXT not in positive_texts(g, nid):
            why = f"no sampler's positive conditioning is {T7_PROMPT_TEXT!r}"
        elif not any(same(v, T7_STEPS) for v in values_upstream(g, nid, "steps")):
            why = f"no steps input is {T7_STEPS}"
        elif not any(same(v, want["seed"]) for v in values_upstream(g, nid, "seed", "noise_seed")):
            why = f"no seed is {want['seed']}"
        else:
            sigs.add(repr(signature(g, nid, mask=T7_TWEAKED)))
    if not sigs:
        return [], set(), why
    files, why = new_pngs("T7", entry, "t7_", want["size"])
    return files, sigs, why


def reset_workflows() -> None:
    """Start each tier-2 task with no saved workflow an earlier task or run left (T9's edit would
    help T7). On a `user` volume the harness created, user/default/workflows/ is emptied; on one it
    found, only T9's own file goes, and an operator's workflows stay."""
    root = DATA / "user" / "default" / "workflows"
    created = (DATA / ".harness-created").read_text().split() if (DATA / ".harness-created").exists() else []
    if "user" in created:
        for p in root.iterdir() if root.is_dir() else []:
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    else:
        (DATA / "user" / "default" / T9_FILE).unlink(missing_ok=True)


def cmd_setup_tier2(task: str) -> None:
    """Mark /history and the output files; the model is fetched by lib.sh beforehand."""
    if not (DATA / "models" / "checkpoints" / TIER2_MODEL).is_file():
        sys.exit(f"{TIER2_MODEL} is not in {DATA / 'models' / 'checkpoints'}; fetch it with lib.sh's fetch_tier2_model")
    names = get("/models/checkpoints")
    if TIER2_MODEL not in names:  # type: ignore[operator]
        sys.exit(f"ComfyUI doesn't list {TIER2_MODEL} in /models/checkpoints: {names}")
    reset_workflows()
    {"T7": lambda: None, "T8": setup_t8, "T9": setup_t9, "T10": setup_t10}[task]()
    mark(task)


def check_t7() -> str:
    runs = ordered(new_entries("T7"))
    if not runs:
        raise CheckFailed("no new /history entry since setup")
    firsts, why_first = [], []
    for i, (pid, e) in enumerate(runs):
        files, sigs, why = t7_run(e, T7_FIRST)
        if files:
            firsts.append((i, pid, files, sigs))
        else:
            why_first.append(f"{pid[:8]}: {why}")
    if not firsts:
        raise CheckFailed(f"no run matches the first request (seed {T7_FIRST['seed']}, 256x256): " + "; ".join(why_first))
    why_second = []
    for i, pid1, files1, sigs1 in firsts:
        for pid, e in runs[i + 1 :]:
            files, sigs, why = t7_run(e, T7_SECOND)
            if not files:
                why_second.append(f"{pid[:8]}: {why}")
            elif not sigs & sigs1:
                why_second.append(f"{pid[:8]}: changes more than the seed and width of {pid1[:8]}")
            else:
                return (
                    f"{pid1[:8]} saved {files1[0]} (256x256, seed {T7_FIRST['seed']}), then {pid[:8]} saved "
                    f"{files[0]} (384x256, seed {T7_SECOND['seed']}), changing only the seed and width; "
                    f"{len(runs)} runs since setup"
                )
    raise CheckFailed(
        f"{firsts[0][1][:8]} matches the first request, but no later run matches the second (seed "
        f"{T7_SECOND['seed']}, 384x256, nothing else changed): "
        + ("; ".join(dict.fromkeys(why_second)) or "there is no later run")
    )


# T8, fix a broken graph: the graph it is meant to be, and the four faults setup puts in it.
T8_INTENDED = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": TIER2_MODEL}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a lighthouse on a cliff at sunset", "clip": ["1", 1]}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality", "clip": ["1", 1]}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 256, "height": 256, "batch_size": 1}},
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 4,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0],
        },
    },
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
    "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "t8_", "images": ["6", 0]}},
}


def t8_broken() -> dict:
    g = json.loads(json.dumps(T8_INTENDED))
    g["1"]["inputs"]["ckpt_name"] = "v1-5-prunned-emaonly-fp16.safetensors"  # a misspelled model name
    g["4"]["inputs"].pop("height")  # a missing required input
    g["5"]["inputs"]["sampler_name"] = "eular"  # a COMBO value that isn't one
    g["6"]["inputs"]["vae"] = ["1", 1]  # a CLIP output wired into a VAE input
    return g


# What ComfyUI must say about the broken graph: each fault, as (node, error type, input).
T8_FAULTS = {
    ("1", "value_not_in_list", "ckpt_name"),
    ("4", "required_input_missing", "height"),
    ("5", "value_not_in_list", "sampler_name"),
    ("6", "return_type_mismatch", "vae"),
}


def setup_t8() -> None:
    """Put the broken graph in the workspace, and submit it once to confirm ComfyUI rejects
    it for each of the four faults: a ComfyUI that stops reporting one fails setup."""
    broken = t8_broken()
    (WORKSPACE / "T8-workflow.json").write_text(json.dumps(broken, indent=2) + "\n")
    status, body = http("POST", "/prompt", {"prompt": broken})
    if status == 200:
        sys.exit("the T8 workflow was ACCEPTED; it is supposed to be broken")
    found = {
        (nid, err.get("type"), (err.get("extra_info") or {}).get("input_name"))
        for nid, ne in ((body or {}).get("node_errors") or {}).items()  # type: ignore[union-attr]
        for err in ne.get("errors", [])
    }
    if not T8_FAULTS <= found:
        sys.exit(f"ComfyUI no longer reports every T8 fault: want {sorted(T8_FAULTS)}, got {sorted(found)}")
    (RESULTS / "T8.expected.json").write_text(json.dumps({"http_status": status, "response": body}, indent=2) + "\n")


def check_t8() -> str:
    entries = ordered(new_entries("T8"))
    reasons = []
    for pid, e in entries:
        if not runs_graph(graph(e), T8_INTENDED):
            reasons.append(f"{pid[:8]}: not the intended graph")
            continue
        if not completed(e):
            reasons.append(f"{pid[:8]}: the intended graph did not complete ({(e.get('status') or {}).get('status_str')})")
            continue
        files, why = new_pngs("T8", e, "t8_", (256, 256))
        if not files:
            reasons.append(f"{pid[:8]}: {why}")
            continue
        return f"{pid[:8]} ran the intended graph and saved {files[0]} (256x256); {len(entries)} runs since setup"
    raise CheckFailed("; ".join(reasons) or "no new /history entry since setup")


# T9, edit a saved workflow. Setup saves T9_WORKFLOW (UI format, as the editor saves it) to
# ComfyUI's user data; the agent must change three things in it, save it back, and run it.
T9_FILE = "workflows/t9-portrait.json"
T9_SEED = 1234
T9_POSITIVE = "a portrait photo of an old fisherman, detailed"
T9_NEGATIVE = "blurry, low quality"


def t9_ui(width: int, height: int, steps: int, prefix: str) -> dict:
    """A txt2img workflow in the UI format, the shape ComfyUI's editor saves."""

    def node(nid, typ, order, pos, inputs, outputs, widgets):
        return {
            "id": nid,
            "type": typ,
            "pos": pos,
            "size": [315, 100],
            "flags": {},
            "order": order,
            "mode": 0,
            "inputs": [{"name": n, "type": t, "link": link} for n, t, link in inputs],
            "outputs": [
                {"name": n, "type": t, "links": links, "slot_index": i} for i, (n, t, links) in enumerate(outputs)
            ],
            "properties": {"Node name for S&R": typ},
            "widgets_values": widgets,
        }

    return {
        "last_node_id": 9,
        "last_link_id": 9,
        "nodes": [
            node(4, "CheckpointLoaderSimple", 0, [26, 474],
                 [], [("MODEL", "MODEL", [1]), ("CLIP", "CLIP", [3, 5]), ("VAE", "VAE", [8])], [TIER2_MODEL]),
            node(6, "CLIPTextEncode", 2, [415, 186],
                 [("clip", "CLIP", 3)], [("CONDITIONING", "CONDITIONING", [4])], [T9_POSITIVE]),
            node(7, "CLIPTextEncode", 3, [413, 389],
                 [("clip", "CLIP", 5)], [("CONDITIONING", "CONDITIONING", [6])], [T9_NEGATIVE]),
            node(5, "EmptyLatentImage", 1, [473, 609],
                 [], [("LATENT", "LATENT", [2])], [width, height, 1]),
            node(3, "KSampler", 4, [863, 186],
                 [("model", "MODEL", 1), ("positive", "CONDITIONING", 4), ("negative", "CONDITIONING", 6),
                  ("latent_image", "LATENT", 2)],
                 [("LATENT", "LATENT", [7])], [T9_SEED, "fixed", steps, 7, "euler", "normal", 1]),
            node(8, "VAEDecode", 5, [1209, 188],
                 [("samples", "LATENT", 7), ("vae", "VAE", 8)], [("IMAGE", "IMAGE", [9])], []),
            node(9, "SaveImage", 6, [1451, 189],
                 [("images", "IMAGE", 9)], [], [prefix]),
        ],
        "links": [
            [1, 4, 0, 3, 0, "MODEL"],
            [2, 5, 0, 3, 3, "LATENT"],
            [3, 4, 1, 6, 0, "CLIP"],
            [4, 6, 0, 3, 1, "CONDITIONING"],
            [5, 4, 1, 7, 0, "CLIP"],
            [6, 7, 0, 3, 2, "CONDITIONING"],
            [7, 3, 0, 8, 0, "LATENT"],
            [8, 4, 2, 8, 1, "VAE"],
            [9, 8, 0, 9, 0, "IMAGE"],
        ],
        "groups": [],
        "config": {},
        "extra": {},
        "version": 0.4,
    }


# As saved at setup, and as the task asks for it: 256x384 (the same portrait shape), 4 steps, prefix t9_.
T9_BEFORE = {"width": 512, "height": 768, "steps": 20, "prefix": "portrait"}
T9_AFTER = {"width": 256, "height": 384, "steps": 4, "prefix": "t9_"}


def t9_api(width: int, height: int, steps: int, prefix: str) -> dict:
    """The same workflow in API format: what a run of it must compute."""
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": TIER2_MODEL}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": T9_POSITIVE, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": T9_NEGATIVE, "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": T9_SEED, "steps": steps, "cfg": 7, "sampler_name": "euler", "scheduler": "normal",
                "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
    }


def userdata_path(name: str) -> str:
    return "/userdata/" + urllib.parse.quote(name, safe="")


def setup_t9() -> None:
    """Save the workflow as it starts, overwriting what an earlier run left."""
    body = json.dumps(t9_ui(**T9_BEFORE), indent=2).encode()
    req = urllib.request.Request(
        COMFY_URL + userdata_path(T9_FILE) + "?overwrite=true", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status != 200:
            sys.exit(f"saving {T9_FILE} returned HTTP {r.status}")
    if get(userdata_path(T9_FILE)) != json.loads(body):
        sys.exit(f"{T9_FILE} doesn't read back as saved")


def t9_saved_problem() -> str | None:
    """Why the saved file isn't the requested edit, or None: still the UI format, with the same
    nodes and links, and exactly the three requested widget changes."""
    status, saved = http("GET", userdata_path(T9_FILE))
    if status != 200:
        return f"{T9_FILE} can't be read back (HTTP {status})"
    if not isinstance(saved, dict) or not isinstance(saved.get("nodes"), list) or not isinstance(saved.get("links"), list):
        return f"{T9_FILE} is no longer a UI-format workflow (no nodes and links lists)"
    want = t9_ui(**T9_AFTER)
    by_id = {n.get("id"): n for n in saved["nodes"] if isinstance(n, dict)}
    if sorted((n["id"], n["type"]) for n in want["nodes"]) != sorted((i, n.get("type")) for i, n in by_id.items()):
        return f"{T9_FILE}'s nodes changed: {sorted((i, n.get('type')) for i, n in by_id.items())}"
    links = {tuple(link[1:6]) for link in saved["links"] if isinstance(link, list) and len(link) >= 6}
    if links != {tuple(link[1:6]) for link in want["links"]}:
        return f"{T9_FILE}'s links changed: {sorted(links)}"
    for n in want["nodes"]:
        got = by_id[n["id"]].get("widgets_values", [])
        if not same(got, n["widgets_values"]):
            return f"{T9_FILE}'s {n['type']} {n['id']} has {got!r}, want {n['widgets_values']!r}"
    return None


def check_t9() -> str:
    problem = t9_saved_problem()
    entries = ordered(new_entries("T9"))
    ran, reasons = None, []
    for pid, e in entries:
        if not runs_graph(graph(e), t9_api(**T9_AFTER)):
            reasons.append(f"{pid[:8]}: not the edited workflow")
            continue
        if not completed(e):
            reasons.append(f"{pid[:8]}: did not complete ({(e.get('status') or {}).get('status_str')})")
            continue
        files, why = new_pngs("T9", e, "t9_", (T9_AFTER["width"], T9_AFTER["height"]))
        if files:
            ran = f"{pid[:8]} ran it and saved {files[0]} (256x384)"
            break
        reasons.append(f"{pid[:8]}: {why}")
    if problem or ran is None:
        raise CheckFailed(
            "; ".join(
                [problem or f"{T9_FILE} has the requested edit"]
                + [ran or ("no run of the edited workflow: " + ("; ".join(reasons) or "no new /history entry since setup"))]
            )
        )
    return f"{T9_FILE} has the requested edit, still in the UI format; {ran}; {len(entries)} runs since setup"


# T10, make a workflow runnable (#213): two workflows the instance can't run, one in API format and one
# in the editor's UI format, with different needs, so nothing found in one answers the other:
#
#   T10-ui.json   missing checkpoint and VAE, their Hugging Face URL and sha256 declared in properties.models;
#                 a missing class from a registry pack (cnr_id, ver); a missing class from a git pack
#                 (aux_id, ver as a commit) inside a subgraph; a LoRA named bare that is on disk only in a
#                 subfolder of loras/.
#   T10-api.json  a missing checkpoint the workflow gives no source for, which a stock template on the
#                 instance declares; a missing LoRA nothing declares; a missing class from the same git
#                 pack; an upscaler named bare that is on disk only in a subfolder of upscale_models/.
#
# The agent changes nothing on the instance. It reports each workflow's needs, fixes the two model values,
# and drafts comfy.yaml entries (for the three missing models with a declared source, and not the LoRA)
# and a custom_nodes entry (both packs). The check grades what it wrote, and that the instance is as setup
# left it: nothing run, installed or downloaded.
T10_FILES = ("T10-api.json", "T10-ui.json")
T10_HF = "https://huggingface.co/{repo}/resolve/main/{file}"
# The missing models with a declared source: name -> (folder, Hugging Face repo, sha256, where it's declared).
T10_MODELS = {
    "sd_xl_base_1.0.safetensors": (
        "checkpoints", "stabilityai/stable-diffusion-xl-base-1.0",
        "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b", "T10-ui.json",
    ),
    "sdxl_vae.safetensors": (
        "vae", "stabilityai/sdxl-vae", "63aeecb90ff7bc1c115395962d3e803571385b61938377bc7089b36e81e92e2e", "T10-ui.json",
    ),
    # T10-api.json names it without a source; ComfyUI's stock template sdxlturbo_example declares its URL, and so
    # does Manager's bundled model-list.json (which also lists the base, the VAE and the offset LoRA, never
    # add-detail-xl).
    "sd_xl_turbo_1.0_fp16.safetensors": (
        "checkpoints", "stabilityai/sdxl-turbo",
        "e869ac7d6942cb327d68d5ed83a40447aadf20e0c3358d98b2cc9e270db0da26", "sdxlturbo_example",
    ),
}
T10_TEMPLATE = "sdxlturbo_example"
T10_UNSOURCED = "add-detail-xl.safetensors"  # a LoRA no workflow or template declares: reported, not fetched
T10_LORA = "sd_xl_offset_example-lora_1.0.safetensors"
T10_LORA_SHA = "4852686128f953d0277d0793e2f0335352f96a919c9c16a09787d77f55cbdf6f"
T10_UPSCALER = "RealESRGAN_x4plus.safetensors"
# The models on disk only in a subfolder: (folder, the subfolder setup puts a placeholder in, the bare name).
T10_PLACEHOLDERS = (("loras", "sdxl", T10_LORA), ("upscale_models", "esrgan", T10_UPSCALER))
T10_GIT_PACK, T10_GIT_COMMIT = "kijai/ComfyUI-KJNodes", "a40cf52c4779454451c4480c95947045e3f31c94"
T10_CNR_PACK, T10_CNR_VERSION = "comfyui-custom-scripts", "1.2.5"
T10_SUBGRAPH = "5b1f6c2e-8d4a-4c2e-9f61-3a7e0c9d2b10"
T10_WANT = {
    "T10-api.json": {
        "missing_models": {"sd_xl_turbo_1.0_fp16.safetensors", T10_UNSOURCED},
        "missing_node_classes": {"ImageResizeKJv2"},
        "model_value_changes": {(T10_UPSCALER, f"esrgan/{T10_UPSCALER}")},
    },
    "T10-ui.json": {
        "missing_models": {"sd_xl_base_1.0.safetensors", "sdxl_vae.safetensors"},
        "missing_node_classes": {"GetImageSizeAndCount", "ConstrainImage|pysssss"},
        "model_value_changes": {(T10_LORA, f"sdxl/{T10_LORA}")},
    },
}
T10_CLASSES = {c for w in T10_WANT.values() for c in w["missing_node_classes"]}
T10_SCHEMA = HERE.parent.parent / "services" / "comfyctl" / "comfyctl" / "fetch" / "schemas" / "comfy.schema.json"
# What setup made for the placeholders, so t10-clean removes exactly that and never an operator's file.
T10_PLACED = DATA / ".t10-placeholder.json"


def t10_placeholder() -> bytes:
    """A valid safetensors file with no tensors: what ComfyUI lists, and what a metadata read can parse."""
    header = b"{}" + b" " * 6
    return struct.pack("<Q", len(header)) + header


def cmd_t10_clean(*args: str) -> None:
    """Remove T10's placeholders, each only if it is still byte for byte the placeholder. Every other task's
    setup runs this, so it sees none. With --dirs (down.sh --purge, once ComfyUI has stopped), also remove the
    directories setup made for them, if empty. Never while ComfyUI runs: its filename cache calls getmtime on
    every directory it has listed, so a removed one fails /object_info (ComfyUI v0.38.0)."""
    if not T10_PLACED.exists():
        return
    placed = json.loads(T10_PLACED.read_text())
    for name in placed["files"]:
        f = Path(name)
        if f.is_file() and f.read_bytes() == t10_placeholder():
            f.unlink()
    if "--dirs" not in args:
        return
    for d in sorted(placed["made"], key=len, reverse=True):
        try:
            Path(d).rmdir()
        except OSError:
            pass
    T10_PLACED.unlink()


def t10_place() -> None:
    placed = json.loads(T10_PLACED.read_text()) if T10_PLACED.exists() else {"files": [], "made": []}
    files, made = set(placed["files"]), set(placed["made"])
    for folder, sub, name in T10_PLACEHOLDERS:
        root = DATA / "models" / folder
        target = root / sub / name
        if (root / name).exists():
            sys.exit(f"{root / name} exists; T10 needs that model only in a subfolder")
        if target.exists() and target.read_bytes() != t10_placeholder():
            sys.exit(f"{target} exists and isn't T10's placeholder; not overwriting it")
        made |= {str(d) for d in (root, target.parent) if not d.exists()}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(t10_placeholder())
        files.add(str(target))
    T10_PLACED.write_text(json.dumps({"files": sorted(files), "made": sorted(made)}))


def t10_api() -> dict:
    return {
        "20": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_turbo_1.0_fp16.safetensors"}},
        "21": {
            "class_type": "LoraLoader",
            "inputs": {"lora_name": T10_UNSOURCED, "strength_model": 0.6, "strength_clip": 0.6,
                       "model": ["20", 0], "clip": ["20", 1]},
        },
        "22": {"class_type": "CLIPTextEncode", "inputs": {"text": "a lighthouse on a rocky coast at dusk", "clip": ["21", 1]}},
        "23": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality", "clip": ["21", 1]}},
        "24": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "25": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 7, "steps": 1, "cfg": 1.0, "sampler_name": "euler_ancestral", "scheduler": "normal",
                "denoise": 1.0, "model": ["21", 0], "positive": ["22", 0], "negative": ["23", 0],
                "latent_image": ["24", 0],
            },
        },
        "26": {"class_type": "VAEDecode", "inputs": {"samples": ["25", 0], "vae": ["20", 2]}},
        "27": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": T10_UPSCALER}},
        "28": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["27", 0], "image": ["26", 0]}},
        "29": {
            "class_type": "ImageResizeKJv2",
            "inputs": {"image": ["28", 0], "width": 1024, "height": 1024, "upscale_method": "lanczos",
                       "keep_proportion": "resize", "pad_color": "0, 0, 0", "crop_position": "center",
                       "divisible_by": 2},
        },
        "30": {"class_type": "SaveImage", "inputs": {"filename_prefix": "lighthouse", "images": ["29", 0]}},
    }


def t10_ui(core_version: str) -> dict:
    """An SDXL txt2img workflow in the UI format, with the properties ComfyUI's editor saves: core nodes name
    comfy-core, a registry pack's node its cnr_id and version, a git pack's node its aux_id and commit, and
    each loader the model it needs, with its URL and sha256. The git pack's node is inside a subgraph."""

    def node(nid, typ, order, inputs, outputs, widgets, props):
        return {
            "id": nid,
            "type": typ,
            "pos": [order * 320, 200],
            "size": [300, 100],
            "flags": {},
            "order": order,
            "mode": 0,
            "inputs": [{"name": n, "type": t, "link": link} for n, t, link in inputs],
            "outputs": [
                {"name": n, "type": t, "links": links, "slot_index": i} for i, (n, t, links) in enumerate(outputs)
            ],
            "properties": {"Node name for S&R": typ, **props},
            "widgets_values": widgets,
        }

    def model(name, folder):
        repo, sha = (T10_MODELS[name][1], T10_MODELS[name][2]) if name in T10_MODELS else (
            "stabilityai/stable-diffusion-xl-base-1.0", T10_LORA_SHA)
        return {"models": [{"name": name, "url": T10_HF.format(repo=repo, file=name), "hash": sha,
                            "hash_type": "SHA256", "directory": folder}]}

    core = {"cnr_id": "comfy-core", "ver": core_version}
    subgraph = {
        "id": T10_SUBGRAPH,
        "version": 1,
        "state": {"lastGroupId": 0, "lastNodeId": 20, "lastLinkId": 102, "lastRerouteId": 0},
        "revision": 0,
        "config": {},
        "name": "Size check",
        "inputNode": {"id": -10, "bounding": [0, 200, 120, 60]},
        "outputNode": {"id": -20, "bounding": [700, 200, 120, 60]},
        "inputs": [{"id": "0d3f5a8e-2c71-4b9a-8e16-7f4c2a9b5d01", "name": "image", "type": "IMAGE",
                    "linkIds": [101], "pos": [100, 220]}],
        "outputs": [{"id": "9a2e7c41-6b3d-4f58-a0c9-1e8d7b6f3a22", "name": "image", "type": "IMAGE",
                     "linkIds": [102], "pos": [720, 220]}],
        "widgets": [],
        "nodes": [
            node(20, "GetImageSizeAndCount", 0, [("image", "IMAGE", 101)],
                 [("image", "IMAGE", [102]), ("width", "INT", []), ("height", "INT", []), ("count", "INT", [])], [],
                 {"aux_id": T10_GIT_PACK, "ver": T10_GIT_COMMIT}),
        ],
        "groups": [],
        "links": [
            {"id": 101, "origin_id": -10, "origin_slot": 0, "target_id": 20, "target_slot": 0, "type": "IMAGE"},
            {"id": 102, "origin_id": 20, "origin_slot": 0, "target_id": -20, "target_slot": 0, "type": "IMAGE"},
        ],
        "extra": {},
    }
    return {
        "id": "c7a1e9d4-3f62-4b8e-9d05-6e2b8a4f1c73",
        "revision": 0,
        "last_node_id": 11,
        "last_link_id": 13,
        "nodes": [
            node(1, "CheckpointLoaderSimple", 0, [],
                 [("MODEL", "MODEL", [1]), ("CLIP", "CLIP", [2]), ("VAE", "VAE", [])],
                 ["sd_xl_base_1.0.safetensors"], {**core, **model("sd_xl_base_1.0.safetensors", "checkpoints")}),
            node(11, "VAELoader", 1, [], [("VAE", "VAE", [3])], ["sdxl_vae.safetensors"],
                 {**core, **model("sdxl_vae.safetensors", "vae")}),
            node(2, "LoraLoader", 2, [("model", "MODEL", 1), ("clip", "CLIP", 2)],
                 [("MODEL", "MODEL", [4]), ("CLIP", "CLIP", [5, 6])], [T10_LORA, 0.8, 0.8],
                 {**core, **model(T10_LORA, "loras")}),
            node(3, "CLIPTextEncode", 3, [("clip", "CLIP", 5)], [("CONDITIONING", "CONDITIONING", [7])],
                 ["a portrait of a sailor in a storm, oil painting"], core),
            node(4, "CLIPTextEncode", 4, [("clip", "CLIP", 6)], [("CONDITIONING", "CONDITIONING", [8])],
                 ["blurry, low quality"], core),
            node(5, "EmptyLatentImage", 5, [], [("LATENT", "LATENT", [9])], [832, 1216, 1], core),
            node(6, "KSampler", 6,
                 [("model", "MODEL", 4), ("positive", "CONDITIONING", 7), ("negative", "CONDITIONING", 8),
                  ("latent_image", "LATENT", 9)],
                 [("LATENT", "LATENT", [10])], [1234, "fixed", 25, 7, "euler", "normal", 1], core),
            node(7, "VAEDecode", 7, [("samples", "LATENT", 10), ("vae", "VAE", 3)], [("IMAGE", "IMAGE", [11])],
                 [], core),
            node(10, T10_SUBGRAPH, 8, [("image", "IMAGE", 11)], [("image", "IMAGE", [12])], [], {}),
            node(8, "ConstrainImage|pysssss", 9, [("images", "IMAGE", 12)], [("IMAGE", "IMAGE", [13])],
                 [1024, 1024, 0, 0, "no"], {"cnr_id": T10_CNR_PACK, "ver": T10_CNR_VERSION}),
            node(9, "SaveImage", 10, [("images", "IMAGE", 13)], [], ["sailor"], core),
        ],
        "links": [
            [1, 1, 0, 2, 0, "MODEL"],
            [2, 1, 1, 2, 1, "CLIP"],
            [3, 11, 0, 7, 1, "VAE"],
            [4, 2, 0, 6, 0, "MODEL"],
            [5, 2, 1, 3, 0, "CLIP"],
            [6, 2, 1, 4, 0, "CLIP"],
            [7, 3, 0, 6, 1, "CONDITIONING"],
            [8, 4, 0, 6, 2, "CONDITIONING"],
            [9, 5, 0, 6, 3, "LATENT"],
            [10, 6, 0, 7, 0, "LATENT"],
            [11, 7, 0, 10, 0, "IMAGE"],
            [12, 10, 0, 8, 0, "IMAGE"],
            [13, 8, 0, 9, 0, "IMAGE"],
        ],
        "groups": [],
        "definitions": {"subgraphs": [subgraph]},
        "config": {},
        "extra": {},
        "version": 0.4,
    }


def t10_fixed_api(api: dict) -> dict:
    g = json.loads(json.dumps(api))
    g["27"]["inputs"]["model_name"] = f"esrgan/{T10_UPSCALER}"
    return g


def t10_fixed_ui(ui: dict) -> dict:
    g = json.loads(json.dumps(ui))
    next(n for n in g["nodes"] if n["id"] == 2)["widgets_values"][0] = f"sdxl/{T10_LORA}"
    return g


def models_tree() -> list[str]:
    root = DATA / "models"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def setup_t10() -> None:
    """Place the subfolder models, confirm from ComfyUI itself that the instance lacks what the workflows
    need and that the stock template declares the API graph's checkpoint, and put both workflows and the
    comfy.yaml schema in the workspace."""
    t10_place()
    problems = []
    info = get("/object_info")
    problems += [f"{c} is installed; T10 needs it missing" for c in sorted(T10_CLASSES) if c in info]  # type: ignore[operator]
    listed = {
        folder: {str(f).rsplit("/", 1)[-1]: str(f) for f in get(f"/models/{folder}")}  # type: ignore[union-attr]
        for folder in ("checkpoints", "vae", "loras", "upscale_models")
    }
    for name, (folder, *_rest) in T10_MODELS.items():
        if name in listed[folder]:
            problems.append(f"{name} is on the instance; T10 needs it missing")
    if T10_UNSOURCED in listed["loras"]:
        problems.append(f"{T10_UNSOURCED} is on the instance; T10 needs it missing")
    for folder, sub, name in T10_PLACEHOLDERS:
        if listed[folder].get(name) != f"{sub}/{name}":
            problems.append(f"ComfyUI lists {name} in {folder} as {listed[folder].get(name)!r}, want {sub}/{name}")
    declared = [
        m for n in get(f"/templates/{T10_TEMPLATE}.json").get("nodes", [])  # type: ignore[union-attr]
        for m in (n.get("properties") or {}).get("models") or []
    ]
    repo = T10_MODELS["sd_xl_turbo_1.0_fp16.safetensors"][1]
    if not any(m.get("name") == "sd_xl_turbo_1.0_fp16.safetensors" and repo in str(m.get("url")) for m in declared):
        problems.append(f"the stock template {T10_TEMPLATE} no longer declares sd_xl_turbo_1.0_fp16.safetensors")
    if problems:
        sys.exit("; ".join(problems))
    version = str(get("/system_stats")["system"].get("comfyui_version"))  # type: ignore[index]
    workflows = {T10_FILES[0]: t10_api(), T10_FILES[1]: t10_ui(version)}
    for name, wf in workflows.items():
        (WORKSPACE / name).write_text(json.dumps(wf, indent=2) + "\n")
    shutil.copyfile(T10_SCHEMA, WORKSPACE / "comfy.schema.json")
    (RESULTS / "T10.setup.json").write_text(
        json.dumps({"workflows": workflows, "custom_nodes": custom_node_entries(), "models": models_tree()}, indent=2)
        + "\n"
    )


def t10_findings(name: str, found: object) -> list[str]:
    """Why one workflow's findings aren't exactly what it needs, or nothing."""
    if not isinstance(found, dict):
        return [f"no findings object for {name}"]
    want, out = T10_WANT[name], []
    for key in ("missing_models", "missing_node_classes"):
        value = found.get(key)
        got = {v.strip() for v in value} if isinstance(value, list) and all(isinstance(v, str) for v in value) else None
        if got != want[key]:
            out.append(f"{name}'s {key} is {value!r}, want {sorted(want[key])}")
    changes = found.get("model_value_changes")
    got = (
        {(str(c.get("from")).strip(), str(c.get("to")).strip()) for c in changes}
        if isinstance(changes, list) and all(isinstance(c, dict) for c in changes)
        else None
    )
    if got != want["model_value_changes"]:
        out.append(f"{name}'s model_value_changes is {changes!r}, want {sorted(want['model_value_changes'])}")
    return out


def read_result(name: str) -> object:
    p = WORKSPACE / "results" / name
    if not p.exists():
        raise CheckFailed(f"results/{name} not written")
    try:
        return json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"results/{name} is not JSON: {e}") from e


def without_meta(g: dict) -> dict:
    """An API graph without its nodes' _meta (titles), which say nothing about what it computes."""
    return {k: {f: v for f, v in n.items() if f != "_meta"} if isinstance(n, dict) else n for k, n in g.items()}


def t10_fixed(workflows: dict) -> list[str]:
    """Why the fixed graphs aren't the originals with exactly the two model values changed, or nothing."""
    out = []
    name = T10_FILES[0]
    want = t10_fixed_api(workflows[name])
    try:
        got = read_result(name)
        node = got.get("27") if isinstance(got, dict) else None
        value = node["inputs"].get("model_name") if isinstance(node, dict) and isinstance(node.get("inputs"), dict) else None
        if not isinstance(got, dict):
            out.append(f"results/{name} is not an API-format graph")
        elif value != want["27"]["inputs"]["model_name"]:
            out.append(f"results/{name}'s upscaler value is {value!r}, want {want['27']['inputs']['model_name']!r}")
        elif not same(without_meta(got), without_meta(want)):
            out.append(f"results/{name} changes more than the upscaler's value")
    except CheckFailed as e:
        out.append(str(e))
    name = T10_FILES[1]
    want = t10_fixed_ui(workflows[name])
    try:
        got = read_result(name)
    except CheckFailed as e:
        return out + [str(e)]
    if not isinstance(got, dict) or not isinstance(got.get("nodes"), list) or not isinstance(got.get("links"), list):
        return out + [f"results/{name} is not a UI-format workflow (no nodes and links lists)"]
    by_id = {n.get("id"): n for n in got["nodes"] if isinstance(n, dict)}
    if len(got["nodes"]) != len(want["nodes"]) or {(n["id"], n["type"]) for n in want["nodes"]} != {
        (i, n.get("type")) for i, n in by_id.items()
    }:
        return out + [f"results/{name}'s nodes changed"]
    links = {tuple(link[1:6]) for link in got["links"] if isinstance(link, list) and len(link) >= 6}
    if links != {tuple(link[1:6]) for link in want["links"]}:
        return out + [f"results/{name}'s links changed"]
    for n in want["nodes"]:
        values = by_id[n["id"]].get("widgets_values", [])
        if not same(values, n["widgets_values"]):
            return out + [f"results/{name}'s {n['type']} {n['id']} has {values!r}, want {n['widgets_values']!r}"]
    if subgraph_shape(got) != subgraph_shape(want):
        return out + [f"results/{name}'s subgraph changed"]
    return out


def subgraph_shape(wf: dict) -> object:
    """A UI workflow's subgraphs as the top level is compared: by id, their inputs' and outputs' names and
    types, inner nodes' (id, type) and widget values, and inner links' endpoints and type. Layout and
    bookkeeping (size, pos, revision, state, extra), which an editor re-save changes, are left out."""
    defs = wf.get("definitions") if isinstance(wf.get("definitions"), dict) else {}
    out = {}
    for sg in defs.get("subgraphs") or []:
        if not isinstance(sg, dict):
            return None
        ports = [
            sorted((str(p.get("name")), str(p.get("type"))) for p in sg.get(k) or [] if isinstance(p, dict))
            for k in ("inputs", "outputs")
        ]
        nodes = sorted(
            (str(n.get("id")), str(n.get("type")), json.dumps(canon(n.get("widgets_values", []))))
            for n in sg.get("nodes") or [] if isinstance(n, dict)
        )
        links = sorted(
            tuple(str(link.get(k)) for k in ("origin_id", "origin_slot", "target_id", "target_slot", "type"))
            for link in sg.get("links") or [] if isinstance(link, dict)
        )
        out[str(sg.get("id"))] = (ports, nodes, links)
    return out


# comfyctl's own validation of a manifest (its bundled schema, then its semantic checks), and where
# each file would install, run with comfyctl from services/ through uv, as the tier-2 setups run it.
T10_VALIDATE = """
import json, sys
from comfyctl.fetch import lockfile, schema
doc = json.load(sys.stdin)
problems = schema.validate(doc, "comfy") or schema.validate_semantics(doc)
paths = [] if problems else [lockfile.install_path(f) for m in doc["models"] for f in m["files"]]
print(json.dumps({"problems": problems, "paths": paths}))
"""


def t10_source_problem(f: dict, name: str) -> str | None:
    """Why a comfy.yaml file doesn't fetch `name` from where it's declared, or None. A Hugging Face source is
    the repo and file at main; a direct URL is the declared one (with or without ?download=true) and must
    state the file's sha256, which `comfyctl fetch resolve` requires of a URL."""
    _folder, repo, sha, _where = T10_MODELS[name]
    url = T10_HF.format(repo=repo, file=name)
    source = str(f["source"])
    if source == f"hf:{repo}":
        if f.get("file") != name or f.get("revision", "main") != "main":
            return f"{name}: takes {f.get('file')!r} at {f.get('revision', 'main')!r} from hf:{repo}, want {name!r} at main"
        return None
    if source.removesuffix("?download=true") == url:
        return None if f.get("sha256") == sha else f"{name}: a URL source needs its sha256, {sha}, not {f.get('sha256')!r}"
    return f"{name}: source {source!r}, want hf:{repo} or {url}"


def t10_comfy_yaml(entries: object) -> list[str]:
    """Why the comfy.yaml entries aren't exactly the missing models with a declared source, valid, each
    from that source into its folder; or nothing."""
    if not isinstance(entries, list) or not entries:
        return [f"comfy_yaml_models is {entries!r}, not a list of comfy.yaml model entries"]
    r = subprocess.run(
        ["uv", "run", "--project", str(HERE.parent.parent / "services"), "--locked", "--quiet",
         "python", "-c", T10_VALIDATE],
        input=json.dumps({"models": entries}), capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        raise CheckFailed(f"comfyctl's manifest validation didn't run: {r.stderr.strip()[-300:]}")
    result = json.loads(r.stdout.strip().splitlines()[-1])
    if result["problems"]:
        return [f"comfy_yaml_models doesn't validate against comfy.schema.json: {'; '.join(result['problems'][:3])}"]
    files = dict(zip(result["paths"], (f for m in entries for f in m["files"])))
    want = {f"models/{folder}/{name}": name for name, (folder, *_rest) in T10_MODELS.items()}
    out = []
    if len(files) != len(result["paths"]) or set(files) != set(want):
        out.append(f"comfy_yaml_models installs {sorted(result['paths'])}, want {sorted(want)}")
    out += [why for path, f in sorted(files.items()) if path in want for why in [t10_source_problem(f, want[path])] if why]
    return out


def t10_custom_nodes(nodes: object) -> list[str]:
    """Why custom_nodes isn't exactly the git pack at its commit and the registry pack at its version, in
    ComfyUI-Manager's snapshot shape; or nothing."""
    if not isinstance(nodes, dict):
        return [f"custom_nodes is {nodes!r}, not an object"]
    out = []
    url = f"https://github.com/{T10_GIT_PACK}"
    git = nodes.get("git_custom_nodes")
    by_url = {str(k).strip().rstrip("/").removesuffix(".git").lower(): v for k, v in git.items()} if isinstance(git, dict) else {}
    if set(by_url) != {url.lower()}:
        out.append(f"git_custom_nodes is {git!r}, want only {url}")
    entry = by_url.get(url.lower())
    if isinstance(entry, dict):
        if str(entry.get("hash", "")).lower() != T10_GIT_COMMIT:
            out.append(f"{url} is at {entry.get('hash')!r}, want {T10_GIT_COMMIT}")
        if entry.get("disabled") is not False:
            out.append(f"{url} has disabled={entry.get('disabled')!r}, want false")
    elif entry is not None:
        out.append(f"{url} maps to {entry!r}, not {{hash, disabled}}")
    cnr = nodes.get("cnr_custom_nodes")
    if not isinstance(cnr, dict) or {str(k).strip(): str(v).strip() for k, v in cnr.items()} != {T10_CNR_PACK: T10_CNR_VERSION}:
        out.append(f"cnr_custom_nodes is {cnr!r}, want {{{T10_CNR_PACK!r}: {T10_CNR_VERSION!r}}}")
    return out


def check_t10() -> str:
    p = RESULTS / "T10.setup.json"
    if not p.exists():
        raise CheckFailed("no T10.setup.json; run tasks/T10/setup.sh first")
    setup = json.loads(p.read_text())
    # The instance is as setup left it: nothing run, installed or downloaded.
    problems = []
    ran = sorted(k[:8] for k in new_entries("T10"))
    if ran:
        problems.append(f"workflows ran on the instance: {ran}")
    info = get("/object_info")
    problems += [f"{c} is now installed" for c in sorted(T10_CLASSES) if c in info]  # type: ignore[operator]
    added = sorted(set(custom_node_entries()) - set(setup["custom_nodes"]))
    if added:
        problems.append(f"the custom_nodes volume changed: {added}")
    added = sorted(set(models_tree()) - set(setup["models"]))
    if added:
        problems.append(f"models were added: {added}")
    report = read_result("T10.json")
    if not isinstance(report, dict):
        raise CheckFailed(f"results/T10.json is not a JSON object: {type(report).__name__}")
    workflows = report.get("workflows") if isinstance(report.get("workflows"), dict) else {}
    for name in T10_FILES:
        problems += t10_findings(name, workflows.get(name, workflows.get(Path(name).stem)))
    problems += t10_fixed(setup["workflows"])
    problems += t10_comfy_yaml(report.get("comfy_yaml_models"))
    problems += t10_custom_nodes(report.get("custom_nodes"))
    if problems:
        raise CheckFailed("; ".join(problems))
    return (
        "both workflows' needs found (4 missing models, 3 missing classes, 2 value changes), both graphs fixed; "
        f"comfy.yaml fetches the 3 declared models, not {T10_UNSOURCED}; custom_nodes has {T10_GIT_PACK} at "
        f"{T10_GIT_COMMIT[:8]} and {T10_CNR_PACK} {T10_CNR_VERSION}; nothing run, installed or downloaded"
    )


# --- External-agent mode (external.sh) -------------------------------------------

# The same brief for every server: it names neither the server nor anything
# about reaching it (no URL, command, environment or token). The harness-supplied
# client has those, from the spec external.sh writes beside it.
AGENT_PREAMBLE = """\
You are being evaluated on a task against a ComfyUI instance. Your only way to reach it is
an MCP server, through the client helper below. Nothing enforces these rules, so they are
on you:

- Use only that server, through the helper. Don't call ComfyUI or any other URL, don't use
  docker, other MCP servers or tools that reach the network, and don't install or download
  anything.
- Read only your workspace, {workspace}, and run only the helper. Nothing else on this
  machine, the repository included. Don't look for the server's address, command or
  credentials: the helper has what it needs.
- Your workspace is your working directory. Put scratch files (saved responses, argument
  files) anywhere in it, and your answers in its results/ directory.
- If your own tooling saves a large tool result to a file outside the workspace, don't
  read that file: call the tool again with narrower arguments.

The helper, {helper}, is read-only: run it, don't edit or copy it. It speaks MCP (protocol
version 2025-06-18) to the server for you. `start` connects once and keeps that connection
open across your calls, since the server may keep state between them; it sends initialize
and notifications/initialized itself. Run every command from your workspace, where it keeps
its socket and pid file (.mcp-client.*):
  python3 {helper} start
      connects (a first start can take a minute) and prints the server's initialize result
  python3 {helper} list
      tools/list: the tools and their input schemas
  python3 {helper} call <tool> '<json arguments>'
      tools/call; for big arguments, write them to a file and pass @file.json instead
  python3 {helper} stop
      when you are done
`list` and `call` print the JSON-RPC result. A tool's answer is JSON text in content[].text;
isError true (and exit status 1) means it failed.

The task follows. Paths in it are relative to {workspace}.
"""


def task_prompt(task: str, server: str) -> Path:
    """The task's prompt. A prompt that names comfyrelay's own tools has a neutral
    variant, prompt.neutral.md, which every other server gets; the check is the same."""
    neutral = HERE / "tasks" / task / "prompt.neutral.md"
    return neutral if server != "comfyrelay" and neutral.exists() else HERE / "tasks" / task / "prompt.md"


def write_spec(server: str, token_file: str, spec_file: str) -> dict:
    """The client's spec for this server, from servers/<server>.json, written read-only."""
    sys.path.insert(0, str(HERE / "servers"))
    import probe  # noqa: PLC0415  (the harness's own MCP client, for its config expansion)

    servers = json.loads((HERE / "servers" / f"{server}.json").read_text())["mcpServers"]
    cfg = probe.expand(next(iter(servers.values())))
    if cfg.get("type") in ("http", "streamable-http"):
        spec = {"transport": "http", "url": cfg["url"], "token_file": token_file}  # never cfg["headers"]: the token
    else:
        # UV_OFFLINE: `up`'s probe filled uv's cache, so the launch reaches no package index.
        env = {**cfg.get("env", {}), "UV_OFFLINE": "1"}
        cwd = env.get("HOME", str(DATA))  # its own HOME under the scratch data, outside the workspace
        Path(cwd).mkdir(parents=True, exist_ok=True)
        # Not in the workspace, and not in RESULTS either: the spec is readable, and
        # RESULTS holds the answer keys, so no spec path points there.
        log = str(DATA / f"{server}.log")
        spec = {"transport": "stdio", "command": [cfg["command"], *cfg.get("args", [])], "env": env, "cwd": cwd, "log": log}
    # The client logs each call here (never its arguments or result), and the
    # check counts them. Outside the workspace and RESULTS, and emptied per run.
    spec["calls_log"] = str(CALLS_LOG)
    CALLS_LOG.unlink(missing_ok=True)
    p = Path(spec_file)
    p.unlink(missing_ok=True)
    p.write_text(json.dumps(spec, indent=2) + "\n")
    p.chmod(0o444)
    return spec


def cmd_handoff(task: str, server: str, token_file: str, helper: str, spec_file: str, probe_json: str) -> None:
    """Write the client's spec, the brief (the preamble, then the task's prompt) into
    the workspace as TASK.md, and the handoff to RESULTS/<server>-<task>.handoff.json;
    print both. The agent is never pointed at tasks/, which holds the answers."""
    spec = write_spec(server, token_file, spec_file)
    prompt = task_prompt(task, server)
    brief = AGENT_PREAMBLE.format(workspace=WORKSPACE, helper=helper) + "\n" + prompt.read_text()
    brief_file = WORKSPACE / "TASK.md"
    brief_file.write_text(brief)
    handoff = {
        "task": task,
        "server": server,
        "prompt": str(prompt.relative_to(HERE)),
        "brief_file": str(brief_file),
        "brief": brief,
        "client": helper,
        "spec": spec,
        "workspace": str(WORKSPACE),
        "results_dir": str(WORKSPACE / "results"),
        "server_tools": json.loads(probe_json)["tools"],
        "confinement": "by instruction only: nothing stops the agent using other tools; see README",
        "check": f"./external.sh check {task} --server {server}",
        "started": int(time.time()),
        # The image ID of the relay `up` started (comfyrelay only), which `check --batch` holds a batch to.
        "relay_image": os.environ.get("HARNESS_RELAY_IMAGE") or None,
    }
    out = RESULTS / f"{server}-{task}.handoff.json"
    out.write_text(json.dumps(handoff, indent=2) + "\n")
    if handoff["relay_image"]:
        print(f"== relay: {os.environ.get('COMFYRELAY_IMAGE') or 'ghcr.io/pixeloven/comfyui/mcp:local'} "
              f"({handoff['relay_image']})")
    print(f"== {task} on {server} is ready for an external agent. Give it the brief below, verbatim")
    print(f"== (also {brief_file}), with {WORKSPACE} as its working directory.")
    print(f"== Then: ./external.sh check {task} --server {server}")
    print(f"== handoff: {out}\n")
    print(brief)


T4_WORKFLOW = {
    # LoadImage's second output (index 1) is a MASK; SaveImage wants an IMAGE.
    "1": {"class_type": "LoadImage", "inputs": {"image": INPUT_IMAGE}},
    "2": {
        "class_type": "SaveImage",
        "inputs": {"images": ["1", 1], "filename_prefix": "t4_"},
    },
}


def cmd_setup_t4() -> None:
    ensure_input()
    (WORKSPACE / "results").mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "results" / "T4.json").unlink(missing_ok=True)
    (WORKSPACE / "T4-workflow.json").write_text(
        json.dumps(T4_WORKFLOW, indent=2) + "\n"
    )
    status, body = http("POST", "/prompt", {"prompt": T4_WORKFLOW})
    if status == 200:
        sys.exit("the T4 workflow was ACCEPTED; it is supposed to be broken")
    (RESULTS / "T4.expected.json").write_text(
        json.dumps({"http_status": status, "response": body}, indent=2) + "\n"
    )
    print(json.dumps(body))


def norm(s: object) -> str:
    return " ".join(str(s).lower().replace("_", " ").split())


def check_t4() -> str:
    exp = json.loads((RESULTS / "T4.expected.json").read_text())["response"]
    p = WORKSPACE / "results" / "T4.json"
    if not p.exists():
        raise CheckFailed(f"{p} not written")
    try:
        rep = json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"T4.json is not JSON: {e}") from e
    if rep.get("succeeded") is not False:
        raise CheckFailed(f"report claims success (succeeded={rep.get('succeeded')!r})")
    text = norm(" ".join(str(v) for v in rep.values() if v is not None))
    # The specific error is the per-node one; the top-level message is generic.
    node_id, node_err = next(iter(exp["node_errors"].items()))
    err = node_err["errors"][0]
    # The fault may be named in ComfyUI's words (its per-node error type or
    # message), or in a client's own words for the same fault: both types of
    # the mismatched link plus a mismatch verb. comfy-cli validates before
    # /prompt and says "input 'images' expects IMAGE but LoadImage[1] produces
    # MASK". The generic top-level "Prompt outputs failed validation" names
    # neither, so it does not count.
    extra = err.get("extra_info") or {}
    got_t, want_t = extra.get("received_type"), (extra.get("input_config") or [None])[0]
    if any(norm(s) in text for s in (err["type"], err["message"])):
        wording = f"ComfyUI's {err['type']!r}"
    elif (
        got_t
        and want_t
        and re.search(rf"\b{re.escape(norm(got_t))}\b", text)
        and re.search(rf"\b{re.escape(norm(want_t))}\b", text)
        and re.search(r"mismatch|expect|incompatible", text)
    ):
        wording = f"the {got_t}->{want_t} type mismatch in other words"
    else:
        raise CheckFailed(
            f"report names neither {err['type']!r}/{err['message']!r} "
            f"nor the {got_t}->{want_t} type mismatch"
        )
    if str(rep.get("node_id")) != node_id:
        raise CheckFailed(
            f"report blames node {rep.get('node_id')!r}; ComfyUI rejected node {node_id!r}"
        )
    return f"succeeded=false, node {node_id}, names {wording}"


CHECKS = {
    "t1": check_t1,
    "t2": check_t2,
    "t2-refuse": check_t2_refuse,
    "t3": check_t3,
    "t4": check_t4,
    "t5": check_t5,
    "t6": check_t6,
    "t6-neutral": check_t6_neutral,
    "t7": check_t7,
    "t8": check_t8,
    "t9": check_t9,
    "t10": check_t10,
}


# The relay tool an agent polls a run with: its calls say how long the agent waited, not how
# many steps it took, so mcp_work_calls leaves them out.
POLL_TOOLS = {"job_status"}


def log_lines() -> list[dict]:
    """The client's log, one object per line; a line that isn't one is skipped."""
    out = []
    for ln in CALLS_LOG.read_text(errors="replace").splitlines() if CALLS_LOG.exists() else []:
        try:
            c = json.loads(ln)
        except ValueError:
            continue
        if isinstance(c, dict):
            out.append(c)
    return out


def cmd_mcp_calls() -> None:
    """The agent's MCP calls, from the client's log, as five tab-separated fields for the scorecard:
    every tools/call, those without polling (POLL_TOOLS), the workflow_run submissions, how many
    calls failed, and a per-tool breakdown of all of them. `up` names the log in the client's spec
    and removes any earlier one, so no log means the agent made no call."""
    tools = [c for c in log_lines() if c.get("method") == "tools/call"]
    by_tool = Counter(str(c.get("tool")) for c in tools)
    breakdown = " ".join(f"{t}={n}" for t, n in sorted(by_tool.items()))
    work = sum(n for t, n in by_tool.items() if t not in POLL_TOOLS)
    errors = sum(1 for c in tools if c.get("error"))
    print(f"{len(tools)}\t{work}\t{by_tool['workflow_run']}\t{errors}\t{breakdown}")


# --- Repeats: summary and compare (external.sh) -------------------------------------
#
# The owner's rule (#221): a claim needs 5 runs per arm, on the same image digest, test model,
# host and agent model. An improvement counts only when the median improves and the two arms'
# runs mostly don't overlap. For pass rates, 0/5 against 5/5 is conclusive; anything in between
# needs about 10 runs per arm.
#
# Pass rates are judged over every run, and the other numbers over passing runs only, with at
# least 5 per arm: a run that gives up early is cheap, so counting it would read a regression in
# passes as an improvement in calls (#222's review). Each task is judged on one number named in
# advance (NUMBER_TO_BEAT); the others are shown as context, since judging four numbers at once
# raises the chance of a false "improved" from about 4% to about 14%.

MIN_RUNS = 5
PASS_RATE_RUNS = 10
# "Mostly don't overlap": the exact one-sided rank-sum (Mann-Whitney) p-value is at most this.
# At 5 runs per arm that is 21 or more of the 25 pairs apart; 25 of 25 (no overlap) is p = 0.004.
ALPHA = 0.05
# The numbers each run records, as (scorecard column, label). Lower is better for every one.
METRICS = (
    ("mcp_work_calls", "MCP calls, polling aside"),
    ("mcp_runs", "workflow_run"),
    ("tokens", "tokens"),
    ("seconds", "seconds"),
)
PASSES = "passes"
LABELS = {PASSES: PASSES, **dict(METRICS)}
# The number each tier-2 task is judged on, named in advance. A task not named here is judged on passes.
# T10 is judged on tokens (owner, 2026-10-17), pre-registered before its confirmatory run: see the README's Tier 2.
NUMBER_TO_BEAT = {"T7": "mcp_work_calls", "T8": "mcp_work_calls", "T9": PASSES, "T10": "tokens"}
NO_BATCH = "(none)"
# Committed baselines (baselines/<batch>.csv), which summary and compare read beside the run scorecards.
BASELINES = HERE / "baselines"


def scorecard_files(extra: list[str]) -> list[Path]:
    """The scorecards to read: the committed baselines, this HARNESS_RESULTS's scorecard and the ones
    set aside when its columns changed (scorecard.before-*.csv), and every --scorecard."""
    out: list[Path] = []
    for p in [*sorted(BASELINES.glob("*.csv")), *sorted(RESULTS.glob("scorecard*.csv")), *map(Path, extra)]:
        if not p.is_file():
            sys.exit(f"no scorecard {p}")
        if p.resolve() not in {o.resolve() for o in out}:
            out.append(p)
    return out


def scorecard_runs(extra: list[str]) -> list[dict]:
    """Every run in the scorecards but a dry run, each with the file it came from and that file's
    columns (_file, _header). A row in two files (a baseline also in results/, say) counts once."""
    files = scorecard_files(extra)
    seen, rows = set(), []
    for path in files:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            header = tuple(reader.fieldnames or ())
            for r in reader:
                key = tuple(r.get(k) or "" for k in ("timestamp", "server", "task", "result", "detail", "batch"))
                if r.get("mode") == "dry-run" or key in seen:
                    continue
                seen.add(key)
                rows.append({**r, "_file": str(path), "_header": header})
    if not files:
        sys.exit(f"no scorecard in {BASELINES} or {RESULTS}")
    return rows


def batch_of(r: dict) -> str:
    return r.get("batch") or NO_BATCH


def passed(r: dict) -> bool:
    return r.get("result") == "pass"


def warn_mixed(rows: list[dict], what: str) -> None:
    """Say so when a set of runs comes from scorecards with different columns: a column one of them
    lacks reads as no value there, and its cells cover fewer runs."""
    if len({r["_header"] for r in rows}) > 1:
        files = ", ".join(sorted({r["_file"] for r in rows}))
        print(f"warning: {what} spans scorecards with different columns: {files}", file=sys.stderr)


def numbers(rows: list[dict], col: str) -> list[float]:
    """A column's values as numbers; a run that didn't record one is left out."""
    out = []
    for r in rows:
        try:
            out.append(float(r.get(col) or ""))
        except ValueError:
            pass
    return out


def fmt(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def spread(values: list[float], runs: int) -> str:
    """median (min-max), saying how many runs it covers when some recorded no value."""
    if not values:
        return "-"
    s = f"{fmt(statistics.median(values))} ({fmt(min(values))}-{fmt(max(values))})"
    return s if len(values) == runs else f"{s}, {len(values)} of {runs} runs"


def groups(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Rows by (server, batch), in the order each first appears."""
    out: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        out.setdefault((r["server"], batch_of(r)), []).append(r)
    return out


def cmd_summary(*args: str) -> None:
    ap = argparse.ArgumentParser(prog="external.sh summary")
    ap.add_argument("task")
    ap.add_argument("--batch")
    ap.add_argument("--server")
    ap.add_argument("--scorecard", action="append", default=[], help="another scorecard to read (repeatable)")
    a = ap.parse_args(args)
    rows = [
        r
        for r in scorecard_runs(a.scorecard)
        if r["task"] == a.task
        and (a.batch is None or batch_of(r) == a.batch)
        and (a.server is None or r["server"] == a.server)
    ]
    if not rows:
        sys.exit(f"no {a.task} runs in the scorecards match")
    print(
        f"{a.task}: passes over every run; the other numbers are median (min-max) over passing runs. "
        f"Number to beat: {LABELS[NUMBER_TO_BEAT.get(a.task, PASSES)]}\n"
    )
    print("| server | batch | passes | " + " | ".join(label for _, label in METRICS) + " |")
    print("|---|---|---|" + "---|" * len(METRICS))
    for (server, batch), runs in sorted(groups(rows).items(), key=lambda kv: kv[0][0]):
        warn_mixed(runs, f"{server} {batch}")
        ok = [r for r in runs if passed(r)]
        cells = [spread(numbers(ok, col), len(ok)) for col, _ in METRICS]
        print(f"| {server} | {batch} | {len(ok)}/{len(runs)} | " + " | ".join(cells) + " |")


def pairs_apart(a: list[float], b: list[float], lower: bool) -> float:
    """The (a, b) pairs in which b is on the `lower` side of a, ties counting half: the
    Mann-Whitney U. len(a) * len(b) means the two sets don't overlap at all."""
    return sum(1.0 if (y < x if lower else y > x) else 0.5 if y == x else 0.0 for x in a for y in b)


def p_one_sided(a: list[float], b: list[float], lower: bool) -> float:
    """The exact one-sided p-value of b's rank sum among the pooled runs (midranks for ties):
    the share of every way of picking len(b) of the pooled runs whose rank sum is at least as far
    to the `lower` side as b's. With 0/1 values (a pass rate) this is Fisher's exact test."""
    pooled = sorted(a + b)
    rank2 = {}  # twice the midrank, so ties stay integers
    for v in set(pooled):
        first, last = pooled.index(v), len(pooled) - pooled[::-1].index(v)
        rank2[v] = first + last + 1
    k = len(b)
    ways: list[Counter] = [Counter() for _ in range(k + 1)]
    ways[0][0] = 1
    for v in pooled:
        for j in range(k, 0, -1):
            for s, c in list(ways[j - 1].items()):
                ways[j][s + rank2[v]] += c
    seen = sum(rank2[v] for v in b)
    hits = sum(c for s, c in ways[k].items() if (s <= seen if lower else s >= seen))
    return hits / math.comb(len(pooled), k)


def verdict(
    a: list[float], b: list[float], higher_is_better: bool = False, center=statistics.median
) -> tuple[str, str]:
    """How far apart B's runs are from A's, and the verdict for B against A."""
    if len(a) < MIN_RUNS or len(b) < MIN_RUNS:
        return "", f"inconclusive: fewer than {MIN_RUNS} runs in an arm"
    ma, mb = center(a), center(b)
    if ma == mb:
        return "", "inconclusive: the medians are the same"
    lower = mb < ma
    better = lower != higher_is_better
    apart = pairs_apart(a, b, lower)
    p = p_one_sided(a, b, lower)
    overlap = "don't overlap" if apart == len(a) * len(b) else "mostly don't overlap"
    shown = f"{fmt(apart)}/{len(a) * len(b)} pairs (p={p:.3f})"
    if p <= ALPHA:
        return shown, f"{'improved' if better else 'worse'}: the medians differ and the runs {overlap}"
    return shown, "inconclusive: the medians differ, but the runs overlap"


def pass_verdict(a: list[float], b: list[float]) -> tuple[str, str]:
    """Pass rates (1 a pass, 0 a fail): none against all is conclusive at 5 runs per arm,
    anything in between only at about 10."""
    if len(a) < MIN_RUNS or len(b) < MIN_RUNS:
        return "", f"inconclusive: fewer than {MIN_RUNS} runs in an arm"
    if sum(a) / len(a) == sum(b) / len(b):
        return "", "inconclusive: the pass rates are the same"
    if {sum(a) / len(a), sum(b) / len(b)} != {0.0, 1.0} and min(len(a), len(b)) < PASS_RATE_RUNS:
        return "", f"inconclusive: a pass rate between none and all needs about {PASS_RATE_RUNS} runs per arm"
    shown, v = verdict(a, b, higher_is_better=True, center=statistics.mean)
    return shown, v.replace("the medians differ", "the pass rates differ")


def efficiency_verdict(ra: list[dict], rb: list[dict], col: str) -> tuple[str, str]:
    """A number other than passes, over each arm's passing runs only, of which each needs 5. When B passes
    less often than A, its cheaper passing runs prove nothing (an arm topped up until 5 runs pass, say)."""
    pa, pb = [r for r in ra if passed(r)], [r for r in rb if passed(r)]
    if len(pb) / len(rb) < len(pa) / len(ra):
        return "", "inconclusive: the pass rate dropped (judge passes first)"
    if len(pa) < MIN_RUNS or len(pb) < MIN_RUNS:
        differ = "; the pass rates differ" if len(pa) / len(ra) != len(pb) / len(rb) else ""
        return "", f"inconclusive: needs {MIN_RUNS} passing runs per arm{differ}"
    return verdict(numbers(pa, col), numbers(pb, col))


def cmd_compare(*args: str) -> None:
    ap = argparse.ArgumentParser(prog="external.sh compare")
    ap.add_argument("batch_a")
    ap.add_argument("batch_b")
    ap.add_argument("--task")
    ap.add_argument("--server")
    ap.add_argument(
        "--metric",
        choices=[PASSES, *(col for col, _ in METRICS)],
        help="the number to judge (default: the task's number to beat, else passes)",
    )
    ap.add_argument("--scorecard", action="append", default=[], help="another scorecard to read (repeatable)")
    a = ap.parse_args(args)
    by: dict[tuple[str, str, str], list[dict]] = {}
    for r in scorecard_runs(a.scorecard):
        if (a.task is None or r["task"] == a.task) and (a.server is None or r["server"] == a.server):
            by.setdefault((r["task"], r["server"], batch_of(r)), []).append(r)
    pairs = sorted({(t, s) for t, s, _ in by if (t, s, a.batch_a) in by and (t, s, a.batch_b) in by})
    if not pairs:
        sys.exit(f"no task and server has runs in both {a.batch_a} and {a.batch_b}")
    for task, server in pairs:
        ra, rb = by[(task, server, a.batch_a)], by[(task, server, a.batch_b)]
        warn_mixed(ra, f"{task} {server} {a.batch_a}")
        warn_mixed(rb, f"{task} {server} {a.batch_b}")
        metric = a.metric or NUMBER_TO_BEAT.get(task, PASSES)
        print(
            f"\n{task} on {server}, B against A: passes over every run, the other numbers median (min-max) over "
            f"passing runs. Judged on {LABELS[metric]}; the rest is context. Pairs apart counts the (A, B) run "
            f"pairs on the side B moved to, ties half.\n"
        )
        print(f"| | A: {a.batch_a} | B: {a.batch_b} | pairs apart | verdict |")
        print("|---|---|---|---|---|")
        pa, pb = [float(passed(r)) for r in ra], [float(passed(r)) for r in rb]
        judged = pass_verdict(pa, pb) if metric == PASSES else ("", "context")
        print(f"| {PASSES} | {int(sum(pa))}/{len(pa)} | {int(sum(pb))}/{len(pb)} | {judged[0]} | {judged[1]} |")
        oka, okb = [r for r in ra if passed(r)], [r for r in rb if passed(r)]
        for col, label in METRICS:
            row = efficiency_verdict(ra, rb, col) if col == metric else ("", "context")
            if col == metric:
                judged = row
            print(
                f"| {label} | {spread(numbers(oka, col), len(oka))} | {spread(numbers(okb, col), len(okb))} "
                f"| {row[0]} | {row[1]} |"
            )
        print(f"\nverdict on {LABELS[metric]}: {judged[1]}")


def cmd_check(task: str) -> None:
    try:
        print("PASS " + CHECKS[task]())
    except CheckFailed as e:
        print(f"FAIL {e}")
        sys.exit(1)


COMMANDS = {
    "record-instance": cmd_record_instance,
    "mark": mark,
    "ensure-input": lambda: print(ensure_input()),
    "submit": cmd_submit,
    "derive-t3": cmd_derive_t3,
    "derive-t6": cmd_derive_t6,
    "derive-t6-neutral": cmd_derive_t6_neutral,
    "setup-t2-refuse": cmd_setup_t2_refuse,
    "setup-t4": cmd_setup_t4,
    "setup-t5": cmd_setup_t5,
    "setup-tier2": cmd_setup_tier2,
    "t10-clean": cmd_t10_clean,
    "handoff": cmd_handoff,
    "check": cmd_check,
    "mcp-calls": cmd_mcp_calls,
    "summary": cmd_summary,
    "compare": cmd_compare,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: harness.py {{{'|'.join(COMMANDS)}}} [args]")
    if sys.argv[1] not in ("summary", "compare"):  # these only read scorecards
        RESULTS.mkdir(exist_ok=True)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
