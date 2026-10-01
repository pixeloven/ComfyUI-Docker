#!/usr/bin/env python3
"""Stdlib-only helpers shared by the harness's setup and check scripts.

Every check reads ComfyUI's HTTP API or the scratch filesystem, never an agent
transcript. Usage: harness.py <command> [args]; see COMMANDS at the bottom.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.error
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


def mark(task: str) -> None:
    marker_path(task).write_text(json.dumps(sorted(history())))


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
    image = image or os.environ.get("COMFYRELAY_IMAGE", "comfyrelay:latest")
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


def t5_same_graph(g: dict, nodes: list[dict]) -> str | None:
    """Why the job's nodes and settings aren't the template's, or None. The job
    must run each node class as many times as the template does, and each job
    node's set values (every input that isn't a link; an empty dict counts as
    unset) must be widget values of a template node of its class: the template's
    input file, upscale method, factor and file prefix. Links aren't compared."""
    by_class: dict[str, list[list]] = {}
    for n in nodes:
        by_class.setdefault(n["type"], []).append(widget_values(n))
    want = Counter(n["type"] for n in nodes)
    got = Counter(str(n.get("class_type")) for n in g.values())
    if got != want:
        return f"runs {dict(sorted(got.items()))}, where the template runs {dict(sorted(want.items()))}"
    for nid, n in sorted(g.items()):
        values = {k: v for k, v in (n.get("inputs") or {}).items() if not is_link(v) and v != {}}
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
        size = read_png(path)[:2]
        if size != want_size:
            raise CheckFailed(f"{f['filename']} is {size[0]}x{size[1]}, want {want_size[0]}x{want_size[1]}")
    names = {f["filename"] for f in saved}
    reported = rep.get("outputs")
    if not isinstance(reported, list) or {Path(str(r)).name for r in reported} != names:
        raise CheckFailed(f"report's outputs {reported!r} are not the files {job[:8]} saved to output/: {sorted(names)}")

    # The relay's runnability check must agree with what happened: the run succeeded...
    ran = runnability(name)
    if ran.get("runnable") is not True:
        raise CheckFailed(f"{job[:8]} succeeded, but comfyrelay says {name} is not runnable: {json.dumps(ran)}")
    if rep.get("runnable") is not True:
        raise CheckFailed(f"report says runnable={rep.get('runnable')!r}; comfyrelay says true")
    # ...and a candidate that declares a model (none is on disk) must not be runnable.
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
        raise CheckFailed("no candidate declares a model, so the runnability check can't be tested both ways")
    other = runnability(needs_model)
    if other.get("runnable") is not False or not other.get("missing_models"):
        raise CheckFailed(f"comfyrelay says {needs_model}, whose model isn't on disk, is runnable: {json.dumps(other)}")
    return (
        f"{name} is runnable per comfyrelay and {job[:8]} completed with its nodes and settings: "
        f"{len(saved)} {want_size[0]}x{want_size[1]} PNG; {needs_model} is not runnable (missing models)"
    )


# --- External-agent mode (external.sh) -------------------------------------------

AGENT_PREAMBLE = """\
You are being evaluated on a task against a ComfyUI instance. Your only way to reach it is
the comfyrelay MCP server below. Nothing enforces these rules, so they are on you:

- Use only that server. Don't call ComfyUI or any other URL, don't use other MCP servers
  or tools that reach the network, and don't install or download anything.
- Read only two things: the token file below, and your workspace, {workspace}.
  Nothing else on this machine, the repository included.
- Your workspace is your working directory. Put scratch files (a client script, saved
  responses) anywhere in it, and your answers in its results/ directory.
- If your own tooling saves a large tool result to a file outside the workspace, don't
  read that file: call the tool again with narrower arguments.
- Send the token straight from its file on every request, and never print it, echo it, or
  write it anywhere: -H "Authorization: Bearer $(cat {token_file})".

The server speaks MCP (protocol version 2025-06-18) as JSON-RPC 2.0 over streamable HTTP:
one POST per message to {url}, with the headers
  Content-Type: application/json
  Accept: application/json, text/event-stream
  Authorization: Bearer <the token, read from the file as above>
1. POST {{"jsonrpc":"2.0","id":1,"method":"initialize","params":{{"protocolVersion":"2025-06-18","capabilities":{{}},"clientInfo":{{"name":"agent","version":"0"}}}}}}.
   The response has an Mcp-Session-Id header (curl -D - shows it). On every later request,
   also send the headers Mcp-Session-Id: <id> and MCP-Protocol-Version: 2025-06-18.
2. POST {{"jsonrpc":"2.0","method":"notifications/initialized"}} (no id; the answer is empty).
3. POST {{"jsonrpc":"2.0","id":2,"method":"tools/list"}} to see the tools and their input schemas.
4. POST {{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{{"name":"<tool>","arguments":{{...}}}}}}.
   The tool's answer is JSON text in result.content[].text; result.isError true means it failed.
A response may be a server-sent event stream: the JSON-RPC message is on the "data:" line
whose id matches your request. curl or a short stdlib Python client both work. Big
arguments are easier from a file (curl --data @file.json).

The task follows. Paths in it are relative to {workspace}.
"""


def cmd_handoff(task: str, token_file: str, probe_json: str) -> None:
    """Write the brief (the preamble, then the task's prompt) into the workspace as
    TASK.md, and the handoff to RESULTS/<task>.handoff.json; print both. The agent
    is never pointed at tasks/, which holds the answers."""
    url = f"http://127.0.0.1:{os.environ['COMFYRELAY_PORT']}/mcp"
    prompt = (HERE / "tasks" / task / "prompt.md").read_text()
    brief = AGENT_PREAMBLE.format(workspace=WORKSPACE, token_file=token_file, url=url) + "\n" + prompt
    brief_file = WORKSPACE / "TASK.md"
    brief_file.write_text(brief)
    handoff = {
        "task": task,
        "brief_file": str(brief_file),
        "brief": brief,
        "mcp": {"server": "comfyrelay", "url": url, "token_file": token_file},
        "workspace": str(WORKSPACE),
        "results_dir": str(WORKSPACE / "results"),
        "relay_tools": json.loads(probe_json)["tools"],
        "confinement": "by instruction only: nothing stops the agent using other tools; see README",
        "check": f"./external.sh check {task}",
        "started": int(time.time()),
    }
    out = RESULTS / f"{task}.handoff.json"
    out.write_text(json.dumps(handoff, indent=2) + "\n")
    print(f"== {task} is ready for an external agent. Give it the brief below, verbatim (also {brief_file}),")
    print(f"== with {WORKSPACE} as its working directory. Then: ./external.sh check {task}")
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
}


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
    "setup-t2-refuse": cmd_setup_t2_refuse,
    "setup-t4": cmd_setup_t4,
    "setup-t5": cmd_setup_t5,
    "handoff": cmd_handoff,
    "check": cmd_check,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: harness.py {{{'|'.join(COMMANDS)}}} [args]")
    RESULTS.mkdir(exist_ok=True)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
