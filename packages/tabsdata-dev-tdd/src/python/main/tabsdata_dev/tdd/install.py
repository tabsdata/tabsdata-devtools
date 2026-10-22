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
from . import paths, render

COMMAND = "tdd-install"

USAGE = """\
usage: tdd-install [--dir TDD_PATH] [--relock] [--from-wheels] [--format json|view] [--verbose]

Build one venv per toolset in TDD_PATH, plus the envs for tdd-exe and the shell
commands, then write TDD_PATH/tdd-source.sh. Re-run it after changing a
dependency or adding a tool.

  --dir TDD_PATH    default: $TDD_DIR, else ~/.tdd
  --relock          re-resolve every toolset in one pass
  --from-wheels     install from TDD_PATH/wheels instead of this checkout
  --format json|view
                    json is one event per line (default: view)
  --verbose, -v     show every uv command and its output
  --help, -h
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dir_: str | None = None
    relock = from_wheels = verbose = False
    fmt = "view"
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--dir", "--format"):
            if i + 1 >= len(argv):
                return _fallback(argv).error(f"{arg} needs a value (see --help)")
            if arg == "--dir":
                dir_ = argv[i + 1]
            else:
                fmt = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--dir="):
            dir_ = arg.split("=", 1)[1]
        elif arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
        elif arg == "--relock":
            relock = True
        elif arg == "--from-wheels":
            from_wheels = True
        elif arg in ("-v", "--verbose"):
            verbose = True
        elif arg in ("-h", "--help"):
            print(USAGE, end="")
            return 0
        else:
            return _fallback(argv).error(f"unexpected argument {arg!r} (see --help)")
        i += 1
    if fmt not in ("json", "view"):
        return _fallback(argv).error(f"--format must be json or view, got {fmt!r}")
    out = render.Renderer(COMMAND, fmt=fmt, verbose=verbose)
    try:
        return initialize_mod.initialize(
            paths.tdd_dir(dir_), out, relock=relock, from_wheels=from_wheels
        )
    except paths.UvMissing as exc:
        return out.error(str(exc))
    except Exception as exc:  # noqa: BLE001 -- one error line, the traceback in the log
        import traceback

        return out.error(f"{type(exc).__name__}: {exc}", details=traceback.format_exc())


def _fallback(argv: list[str]) -> render.Renderer:
    """Honour a --format the user typed even when parsing fails elsewhere."""
    fmt = "view"
    for i, arg in enumerate(argv):
        if arg == "--format" and i + 1 < len(argv) and argv[i + 1] in ("json", "view"):
            fmt = argv[i + 1]
        elif arg.startswith("--format=") and arg[9:] in ("json", "view"):
            fmt = arg[9:]
    return render.Renderer(COMMAND, fmt=fmt)


if __name__ == "__main__":
    # `python -m tabsdata_dev.tdd.install`: how `cargo make dev` runs it, from
    # the checkout, with no console script installed anywhere.
    raise SystemExit(main())
