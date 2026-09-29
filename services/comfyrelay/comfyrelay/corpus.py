"""The docs corpus (#134): built into the image once, read by docs_search and docs_guide.

`comfyctl relay corpus build` makes it at image build time, from two sources:

    docs.comfy.org  Comfy-Org/docs at COMFY_DOCS_SHA: every English page the
                    `navigation.languages[en]` entry of its docs.json lists.
                    GPL-3.0. Fetched shallow and sparse (the repo is about
                    400 MB with its media; the pages are about 10 MB).
    guides          our own guides, the published skill skills/comfyui-workflows/:
                    each file its SKILL.md links to is a topic, including a
                    link to another skill (comfy-manifest). MIT.

Each page is converted from MDX to plain markdown: front matter goes (its
title and description are kept as fields), and so do `import` lines, JSX and
HTML tags and media. Fenced code is kept as it is. A component imported from
/snippets/ is replaced by that snippet's own converted text. Pages are then
split at their headings, and each section is one row of an SQLite FTS5 table,
carrying `source`, `version` (the docs SHA, or our version for the guides),
`path`, `license` and the upstream `url`.

The build writes, under --out:

    corpus.sqlite   the index, with a `meta` table saying what went in
    source/         the English markdown it indexed, unmodified, with the
                    snippets it inlined and the docs.json that listed the
                    pages (the GPL's Corresponding Source)
    NOTICE          the docs repo and SHA, the license, the build date as a
                    modification notice, where this script is, and the
                    non-affiliation statement
    GPL-3.0.txt     the docs repo's LICENSE, the GPL-3.0 text

The server only ever reads corpus.sqlite, read-only. Nothing here runs at
serve time but `Corpus`.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__

SCHEMA = 1
DOCS_REPO = "https://github.com/Comfy-Org/docs"
DOCS_SITE = "https://docs.comfy.org"
DOCS_SOURCE = "docs.comfy.org"
GUIDES_SOURCE = "guides"
GUIDES_SKILL = "comfyui-workflows"
REPO = "https://github.com/pixeloven/ComfyUI-Docker"
BUILD_SCRIPT = "services/comfyrelay/comfyrelay/corpus.py"
DOCS_LICENSE = "GPL-3.0"
GUIDES_LICENSE = "MIT"
DOCS_NOTE = (
    "docs.comfy.org describes the latest ComfyUI, which may not match the version this server serves; "
    "check a node's inputs with node_describe."
)

COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


class CorpusError(Exception):
    """The corpus can't be built or read. The CLI reports it and exits 1."""


# -- MDX to markdown ------------------------------------------------------------

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_IMPORT = re.compile(r"""^\s*import\s+(?:(\w+)\s+from\s+)?["']([^"']+)["'];?\s*$""")
_ESM = re.compile(r"""^\s*(?:import\s.*\sfrom\s+["']|import\s+["']|export\s+(?:const|default|function|let)\b)""")
# Inline code or a tag, whichever starts first, so a tag's attribute may hold inline code
# (type="`none` | object") and inline code may hold what looks like a tag (`<ComfyUI>/models`).
# An attribute's {expression} may nest one level (style={{margin: 0}}) and hold tags (icon={<Icon />}).
_TOKEN = re.compile(
    r"(?P<code>(?P<ticks>`+)(?:(?!\n\s*\n).)+?(?P=ticks))"
    r"|<(?P<closing>/?)(?P<name>[A-Za-z][\w.-]*)"
    r"(?P<attrs>(?:\s(?:[^<>\"'{}]|\"[^\"]*\"|'[^']*'|\{(?:[^{}]|\{[^{}]*\})*\})*)?)\s*(?P<self>/?)>",
    re.DOTALL,
)
_ATTR = re.compile(r"""([\w-]+)=(?:"([^"]*)"|'([^']*)'|\{["'`]([^"'`]*)["'`]\})""")
_COMMENT = re.compile(r"<!--.*?-->|\{/\*.*?\*/\}", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
# Lowercase names that are HTML, not placeholders such as <your-token>, which stay as text.
_HTML = frozenset(
    (
        "a abbr b blockquote br center code dd details div dl dt em figcaption figure font h1 h2 h3 h4 h5 h6 "
        "hr i kbd li mark ol p pre s section small span strong sub summary sup table tbody td tfoot th thead "
        "tr u ul"
    ).split()
)
# Media and embeds, dropped with everything between their tags.
_MEDIA = frozenset("img video audio source iframe picture svg frame embed object script style".split())
# The attributes whose values are text worth keeping when a component's tags go.
_TEXT_ATTRS = ("title", "name", "path", "body", "query", "header", "label", "type")


@dataclass
class Page:
    title: str
    description: str
    body: str
    snippets: set[str] = field(default_factory=set)  # the /snippets/ files inlined, as repo paths


def front_matter(text: str) -> tuple[dict[str, str], str]:
    """The simple `key: value` front matter, and the text after it."""
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    fields = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and re.fullmatch(r"[A-Za-z_][\w-]*", key.strip()):
            fields[key.strip()] = value.strip().strip("\"'")
    return fields, text[m.end() :]


def _chunks(text: str) -> Iterator[tuple[bool, str]]:
    """(is_code, text) runs: fenced code blocks are code, the rest is prose."""
    prose: list[str] = []
    code: list[str] = []
    fence = ""
    for line in text.splitlines(keepends=True):
        m = _FENCE.match(line)
        if fence:
            code.append(line)
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence)
                and not line.strip()[len(m.group(1)) :]
            ):
                yield True, "".join(code)
                code, fence = [], ""
        elif m:
            if prose:
                yield False, "".join(prose)
                prose = []
            fence = m.group(1)
            code.append(line)
        else:
            prose.append(line)
    if prose:
        yield False, "".join(prose)
    if code:
        yield True, "".join(code)  # an unclosed fence runs to the end, as markdown renders it


