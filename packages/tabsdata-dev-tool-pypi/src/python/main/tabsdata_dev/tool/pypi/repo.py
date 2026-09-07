#
# Copyright 2026 Tabsdata Inc.
#

"""The guard: every subcommand runs at the root of a clone of `pypi-repo`.

The meta tree is a git repository -- `config/lanes.yaml` says where the lanes
are, `pypi-wheels/` is the committed tree, and prod refuses to push what is not
in the remote history. Every path the tool touches is relative to that tree's
root, so running from anywhere else either does nothing or does it in the wrong
place: `generate` writes `pypi-wheels/staging/` under whatever directory it was
started in, and a `push` from a *different* clone would mirror one release
record into a bucket the other one describes.

`tdi-pypi` said "run from the pypi/ directory" in a docstring and found out at
the first missing file. This checks up front, and names which of the three
things is wrong: not a clone, not the root of one, or the root of the wrong one.

The comparison is on the remote, not on the path, because the path is one
machine's. Remotes are compared as `host/org/repo`, so the two ways of writing
the same GitHub remote agree:

    git@github.com:tabsdata/tabsdata-pypi.git   -> github.com/tabsdata/tabsdata-pypi
    https://github.com/tabsdata/tabsdata-pypi   -> github.com/tabsdata/tabsdata-pypi

Every remote is considered, not just `origin`: a fork with `origin` pointing at
the fork and `upstream` at the real one is still a clone of the real one.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

from tabsdata_dev.common.core import proc
from tabsdata_dev.common.core.errors import ToolError

#: The option, the config key, and the name used in every message.
OPTION = "--pypi-repo"


def _git(*args: str) -> subprocess.CompletedProcess:
    return proc.run(["git", *args], capture_output=True, text=True)


def normalize(remote: str) -> str:
    """A remote URL as ``host/org/repo``, lower-cased, with no scheme, no user,
    no port and no ``.git``. Two spellings of one remote normalize alike; two
    different remotes do not collide, since the host and the full path are kept.
    """
    url = remote.strip().rstrip("/")
    if not url:
        return ""
    url = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", url)  # scheme
    url = re.sub(r"^[^/@]+@", "", url)  # user@
    # The port goes before the scp-style colon is turned into a slash, or
    # `ssh://git@host:22/org/repo` would come out with 22 as a path segment.
    url = re.sub(r"^([^/:]+):\d+/", r"\1/", url)  # host:port/
    url = re.sub(r"^([^/:]+):", r"\1/", url)  # host:org/repo (scp style)
    url = re.sub(r"\.git$", "", url)
    return url.lower()


def remotes() -> dict[str, str]:
    """Every remote of the repository here, name -> URL. Empty when there is no
    repository or it has none."""
    r = _git("remote", "-v")
    if r.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out.setdefault(parts[0], parts[1])
    return out


def require_root(pypi_repo: str | None) -> pathlib.Path:
    """-> the repository root, which is also the cwd. Raises otherwise.

    Checked in the order a reader would: is this a repository, is this its root,
    is it a clone of the right one. Each failure says what to do about that one
    thing rather than listing all three.
    """
    if not pypi_repo:
        raise ToolError(
            f"no pypi-repo configured — {OPTION} URL, or set it once:\n"
            "  tdd pypi config --create      then uncomment and set pypi-repo\n"
            "It is the remote of the repository holding config/, raw-wheels/ "
            "and pypi-wheels/."
        )

    r = _git("rev-parse", "--show-toplevel")
    if r.returncode != 0:
        raise ToolError(
            f"{pathlib.Path.cwd()} is not inside a git repository.\n"
            f"tdd pypi runs at the root of a clone of {pypi_repo}."
        )
    root = pathlib.Path(r.stdout.strip()).resolve()
    here = pathlib.Path.cwd().resolve()
    if root != here:
        raise ToolError(
            f"tdd pypi runs at the root of the repository, not under it.\n"
            f"  here: {here}\n  root: {root}\nRun it from {root}."
        )

    want = normalize(pypi_repo)
    have = {name: normalize(url) for name, url in remotes().items()}
    if not have:
        raise ToolError(
            f"{root} is a git repository with no remotes; pypi-repo is "
            f"{pypi_repo}.\nAdd the remote, or point pypi-repo at this one."
        )
    if want not in have.values():
        listed = "\n".join(f"  {n:<10} {u}" for n, u in sorted(remotes().items()))
        raise ToolError(
            f"{root} is a clone of a different repository.\n"
            f"  pypi-repo: {pypi_repo}\n  remotes here:\n{listed}\n"
            f"Run tdd pypi in a clone of {pypi_repo}, or change pypi-repo."
        )
    return root
