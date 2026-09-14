#
# Copyright 2026 Tabsdata Inc.
#

"""A sync that reconciles before it rebases, and so rarely has to force.

`gh stack sync` rebases a stack from the local copies of its branches and then
force-pushes the result, with leases taken from a fetch seconds earlier -- so
the leases always pass and a teammate's commit this clone never had is dropped
and then overwritten. The fix is one step in front of the cascade: bring each
branch up to its OWN remote copy first. A diverged branch replayed onto
`<remote>/<branch>` descends from it, which makes the push a fast-forward; the
cascade then rewrites only the branches that really did move, and those are
force-pushed with the remote tip already in their history.

Nothing here touches a stack object or the stacks API. Every destructive path
in gh-stack's sync is in its reconciliation of the *stack*, and none of that is
needed to move commits between clones. The stack object is `submit`'s business.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from . import gh

#: `<git-dir>/gsx/sync.json`, beside move's: what a sync that stopped needs in
#: order to be finished or undone -- every branch's tip before the run, and
#: where the operator stood. Written before anything moves, removed when the
#: run completes; its presence IS "a sync is stopped here".
SESSION = "gsx/sync.json"


def session_path(runner: gh.Runner) -> pathlib.Path:
    return gh.git_dir(runner) / SESSION


def save_session(
    runner: gh.Runner, branch: str, tips: dict[str, str], remote: str
) -> None:
    """A temporary file and one rename, like every other write here."""
    path = session_path(runner)
    if runner.dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(
        json.dumps({"branch": branch, "tips": tips, "remote": remote}, indent=1),
        encoding="utf-8",
    )
    scratch.replace(path)


def load_session(runner: gh.Runner) -> dict | None:
    path = session_path(runner)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def clear_session(runner: gh.Runner) -> None:
    if not runner.dry_run:
        session_path(runner).unlink(missing_ok=True)


def in_progress(runner: gh.Runner) -> str:
    """`"rebase"`, `"cherry-pick"` or `""`: what git has left half-done."""
    git_dir = gh.git_dir(runner)
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "rebase"
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return "cherry-pick"
    return ""


def finish(runner: gh.Runner, kind: str) -> None:
    """Carry on what the operator has resolved. GIT_EDITOR is off: `--continue`
    opens the message otherwise, and the message is the one the commit had."""
    runner.run(["git", kind, "--continue"], env={"GIT_EDITOR": "true"}, capture=False)


def abort(runner: gh.Runner, session: dict) -> list[str]:
    """Put every branch the run touched back to its pre-run tip.

    `git rebase --abort` undoes only the branch the rebase stopped on; the
    branches the cascade had already rewritten stay rewritten, which is a
    half-restacked stack nobody asked for. The snapshot every run takes for
    its fork points is exactly what is needed to undo them all, so it is kept
    until the run completes. The trunk is not put back: it was only ever
    fast-forwarded, and that is wanted whatever happens to the stack.
    """
    kind = in_progress(runner)
    if kind:
        runner.run(["git", kind, "--abort"], capture=False)
    branch = session.get("branch") or ""
    tips = session.get("tips") or {}
    if branch and gh.sha(runner, f"refs/heads/{branch}"):
        gh.checkout(runner, branch)
    standing = gh.current_branch(runner)
    restored = []
    for name, sha in tips.items():
        if not sha or not gh.sha(runner, f"refs/heads/{name}"):
            continue
        if gh.sha(runner, f"refs/heads/{name}") == sha:
            continue
        if name == standing:
            runner.run(["git", "reset", "-q", "--hard", sha])
        else:
            runner.run(["git", "branch", "-f", name, sha])
        restored.append(name)
    return restored


#: What a branch needs before the cascade may touch it.
CURRENT = "current"  # the remote's copy is already in our history
BEHIND = "behind"  # ours is in theirs: fast-forward onto it
DIVERGED = "diverged"  # both moved: replay ours on top of theirs
UNPUBLISHED = "unpublished"  # no copy on the remote at all

#: In the order they are worth reading: what was done, then what was not.
WORDS = {
    DIVERGED: "reconciled onto",
    BEHIND: "fast-forwarded to",
    CURRENT: "already has",
    UNPUBLISHED: "not on",
}


#: One line per commit: sha, then author|author-date|subject, then the
#: Change-Id(s) comma-separated -- what `identities` reads a commit's identity
#: off. `%x09` is a tab, `%x2C` a comma.
IDENTITY_FORMAT = (
    "%H%x09%ae|%at|%s%x09%(trailers:key=Change-Id,valueonly,separator=%x2C)"
)


def identities(runner: gh.Runner, *revs: str) -> dict[str, str]:
    """identity -> sha for the commits `revs` select, `git log` style.

    A commit's identity is its Change-Id -- the trailer the commit-msg hook
    puts on every commit -- or, for one made without, its author, author date
    and subject: what every rebase, cherry-pick and amend preserves and a
    squash does not. The newest carrier of an identity wins, which only
    matters if a history holds two copies of one commit.
    """
    text = runner.run(["git", "log", f"--format={IDENTITY_FORMAT}", *revs], check=False)
    found: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip():
            continue
        change_id = parts[2].split(",")[0].strip() if len(parts) > 2 else ""
        identity = change_id or parts[1].strip()
        if identity:
            found.setdefault(identity, parts[0].strip())
    return found


def identity(runner: gh.Runner, commit: str) -> str:
    """One commit's identity (see `identities`)."""
    return next(iter(identities(runner, "-n", "1", commit)), "")