def _strip_prose(text: str, components: dict[str, str]) -> str:
    """Tags, media, comments and ESM lines out of prose that holds no fenced code. Inline code is left alone."""
    text = _COMMENT.sub("", text)
    text = "".join(line for line in text.splitlines(keepends=True) if not _ESM.match(line))
    return _strip_tags(text, components)


def _strip_tags(text: str, components: dict[str, str]) -> str:
    text = _MD_IMAGE.sub("", text)
    out: list[str] = []
    last = 0
    skip_until: str | None = None  # inside a media element: drop everything to its closing tag
    for m in _TOKEN.finditer(text):
        if m.group("code"):
            continue  # inline code is text, whatever it holds
        closing, name, attrs, selfclosing = m.group("closing"), m.group("name"), m.group("attrs") or "", m.group("self")
        lower = name.lower()
        if skip_until is not None:
            if closing and lower == skip_until:
                skip_until = None
                last = m.end()
            continue
        component = name[0].isupper()
        if not component and lower not in _HTML and lower not in _MEDIA:
            continue  # a placeholder such as <your-api-key>: text
        out.append(text[last : m.start()])
        last = m.end()
        if lower in _MEDIA:
            if (
                not closing
                and not selfclosing
                and re.search(rf"</{re.escape(name)}\s*>", text[m.end() :], re.IGNORECASE)
            ):
                skip_until = lower
            continue
        if closing:
            out.append("\n" if component else "")
        elif name in components:
            out.append("\n" + components[name] + "\n")
        elif component:
            values = [v for k, *vs in _ATTR.findall(attrs) if k in _TEXT_ATTRS for v in vs if v]
            out.append("\n" + " ".join(values) + "\n" if values else "\n")
        elif (
            lower in ("br", "hr", "p", "div", "li", "tr", "summary", "details")
            or lower[:1] == "h"
            and lower[1:].isdigit()
        ):
            out.append("\n")
    if skip_until is None:
        out.append(text[last:])
    return "".join(out)


def mdx_to_markdown(text: str, read_snippet: Callable[[str], str] | None = None, *, _depth: int = 0) -> Page:
    """One MDX page as plain markdown: see the module docstring. `read_snippet` maps "/snippets/x.mdx" to its MDX."""
    fields, text = front_matter(text)
    components: dict[str, str] = {}
    snippets: set[str] = set()
    for is_code, chunk in _chunks(text):
        if is_code:
            continue
        for line in chunk.splitlines():
            m = _IMPORT.match(line)
            if m and m.group(1) and m.group(2).startswith("/snippets/") and read_snippet and _depth < 5:
                try:
                    inner = mdx_to_markdown(read_snippet(m.group(2)), read_snippet, _depth=_depth + 1)
                except FileNotFoundError:
                    continue  # a missing snippet renders as nothing
                components[m.group(1)] = inner.body.strip()
                snippets |= {m.group(2).lstrip("/")} | inner.snippets
    parts = [chunk if is_code else _strip_prose(chunk, components) for is_code, chunk in _chunks(text)]
    body = "\n".join(line.rstrip() for line in "".join(parts).splitlines())
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    return Page(fields.get("title", ""), fields.get("description", ""), body, snippets)


