#
# Copyright 2026 Tabsdata Inc.
#

"""Installing the two hooks gsx relies on.

- **pre-push**, the guard: the only thing that protects a clone whose owner
  never reads the docs. gsx's own, in `assets/pre-push`.
- **commit-msg**, Gerrit's: it gives every commit a `Change-Id:` trailer, an
  identity that survives every rebase, cherry-pick and conflict resolution
  because it lives in the message rather than in the sha or the patch. Shipped
  verbatim in `assets/commit-msg`, Apache header and all -- the one file in
  this tree that does not start with the house header, because it is not ours
  and a Gerrit user should be able to diff it against the original.

Git will not let a repository configure its own hooks -- `.git/hooks` is never
cloned, by design, because a hook is code the clone's owner runs. So there is
no arrangement in which everybody is protected automatically, and the honest
shapes are two:

- **repo**: `.githooks/<hook>` committed, `core.hooksPath` pointed at it.
  The hooks arrive with the code and are reviewed with it; each clone still
  runs one command once, because the config key is local too. This is the one
  to prefer, and the one a bootstrap target should call.
- **clone**: `.git/hooks/<hook>`, nothing committed and nothing in the
  worktree. For a repository you do not own, or one you would rather not add
  a directory to.

Setting `core.hooksPath` makes git ignore `.git/hooks` entirely, so the two are
alternatives rather than layers, and `--check` says which is in force.
"""

from __future__ import annotations

import pathlib
import stat
from importlib.resources import files

from tabsdata_dev.common.core.errors import ToolError

from . import gh

GUARD = "pre-push"
CHANGE_ID = "commit-msg"

#: Inside the package, found with importlib.resources: a hook is a resource
#: this tool ships, not a file anyone edits in place. Order is install order
#: and report order: the guard first, because it is the one the refusal is
#: about.
ASSETS = {GUARD: "assets/pre-push", CHANGE_ID: "assets/commit-msg"}
HOOKS = tuple(ASSETS)

#: Where the commit-msg hook comes from, and the line in it that says which
#: release it is. The version is read off the file rather than written here,
#: so the asset and what `init` reports cannot disagree; upgrading is fetching
#: the URL again and replacing the asset byte for byte.
CHANGE_ID_SOURCE = "https://gerrit-review.googlesource.com/tools/hooks/commit-msg"
CHANGE_ID_STAMP = "# From Gerrit Code Review "
QUICK_REF = "assets/quick-ref.txt"

REPO = "repo"  # .githooks/<hook> + core.hooksPath
CLONE = "clone"  # .git/hooks/<hook>
DIRECTORY = ".githooks"


def script(hook: str = GUARD) -> str:
    """A hook's text, as shipped."""
    return (files("tabsdata_dev.tool.gsx") / ASSETS[hook]).read_text(encoding="utf-8")


def change_id_version() -> str:
    """The Gerrit release the shipped commit-msg hook came from, off its own
    header line."""
    for line in script(CHANGE_ID).splitlines()[:5]:
        if line.startswith(CHANGE_ID_STAMP):
            return line[len(CHANGE_ID_STAMP) :].strip()
    return "unknown"


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


def target(runner: gh.Runner, where: str, hook: str = GUARD) -> pathlib.Path:
    if where == REPO:
        return top_level(runner) / DIRECTORY / hook
    return gh.git_dir(runner) / "hooks" / hook


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


def install(
    runner: gh.Runner, where: str, force: bool
) -> dict[str, tuple[pathlib.Path, bool]]:
    """Write every hook and, for `repo`, point git at them.

    Returns, per hook, its path and whether anything changed; the config key
    counts as a change of the guard's, since the guard is what it activates.
    Every refusal comes before any write: an install that had written the
    guard and then stopped at a commit-msg somebody else wrote would be half
    done with no way to say so.
    """
    if where == CLONE:
        # `core.hooksPath` REPLACES .git/hooks rather than adding to it, so
        # installing there while it is set writes a file git will never read --
        # and reports success for a guard that cannot fire. Seen in a real
        # checkout whose .githooks had been removed but whose config still
        # named it: `--clone` said "installed", `--check` said "NOT active",
        # and only the second one was right.
        elsewhere = configured(runner)
        if elsewhere:
            raise ToolError(
                f"core.hooksPath is {elsewhere!r}, so git ignores .git/hooks "
                "entirely and a guard installed there would never run.\n"
                f"  `tdd gsx init`                    installs into {elsewhere} instead\n"
                "  `git config --unset core.hooksPath`  then --clone works"
            )
    plans = []
    for hook in HOOKS:
        path = target(runner, where, hook)
        wanted = script(hook)
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if existing and existing != wanted and not force:
            raise ToolError(
                f"{path} already exists and is not the one gsx ships; "
                "--force overwrites it, or move it aside and chain to it yourself"
            )
        plans.append((hook, path, wanted, existing != wanted))
    done: dict[str, tuple[pathlib.Path, bool]] = {}
    for hook, path, wanted, changed in plans:
        if changed:
            # The file is the one write here the shared runner does not see,
            # so --dry-run has to be honoured by hand.
            if runner.dry_run:
                runner.out.info(f"[dry-run] write {path}", dry_run=True)
            else:
                write(path, wanted)
        done[hook] = (path, changed)
    if where == REPO and configured(runner) != DIRECTORY:
        # A relative path resolves against the worktree root for every hook,
        # so it is the same string in every clone -- which is what makes it
        # committable.
        runner.run(["git", "config", "core.hooksPath", DIRECTORY])
        done[GUARD] = (done[GUARD][0], True)
    return done


def state(runner: gh.Runner) -> dict:
    """What is installed here, for `--check` and for `--format json`.

    `repo`/`clone`/`protected` are the guard's, because the refusal reads
    them; the Change-Id hook has its own `commit_msg` and `change_id`, since a
    clone without it is unprotected against nothing -- it only commits without
    an identity.
    """
    path = configured(runner)
    wanted = {hook: script(hook) for hook in HOOKS}

    def status(where: str, hook: str) -> str:
        file = target(runner, where, hook)
        if not file.is_file():
            return "missing"
        text = file.read_text(encoding="utf-8", errors="replace")
        return "current" if text == wanted[hook] else "other"

    # Only one of the two can run: core.hooksPath, when set, replaces
    # .git/hooks rather than adding to it.
    active = REPO if path == DIRECTORY else CLONE if not path else "elsewhere"
    guard = {where: status(where, GUARD) for where in (REPO, CLONE)}
    change_id = {where: status(where, CHANGE_ID) for where in (REPO, CLONE)}
    return {
        "hooks_path": path,
        "active": active,
        "repo": guard[REPO],
        "clone": guard[CLONE],
        "protected": guard.get(active) == "current",
        "commit_msg": change_id,
        "change_id": change_id.get(active) == "current",
        "gerrit_version": change_id_version(),
    }
