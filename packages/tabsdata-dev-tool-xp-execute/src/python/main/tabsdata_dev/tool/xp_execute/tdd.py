#
# Copyright 2026 Tabsdata Inc.
#
"""`tdd`, for an xp check script: every tdd tool, one function away.

    from tdd import tdd

    versions = json.loads(tdd("tdk", "table", "versions", "--proj", proj, ..., "--format", "json"))
    tdd("pqt", "csv", "t.parquet", out=Path("t.csv"))

`tdd` is a shell function and cannot be exec'd; `tdd-exe` is the executable
behind it, and xp puts it on the script's PATH. This module is put on the
script's path by `tdd _xp-execute`, which runs the script: in its own venv, or
in the one-off venv an execute entry's `requirements` asked for. Standard
library only, so it works in either.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

__all__ = ["tdd", "TddError"]


class TddError(RuntimeError):
    """A tdd command that failed, with what it said."""

    def __init__(self, args: tuple[str, ...], status: int, output: str):
        self.status = status
        self.output = output
        super().__init__(f"tdd {' '.join(args)} exited {status}:\n{output}")


def tdd(*args: str, out: Path | None = None, check: bool = True) -> str:
    """Run `tdd ARGS...` and return its stdout, or write it to `out` (and return
    it too). A failure raises TddError with what the command said -- or, with
    ``check=False``, returns its stdout anyway."""
    done = subprocess.run(["tdd-exe", *args], capture_output=True, text=True)
    if done.returncode != 0 and check:
        raise TddError(args, done.returncode, done.stderr or done.stdout)
    if out is not None:
        Path(out).write_text(done.stdout, encoding="utf-8")
    return done.stdout


if __name__ == "__main__":  # `python tdd.py ARGS...`: the same, from a shell
    sys.stdout.write(tdd(*sys.argv[1:]))