@dataclass
class Section:
    heading: str  # the heading trail, "Routes › Built in routes", or "" before the first heading
    anchor: str  # the last heading as a URL fragment, or ""
    text: str


def slug(heading: str) -> str:
    """A heading as docs.comfy.org (Mintlify) makes its anchor, near enough: lowercase words joined by hyphens."""
    words = re.sub(r"[^\w\s-]", "", heading.replace("`", "").lower()).split()
    return "-".join(words)


def sections(markdown: str) -> list[Section]:
    """Split at headings outside fenced code. A heading with no text of its own is folded into the next section."""
    out: list[Section] = []
    trail: list[tuple[int, str]] = []
    anchor = ""
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text and any(not _HEADING.match(line) for line in lines if line.strip()):
            out.append(Section(" › ".join(h for _, h in trail), anchor, text))
            lines.clear()

    for is_code, chunk in _chunks(markdown):
        for line in chunk.splitlines():
            m = None if is_code else _HEADING.match(line)
            if m:
                flush()
                level = len(m.group(1))
                heading = re.sub(r"\\(.)", r"\1", m.group(2).replace("`", ""))
                custom = re.search(r"\s*\{#([^{}]+)\}$", heading)  # an explicit anchor: "Run {#run}"
                heading = heading[: custom.start()] if custom else heading
                anchor = slug(custom.group(1) if custom else heading)
                trail[:] = [(lv, h) for lv, h in trail if lv < level] + [(level, heading)]
            lines.append(line)
    flush()
    return out


# -- the page list --------------------------------------------------------------

_OPERATION = re.compile(r"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\s+/", re.IGNORECASE)


def docs_pages(docs_json: dict[str, Any], language: str = "en") -> tuple[list[str], list[str]]:
    """The pages the site's navigation lists for one language, in order: (paths, entries that are not pages).

    Page entries are strings, nested in groups, tabs and the like. An entry
    that is an HTTP method and a path ("GET /nodes") is an OpenAPI operation
    that Mintlify generates a page for from a spec, not a file in the repo.
    A file name may hold a space ("built-in-nodes/Video Slice").
    """
    langs = docs_json.get("navigation", {}).get("languages", [])
    nav = next((lang for lang in langs if lang.get("language") == language), None)
    if nav is None:
        raise CorpusError(f"docs.json has no navigation.languages entry for {language!r}")
    pages: list[str] = []
    other: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            (other if _OPERATION.match(node.strip()) else pages).append(node.strip().strip("/"))
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key != "language" and isinstance(value, (list, dict)):
                    walk(value)

    walk(nav)
    return list(dict.fromkeys(pages)), other


# -- the build ------------------------------------------------------------------


def _git(cwd: Path, *args: str, stdin: str | None = None) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, input=stdin, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise CorpusError("git is not installed; the corpus build fetches the docs with it") from exc
    if done.returncode != 0:
        raise CorpusError(f"git {' '.join(args[:2])} failed: {done.stderr.strip()[-500:]}")
    return done.stdout


def fetch_docs(repo: str, sha: str, dest: Path) -> list[str]:
    """A shallow, sparse checkout of `repo` at `sha` in `dest`: docs.json, LICENSE, the snippets and the English
    pages docs.json lists. No history and no media are fetched. Returns the page paths docs.json lists."""
    if not COMMIT_SHA.fullmatch(sha):
        raise CorpusError(f"the docs pin must be a full 40-character commit SHA, not {sha!r}")
    dest.mkdir(parents=True, exist_ok=True)
    _git(dest, "init", "-q")
    _git(dest, "fetch", "-q", "--depth", "1", "--filter=blob:none", repo, sha)
    got = _git(dest, "rev-parse", "FETCH_HEAD").strip()
    if got != sha:
        raise CorpusError(f"fetched {got}, not the pinned {sha}")
    pages, _ = docs_pages(json.loads(_git(dest, "show", "FETCH_HEAD:docs.json")))
    patterns = ["/docs.json", "/LICENSE", "/snippets/"] + [f"/{p}.mdx\n/{p}.md" for p in pages]
    _git(dest, "sparse-checkout", "set", "--no-cone", "--stdin", stdin="\n".join(patterns) + "\n")
    _git(dest, "checkout", "-q", "FETCH_HEAD")
    return pages


