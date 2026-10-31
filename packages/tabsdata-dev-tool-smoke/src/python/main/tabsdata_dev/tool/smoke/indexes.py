#
# Copyright 2026 Tabsdata Inc.
#

"""The named indexes `--uv-index` takes in place of a URL.

Here rather than in each script, because every script has to mean the same
thing by @dev -- and because a CloudFront hostname is not something a reader
can check by eye on a command line, which is the whole point of having a name
for it. `@dev:NAME` is a developer's namespace on the dev index, the one
`tdd pypi push --lane staging --at NAME` publishes: NAME takes the place of
`simple` in the URL, and an empty NAME is `simple` itself. An unknown `@marker` resolves to nothing, for the script to refuse
there and then: passed on, uv would take it for a URL and fail several stages
later, in a message about a failed install that says nothing about the option
that caused it.
"""

from __future__ import annotations

import re

MARKER = "@"
DEV = "@dev"
SIMPLE = "simple"

NAMED = {
    DEV: "https://d3mm0r95u5i3hf.cloudfront.net/simple/",
    "@prod": "https://pypi.tabsdata.com/simple/",
}

#: What `tdd pypi push --at` accepts: one URL segment, and not the index's own
#: `files`. A name it would refuse is no index at all.
_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")


def resolve(value: str) -> str | None:
    """The URL VALUE stands for: a named index resolves, a URL (or nothing,
    no index asked for) passes through, an unknown `@marker` is None."""
    if not value.startswith(MARKER):
        return value
    marker, colon, name = value.partition(":")
    if not colon:
        return NAMED.get(value)
    name = name or SIMPLE
    if marker != DEV or name == "files" or not _NAMESPACE.fullmatch(name):
        return None
    return NAMED[DEV].removesuffix(f"{SIMPLE}/") + f"{name}/"
