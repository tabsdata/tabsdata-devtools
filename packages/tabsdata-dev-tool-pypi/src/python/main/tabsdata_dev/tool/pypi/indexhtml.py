#
# Copyright 2026 Tabsdata Inc.
#

"""Dist list -> PEP 503 HTML.

Pure: no AWS, no filesystem, no clock. This is where the correctness risk lives
(normalization, escaping, relative hrefs, sort order), so it is the module with
real unit tests. It must also be deterministic — the same sidecars produce
byte-identical HTML — because both `generate --check` and the push plan's
"unchanged" verdict depend on that.
"""

from __future__ import annotations

import html
from collections import defaultdict
from urllib.parse import quote

from markupsafe import Markup
from packaging.version import InvalidVersion, Version
from tabsdata_dev.common.core import resources

from .model import Dist

#: The templates are index/<page>.html in this package's resources.
PACKAGE = "tabsdata_dev.tool.pypi"


def _page(name: str, **values) -> str:
    return resources.render(PACKAGE, f"index/{name}.html", **values)


def _escaped(text: str) -> Markup:
    """`text` escaped as these pages always have been -- html.escape, quotes
    included -- and so not escaped again by the template. Jinja's own escaping
    spells quotes differently (&#34; for &quot;), and a page that changes byte
    for byte is a page the push plan uploads again."""
    return Markup(html.escape(text, quote=True))


def _sort_key(d: Dist) -> tuple:
    """Version-aware, so 0.9.10 sorts after 0.9.5 and diffs stay additive.

    The leading tag keeps parseable and unparseable versions from ever being
    compared to each other: tuple comparison short-circuits on 0 != 1 and never
    reaches the mismatched second elements.
    """
    try:
        return ((0, Version(d.version)), d.filename)
    except InvalidVersion:
        return ((1, d.version), d.filename)


def render_landing() -> str:
    """Tree-root page, so the bare domain is not a 404.

    The distribution's default root object resolves to <base_path>/index.html,
    which would otherwise not exist.
    """
    return _page("landing", title="Tabsdata package index")


def render_root(projects: set[str]) -> str:
    return _page("root", title="Simple index", projects=sorted(projects))


def render_project(project: str, dists: list[Dist], files: str = "../../files") -> str:
    rows = [
        {
            # Relative on purpose: resolves against the viewer URL, so the same
            # tree works at localhost, on a vanilla CloudFront domain, and at the
            # custom domain -- and is unaffected by the distribution's origin
            # path. quote() leaves nothing an attribute would need escaped.
            "href": Markup(f"{files}/{quote(d.filename)}#sha256={d.sha256}"),
            "requires_python": _escaped(d.requires_python or ""),
            "core_metadata": d.core_metadata_sha256 or "",
            # PEP 592. pip keeps resolving this file for anyone pinning the
            # exact version, and refuses to select it otherwise.
            "yanked": _escaped(d.yanked or ""),
            "name": Markup(html.escape(d.filename)),
        }
        for d in sorted(dists, key=_sort_key)
    ]
    return _page("project", title=f"Links for {project}", rows=rows)


def _by_project(dists: list[Dist]) -> dict[str, list[Dist]]:
    by_project: dict[str, list[Dist]] = defaultdict(list)
    for d in dists:
        by_project[d.project].append(d)
    return by_project


def render_all(dists: list[Dist]) -> dict[str, str]:
    """-> {tree-relative path: html}"""
    by_project = _by_project(dists)
    pages = {
        "index.html": render_landing(),
        "simple/index.html": render_root(set(by_project)),
    }
    for project, group in by_project.items():
        pages[f"simple/{project}/index.html"] = render_project(project, group)
    return pages


def render_namespace(dists: list[Dist]) -> dict[str, str]:
    """-> {namespace-relative path: html}, for `push --at NAME`: the project list
    at the namespace's root and each project's page beside it, so pip finds
    `<NAME>/<project>/` where the lane has `simple/<project>/`. The namespace keeps
    its own files/, one level nearer than the lane's. No landing page: the bare
    domain is the lane's."""
    by_project = _by_project(dists)
    pages = {"index.html": render_root(set(by_project))}
    for project, group in by_project.items():
        pages[f"{project}/index.html"] = render_project(project, group, "../files")
    return pages