def patch_id(runner: gh.Runner, commit: str) -> str:
    """The patch-id of one commit, for telling two copies of it apart."""
    diff = runner.run(["git", "diff-tree", "-p", "--root", commit], check=False)
    if not diff.strip():
        return ""
    words = runner.run(
        ["git", "patch-id", "--stable"], stdin_text=diff, check=False
    ).split()
    return words[0] if words else ""


def own_commits(
    runner: gh.Runner,
    branch: str,
    remote: str,
    base: str,
    out=None,
) -> list[str]:
    """The commits `<remote>/<branch>` has of its OWN that `branch` lacks.

    "Of its own" is measured from the PR's base **as GitHub has it**, which is
    the only thing that knows where the remote copy's history stops being the
    parent's. Oldest first, because that is the order they have to be replayed
    in.

    **A commit is known by its identity, never by its patch.** The identity is
    the Change-Id the commit-msg hook gave it, or for a commit made without one
    its author, author date and subject; a remote commit is lacking here
    exactly when no commit of `branch` above the base carries that identity.
    The patch is compared only to *say* something: two copies of one commit
    that differ by patch are a conflict resolution, or a change somebody made
    to the commit, and `out` is told which -- measured in tabsdata-os, where
    `OS-3512`'s one commit came out with a different patch-id on each side
    after a resolution. The first version matched by patch and then by
    subject; the user's decision is that the patch is a fact to report, not an
    identity to match on.
    """
    if not base:
        return []
    tracked = f"{remote}/{branch}"
    theirs = runner.run(
        ["git", "rev-list", "--reverse", tracked, "--not", base], check=False
    ).split()
    if not theirs:
        return []
    mine = identities(runner, branch, "--not", base)
    kept, same, differ = [], 0, []
    for commit in theirs:
        here = mine.get(identity(runner, commit))
        if not here:
            kept.append(commit)
        elif here == commit or patch_id(runner, commit) == patch_id(runner, here):
            same += 1
        else:
            differ.append(commit)
    if out is not None and (same or differ):
        for commit in differ:
            named = runner.run(
                ["git", "log", "-1", "--format=%h %s", commit], check=False
            ).strip()
            out.warn(
                f"{branch}: {named}: present here with a DIFFERENT PATCH from "
                f"{tracked}'s copy -- a conflict resolution, or a change to the commit",
                branch=branch,
                commit=commit,
            )
        out.info(
            f"{branch}: {same + len(differ)} commit(s) of {tracked} present here "
            f"({same} identical by patch"
            + (f", {len(differ)} with a different patch" if differ else "")
            + ")",
            branch=branch,
            identical=same,
            different=len(differ),
        )
    return kept