_COLUMNS = ("title", "section", "description", "body", "source", "version", "path", "url", "license")


def _create(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE VIRTUAL TABLE docs USING fts5(
            title, section, description, body,
            source UNINDEXED, version UNINDEXED, path UNINDEXED, url UNINDEXED, license UNINDEXED,
            tokenize = 'porter unicode61'
        );
        CREATE TABLE guides (
            topic TEXT PRIMARY KEY, title TEXT NOT NULL, summary TEXT NOT NULL, path TEXT NOT NULL,
            url TEXT NOT NULL, license TEXT NOT NULL, version TEXT NOT NULL, text TEXT NOT NULL, position INTEGER
        );
        """
    )


def _insert(db: sqlite3.Connection, page: Page, **row: str) -> int:
    count = 0
    for i, sec in enumerate(sections(page.body)):
        url = row["url"] + (f"#{sec.anchor}" if sec.anchor else "")
        values = {
            **row,
            "title": page.title,
            "section": sec.heading,
            "description": page.description if i == 0 else "",
            "body": sec.text,
            "url": url,
        }
        db.execute(
            f"INSERT INTO docs ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
            [values[c] for c in _COLUMNS],
        )
        count += 1
    return count


def index_docs(db: sqlite3.Connection, checkout: Path, sha: str, source_out: Path | None) -> dict[str, Any]:
    """Index the English pages of a docs checkout. Copies each indexed page, and the snippets it inlined, to
    `source_out`. Returns this source's entry for the meta table."""
    pages, operations = docs_pages(json.loads((checkout / "docs.json").read_text()))

    def read_snippet(ref: str) -> str:
        path = (checkout / ref.lstrip("/")).resolve()
        if checkout.resolve() not in path.parents:
            raise FileNotFoundError(ref)
        return path.read_text()

    indexed, missing, used, sections_n = 0, [], set(), 0
    for page_path in pages:
        found = next(
            (checkout / f"{page_path}{ext}" for ext in (".mdx", ".md") if (checkout / f"{page_path}{ext}").is_file()),
            None,
        )
        if found is None:
            missing.append(page_path)
            continue
        rel = found.relative_to(checkout).as_posix()
        page = mdx_to_markdown(found.read_text(), read_snippet)
        page.title = page.title or page_path.rsplit("/", 1)[-1]
        sections_n += _insert(
            db,
            page,
            source=DOCS_SOURCE,
            version=sha,
            path=rel,
            url=f"{DOCS_SITE}/{'' if page_path == 'index' else quote(page_path)}".rstrip("/"),
            license=DOCS_LICENSE,
        )
        indexed += 1
        used |= {rel} | page.snippets
    if source_out is not None:
        for rel in sorted(used | {"docs.json"}):  # docs.json chose the pages, so it is part of the source
            (source_out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checkout / rel, source_out / rel)
    return {
        "name": DOCS_SOURCE,
        "repo": DOCS_REPO,
        "version": sha,
        "license": DOCS_LICENSE,
        "url": DOCS_SITE,
        "pages": indexed,
        "sections": sections_n,
        "skipped": {"openapi_operations": len(operations), "missing": missing},
        "note": DOCS_NOTE,
    }


_LINK = re.compile(r"\]\(([^)\s]+\.md)\)")


def _summary(fields: dict[str, str], body: str) -> tuple[str, str]:
    """A guide's title (its H1) and one-paragraph summary (its description, else the first paragraph)."""
    title = next((m.group(2) for m in map(_HEADING.match, body.splitlines()) if m and len(m.group(1)) == 1), "")
    if fields.get("description"):
        return title, fields["description"]
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip() and not p.lstrip().startswith("#")]
    return title, " ".join(paras[0].split()) if paras else ""


