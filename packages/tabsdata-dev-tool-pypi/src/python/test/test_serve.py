#
# Copyright 2026 Tabsdata Inc.
#

"""serve --at NAME: the tree, and under /NAME/ the namespace as push lays it out."""

from __future__ import annotations

import functools
import http.client
import http.server
import threading
import urllib.request
from urllib.parse import urljoin

import pytest
from conftest import release
from tabsdata_dev.tool import pypi
from tabsdata_dev.tool.pypi import serve as serve_mod
from tabsdata_dev.tool.pypi.generate import generate
from tabsdata_dev.tool.pypi.indexhtml import render_namespace
from tabsdata_dev.tool.pypi.tree import load_index


@pytest.fixture
def server(raw, staging, tmp_path, out):
    release(raw)
    generate(raw, staging, out)
    pages = tmp_path / "pages"
    for rel, text in render_namespace(load_index(staging)).items():
        (pages / rel).parent.mkdir(parents=True, exist_ok=True)
        (pages / rel).write_text(text)
    handler = functools.partial(
        serve_mod._Handler, tree=staging, at="tucu", pages=pages
    )
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url: str) -> bytes:
    with urllib.request.urlopen(url) as resp:
        return resp.read()


def href(page: bytes) -> str:
    return page.decode().split('href="', 1)[1].split('"', 1)[0]


def test_a_namespace_is_served_beside_the_tree(server, staging):
    d = load_index(staging)[0]
    wheel = (staging / "files" / d.filename).read_bytes()
    assert href(get(f"{server}/tucu/")) == "tabsdata/"
    project = f"{server}/tucu/tabsdata/"
    url = urljoin(project, href(get(project))).split("#", 1)[0]
    assert url == f"{server}/tucu/files/{d.filename}"
    assert get(url) == wheel
    assert (
        get(f"{url}.metadata")
        == (staging / "files" / f"{d.filename}.metadata").read_bytes()
    )
    # the lane's own layout is still there
    lane = f"{server}/simple/tabsdata/"
    assert get(urljoin(lane, href(get(lane))).split("#", 1)[0]) == wheel


def test_a_namespace_url_without_its_slash_is_redirected(server):
    host, port = server.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port))
    conn.request("GET", "/tucu")
    resp = conn.getresponse()
    assert resp.status == 301 and resp.getheader("Location") == "/tucu/"


def test_serve_takes_at():
    parse = pypi.build_parser().parse_args
    assert parse(["serve"]).at == "simple"
    a = parse(["serve", "--lane", "prod", "--at", "tucu", "--port", "9000"])
    assert (a.lane, a.at, a.port) == ("prod", "tucu", 9000)