def once_mine(runner: gh.Runner, branch: str, tracked: str) -> bool:
    """Whether the remote tip was ever a tip of this local branch.

    The question that tells a rewrite of our own history from a change by
    somebody else, and it is answered from the reflog -- the same way the
    guard's first rule answers it, so the two cannot disagree. After an
    interleave the remote tip is the tip we rewrote, and it is there; after a
    teammate's restack it is a sha this clone never held, and it is not.

    The first attempt asked instead whether the remote held any patch we
    lacked above the trunk, and that was too broad: a branch a teammate had
    merely restacked onto a newer trunk answered "nothing new" too, was left on
    the old trunk, restacked here, and force-pushed with fresh shas over
    perfectly good ones -- every sync by anyone then rewrote every branch, and
    in the sandbox the second round conflicted. Only a tip this clone once held
    is a rewrite of its own.
    """
    if not tracked:
        return False
    tips = runner.run(
        ["git", "log", "-g", "--format=%H", f"refs/heads/{branch}"], check=False
    ).split()
    if not tips:
        return False
    left = runner.run(
        ["git", "rev-list", "-n", "1", tracked, "--not", *tips], check=False
    ).strip()
    return not left


def classify(local: str, tracked: str, ancestor) -> str:
    """What one branch needs, from the two shas and an is-ancestor test.

    `ancestor(older, newer)` is the only thing that touches git, which keeps
    the decision itself testable without a repository. A branch with no remote
    copy is UNPUBLISHED rather than diverged: there is nothing to reconcile
    with, and `submit` is what publishes it.
    """
    if not tracked:
        return UNPUBLISHED
    if local == tracked or ancestor(tracked, local):
        return CURRENT
    if ancestor(local, tracked):
        return BEHIND
    return DIVERGED


@dataclass
class Outcome:
    """What one run did, per branch, so the caller can report and the tests
    can assert without reading a terminal."""

    reconciled: dict[str, str] = field(default_factory=dict)
    restacked: list[str] = field(default_factory=list)
    fast_forward: list[str] = field(default_factory=list)
    forced: list[str] = field(default_factory=list)

    @property
    def touched(self) -> list[str]:
        return self.fast_forward + self.forced


def unreconciled(
    runner: gh.Runner,
    branches: list[str],
    remote: str,
    bases: dict[str, str] | None = None,
    trunk: str = "",
    known: set[str] | None = None,
) -> list[str]:
    """The branches holding less than their remote copy does.

    The precondition of every push this tool makes, and the check
    `submit --move` runs before the one step it cannot undo: a branch whose
    remote copy is not in its history will either lose those commits to the
    cascade or be refused by the guard, and finding that out mid-publish is
    the worst moment for it.

    **A moved branch is judged by patch, not by ancestry.** Reconciling one
    cherry-picks the remote's own commits onto where it now sits, which gives
    them new shas -- so `<remote>/<branch>` is deliberately not an ancestor
    afterwards, and asking whether it is would call every correctly reconciled
    move unreconciled. It did, the first time: `submit --move` refused a
    branch that was holding every commit the remote had. What is asked instead
    is whether anything of the remote's own is still missing.
    """
    bases = bases or {}
    moved = moved_branches(branches, trunk, bases, known)
    behind = []
    for branch in branches:
        local = gh.sha(runner, f"refs/heads/{branch}")
        tracked = gh.sha(runner, f"refs/remotes/{remote}/{branch}")
        if not local:
            continue
        base = bases.get(branch, "")
        if branch in moved and base:
            if own_commits(runner, branch, remote, f"{remote}/{base}"):
                behind.append(branch)
            continue
        verdict = classify(local, tracked, lambda a, b: gh.is_ancestor(runner, a, b))
        if verdict == BEHIND or (
            verdict == DIVERGED and not once_mine(runner, branch, tracked)
        ):
            behind.append(branch)
    return behind


