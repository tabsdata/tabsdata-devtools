#
# Copyright 2026 Tabsdata Inc.
#

"""What a smoke run puts on the screen beyond its stage lines: the rolling
window under a running command, the log files a failed command named, and a
script's help page painted the way every tdd command paints one."""

from __future__ import annotations

import os
import pathlib
import re
import time
from collections.abc import Callable

import psutil

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# ---------------------------------------------------------------- window

#: How often the window is redrawn, and how often a stop is looked for.
WINDOW_PERIOD = 0.5
WINDOW_POLL = 0.05
WINDOW_INDENT = "      "
DIM = "\033[2m"


def written_since(log: pathlib.Path, offset: int) -> str:
    """What the log gained since byte OFFSET: what the running command wrote.
    The log also carries a plain copy of every screen line, and replaying the
    stage header and the previous `ok` inside the window read as if the run
    had looped."""
    try:
        with log.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def window_lines(text: str, count: int) -> list[str]:
    lines = [ANSI.sub("", line.replace("\r", "")) for line in text.splitlines()]
    return lines[-count:] if count > 0 else []


def _stopped(stop: pathlib.Path, parent: int) -> bool:
    return stop.exists() or not psutil.pid_exists(parent)


def window(
    log: pathlib.Path,
    offset: int,
    count: int,
    stop: pathlib.Path,
    parent: int,
    live: Callable[[list[str]], None],
    dim: tuple[str, str] = ("", ""),
) -> None:
    """Redraw the last COUNT lines of what the log gained since OFFSET until
    STOP exists or PARENT is gone, then erase them. Always COUNT rows, blank
    ones below what there is so far: the window keeps its height from the
    first redraw, so the screen does not grow under a command row by row.
    Stopped by a file rather than a signal: the engine starts this in the
    background through the `tdd` function, and a signal to that job would not
    reach this process."""
    on, off = dim
    while not _stopped(stop, parent):
        lines = window_lines(written_since(log, offset), count)
        drawn = [f"{WINDOW_INDENT}{on}{line}{off}" for line in lines]
        live(drawn + [""] * (count - len(drawn)))
        waited = 0.0
        while waited < WINDOW_PERIOD and not _stopped(stop, parent):
            time.sleep(WINDOW_POLL)
            waited += WINDOW_POLL
    live([])
    try:
        stop.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- pointers

#: A path as a command names it: absolute, Unix or Windows.
_PATH = r"(/\S+|[A-Za-z]:[\\/]\S+)"
_LABELLED = re.compile(rf"^\s*(details|errors|lane log|lane errors|log):\s+{_PATH}")
_FULL_OUTPUT = re.compile(rf"full output in {_PATH}")

#: How many pointers are kept: the last ones, a summary comes last.
POINTERS = 6


def pointers(text: str) -> list[str]:
    """`LABEL PATH` for the log files a failed command named -- `details:
    PATH`, `errors: PATH`, `lane log:`, `full output in PATH`; every tdd
    command writes a failure log and says so -- the last few distinct ones."""
    found: list[str] = []
    for raw in ANSI.sub("", text).splitlines():
        labelled = _LABELLED.match(raw)
        if labelled:
            found.append(f"{labelled.group(1)} {labelled.group(2)}")
            continue
        full = _FULL_OUTPUT.search(raw)
        if full:
            found.append(f"output {full.group(1)}")
    distinct = list(dict.fromkeys(found))
    return distinct[-POINTERS:]


# ---------------------------------------------------------------- help

BOLD = "\033[1m"
CYAN = "\033[36m"
RED = "\033[31m"
OFF = "\033[0m"

_SECTION = re.compile(r"^[a-z][a-z0-9 /_-]*:$")
_INLINE_SECTION = re.compile(r"^(usage|examples?|options?):( |$)")
_TERM_START = re.compile(r"^ {1,6}[^ ]")


def paint_help(text: str, required: set[str], tty: bool) -> str:
    """A help page painted the way every tdd command paints one: a heading
    bold, an entry's term cyan -- or RED for an option in REQUIRED: on a page
    where half a dozen options are mandatory, that belongs where the eye
    already is. A painter, not a layout engine: the pages are hand-aligned
    in the script that owns them, so nothing here moves a column."""
    if not tty or os.environ.get("NO_COLOR"):
        return text
    out, section = [], False
    for line in text.split("\n"):
        if _SECTION.match(line):
            section = True
            out.append(f"{BOLD}{line}{OFF}")
            continue
        if _INLINE_SECTION.match(line):
            colon = line.index(":") + 1
            section = False
            out.append(f"{BOLD}{line[:colon]}{OFF}{line[colon:]}")
            continue
        # A line starting at column 1 ends the section it followed: what is
        # indented under a prose paragraph belongs to the paragraph, not to a
        # term list -- the closing "drivers added ..." block is exactly that.
        if line and not line.startswith(" "):
            section = False
        start = _TERM_START.match(line) if section else None
        if not start:
            out.append(line)
            continue
        begin = start.end() - 1
        gap = line.find("  ", begin)
        if gap < 0:
            # a long term sits on a line of its own, its description on the
            # next: there is no two-space run, and the term is the whole line
            line = line.rstrip(" ")
            gap = len(line)
        term = line[begin:gap]
        name = re.split(r"[ ,]", term, maxsplit=1)[0]
        colour = RED if name in required else CYAN
        out.append(f"{line[:begin]}{colour}{term}{OFF}{line[gap:]}")
    return "\n".join(out)
