#
# Copyright 2026 Tabsdata Inc.
#

"""Installing the two hooks gsx relies on.

- **pre-push**, the guard: the only thing that protects a clone whose owner
  never reads the docs. gsx's own, in the resource `hooks/pre-push`.
- **commit-msg**, Gerrit's: it gives every commit a `Change-Id:` trailer, an
  identity that survives every rebase, cherry-pick and conflict resolution
  because it lives in the message rather than in the sha or the patch. Shipped
  verbatim in the resource `hooks/commit-msg`, Apache header and all -- the one file in
  this tree that does not start with the house header, because it is not ours
  and a Gerrit user should be able to diff it against the original.

Git will not let a repository configure its own hooks -- neither `.git/hooks`
nor `core.hooksPath` is cloned, by design, because a hook is code the clone's
owner runs. So there is no arrangement in which everybody is protected
automatically, and the honest shape is one: the files live in `.githooks/`,
committed, so they arrive with the code, are reviewed with it and are upgraded
by a commit; and each clone runs `init` once, which points `core.hooksPath` at
that directory. In a clone that already has the files, that is all it does.

There used to be a `--clone` form that wrote the same files to `.git/hooks`
and set nothing. It went because nobody could state its difference from the
default -- every clone runs `init` either way -- and because it had a failure
mode of its own: `core.hooksPath` REPLACES `.git/hooks`, so in a clone whose
config still named a removed `.githooks` it reported success for a hook git
would never run. Its one real use, a repository that is not yours to add a
directory to, is served by listing `.githooks` in `.git/info/exclude`.
"""

from __future__ import annotations

import pathlib
import stat

from tabsdata_dev.common.core import resources
from tabsdata_dev.common.core.errors import ToolError

from . import gh

GUARD = "pre-push"
CHANGE_ID = "commit-msg"

#: This package, whose resources hold the hooks and the quick-reference card.
PACKAGE = "tabsdata_dev.tool.gsx"

#: In the package's resources: a hook is a file this tool ships, not one anyone
#: edits in place. Order is install order and report order: the guard first,
#: because it is the one the refusal is about.
ASSETS = {GUARD: "hooks/pre-push", CHANGE_ID: "hooks/commit-msg"}
HOOKS = tuple(ASSETS)

#: Where the commit-msg hook comes from, and the line in it that says which
#: release it is. The version is read off the file rather than written here,
#: so the asset and what `init` reports cannot disagree; upgrading is fetching
#: the URL again and replacing the asset byte for byte.
CHANGE_ID_SOURCE = "https://gerrit-review.googlesource.com/tools/hooks/commit-msg"
CHANGE_ID_STAMP = "# From Gerrit Code Review "
QUICK_REF = "quick-ref.txt"

DIRECTORY = ".githooks"

#: What `core.hooksPath` says, for `state()["active"]`: ours, somebody else's,
#: or nothing -- in which case git would run `.git/hooks`, where gsx puts
#: nothing any more.
REPO = "repo"
ELSEWHERE = "elsewhere"
NONE = "none"


def script(hook: str = GUARD) -> str:
    """A hook's text, as shipped."""
    return resources.text(PACKAGE, ASSETS[hook])


def change_id_version() -> str:
    """The Gerrit release the shipped commit-msg hook came from, off its own
    header line."""
    for line in script(CHANGE_ID).splitlines()[:5]:
        if line.startswith(CHANGE_ID_STAMP):
            return line[len(CHANGE_ID_STAMP) :].strip()
    return "unknown"


def quick_ref() -> str:
    """The one-screen card, as shipped.

    A resource rather than a string in the source, because
    `docs/stack-workflow.md` prints the same bytes and a test pins the two
    together: a card that has drifted from the guide is worse than no card.
    """
    return resources.text(PACKAGE, QUICK_REF)


def top_level(runner: gh.Runner) -> pathlib.Path:
    """The worktree root, which is what a relative `core.hooksPath` resolves
    against."""
    return pathlib.Path(runner.run(["git", "rev-parse", "--show-toplevel"])).resolve()


def target(runner: gh.Runner, hook: str = GUARD) -> pathlib.Path:
    return top_level(runner) / DIRECTORY / hook


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


def install(runner: gh.Runner, force: bool) -> dict[str, tuple[pathlib.Path, bool]]:
    """Write every hook that is not already the shipped one, and point git at
    the directory.

    Returns, per hook, its path and whether anything changed; the config key
    counts as a change of the guard's, since the guard is what it activates.
    Every refusal comes before any write: an install that had written the
    guard and then stopped at a commit-msg somebody else wrote would be half
    done with no way to say so.
    """
    elsewhere = configured(runner)
    if elsewhere and elsewhere != DIRECTORY and not force:
        # git runs ONE hooks directory. Pointing it at ours silences whatever a
        # husky or a house hook had in theirs, which is not gsx's call to make
        # without being told.
        raise ToolError(
            f"core.hooksPath is {elsewhere!r}, which gsx did not set: git runs one "
            f"hooks directory, so pointing it at {DIRECTORY} would silence whatever "
            "is there.\n"
            f"  `tdd gsx init --force`   points it at {DIRECTORY} anyway\n"
            f"  or chain to {DIRECTORY}/{GUARD} and {DIRECTORY}/{CHANGE_ID} from "
            f"{elsewhere}"
        )
    plans = []
    for hook in HOOKS:
        path = target(runner, hook)
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
    if elsewhere != DIRECTORY:
        # A relative path resolves against the worktree root for every hook,
        # so it is the same string in every clone -- which is what makes it
        # committable.
        runner.run(["git", "config", "core.hooksPath", DIRECTORY])
        done[GUARD] = (done[GUARD][0], True)
    return done


def state(runner: gh.Runner) -> dict:
    """What is installed here, for `--check` and for `--format json`.

    `guard`/`protected` are the guard's, because the refusal reads them; the
    Change-Id hook has its own `commit_msg` and `change_id`, since a clone
    without it is unprotected against nothing -- it only commits without an
    identity.
    """
    path = configured(runner)
    active = REPO if path == DIRECTORY else ELSEWHERE if path else NONE

    def status(hook: str) -> str:
        file = target(runner, hook)
        if not file.is_file():
            return "missing"
        text = file.read_text(encoding="utf-8", errors="replace")
        return "current" if text == script(hook) else "other"

    guard, change_id = status(GUARD), status(CHANGE_ID)
    return {
        "hooks_path": path,
        "active": active,
        "guard": guard,
        "commit_msg": change_id,
        "protected": active == REPO and guard == "current",
        "change_id": active == REPO and change_id == "current",
        "gerrit_version": change_id_version(),
    }