def moved_branches(
    branches: list[str],
    trunk: str,
    bases: dict[str, str],
    known: set[str] | None = None,
) -> set[str]:
    """The branches this clone has taken off the parent GitHub records for them.

    **By where the PR's base is, not by ancestry.** The first version asked whether
    `<remote>/<base>` was an ancestor of the branch, which is also false in the
    commonest case of all -- a parent that has simply gained commits this clone
    has not restacked onto yet. Measured in tabsdata-os: `OS-3508`, whose local
    parent and whose PR base were both `OS-3505`, was reported as "moved off its
    base here" and cherry-picked, when a plain fast-forward was what it needed.
    What is asked instead is whether the PR's base is still a branch of this
    stack: that is the question that was meant -- has anything here been taken
    off a chain that is still somebody else's.

    **And a move taints everything above it.** Only the bottom branch of a moved
    slice gets a new parent name; the ones above keep theirs, while their remote
    copies still sit on the old chain below. Reconciling those the ordinary way
    would drag that chain back in, which is the bug this whole path exists for.

    The PR's base is what it is compared against because gh-stack's state is
    rewritten by the move the moment it runs, so it agrees with the move by
    construction and could never notice one; GitHub keeps the old base until
    `submit --move` publishes.
    """
    known = known if known is not None else set(branches)
    moved: set[str] = set()
    tainted = False
    for index, branch in enumerate(branches):
        parent = branches[index - 1] if index else trunk
        base = bases.get(branch)
        # A base still inside this stack is not a move even when it is not the
        # immediate parent: that is a branch between the two whose PR has
        # landed and whose local copy is gone, and its commits are in the trunk
        # now, so the ordinary reconcile drops them as already upstream. A base
        # OUTSIDE the stack is the move -- the branch has been taken off a
        # chain that is still somebody's.
        #
        # The trunk is not an exception to that, and an earlier version made it
        # one. A branch whose PR still targets the trunk while it sits on a
        # stack here is the plainest move there is -- `gsx move --to <top>` on
        # an unsubmitted branch makes exactly it -- and excluding it sent the
        # branch down the ordinary path, where `git rebase <remote>/<branch>`
        # would have replayed a whole 32-branch stack onto a copy of the branch
        # that still sat on the trunk. A bottom branch that really is on the
        # trunk needs no exception: its base and its parent are both the trunk,
        # so the comparison above already passes it.
        if base and base != parent and base not in known:
            tainted = True
        # No PR, no recorded base: nothing to disagree with. It cannot start a
        # taint, but it inherits one.
        if tainted:
            moved.add(branch)
    return moved


def integrated(runner: gh.Runner, branch: str, remote: str, tracked: str) -> None:
    """Record in the branch's reflog that the remote tip has been taken in.

    A moved branch is reconciled by cherry-pick, which never makes the remote
    tip an ancestor of the branch -- and the guard's first rule, like
    `once_mine`, reads the reflog to decide whether a forced push discards
    somebody else's work. Without this the publish of a move whose branch a
    teammate had pushed to was refused by the guard AFTER the old stack had
    been dissolved on GitHub, which is the one order of events this whole tool
    exists to prevent. Two `update-ref`s with honest messages: the branch
    pointed at the remote tip, then at the result that holds its commits. The
    working tree is the result throughout, so nothing moves under the
    operator; and `git rebase <remote>/<branch>`, the other reconcile, leaves
    the same fact in the reflog by making the tip an ancestor.
    """
    result = gh.sha(runner, f"refs/heads/{branch}")
    ref = f"refs/heads/{branch}"
    runner.run(
        [
            "git",
            "update-ref",
            "-m",
            f"gsx sync: integrated {remote}/{branch}",
            ref,
            tracked,
            result,
        ]
    )
    runner.run(
        [
            "git",
            "update-ref",
            "-m",
            f"gsx sync: {branch} holding {remote}/{branch}'s commits where it now sits",
            ref,
            result,
            tracked,
        ]
    )


