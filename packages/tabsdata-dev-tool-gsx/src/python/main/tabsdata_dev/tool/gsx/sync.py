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

from dataclasses import dataclass, field

from . import gh

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


def own_commits(runner: gh.Runner, branch: str, remote: str, base: str) -> list[str]:
    """The commits `<remote>/<branch>` has of its OWN that `branch` lacks.

    "Of its own" is measured from the PR's base **as GitHub has it**, which is
    the only thing that knows where the remote copy's history stops being the
    parent's. Judged by patch (`--cherry-pick`), so a commit we already hold
    under a different sha -- every restack makes those -- is not fetched twice.
    Oldest first, because that is the order they have to be replayed in.
    """
    if not base:
        return []
    listed = runner.run(
        [
            "git",
            "rev-list",
            "--reverse",
            "--right-only",
            "--cherry-pick",
            f"{branch}...{remote}/{branch}",
            "--not",
            base,
        ],
        check=False,
    )
    return [line for line in listed.split() if line]


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
    behind = []
    for branch in branches:
        local = gh.sha(runner, f"refs/heads/{branch}")
        tracked = gh.sha(runner, f"refs/remotes/{remote}/{branch}")
        if not local:
            continue
        base = bases.get(branch, "")
        if moved_away(runner, branch, remote, base):
            if own_commits(runner, branch, remote, f"{remote}/{base}"):
                behind.append(branch)
            continue
        if classify(local, tracked, lambda a, b: gh.is_ancestor(runner, a, b)) in (
            BEHIND,
            DIVERGED,
        ):
            behind.append(branch)
    return behind


def moved_away(runner: gh.Runner, branch: str, remote: str, base: str) -> bool:
    """Whether this clone has taken `branch` off the parent GitHub has it on.

    The question that decides how to reconcile, and it is asked of the PR's
    base rather than of gh-stack's state: a `gsx move` rewrites the state the
    moment it runs, so the state agrees with the move by construction and
    could never notice one. GitHub still has the old base until the move is
    published, which is exactly the window this matters in.
    """
    if not base:
        return False
    tip = gh.sha(runner, f"refs/remotes/{remote}/{base}") or gh.sha(
        runner, f"refs/heads/{base}"
    )
    return bool(tip) and not gh.is_ancestor(runner, tip, branch)


def reconcile(
    runner: gh.Runner,
    branches: list[str],
    remote: str,
    out,
    bases: dict[str, str] | None = None,
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
    done = {}
    for branch in branches:
        local = gh.sha(runner, f"refs/heads/{branch}")
        tracked = gh.sha(runner, f"refs/remotes/{remote}/{branch}")
        if not local:
            continue
        verdict = classify(local, tracked, lambda a, b: gh.is_ancestor(runner, a, b))
        done[branch] = verdict
        base = bases.get(branch, "")
        if moved_away(runner, branch, remote, base):
            taking = own_commits(runner, branch, remote, f"{remote}/{base}")
            if not taking:
                done[branch] = CURRENT
                continue
            done[branch] = DIVERGED
            gh.checkout(runner, branch)
            runner.run(["git", "cherry-pick", *taking], capture=False)
            out.info(
                f"{branch}: took {len(taking)} commit(s) from {remote}/{branch} "
                "(moved off its base here, so only its own came over)",
                branch=branch,
                took=len(taking),
            )
            continue
        if verdict in (CURRENT, UNPUBLISHED):
            continue
        gh.checkout(runner, branch)
        runner.run(["git", "rebase", f"{remote}/{branch}"], capture=False)
        out.info(f"{branch}: {WORDS[verdict]} {remote}/{branch}", branch=branch)
    return done


def restack(runner: gh.Runner, branches: list[str], trunk: str, out) -> list[str]:
    """Put each branch back on top of the one below it, where it is not already.

    Only after `reconcile`, and only where it is needed: a teammate who
    restacked before us already pushed the answer, and our fast-forward to it
    left nothing to do. What is left is the branches this clone moved.
    """
    rewritten = []
    for index, branch in enumerate(branches):
        parent = branches[index - 1] if index else trunk
        if not gh.sha(runner, f"refs/heads/{parent}"):
            continue
        if gh.is_ancestor(runner, parent, branch):
            continue
        base = runner.run(["git", "merge-base", parent, branch])
        gh.checkout(runner, branch)
        runner.run(["git", "rebase", "--onto", parent, base, branch], capture=False)
        rewritten.append(branch)
        out.info(f"{branch}: restacked onto {parent}", branch=branch, parent=parent)
    return rewritten


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
