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

from packaging.version import InvalidVersion, Version

from .model import Dist

_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta name="pypi:repository-version" content="1.0">
<title>{title}</title>
</head>
<body>
{body}
</body>
</html>
"""


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
    return _PAGE.format(
        title="Tabsdata package index",
        body='<a href="simple/">simple/</a><br/>',
    )


def render_root(projects: set[str]) -> str:
    body = "\n".join(f'<a href="{p}/">{p}</a><br/>' for p in sorted(projects))
    return _PAGE.format(title="Simple index", body=body)


def render_project(project: str, dists: list[Dist]) -> str:
    rows = []
    for d in sorted(dists, key=_sort_key):
        attrs = ""
        if d.requires_python:
            rp = html.escape(d.requires_python, quote=True)
            attrs += f' data-requires-python="{rp}"'
        if d.core_metadata_sha256:
            attrs += f' data-core-metadata="sha256={d.core_metadata_sha256}"'
        if d.yanked:
            # PEP 592. pip keeps resolving this file for anyone pinning the exact
            # version, and refuses to select it otherwise.
            attrs += f' data-yanked="{html.escape(d.yanked, quote=True)}"'
        # Relative on purpose: resolves against the viewer URL, so the same tree
        # works at localhost, on a vanilla CloudFront domain, and at the custom
        # domain — and is unaffected by the distribution's origin path.
        href = f"../../files/{quote(d.filename)}#sha256={d.sha256}"
        rows.append(f'<a href="{href}"{attrs}>{html.escape(d.filename)}</a><br/>')
    return _PAGE.format(title=f"Links for {project}", body="\n".join(rows))


def render_all(dists: list[Dist]) -> dict[str, str]:
    """-> {tree-relative path: html}"""
    by_project: dict[str, list[Dist]] = defaultdict(list)
    for d in dists:
        by_project[d.project].append(d)

    pages = {
        "index.html": render_landing(),
        "simple/index.html": render_root(set(by_project)),
    }
    for project, group in by_project.items():
        pages[f"simple/{project}/index.html"] = render_project(project, group)
    return pages
