#
# Copyright 2026 Tabsdata Inc.
#

"""The named indexes `--uv-index` takes in place of a URL.

Here rather than in each script, because every script has to mean the same
thing by @dev -- and because a CloudFront hostname is not something a reader
can check by eye on a command line, which is the whole point of having a name
for it. An unknown `@marker` resolves to nothing, for the script to refuse
there and then: passed on, uv would take it for a URL and fail several stages
later, in a message about a failed install that says nothing about the option
that caused it.
"""

from __future__ import annotations

MARKER = "@"

NAMED = {
    "@dev": "https://d3mm0r95u5i3hf.cloudfront.net/simple/",
    "@prod": "https://pypi.tabsdata.com/simple/",
}


def resolve(value: str) -> str | None:
    """The URL VALUE stands for: a named index resolves, a URL (or nothing,
    no index asked for) passes through, an unknown `@marker` is None."""
    if not value.startswith(MARKER):
        return value
    return NAMED.get(value)
