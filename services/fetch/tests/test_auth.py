"""Credential resolution, including the redirect behaviour a naive port loses."""
import http.server
import json
import socketserver
import threading

import pytest
from comfyfetch import http as cf
from comfyfetch.auth import AuthMap


def test_literal_token_is_ignored():
    """The schema rejects literals; the code must not honour one that slips through."""
    a = AuthMap.from_document({"auth": {"civitai.com": "sk-real-token"}})
    assert a.var_for("https://civitai.com/x") is None


def test_token_resolves_by_host(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "t")
    a = AuthMap.from_document({"auth": {"huggingface.co": "${HF_TOKEN}"}})
    assert a.token_for("https://huggingface.co/a") == "t"
    # A different host -- the CDN a HuggingFace download redirects to -- gets nothing.
    assert a.token_for("https://us.aws.cdn.hf.co/a") is None


def test_missing_var_is_reported_not_enforced(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    a = AuthMap.from_document({"auth": {"huggingface.co": "${HF_TOKEN}"}})
    assert a.token_for("https://huggingface.co/a") is None
    assert a.missing_var_for("https://huggingface.co/a") == "HF_TOKEN"


class _Echo(http.server.BaseHTTPRequestHandler):
    seen: dict = {}

    def do_GET(self):
        _Echo.seen[self.server.server_address[1]] = {
            k.lower(): v for k, v in self.headers.items()}
        if self.path.startswith("/cross"):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.other}/d")
            self.end_headers()
        elif self.path.startswith("/same"):
            self.send_response(302)
            self.send_header("Location", "/d")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


@pytest.fixture
def two_servers():
    servers = []
    for _ in range(2):
        s = socketserver.TCPServer(("127.0.0.1", 0), _Echo)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
    servers[0].other = servers[1].server_address[1]
    servers[1].other = servers[0].server_address[1]
    _Echo.seen = {}
    yield [s.server_address[1] for s in servers]
    for s in servers:
        s.shutdown()


def test_credential_stripped_on_cross_origin_redirect(two_servers):
    """urllib forwards Authorization across redirects; curl does not.

    HuggingFace answers /resolve/ with a 302 to a different host, so without
    this the account token reaches the CDN on every gated download.
    """
    first, other = two_servers
    cf.request(f"http://127.0.0.1:{first}/cross", token="CANARY").read()
    assert "authorization" in _Echo.seen[first]
    assert "authorization" not in _Echo.seen[other]


def test_credential_kept_on_same_origin_redirect(two_servers):
    first, _ = two_servers
    cf.request(f"http://127.0.0.1:{first}/same", token="CANARY").read()
    assert "authorization" in _Echo.seen[first]
