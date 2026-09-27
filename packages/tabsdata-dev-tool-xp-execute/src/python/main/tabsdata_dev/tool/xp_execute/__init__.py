#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd _xp-execute SCRIPT ARGS...`` -- run an xp check script, `tdd` in reach.

The runner of xp's execute stage. The script runs on this toolset's python --
a venv of its own, built by tdd-install, bare but for what every tool is
reached through, the ``tdd`` module (``from tdd import tdd``) -- or, when xp
names one in ``_TDD_XP_EXECUTE_VENV``, on that venv's python: the one-off venv
an entry's ``requirements`` asked for. Either way the module is this package's
``tdd.py``, found with importlib.resources: put on the script's PYTHONPATH here,
copied into the one-off venv's site-packages there.

A launcher (every argument is the script's): its output is untouched and its
status comes back -- a non-zero one as one error event carrying it.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile
from importlib.resources import files

from tabsdata_dev.common.core import cli, managedvenv, proc, render

NAME = "_xp-execute"
DESCRIPTION = "run an xp suite's check script with the tdd module on its path"
#: The one-off venv to run the script in instead of this one (xp's own variable).
VENV_ENV = "_TDD_XP_EXECUTE_VENV"
MODULE = "tdd.py"


def module_text() -> str:
    """The ``tdd`` module's source, as this package ships it."""
    return files(__package__).joinpath(MODULE).read_text(encoding="utf-8")


def venv_python(prefix: pathlib.Path) -> pathlib.Path | None:
    for leaf in ("python", "python3", "python.exe"):
        candidate = managedvenv.bin_dir(prefix) / leaf
        if candidate.is_file():
            return candidate
    return None


def site_packages(python: pathlib.Path) -> pathlib.Path:
    """Where `python` installs pure modules: asked of it, since the layout is
    the platform's (lib/pythonX.Y/site-packages, Lib\\site-packages)."""
    done = subprocess.run(
        [
            str(python),
            "-c",
            "import sysconfig; print(sysconfig.get_paths()['purelib'])",
        ],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0 or not done.stdout.strip():
        raise RuntimeError(
            f"{python} could not say where its site-packages is: {done.stderr}"
        )
    return pathlib.Path(done.stdout.strip())


def interpreter(scratch: pathlib.Path) -> tuple[pathlib.Path, dict]:
    """The python the script runs on, and its environment: the one-off venv's
    with `tdd` copied in, or this venv's with `tdd` on PYTHONPATH."""
    env = dict(os.environ)
    env.pop(VENV_ENV, None)
    one_off = os.environ.get(VENV_ENV)
    if one_off:
        python = venv_python(pathlib.Path(one_off))
        if python is None:
            raise RuntimeError(f"{VENV_ENV}={one_off} is not a venv (no python in it)")
        (site_packages(python) / MODULE).write_text(module_text(), encoding="utf-8")
        return python, env
    (scratch / MODULE).write_text(module_text(), encoding="utf-8")
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(scratch), env.get("PYTHONPATH", "")) if p
    )
    return pathlib.Path(sys.executable), env


def main(argv: list[str] | None = None) -> int:
    args_ = list(sys.argv[1:] if argv is None else argv)

    def body(_: argparse.Namespace, out: render.Renderer) -> int:
        if not args_:
            return out.error(f"usage: tdd {NAME} SCRIPT [ARGS...]")
        with tempfile.TemporaryDirectory(prefix="tdd-xp-execute-lib-") as tmp:
            try:
                python, env = interpreter(pathlib.Path(tmp))
            except RuntimeError as exc:
                return out.error(str(exc))
            try:
                done = proc.run([str(python), *args_], env=env)
            except KeyboardInterrupt:
                out.warn(f"{args_[0]} interrupted")
                return 1
        if done.returncode != 0:
            return out.error(
                f"{args_[0]} exited with status {done.returncode}",
                status=done.returncode,
            )
        return 0

    return cli.run(NAME, DESCRIPTION, body, argv=[])


if __name__ == "__main__":
    sys.exit(main())
