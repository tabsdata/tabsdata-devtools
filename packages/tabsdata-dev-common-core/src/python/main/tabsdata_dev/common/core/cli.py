#
# Copyright 2026 Tabsdata Inc.
#

"""A common argparse base so every tool shares its outer shape."""

from __future__ import annotations

import argparse


def parser(prog: str, description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="files or directories to act on (default: .)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="report only; make no changes",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p
