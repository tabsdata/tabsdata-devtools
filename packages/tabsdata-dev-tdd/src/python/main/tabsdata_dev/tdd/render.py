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
import pathlib
import sys
from typing import Any, TextIO

KINDS = ("ok", "error", "warn", "info", "debug")

# ANSI SGR codes. info is deliberately plain: it is the running commentary,
# colour is for the things that need the eye.
COLORS = {"ok": "32", "error": "31", "warn": "33", "debug": "37"}
RESET = "\033[0m"

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
    code = COLORS.get(kind)
    if not code or os.environ.get("NO_COLOR") or not _isatty(stream):
        return text
    return f"\033[{code}m{text}{RESET}"


def _isatty(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


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

    def error(self, message: str, details: str = "", **fields: Any) -> int:
        """The failure: exactly one, last. Writes the log, returns 1.

        The terminal keeps one line of *what* went wrong; the log has the why:
        the command line, where it ran, and whatever details the caller
        captured (a traceback, a subprocess's output).
        """
        log = write_failure_log(self.command, message, details)
        self._event("error", message, {**fields, "log": str(log)})
        if self.fmt != "json":
            print(colored("error", f"details: {log}", self.err), file=self.err)
        return 1


def write_failure_log(command: str, message: str, details: str = "") -> pathlib.Path:
    """/tmp/tdd-<command>-<stamp>-<pid>.log, as the guidelines specify."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = LOG_DIR / f"tdd-{command}-{stamp}-{os.getpid()}.log"
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
        path.write_text("\n".join(lines) + "\n")
    except OSError:
        pass  # a log that cannot be written must not mask the error itself
    return path
