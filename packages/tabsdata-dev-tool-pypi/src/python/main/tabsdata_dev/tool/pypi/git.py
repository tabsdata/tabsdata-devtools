#
# Copyright 2026 Tabsdata Inc.
#

"""Verify the release step: the tree is committed, and HEAD is in the remote.

Git is the release record, so a prod push that is not in the remote history
would be unattributable and un-revertable by anyone but the person who ran it.

Shells out to git rather than taking a library dependency.
"""

from __future__ import annotations

import subprocess

from tabsdata_dev.common.core import proc
from tabsdata_dev.common.core.errors import ToolError


def _run(*args: str) -> subprocess.CompletedProcess:
    # proc.run, not subprocess.run: it refuses a binary this toolset neither
    # pins nor declares, so `git` staying in bin-reqs.txt is enforced rather
    # than remembered.
    return proc.run(["git", *args], capture_output=True, text=True)


def _git(*args: str) -> str:
    r = _run(*args)
    if r.returncode != 0:
        raise ToolError(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def _ok(*args: str) -> bool:
    return _run(*args).returncode == 0


def assert_committed_and_pushed(paths: list[str], release_ref: str) -> str:
    """-> the HEAD sha.

    Raises unless every path is clean and HEAD is reachable from release_ref.
    """
    if not _ok("rev-parse", "--git-dir"):
        raise ToolError("not a git repository — the prod lane requires one")

    # --porcelain reports untracked files as '??', so a new sidecar that was
    # never `git add`ed is caught here too.
    dirty = _git("status", "--porcelain", "--", *paths)
    if dirty:
        raise ToolError(
            f"refusing to push — uncommitted changes under {', '.join(paths)}:\n"
            + "\n".join(f"  {line}" for line in dirty.splitlines())
            + "\n\nCommit and push them first; the git history is the release record."
        )

    # Refresh the remote ref. Being offline must fail here rather than let a
    # stale local ref satisfy the ancestry check below.
    remote = release_ref.split("/", 1)[0]
    if not _ok("fetch", "--quiet", remote):
        raise ToolError(
            f"refusing to push — could not `git fetch {remote}`.\n"
            f"Without a fresh {release_ref} the push check would be meaningless."
        )

    if not _ok("rev-parse", "--verify", "--quiet", release_ref):
        raise ToolError(f"release ref {release_ref} does not exist")

    head = _git("rev-parse", "HEAD")
    # --is-ancestor, not equality: this still passes when the ref has moved on
    # since your commit landed, which is what you want for a release that took a
    # while to verify.
    if not _ok("merge-base", "--is-ancestor", head, release_ref):
        raise ToolError(
            f"refusing to push — HEAD ({head[:12]}) is not reachable from "
            f"{release_ref}.\n"
            "Push the commit before pushing to prod:\n"
            "  git push origin main:main\n"
            f"  git log --oneline {release_ref}..HEAD    # what is not pushed yet"
        )
    return head