def guide_topics(skills: Path) -> list[tuple[str, Path, str]]:
    """(topic, file, summary) for every guide a list item in the comfyui-workflows index links to, in its order.
    The summary is the item's text after the link. A file named SKILL.md is another skill, and its topic is that
    skill's directory name."""
    index = skills / GUIDES_SKILL / "SKILL.md"
    if not index.is_file():
        raise CorpusError(f"no guides index at {index}")
    items: list[str] = []
    for line in index.read_text().splitlines():
        if re.match(r"\s*[-*]\s", line):
            items.append(line.strip()[1:].strip())
        elif items and line.startswith(" ") and line.strip():
            items[-1] += " " + line.strip()
    topics: dict[str, tuple[Path, str]] = {}
    for item in items:
        m = _LINK.search(item)
        if not m:
            continue
        path = (index.parent / m.group(1)).resolve()
        if skills.resolve() not in path.parents or not path.is_file():
            raise CorpusError(f"{index} links to {m.group(1)}, which is not a file under {skills}")
        summary = item[m.end() :].lstrip(":—- ").strip()
        topics.setdefault(path.parent.name if path.name == "SKILL.md" else path.stem, (path, summary))
    if not topics:
        raise CorpusError(f"{index} links to no topic")
    return [(topic, path, summary) for topic, (path, summary) in topics.items()]


def index_guides(db: sqlite3.Connection, skills: Path, version: str) -> dict[str, Any]:
    root = skills.resolve().parent
    topics = guide_topics(skills)
    count = 0
    for position, (topic, path, listed) in enumerate(topics):
        fields, body = front_matter(path.read_text())
        title, summary = _summary(fields, body)
        summary = listed or summary
        rel = path.resolve().relative_to(root).as_posix()
        url = f"{REPO}/blob/v{version}/{rel}"
        db.execute(
            "INSERT INTO guides VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (topic, title or topic, summary, rel, url, GUIDES_LICENSE, version, body.strip() + "\n", position),
        )
        count += _insert(
            db,
            Page(title or topic, summary, body),
            source=GUIDES_SOURCE,
            version=version,
            path=rel,
            url=url,
            license=GUIDES_LICENSE,
        )
    return {
        "name": GUIDES_SOURCE,
        "repo": REPO,
        "version": version,
        "license": GUIDES_LICENSE,
        "url": f"{REPO}/tree/v{version}/skills/{GUIDES_SKILL}",
        "pages": len(topics),
        "sections": count,
        "topics": [t for t, _, _ in topics],
    }


def notice(sha: str, built: str, version: str) -> str:
    return f"""\
comfyrelay: third-party content in this image

The docs corpus (/opt/corpus/corpus.sqlite, and the markdown it was built from
in /opt/corpus/source/) comes from Comfy-Org/docs, the source of
{DOCS_SITE}:

    {DOCS_REPO}
    commit {sha}

It is licensed under the GNU General Public License, version 3 (GPL-3.0). The
full text is in /licenses/GPL-3.0.txt.

Modified on {built}: the English pages listed in the repository's docs.json
were converted to plain markdown (front matter, import lines, JSX and HTML
tags, images and videos removed; /snippets/ content inlined; code kept), split
at their headings, and indexed in corpus.sqlite. The unmodified pages that
were indexed, the snippets they include, and the docs.json that chose them
are in /opt/corpus/source/.

The build script is {BUILD_SCRIPT}
in {REPO}, at the tag v{version}:
{REPO}/blob/v{version}/{BUILD_SCRIPT}

corpus.sqlite as a whole is licensed GPL-3.0. It also holds this project's own
guides (skills/{GUIDES_SKILL}/), which are MIT-licensed. comfyrelay's code is
MIT-licensed; it reads the corpus as a separate data file (an aggregate).

© Comfy Org. Not affiliated with or endorsed by Comfy Org.
"""


def build(*, docs: Path, sha: str, skills: Path, out: Path, version: str = __version__) -> dict[str, Any]:
    """Build the corpus in `out` from a docs checkout at `sha` and the skills directory. Returns the meta summary."""
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "corpus.sqlite"
    db_path.unlink(missing_ok=True)
    built = datetime.now(UTC).strftime("%Y-%m-%d")
    db = sqlite3.connect(db_path)
    try:
        _create(db)
        sources = [index_docs(db, docs, sha, out / "source"), index_guides(db, skills, version)]
        if not sources[0]["pages"]:
            raise CorpusError(f"no docs page was found in {docs}")
        meta = {"schema": SCHEMA, "built_at": built, "builder": f"comfyrelay {version}", "sources": sources}
        db.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
        db.execute("INSERT INTO docs(docs) VALUES ('optimize')")
        db.commit()
    finally:
        db.close()
    db = sqlite3.connect(db_path)
    db.execute("VACUUM")
    db.close()
    (out / "NOTICE").write_text(notice(sha, built, version))
    shutil.copyfile(docs / "LICENSE", out / "GPL-3.0.txt")
    return {
        **meta,
        "bytes": db_path.stat().st_size,
        "seconds": round(time.monotonic() - started, 1),
    }


