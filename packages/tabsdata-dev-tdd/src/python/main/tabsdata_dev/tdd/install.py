#
# Copyright 2026 Tabsdata Inc.
#

"""`tdd-install` -- the one command to run before anything is sourced.

`tdd` itself is a shell function, so it cannot exist until tdd-source.sh has been
sourced, and tdd-source.sh does not exist until something has written it. This
entry point breaks that cycle: it is a real executable that performs the whole
setup, then tells you what to source.

It is also the *only* way to set a tdd dir up. `tdd-exe` has no init word: a
user never wants to build envs from inside a tool invocation, and re-running
`tdd-install` is the documented way to pick up a dependency change.
"""

from __future__ import annotations

import sys

from . import initialize as initialize_mod
from . import paths

USAGE = """\
usage: tdd-install [--dir TDD_PATH] [--relock] [--from-wheels]

Build one venv per toolset in TDD_PATH, plus the envs for tdd-exe and the shell
commands, then write TDD_PATH/tdd-source.sh. Re-run it after changing a
dependency or adding a tool.

  --dir TDD_PATH    default: $TDD_DIR, else ~/.tdd
  --relock          re-resolve every toolset in one pass
  --from-wheels     install from TDD_PATH/wheels instead of this checkout
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dir_: str | None = None
    relock = from_wheels = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--dir":
            if i + 1 >= len(argv):
                print("tdd-install: --dir needs a path", file=sys.stderr)
                return 2
            dir_ = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--dir="):
            dir_ = arg.split("=", 1)[1]
        elif arg == "--relock":
            relock = True
        elif arg == "--from-wheels":
            from_wheels = True
        elif arg in ("-h", "--help"):
            print(USAGE, end="")
            return 0
        else:
            print(f"tdd-install: unexpected argument {arg!r}", file=sys.stderr)
            print(USAGE, end="", file=sys.stderr)
            return 2
        i += 1
    try:
        return initialize_mod.initialize(
            paths.tdd_dir(dir_), relock=relock, from_wheels=from_wheels
        )
    except paths.UvMissing as exc:
        print(f"tdd-install: {exc}", file=sys.stderr)
        return 2