def reconcile(
    runner: gh.Runner,
    branches: list[str],
    remote: str,
    out,
    bases: dict[str, str] | None = None,
    trunk: str = "",
    known: set[str] | None = None,
) -> dict[str, str]:
    """Bring every branch up to its own remote copy, bottom-up.

    The whole point of the command, and the step `gh stack sync` does not
    have. Two shapes, and which one applies is not a preference:

    **Still where GitHub has it** -- `git rebase <remote>/<branch>`. One
    command covers a fast-forward and a divergence alike, and it drops any
    commit whose patch the remote already holds. Afterwards the branch
    descends from its remote copy, so the push is an ordinary fast-forward.
    That is the case worth optimising, because it is nearly all of them.

    **Moved off its base here** (an unpublished `gsx move`) -- the same rebase
    would drag the OLD parent chain back in, and measured on a real move it
    did: a branch that should have carried three commits over its new parent
    came back carrying eight, the extra five belonging to the two PRs it had
    just been moved away from. So only the remote's own commits are taken, and
    they are cherry-picked onto the branch where it now sits. The cost is that
    the branch no longer descends from its remote copy and its push is a
    forced one -- correct, since a moved branch is a rewrite by definition.
    """
    bases = bases or {}
    moved = moved_branches(branches, trunk, bases, known)
    done = {}
    for branch in branches:
        local = gh.sha(runner, f"refs/heads/{branch}")
        tracked = gh.sha(runner, f"refs/remotes/{remote}/{branch}")
        if not local:
            continue
        verdict = classify(local, tracked, lambda a, b: gh.is_ancestor(runner, a, b))
        done[branch] = verdict
        base = bases.get(branch, "")
        if branch in moved and base:
            taking = own_commits(runner, branch, remote, f"{remote}/{base}", out=out)
            if taking:
                done[branch] = DIVERGED
                gh.checkout(runner, branch)
                runner.run(["git", "cherry-pick", *taking], capture=False)
                out.info(
                    f"{branch}: took {len(taking)} commit(s) from {remote}/{branch} "
                    "(moved off its base here, so only its own came over)",
                    branch=branch,
                    took=len(taking),
                )
            else:
                done[branch] = CURRENT
            if tracked and tracked != gh.sha(runner, f"refs/heads/{branch}"):
                integrated(runner, branch, remote, tracked)
            continue
        if verdict in (CURRENT, UNPUBLISHED):
            continue
        if verdict == DIVERGED and once_mine(runner, branch, tracked):
            # Ours is a rewrite of theirs -- an interleave, a reorder -- and
            # we once held exactly what the remote has. Rebasing onto it would
            # put its order back. Left alone; the push forces, and the guard
            # lets a rewrite of one's own history through.
            done[branch] = CURRENT
            continue
        gh.checkout(runner, branch)
        runner.run(["git", "rebase", f"{remote}/{branch}"], capture=False)
        out.info(f"{branch}: {WORDS[verdict]} {remote}/{branch}", branch=branch)
    return done


def tips(runner: gh.Runner, branches: list[str]) -> dict[str, str]:
    """Every branch's tip before this run touches anything.

    The cascade needs it: a branch's own commits are the ones after the tip its
    parent had **when the branch was built on it**, and once the parent has
    been rewritten there is nothing left in the repository that remembers where
    that was.
    """
    return {
        branch: sha
        for branch in branches
        if (sha := gh.sha(runner, f"refs/heads/{branch}"))
    }


