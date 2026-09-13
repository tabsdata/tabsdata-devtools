#
# Copyright 2026 Tabsdata Inc.
#

"""Installing the pre-push guard, which is the only thing that protects a
clone whose owner never reads the docs.

Git will not let a repository configure its own hooks -- `.git/hooks` is never
cloned, by design, because a hook is code the clone's owner runs. So there is
no arrangement in which everybody is protected automatically, and the honest
shapes are two:

- **repo**: `.githooks/pre-push` committed, `core.hooksPath` pointed at it.
  The hook arrives with the code and is reviewed with it; each clone still
  runs one command once. This is the one to prefer, and the one a bootstrap
  target should call.
- **clone**: `.git/hooks/pre-push`, nothing committed. For a repository you do
  not own, or one you would rather not add a directory to.

Setting `core.hooksPath` makes git ignore `.git/hooks` entirely, so the two are
alternatives rather than layers, and `--check` says which is in force.
"""

from __future__ import annotations

import pathlib
import stat
from importlib.resources import files

from tabsdata_dev.common.core.errors import ToolError

from . import gh

#: Inside the package, found with importlib.resources: the hook is a resource
#: this tool ships, not a file anyone edits in place.
ASSET = "assets/pre-push"
QUICK_REF = "assets/quick-ref.txt"

REPO = "repo"  # .githooks/pre-push + core.hooksPath
CLONE = "clone"  # .git/hooks/pre-push
NAME = "pre-push"
DIRECTORY = ".githooks"


def script() -> str:
    """The guard's text, as shipped."""
    return (files("tabsdata_dev.tool.gsx") / ASSET).read_text(encoding="utf-8")


def quick_ref() -> str:
    """The one-screen card, as shipped.

    An asset rather than a string in the source, because `docs/stack-workflow.md`
    prints the same bytes and a test pins the two together: a card that has
    drifted from the guide is worse than no card.
    """
    return (files("tabsdata_dev.tool.gsx") / QUICK_REF).read_text(encoding="utf-8")


def top_level(runner: gh.Runner) -> pathlib.Path:
    """The worktree root, which is what a relative `core.hooksPath` resolves
    against."""
    return pathlib.Path(runner.run(["git", "rev-parse", "--show-toplevel"])).resolve()


def target(runner: gh.Runner, where: str) -> pathlib.Path:
    if where == REPO:
        return top_level(runner) / DIRECTORY / NAME
    return gh.git_dir(runner) / "hooks" / NAME


def configured(runner: gh.Runner) -> str:
    """`core.hooksPath` as set here, or `""`."""
    return runner.run(["git", "config", "core.hooksPath"], check=False).strip()


def write(path: pathlib.Path, text: str) -> None:
    """The hook, executable, written through a temporary file and one rename.

    The same care every other write in this tool takes: a half-written hook is
    a hook that silently passes everything.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".gsx-tmp")
    scratch.write_text(text, encoding="utf-8")
    scratch.chmod(scratch.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    scratch.replace(path)


def install(runner: gh.Runner, where: str, force: bool) -> tuple[pathlib.Path, bool]:
    """Write the guard and, for `repo`, point git at it. Returns the path and
    whether anything changed."""
    path = target(runner, where)
    wanted = script()
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if existing and existing != wanted and not force:
        raise ToolError(
            f"{path} already exists and is not the one gsx ships; "
            "--force overwrites it, or move it aside and chain to it yourself"
        )
    changed = existing != wanted
    if changed:
        write(path, wanted)
    if where == REPO:
        # A relative path resolves against the worktree root for pre-push, so
        # it is the same string in every clone -- which is what makes it
        # committable.
        if configured(runner) != DIRECTORY:
            runner.run(["git", "config", "core.hooksPath", DIRECTORY])
            changed = True
    return path, changed


def state(runner: gh.Runner) -> dict:
    """What is installed here, for `--check` and for `--format json`."""
    path = configured(runner)
    repo_hook = target(runner, REPO)
    clone_hook = target(runner, CLONE)
    wanted = script()

    def status(hook: pathlib.Path) -> str:
        if not hook.is_file():
            return "missing"
        text = hook.read_text(encoding="utf-8", errors="replace")
        return "current" if text == wanted else "other"

    # Only one of the two can run: core.hooksPath, when set, replaces
    # .git/hooks rather than adding to it.
    active = REPO if path == DIRECTORY else CLONE if not path else "elsewhere"
    return {
        "hooks_path": path,
        "active": active,
        "repo": status(repo_hook),
        "clone": status(clone_hook),
        "protected": (active == REPO and status(repo_hook) == "current")
        or (active == CLONE and status(clone_hook) == "current"),
    }
