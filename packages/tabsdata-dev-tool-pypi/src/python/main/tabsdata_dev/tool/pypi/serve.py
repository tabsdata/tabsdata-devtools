#
# Copyright 2026 Tabsdata Inc.
#

"""serve --lane L [--at NAME]: a local tree over http.server, before any
credential is involved -- and, with --at, as namespace NAME serves it, so the
index `push --at NAME` would publish can be tried with a real uv first
(`@local::PORT:NAME`)."""

from __future__ import annotations

import functools
import http.server
import tempfile
from pathlib import Path

from tabsdata_dev.common.core.render import Renderer

from .config import DEFAULT_AT
from .indexhtml import render_namespace
from .tree import load_index


class _Handler(http.server.SimpleHTTPRequestHandler):
    """The tree as it is, and under /<at>/ the namespace: its pages from
    `pages`, its files/ the tree's own. Nothing of the tree is copied."""

    def __init__(self, *args, tree: Path, at: str, pages: Path | None, **kwargs):
        self.tree, self.at, self.pages = tree, at, pages
        super().__init__(*args, directory=str(tree), **kwargs)

    def translate_path(self, path: str) -> str:
        prefix = f"/{self.at}/"
        if self.pages is None or not (path + "/").startswith(prefix):
            self.directory = str(self.tree)
            return super().translate_path(path)
        rest = path[len(prefix) - 1 :]
        # One handler per request, so the directory is this request's alone.
        self.directory = str(self.tree if rest.startswith("/files/") else self.pages)
        return super().translate_path(rest)


def serve(tree: Path, port: int, at: str, out: Renderer) -> int:
    dists = load_index(tree)  # refuses if the tree is incomplete
    with tempfile.TemporaryDirectory(prefix="tdd-pypi-pages-") as stage:
        pages = None
        if at != DEFAULT_AT:
            pages = Path(stage)
            for rel, text in render_namespace(dists).items():
                (pages / rel).parent.mkdir(parents=True, exist_ok=True)
                (pages / rel).write_text(text)
        handler = functools.partial(_Handler, tree=tree, at=at, pages=pages)
        out.info(f"serving {tree}/ at http://localhost:{port}/{at}/   (ctrl-c to stop)")
        # Blocks until interrupted; cli.run() turns the KeyboardInterrupt into
        # the one error line. There is no `ok` on this path -- nothing completed.
        http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
    return 0
