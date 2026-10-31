#
# Copyright 2026 Tabsdata Inc.
#

"""The named indexes `--uv-index` takes in place of a URL.

Here rather than in each script, because every script has to mean the same
thing by @dev -- and because a CloudFront hostname is not something a reader
can check by eye on a command line, which is the whole point of having a name
for it.

- `@dev`, `@prod`: the staging and the published index.
- `@dev:NAME`: a developer's namespace on the dev index, the one `tdd pypi push
  --lane staging --at NAME` publishes, NAME in place of `simple` in the URL.
- `@local[::PORT][:NAME]`: `tdd pypi serve [--port PORT] [--at NAME]` on this
  machine, PORT 8000 and NAME `simple` unless given.

A NAME or PORT left out is its default; one written empty (`@dev:`,
`@local::`) is refused like any other that names no index. An unknown
`@marker`, or such a NAME or PORT, resolves to nothing, for the script to refuse there and
then: passed on, uv would take it for a URL and fail several stages later, in a
message about a failed install that says nothing about the option that caused
it.
"""

from __future__ import annotations

import re

MARKER = "@"
DEV = "@dev"
LOCAL = "@local"
SIMPLE = "simple"
#: `tdd pypi serve`'s own default.
LOCAL_PORT = "8000"

NAMED = {
    DEV: "https://d3mm0r95u5i3hf.cloudfront.net/simple/",
    "@prod": "https://pypi.tabsdata.com/simple/",
}

#: What `tdd pypi push --at` accepts: one URL segment, and not the index's own
#: `files`. A name it would refuse is no index at all.
_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
_PORT = re.compile(r"[1-9][0-9]{0,4}")


def _namespace(name: str) -> str | None:
    return name if name != "files" and _NAMESPACE.fullmatch(name) else None


def _local(rest: str) -> str | None:
    """`@local` with `rest` after it: '', ':NAME', '::PORT' or '::PORT:NAME'."""
    port, name = LOCAL_PORT, SIMPLE
    if rest.startswith("::"):
        port, colon, given = rest[2:].partition(":")
        if colon:
            name = given
    elif rest:
        name = rest[1:]
    name = _namespace(name)
    if name is None or not _PORT.fullmatch(port) or int(port) > 65535:
        return None
    return f"http://localhost:{port}/{name}/"


def is_local(value: str) -> bool:
    """Whether VALUE is an `@local` marker, good or bad: a cluster script
    refuses them all, its index going to pods that cannot reach this machine."""
    return value == LOCAL or value.startswith(f"{LOCAL}:")


def resolve(value: str) -> str | None:
    """The URL VALUE stands for: a named index resolves, a URL (or nothing,
    no index asked for) passes through, an unknown `@marker` is None."""
    if not value.startswith(MARKER):
        return value
    if value in NAMED:
        return NAMED[value]
    if value.startswith(f"{DEV}:"):
        name = _namespace(value[len(DEV) + 1 :])
        return name and NAMED[DEV].removesuffix(f"{SIMPLE}/") + f"{name}/"
    if is_local(value):
        return _local(value[len(LOCAL) :])
    return None