def restack(
    runner: gh.Runner,
    branches: list[str],
    trunk: str,
    out,
    before: dict[str, str] | None = None,
    reconciled: dict[str, str] | None = None,
) -> list[str]:
    """Put each branch back on top of the one below it, where it is not already.

    Only after `reconcile`, and only where it is needed: a teammate who
    restacked before us already pushed the answer, and our fast-forward to it
    left nothing to do. What is left is the branches this clone moved.

    **The upstream is the parent's tip from before this run**, not
    `git merge-base <parent> <branch>`. Once the parent has been rewritten --
    which is exactly when a restack is needed -- the merge-base falls back past
    the parent's own commits, and the rebase replays them onto a parent that
    already has them. Measured in tabsdata-os: restacking `OS-3482` after
    `OS-3481` was rewritten took the merge-base back to the tip of `TD-3329`,
    three branches below, and replayed `[OS-3481] Add excel file parsing logic`
    onto the new `OS-3481` -- an add/add conflict in a file neither side had
    really touched twice. gh-stack avoids it by keeping a recorded base per
    branch; a snapshot taken at the start of the run is the same fact, and one
    this code already has to hand.

    The merge-base is still the fallback, for a branch whose recorded tip is not
    in its history at all -- a branch built somewhere else entirely, where the
    snapshot would name the wrong range.
    """
    before = before or {}
    reconciled = reconciled or {}
    rewritten = []
    for index, branch in enumerate(branches):
        parent = branches[index - 1] if index else trunk
        if not gh.sha(runner, f"refs/heads/{parent}"):
            continue
        if gh.is_ancestor(runner, parent, branch):
            continue
        was = fork_point(
            runner,
            parent,
            branch,
            [before.get(parent, ""), reconciled.get(parent, "")],
        )
        gh.checkout(runner, branch)
        runner.run(["git", "rebase", "--onto", parent, was, branch], capture=False)
        rewritten.append(branch)
        out.info(f"{branch}: restacked onto {parent}", branch=branch, parent=parent)
    return rewritten


def fork_point(runner: gh.Runner, parent: str, branch: str, earlier: list[str]) -> str:
    """Where `branch`'s own commits start: the LATEST of its merge-bases with
    every state the parent has had this run -- before the run, after
    reconcile, and now.

    Each state is the fork point in some case, and every pair was tried and
    found short. The current parent is wrong once it has been rewritten in
    this run -- which is exactly when a restack is needed -- because the
    merge-base then falls past the parent's own commits and the rebase replays
    them onto a parent that already holds them (the tabsdata-os conflict). The
    pre-run tip is wrong when the parent already carried a local commit the
    child was not built on: bob committed to B3-3 and then synced, so the
    snapshot held his commit while B3-4 had forked before it. And a child that
    was itself reconciled onto a remote copy sitting on the parent's REMOTE
    version forked from the parent as it stood after reconcile and before
    restack, which neither of those two is: alice's B2-5, reconciled onto bob's
    B2-5, met bob's B2-4 there, while B2-4 here had by then been restacked
    again -- and the range from the next-best candidate replayed `[B2-4]
    initial` onto a B2-4 that already had it.

    Whichever candidate is the most recent is where the child was really
    built, and the range above it holds the child's commits alone. gh-stack
    keeps one recorded base per branch for this; three snapshots are that
    fact, computed rather than stored, for a run that rewrites branches twice.
    """
    candidates = []
    for ref in [*earlier, parent]:
        if not ref:
            continue
        base = runner.run(["git", "merge-base", ref, branch], check=False).strip()
        if base and base not in candidates:
            candidates.append(base)
    if not candidates:
        return runner.run(["git", "merge-base", parent, branch])
    latest = candidates[0]
    for candidate in candidates[1:]:
        if gh.is_ancestor(runner, latest, candidate):
            latest = candidate
    return latest


def push_args(
    runner: gh.Runner, branches: list[str], remote: str
) -> tuple[list[str], list[str], list[str]]:
    """The one push, and which branches are in it forced and which plain.

    A lease per rewritten branch, pinned to the sha this run fetched, so a
    remote that moved between the fetch and the push is a refusal rather than
    a loss -- and `--atomic`, because half a stack on the remote is a worse
    state than none of it.
    """
    plain, forced, leases = [], [], []
    for branch in branches:
        local = gh.sha(runner, f"refs/heads/{branch}")
        tracked = gh.sha(runner, f"refs/remotes/{remote}/{branch}")
        if not local:
            continue
        if not tracked or gh.is_ancestor(runner, tracked, local):
            if local != tracked:
                plain.append(branch)
            continue
        forced.append(branch)
        leases.append(f"--force-with-lease=refs/heads/{branch}:{tracked}")
    return plain, forced, leases
