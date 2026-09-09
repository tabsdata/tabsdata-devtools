#
# Copyright 2026 Tabsdata Inc.
#

"""The event model and its two renderings -- docs/command-cli-guidelines.md.

Every line a command prints is an Event: which command, what kind (ok, error,
warn, info, debug), a message, and optional fields. The Renderer turns events
into either JSON Lines or terminal text, colours them by kind when the target
stream is a terminal, hides debug unless --verbose, and writes the failure log
an error requires. Commands never print; they call the renderer.

This file exists twice, byte for byte: here for the tools, and as
tabsdata_dev.tdd.render for tdd-exe, which is standard-library only and cannot
import this package. A test in tabsdata-dev-tdd fails when the two diverge.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import re
import pathlib
import sys
from typing import Any, TextIO

KINDS = ("ok", "error", "warn", "info", "debug")

# ANSI SGR codes. info is deliberately plain: it is the running commentary,
# colour is for the things that need the eye.
COLORS = {"ok": "32", "error": "31", "warn": "33", "debug": "37"}
RESET = "\033[0m"

# Paints for a message that colours its own pieces rather than taking one
# colour by kind -- `config --show` marks every value it prints this way: green
# a built-in default, blue what the file sets, white the built-in beside it;
# `gsx stacks` paints the stack you are on green, the others blue, and the
# branch you are on yellow.
# Blue is a 256-colour cube entry, not palette 34 or 94: themes remap the
# sixteen palette colours (34 is a near-black navy on a dark theme, 94 a
# grey-white under "minimum contrast") but leave the cube alone, so 38;5;33 is
# the same azure everywhere. The shell half paints with the same four codes
# (`_tdd_color`) -- keep them in step.
PAINTS = {"green": "32", "blue": "38;5;33", "white": "37", "yellow": "33"}

LOG_DIR = pathlib.Path("/tmp")


@dataclasses.dataclass(frozen=True)
class Event:
    command: str
    kind: str
    message: str
    fields: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown event kind {self.kind!r}; one of {KINDS}")

    def as_json(self) -> str:
        # command and event first so a line reads left to right; fields never
        # override them.
        body = {"command": self.command, "event": self.kind, "message": self.message}
        body.update({k: v for k, v in self.fields.items() if k not in body})
        return json.dumps(body, default=str, separators=(",", ":"))


def colored(kind: str, text: str, stream: TextIO) -> str:
    """Wrap text in the kind's colour when the stream is a terminal.

    Both formats are coloured -- a JSON line on a terminal is still read by a
    person -- but a pipe never sees an escape code. NO_COLOR is honoured.
    """
    return _painted(COLORS.get(kind), text, stream)


def paint(name: str, text: str, stream: TextIO) -> str:
    """Wrap text in a named paint (PAINTS), for a message that colours its own
    pieces. The renderer leaves a message carrying an escape as it is, so what
    is painted here is never painted a second time by its event kind."""
    return _painted(PAINTS.get(name), text, stream)


def _painted(code: str | None, text: str, stream: TextIO) -> str:
    if not code or os.environ.get("NO_COLOR") or not _isatty(stream):
        return text
    return f"\033[{code}m{text}{RESET}"


def _isatty(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


# ------------------------------------------------------------------- help
ESC = "\033"
HELP_HEADING = "1"  # bold
HELP_TERM = "36"  # cyan: an option or a subcommand, next to its description
_HEADING = re.compile(r"^([a-z][a-z0-9 /_-]*:)(\s*)$")
# `usage:`/`example:` carry their line with them; any other word before a
# colon may just be prose, so only these two are taken as headings.
_INLINE_HEADING = re.compile(r"^(usage:|examples?:)( .*)$")
# `  -v, --verbose         show debug events too` -- a term is what stands at a
# shallow indent before its description, which the two spaces mark. A line of
# prose has no such gap, and a wrapped description sits far to the right.
_TERM = re.compile(r"^( {1,6})(\S.*?)( {2,})")


def colorize_help(text: str, stream: TextIO) -> str:
    """Help text with its headings bold and its terms coloured.

    Applied after the layout is done, so nothing here changes a column: every
    escape wraps text that is already in place. Both halves of tdd colour help
    the same way -- the shell one does this in awk.
    """
    if os.environ.get("NO_COLOR") or not _isatty(stream):
        return text
    out = []
    for line in text.split("\n"):
        if ESC in line:
            # Python 3.14's argparse colours its own help; what it has already
            # painted is left alone, and what it leaves plain (an epilog, a
            # hand-written help text) is painted here.
            out.append(line)
            continue
        heading = _HEADING.match(line) or _INLINE_HEADING.match(line)
        if heading:
            out.append(
                f"\033[{HELP_HEADING}m{heading.group(1)}{RESET}{heading.group(2)}"
            )
            continue
        term = _TERM.match(line)
        if term and not line.strip().startswith("#"):
            out.append(
                f"{term.group(1)}\033[{HELP_TERM}m{term.group(2)}{RESET}"
                f"{term.group(3)}{line[term.end() :]}"
            )
            continue
        out.append(line)
    return "\n".join(out)


class Renderer:
    """Where a command's output goes. One per invocation.

    json: every event is one JSON object on stdout, nothing else is written.
    view: ok goes to stdout, everything else to stderr, so results pipe clean.
    """

    def __init__(
        self,
        command: str,
        fmt: str = "view",
        verbose: bool = False,
        out: TextIO | None = None,
        err: TextIO | None = None,
    ):
        if fmt not in ("json", "view"):
            raise ValueError(f"--format must be json or view, got {fmt!r}")
        self.command = command
        self.fmt = fmt
        self.verbose = verbose
        self.out = out or sys.stdout
        self.err = err or sys.stderr

    def emit(self, event: Event) -> None:
        if event.kind == "debug" and not self.verbose:
            return
        if self.fmt == "json":
            stream = self.out
            text = event.as_json()
        else:
            stream = self.out if event.kind == "ok" else self.err
            text = event.message
            if ESC in text:
                # A message that paints itself -- a help document -- is left as
                # it is: one colour over the whole of it would undo its own.
                print(text, file=stream)
                stream.flush()
                return
        print(colored(event.kind, text, stream), file=stream)
        stream.flush()

    def _event(self, kind: str, message: str, fields: dict[str, Any]) -> None:
        self.emit(Event(self.command, kind, message, fields))

    def ok(self, message: str, **fields: Any) -> int:
        """The outcome: exactly one, last. Returns the exit code to use."""
        self._event("ok", message, fields)
        return 0

    def info(self, message: str, **fields: Any) -> None:
        self._event("info", message, fields)

    def warn(self, message: str, **fields: Any) -> None:
        self._event("warn", message, fields)

    def debug(self, message: str, **fields: Any) -> None:
        self._event("debug", message, fields)

    def error(
        self, message: str, details: str = "", log: str | None = None, **fields: Any
    ) -> int:
        """The failure: exactly one, last. Writes the log, returns 1.

        The terminal keeps one line of *what* went wrong; the log has the why:
        the command line, where it ran, and whatever details the caller
        captured (a traceback, a subprocess's output). A command that kept its
        own detail log all along passes it as `log`; the failure block is
        appended there instead of starting a second file.
        """
        log = write_failure_log(self.command, message, details, path=log)
        self._event("error", message, {**fields, "log": str(log)})
        if self.fmt != "json":
            print(colored("error", f"details: {log}", self.err), file=self.err)
        return 1


def write_failure_log(
    command: str,
    message: str,
    details: str = "",
    path: str | pathlib.Path | None = None,
) -> pathlib.Path:
    """/tmp/tdd-<command>-<stamp>-<pid>.log, as the guidelines specify -- or,
    given `path`, the failure block appended to that existing log."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = (
        pathlib.Path(path)
        if path
        else LOG_DIR / f"tdd-{command}-{stamp}-{os.getpid()}.log"
    )
    tdd_dir = os.environ.get("TDD_DIR", "")
    version = ""
    if tdd_dir and (pathlib.Path(tdd_dir) / "VERSION").is_file():
        version = (pathlib.Path(tdd_dir) / "VERSION").read_text().strip()
    lines = [
        f"command: {' '.join(sys.argv)}",
        f"cwd:     {os.getcwd()}",
        f"TDD_DIR: {tdd_dir}",
        f"version: {version}",
        f"time:    {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"error:   {message}",
    ]
    if details:
        lines += ["", "details:", details.rstrip("\n")]
    try:
        with path.open("a") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass  # a log that cannot be written must not mask the error itself
    return path
