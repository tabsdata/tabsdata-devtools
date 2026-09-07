#
# Copyright 2026 Tabsdata Inc.
#

"""render.py is pure, and it is where a mistake ships a broken index silently."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import pytest
from conftest import make_dist

from tabsdata_dev.tool.pypi.model import normalize
from tabsdata_dev.tool.pypi.indexhtml import render_all, render_project, render_root


class _Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.anchors.append(dict(attrs))


def anchors(html: str) -> list[dict]:
    p = _Anchors()
    p.feed(html)
    return p.anchors


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tabsdata", "tabsdata"),
        ("Tabs_Data.Core", "tabs-data-core"),
        ("tabs--data", "tabs-data"),
        ("TABS._-DATA", "tabs-data"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_every_anchor_carries_a_sha256_fragment():
    dists = [make_dist("0.9.5"), make_dist("0.9.6")]
    for a in anchors(render_project("tabsdata", dists)):
        assert re.search(r"#sha256=[0-9a-f]{64}$", a["href"])


def test_requires_python_is_escaped():
    html = render_project("tabsdata", [make_dist(requires_python=">=3.10")])
    assert 'data-requires-python="&gt;=3.10"' in html
    assert 'data-requires-python=">=3.10"' not in html


def test_hrefs_are_relative_and_resolve_from_the_project_page():
    d = make_dist()
    a = anchors(render_project("tabsdata", [d]))[0]
    assert a["href"].startswith("../../files/")
    resolved = urljoin("https://pypi.tabsdata.com/simple/tabsdata/", a["href"])
    assert resolved.startswith(f"https://pypi.tabsdata.com/files/{d.filename}")


def test_version_order_is_not_lexical():
    html = render_project(
        "tabsdata", [make_dist("0.9.5"), make_dist("0.9.10"), make_dist("0.10.0")]
    )
    names = [a["href"] for a in anchors(html)]
    assert [n.split("-")[1] for n in names] == ["0.9.5", "0.9.10", "0.10.0"]


def test_unparseable_version_sorts_last_without_raising():
    html = render_project("tabsdata", [make_dist("not-a-version"), make_dist("1.0.0")])
    hrefs = [a["href"] for a in anchors(html)]
    assert len(hrefs) == 2
    assert "1.0.0" in hrefs[0]
    assert "not-a-version" in hrefs[1]


def test_yanked_emits_the_attribute_only_when_set():
    plain = render_project("tabsdata", [make_dist(yanked=None)])
    assert "data-yanked" not in plain

    yanked = render_project("tabsdata", [make_dist(yanked="bad AVX512 kernel")])
    assert 'data-yanked="bad AVX512 kernel"' in yanked


def test_yank_reason_is_escaped():
    html = render_project("tabsdata", [make_dist(yanked='broke <everything> & "more"')])
    assert 'data-yanked="broke &lt;everything&gt; &amp; &quot;more&quot;"' in html
    assert "<everything>" not in html


def test_render_is_deterministic():
    dists = [make_dist("0.9.6"), make_dist("0.9.5")]
    assert render_all(dists) == render_all(list(reversed(dists)))


def test_render_all_includes_landing_and_root_pages():
    pages = render_all([make_dist()])
    assert set(pages) == {
        "index.html",
        "simple/index.html",
        "simple/tabsdata/index.html",
    }
    assert 'href="simple/"' in pages["index.html"]


def test_root_page_links_every_project():
    hrefs = [a["href"] for a in anchors(render_root({"zeta", "tabsdata", "alpha"}))]
    assert hrefs == ["alpha/", "tabsdata/", "zeta/"]


def test_repository_version_meta_is_present():
    for html in render_all([make_dist()]).values():
        assert '<meta name="pypi:repository-version" content="1.0">' in html
