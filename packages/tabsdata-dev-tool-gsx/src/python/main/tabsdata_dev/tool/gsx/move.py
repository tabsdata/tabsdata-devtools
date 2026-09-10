#
# Copyright 2026 Tabsdata Inc.
#

"""`gsx move`: take the branch you are on, and everything above it, elsewhere.

**Nothing here reaches GitHub.** The move is four `gh stack` commands that
only ever write local branches and gh-stack's own tracking file, and the
publishing is `gsx submit --move`, later, deliberately. So a move can be looked
at, slept on, and undone.

The four commands, and why they are gh-stack's rather than ours:

    gh stack unstack --local                     # forget the source stack
    gh stack checkout T && gh stack unstack --local   # ...and the target's
    git checkout <trunk> && gh stack init --base <trunk> <kept...>
    git checkout <trunk> && gh stack init --base <base> <target...> <moved...>
    gh stack rebase --no-trunk                   # replay what changed parent

Each `init` runs from the trunk because it refuses to run from inside a stack
-- including the one it has just made, since it leaves you on top of it.

`gh stack init` records each branch's base as **the tip its commits actually
sit on**, not the parent it was just declared to have -- measured: a branch
declared above another stack's top came out with its old trunk sha as its base.
`gh stack rebase --no-trunk` then replays `--onto <new parent> <recorded base>`,
so every branch keeps exactly its own commits, only the branches whose parent
really changed are rewritten, and nothing is fetched or pushed (it says so:
"To push up your changes, run `gh stack push`"). It also owns the conflict:
`.git/gh-stack-rebase-state` holds every branch's original ref, and
`gh stack rebase --continue|--abort` finishes or unwinds it. That is why this
module has no rebase code, no state file and no undo of its own -- an earlier
draft had all three.

What GitHub still thinks is the old arrangement, and `pending()` is how that is
noticed: a PR whose GitHub stack holds PRs that now live in **two** local
stacks has moved here and not there. `stack` says so, and `submit` refuses to
publish it without `--move`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tabsdata_dev.common.core.errors import ToolError

from . import gh

#: What `--to` turned out to name, which decides the destination's branches.
STACK = "stack"  # the top of another tracked stack: the moved branches join it
PLAIN = "plain"  # a branch whose PR is in no stack: the two become a stack
TRUNK = "trunk"  # the trunk: the moved branches become a stack of their own


@dataclass
class Source:
    """The stack being moved out of, as gh-stack tracks it here."""

    number: int | None
    trunk: str
    branches: list[str]
    prs: list[int | None]
    index: int  # 1-based position of the checked-out branch
    current: str

    @property
    def keep(self) -> list[str]:
        """The branches below the current one, which stay where they are."""
        return self.branches[: self.index - 1]

    @property
    def moving(self) -> list[str]:
        """The current branch and every branch above it."""
        return self.branches[self.index - 1 :]

    @property
    def moving_prs(self) -> list[int]:
        return [pr for pr in self.prs[self.index - 1 :] if pr]

    @property
    def tag(self) -> str:
        return f"#{self.number}" if self.number else "the unsubmitted stack"


@dataclass
class Target:
    mode: str
    head: str  # the branch the moved branches are stacked on top of
    number: int | None = None  # its stack's number, when it has one
    branches: list[str] = field(default_factory=list)  # its stack, bottom-up
    trunk: str = ""  # what that stack sits on
    pr: int | None = None


@dataclass
class Plan:
    source: Source
    target: Target
    keep_init: list[str] = field(default_factory=list)
    dest_init: list[str] = field(default_factory=list)
    dest_base: str = ""
    untrack_target: bool = False
    parent: str = ""  # the branch the moved ones used to sit on
    upstream: str = ""  # ...and its tip, which is where the replay starts
    steps: list[str] = field(default_factory=list)


# ------------------------------------------------------------ the two ends
def source_stack(state: dict, current: str) -> Source:
    """The one locally tracked stack `current` belongs to.

    You move out of the stack you are standing in, so this is not something the
    command takes an option for: being on the branch IS the argument.
    """
    holding = [
        stack
        for stack in state.get("stacks") or []
        if any(entry.get("branch") == current for entry in stack.get("branches") or [])
    ]
    if not holding:
        raise ToolError(
            f"branch {current!r} is not in any stack tracked here; there is nothing "
            "to move it out of"
        )
    if len(holding) > 1:
        raise ToolError(
            f"branch {current!r} is in several stacks tracked here; cannot tell which "
            "to move out of"
        )
    stack = holding[0]
    entries = [item for item in stack.get("branches") or [] if item.get("branch")]
    branches = [item["branch"] for item in entries]
    trunk = ((stack.get("trunk") or {}).get("branch")) or ""
    if current == trunk:
        raise ToolError(
            f"you are on the trunk {current!r}; check out the branch you want to move"
        )
    number = stack.get("number")
    return Source(
        number=int(number) if number else None,
        trunk=trunk,
        branches=branches,
        prs=[(item.get("pullRequest") or {}).get("number") for item in entries],
        index=branches.index(current) + 1,
        current=current,
    )


def stack_of(state: dict, branch: str) -> dict | None:
    """The locally tracked stack holding `branch`, if any."""
    for stack in state.get("stacks") or []:
        if any(item.get("branch") == branch for item in stack.get("branches") or []):
            return stack
    return None


def resolve_target(
    runner: gh.Runner,
    target: str,
    source: Source,
    state: dict,
    default_branch: str,
    out,
) -> Target:
    """What `--to` names: a stack by number, a branch, or the trunk.

    A stack has to be **tracked here**, because the destination is rebuilt with
    `gh stack init` over local branches; one that exists only on GitHub is a
    `gh stack checkout` away and saying so is better than fetching behind the
    operator's back. A branch has to be the **top** of its stack, because the
    moved branches go above it and anything else would rewrite what is already
    up there.
    """
    if target.startswith("#"):
        return _by_number(target[1:], source, state)
    if target in (source.trunk, default_branch):
        if source.index <= 1:
            raise ToolError(
                f"{source.current!r} is already the bottom of {source.tag}, which "
                f"sits on {target!r} already; nothing to move"
            )
        _require_local(runner, target)
        return Target(mode=TRUNK, head=target, trunk=target)
    return _by_branch(runner, target, source, state, default_branch, out)


def _by_number(value: str, source: Source, state: dict) -> Target:
    if not value.isdigit():
        raise ToolError(f"'#{value}' is not a stack number")
    number = int(value)
    if source.number == number:
        raise ToolError(
            f"#{number} is the stack you are standing in; reordering inside a stack "
            "is `gh stack modify`"
        )
    for stack in state.get("stacks") or []:
        if stack.get("number") == number:
            branches = [
                item["branch"]
                for item in stack.get("branches") or []
                if item.get("branch")
            ]
            if not branches:
                raise ToolError(f"stack #{number} is tracked here but has no branches")
            entries = stack.get("branches") or []
            return Target(
                mode=STACK,
                head=branches[-1],
                number=number,
                branches=branches,
                trunk=((stack.get("trunk") or {}).get("branch")) or "",
                pr=(entries[-1].get("pullRequest") or {}).get("number"),
            )
    raise ToolError(
        f"stack #{number} is not tracked in this checkout; `gh stack checkout "
        f"{number}` first (the move rebuilds it from local branches)"
    )


def _by_branch(
    runner: gh.Runner, branch: str, source: Source, state: dict, default: str, out
) -> Target:
    _require_local(runner, branch)
    if branch in source.branches:
        raise ToolError(
            f"{branch!r} is in {source.tag}, the stack you are moving out of; "
            "reordering inside a stack is `gh stack modify`"
        )
    stack = stack_of(state, branch)
    if stack is None:
        # A branch with no stack of its own: its PR (if it has one) and the
        # moved branches become a stack together, which is the one case where
        # `--to` grows something that was never a stack.
        out.info(
            f"{branch!r} is in no stack tracked here; it becomes the bottom of a new "
            "stack with the moved branches above it"
        )
        return Target(mode=PLAIN, head=branch, trunk=default, branches=[branch])
    entries = [item for item in stack.get("branches") or [] if item.get("branch")]
    branches = [item["branch"] for item in entries]
    if branches[-1] != branch:
        raise ToolError(
            f"{branch!r} is not the top of its stack ({' <- '.join(branches)}); the "
            f"moved branches go above it, so target {branches[-1]!r} -- or "
            "`gh stack modify` that stack first"
        )
    number = stack.get("number")
    if number and source.number == number:
        raise ToolError(f"#{number} is the stack you are standing in")
    return Target(
        mode=STACK,
        head=branch,
        number=int(number) if number else None,
        branches=branches,
        trunk=((stack.get("trunk") or {}).get("branch")) or "",
        pr=(entries[-1].get("pullRequest") or {}).get("number"),
    )


def _require_local(runner: gh.Runner, branch: str) -> None:
    if not gh.sha(runner, f"refs/heads/{branch}"):
        raise ToolError(
            f"branch {branch!r} does not exist here; check it out first "
            f"(`gh stack checkout {branch}`, or `git fetch && git switch {branch}`)"
        )


# --------------------------------------------------------------- the plan
def build(source: Source, target: Target) -> Plan:
    """Everything the four commands need, worked out before any of them runs."""
    plan = Plan(source=source, target=target)
    plan.keep_init = list(source.keep)
    plan.dest_init = [*target.branches, *source.moving]
    plan.dest_base = target.trunk or source.trunk
    plan.untrack_target = target.mode == STACK
    plan.parent = source.keep[-1] if source.keep else source.trunk
    plan.steps = steps(plan)
    return plan


def steps(plan: Plan) -> list[str]:
    """The commands, in order, as the operator reads them before confirming."""
    source, target = plan.source, plan.target
    lines = [f"gh stack unstack --local   # forget {source.tag}"]
    if plan.untrack_target:
        named = f"#{target.number}" if target.number else "its stack"
        lines.append(
            f"gh stack checkout {target.head} && gh stack unstack --local"
            f"   # ...and {named}"
        )
    # Each init runs from the trunk: `gh stack init` refuses when the CURRENT
    # branch is in a stack, and the init before it leaves you on the top of the
    # one it just made.
    if plan.keep_init:
        lines.append(
            f"git checkout {source.trunk} && gh stack init --base {source.trunk} "
            f"{' '.join(plan.keep_init)}   # what stays below"
        )
    lines.append(
        f"git checkout {source.trunk} && gh stack init --base {plan.dest_base} "
        f"{' '.join(plan.dest_init)}   # the destination"
    )
    lines.append(
        f"git rebase --onto {target.head} {plan.parent} {source.moving[0]}"
        f"   # replay {source.moving[0]}, off {plan.parent}"
    )
    if len(source.moving) > 1:
        lines.append(
            f"git checkout {source.moving[0]} && gh stack rebase --upstack --no-trunk"
            f"   # replay {' '.join(source.moving[1:])}"
        )
    lines.append(f"git checkout {source.current}")
    return lines


def text(plan: Plan) -> str:
    """The plan as one block: what moves, where to, and every step."""
    source, target = plan.source, plan.target
    lines = [
        "Plan",
        f"  from  {source.tag}   stay : {' '.join(source.keep) or '(none)'}",
        f"  from  {source.tag}   move : {' '.join(source.moving)}",
    ]
    if target.mode == TRUNK:
        lines.append(
            f"  onto  {target.head}      ->  a new stack: {' '.join(source.moving)}"
        )
    else:
        where = f"#{target.number}" if target.number else "an unsubmitted stack"
        if target.mode == PLAIN:
            where = f"#{target.pr}" if target.pr else "no stack"
        lines.append(
            f"  onto  {target.head} ({where})   ->  {' '.join(plan.dest_init)}"
        )
    lines.append("")
    lines.extend(f"  {n}. {step}" for n, step in enumerate(plan.steps, start=1))
    lines.append("")
    lines.append("  all local; `gsx submit --move` is what publishes it")
    return "\n".join(lines)


# ------------------------------------------------------------- the moving
def run(runner: gh.Runner, plan: Plan, steps_counter) -> dict:
    """Drive the four commands. Each one is gh-stack's, and each is local.

    A conflict stops in `gh stack rebase` and stays there: it holds every
    branch's original ref in `.git/gh-stack-rebase-state`, so the operator
    resolves and runs `gh stack rebase --continue`, or `--abort` to put every
    branch back. Failing here leaves the tracking rearranged and the branches
    untouched, which `gh stack checkout <n>` re-imports from GitHub.
    """
    source, target = plan.source, plan.target
    gh.stack_unstack_local(runner)
    steps_counter.step(f"forgot {source.tag} locally", stage="untrack-source")

    if plan.untrack_target:
        gh.stack_checkout(runner, target.head)
        gh.stack_unstack_local(runner)
        steps_counter.step(
            f"forgot the stack of {target.head} locally", stage="untrack-target"
        )
    if plan.keep_init:
        gh.checkout(runner, source.trunk)
        gh.stack_init(runner, plan.keep_init, base=source.trunk)
        steps_counter.step(
            f"tracked what stays below: {' '.join(plan.keep_init)}", stage="init-kept"
        )
    # From the trunk, because the init above left us on the top of the stack it
    # made and `gh stack init` refuses to run from inside a stack (exit 5,
    # `current branch "X" is already part of a stack`).
    gh.checkout(runner, source.trunk)
    gh.stack_init(runner, plan.dest_init, base=plan.dest_base)
    steps_counter.step(
        f"tracked the destination: {' '.join(plan.dest_init)}", stage="init-destination"
    )
    bottom = source.moving[0]
    # The one branch whose parent changed is replayed off the branch it used to
    # sit on, with plain git. Not from the base `gh stack init` recorded: that
    # is the merge-base with the parent it was just DECLARED to have, which is
    # the trunk for a branch being put on the trunk -- replaying from there
    # brings along every commit of whatever it used to sit on. Measured: a
    # one-commit branch came out with 37.
    gh.rebase_onto(runner, target.head, plan.upstream or plan.parent, bottom)
    steps_counter.step(f"replayed {bottom} onto {target.head}", stage="rebase")
    if len(source.moving) > 1:
        # The rest are gh-stack's: each still sits on the one below it, whose
        # recorded base is that branch's own old tip, so the cascade's ranges
        # are right. `--upstack` from the bottom moved branch rebases what is
        # above it and not itself, which is exactly what is left to do.
        gh.checkout(runner, bottom)
        gh.stack_rebase_upstack(runner)
        steps_counter.step(
            f"replayed {len(source.moving) - 1} more onto {bottom}", stage="rebase-rest"
        )
    gh.checkout(runner, source.current)
    steps_counter.step(f"back on {source.current}", stage="checkout")
    return {
        "moved": source.moving,
        "kept": plan.keep_init,
        "onto": target.head,
        "mode": target.mode,
        "stack": target.number,
        "pushed": False,
        "next": "gsx submit --move",
    }


# ----------------------------------------------------- what GitHub missed
@dataclass
class Pending:
    """A move this checkout has made and GitHub has not been told about.

    `dissolve` are the stack numbers GitHub has to lose, because their PRs no
    longer sit together; `stacks` are the local stacks that hold those PRs now
    and so have to be submitted. Both fall out of one comparison, and both
    `stack` (which says so) and `submit --move` (which acts on it) read it.
    """

    dissolve: list[int] = field(default_factory=list)
    stacks: list[list[str]] = field(default_factory=list)
    prs: dict[int, int] = field(default_factory=dict)  # pr -> the stack it left

    def __bool__(self) -> bool:
        return bool(self.dissolve)

    def line(self) -> str:
        """What has to happen, rather than which PRs moved.

        Naming the movers would mean picking them out of the stack that lost
        them, and the useful fact is the other one: this stack no longer holds
        its PRs the way GitHub does, so it has to be dissolved and relinked
        from here. An early version said "#3485, #3486, #3487 left stack #3488"
        when only one of the three had gone anywhere.
        """
        stacks = sorted(set(self.prs.values()))
        which = ", ".join(f"#{number}" for number in stacks)
        prs = ", ".join(f"#{pr}" for pr in sorted(self.prs))
        return (
            f"a move is in progress: stack {which} on GitHub no longer holds its PRs "
            f"({prs}) the way this checkout does -- `gsx submit --move` dissolves it "
            "and relinks them from here, `gh stack checkout <n>` re-imports what "
            "GitHub has instead"
        )


def pending(state: dict, listing: list[dict]) -> Pending:
    """Which GitHub stacks this checkout has taken apart.

    A GitHub stack is still **satisfiable** while its PRs are the bottom of one
    local stack, in order: `gh stack link <n> ...` appends, so such a stack can
    grow into whatever is now above it and keeps its number. Anything else --
    its PRs split across two local stacks, or sitting on top of another stack's
    PRs -- can only be reached by removing PRs from it, which the API cannot
    do. That one has to be dissolved, and every local stack holding its PRs
    submitted afterwards.

    Prefixes are the whole test because a move can only ever make prefixes: you
    stand on a branch and everything above it goes with you, so what stays
    below is a prefix and what arrives goes on top. PRs this checkout does not
    track are not evidence either way and are left out of the comparison.
    """
    order: list[list[int]] = []
    names: list[list[str]] = []
    for stack in state.get("stacks") or []:
        prs, branches = [], []
        for item in stack.get("branches") or []:
            if not item.get("branch"):
                continue
            branches.append(item["branch"])
            number = (item.get("pullRequest") or {}).get("number")
            if number:
                prs.append(int(number))
        order.append(prs)
        names.append(branches)
    tracked = {pr for prs in order for pr in prs}

    found = Pending()
    for stack in listing:
        if not stack.get("open") or not stack.get("number"):
            continue
        mine = [
            int(pull["number"])
            for pull in stack.get("pull_requests") or []
            if pull.get("number") and int(pull["number"]) in tracked
        ]
        if not mine or any(prs[: len(mine)] == mine for prs in order):
            continue
        number = int(stack["number"])
        found.dissolve.append(number)
        for pr in mine:
            found.prs[pr] = number
        for prs, branches in zip(order, names):
            if set(mine) & set(prs) and branches not in found.stacks:
                found.stacks.append(branches)
    return found