# -- reading it -------------------------------------------------------------------


@dataclass
class Hit:
    source: str
    version: str
    path: str
    url: str
    license: str
    title: str
    section: str
    text: str
    topic: str | None = None  # a guide's docs_guide topic


class Corpus:
    """The built index, read-only. Each call opens its own connection, so a search can run in a worker thread."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise CorpusError(f"no corpus at {self.path}")
        try:
            with self._connect() as db:
                self.meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
        except sqlite3.Error as exc:
            raise CorpusError(f"{self.path} is not a corpus this server can read: {exc}") from exc
        if self.meta.get("schema") != SCHEMA:
            raise CorpusError(f"{self.path} has corpus schema {self.meta.get('schema')}, not {SCHEMA}")

    def _connect(self) -> closing[sqlite3.Connection]:
        return closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro&immutable=1", uri=True))

    def search(self, words: list[str], limit: int, max_chars: int) -> tuple[list[Hit], int, str]:
        """Sections matching every one of `words`, best first; failing that, any of them. (hits, total, "all"|"any").

        Each word is quoted, so FTS5 syntax in it is text, and one that the tokenizer splits (sd1.5) is a phrase."""
        words = [w.replace('"', "") for w in words if w.replace('"', "")]
        if not words:
            return [], 0, "any"
        with self._connect() as db:
            for mode, joiner in (("all", " "), ("any", " OR ")):
                match = joiner.join(f'"{w}"' for w in words)
                total = db.execute("SELECT count(*) FROM docs WHERE docs MATCH ?", (match,)).fetchone()[0]
                if total:
                    break
            if not total:
                return [], 0, "any"
            rows = db.execute(
                "SELECT docs.source, docs.version, docs.path, docs.url, docs.license, docs.title, docs.section, "
                "docs.body, guides.topic FROM docs LEFT JOIN guides ON guides.path = docs.path WHERE docs MATCH ? "
                "ORDER BY bm25(docs, 8.0, 4.0, 2.0, 1.0) LIMIT ?",
                (match, limit),
            ).fetchall()
        return [Hit(*row[:7], excerpt(row[7], words, max_chars), row[8]) for row in rows], total, mode

    def topics(self) -> list[dict[str, str]]:
        with self._connect() as db:
            rows = db.execute("SELECT topic, title, summary, path, url FROM guides ORDER BY position").fetchall()
        return [dict(zip(("topic", "title", "summary", "path", "url"), r, strict=True)) for r in rows]

    def guide(self, topic: str) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT topic, title, summary, path, url, license, version, text FROM guides WHERE topic = ?", (topic,)
            ).fetchone()
        keys = ("topic", "title", "summary", "path", "url", "license", "version", "text")
        return dict(zip(keys, row, strict=True)) if row else None

    def info(self) -> dict[str, Any]:
        """What server_info reports: the sources with their versions and licenses, and the page count."""
        sources = [{k: v for k, v in s.items() if k != "skipped"} for s in self.meta["sources"]]
        return {
            "status": "built",
            "built_at": self.meta["built_at"],
            "pages": sum(s["pages"] for s in sources),
            "sources": sources,
            "notice": "/licenses/NOTICE in the image",
        }


def excerpt(text: str, words: list[str], limit: int) -> str:
    """`text` if it fits in `limit` characters. Otherwise the `limit` characters around the stretch that holds the
    most distinct query words (earliest first), with its first matched word a third of the way in. A word matches
    at the start of a word in the text, by its stem as well (grouping finds group), as the stemmed index does."""
    if len(text) <= limit:
        return text
    lower = text.lower()
    stems = {w: w if len(w) <= 4 else w[: max(4, len(w) - 3)] for w in words}
    hits = sorted(
        (m.start(), w) for w, stem in stems.items() for m in re.finditer(rf"(?<![a-z0-9]){re.escape(stem)}", lower)
    )[:500]
    span = limit * 2 // 3

    def covered(at: int) -> int:
        return len({w for i, w in hits if at <= i < at + span})

    at = max((i for i, _ in hits), key=lambda i: (covered(i), -i), default=0)
    start = max(0, min(at - limit // 3, len(text) - limit))
    cut = text[start : start + limit].rstrip()
    return ("…" if start else "") + cut + ("…" if start + limit < len(text) else "")
