#
# Copyright 2026 Tabsdata Inc.
#

"""`gsx move`: take the branch you are on, and everything above it, elsewhere.

**Nothing here reaches GitHub.** The move is gh-stack's own commands and one
`git rebase` that
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

A conflict stops the replay, and by then the tracking is already the new
arrangement -- so "resolve and rerun" is not available and neither is "just
abort". `<git-dir>/gsx-move` is what makes both directions one command each:
it holds what is left to replay and what an undo needs (every moved branch's
tip, and gh-stack's whole tracking file as text). `--continue` finishes,
`--abort` puts the branches and both stacks back, and while it exists a second
move is refused, because that file is the only record of how to undo the first.

What GitHub still thinks is the old arrangement, and `pending()` is how that is
noticed: a PR whose GitHub stack holds PRs that now live in **two** local
stacks has moved here and not there. That is a disagreement between the two
sides, not a move in progress -- the move is over by then. `stack` says so, and
`submit` refuses to publish it without `--move`.
"""

from __future__ import annotations

import json
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
    prs: list[int | None] = field(default_factory=list)  # aligned with them
    trunk: str = ""  # what that stack sits on
    pr: int | None = None


@dataclass
class Plan:
    source: Source
    target: Target
    keep_init: list[str] = field(default_factory=list)
    dest_init: list[str] = field(default_factory=list)
    landed: list[str] = field(default_factory=list)  # ...and what they leave out
    absent: list[str] = field(
        default_factory=list
    )  # kept branches not in this checkout
    dest_base: str = ""
    untrack_target: bool = False
    parent: str = ""  # the branch the moved ones used to sit on
    upstream: str = ""  # ...and its tip, which is where the replay starts
    remote: str = "origin"  # only for the way back, if a replay stops
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


def _prs(entries: list[dict]) -> list[int | None]:
    """Each tracked branch's PR number, aligned with the branch list."""
    return [(item.get("pullRequest") or {}).get("number") for item in entries]


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
            entries = [
                item for item in stack.get("branches") or [] if item.get("branch")
            ]
            branches = [item["branch"] for item in entries]
            if not branches:
                raise ToolError(f"stack #{number} is tracked here but has no branches")
            return Target(
                mode=STACK,
                head=branches[-1],
                number=number,
                branches=branches,
                prs=_prs(entries),
                trunk=((stack.get("trunk") or {}).get("branch")) or "",
                pr=_prs(entries)[-1],
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
        return Target(
            mode=PLAIN, head=branch, trunk=default, branches=[branch], prs=[None]
        )
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
        prs=_prs(entries),
        trunk=((stack.get("trunk") or {}).get("branch")) or "",
        pr=_prs(entries)[-1],
    )


def _require_local(runner: gh.Runner, branch: str) -> None:
    if not gh.sha(runner, f"refs/heads/{branch}"):
        raise ToolError(
            f"branch {branch!r} does not exist here; check it out first "
            f"(`gh stack checkout {branch}`, or `git fetch && git switch {branch}`)"
        )


# --------------------------------------------------------------- the plan
def still_going(
    branches: list[str], prs: list[int | None], landed: set[int]
) -> tuple[list[str], list[str]]:
    """A stack's branches with the finished run at its bottom dropped.

    `gh stack checkout <n>` imports every branch a stack ever had, merged ones
    included -- a stack that has landed ninety PRs arrives as ninety-three
    branches, all but three of them pointing at the trunk's tip. Re-declaring
    those to `gh stack init` is worse than useless: it makes a hundred-branch
    stack out of a three-branch one, `init` drops the PR association of every
    branch it cannot find an open PR for (so `gsx stack` stops recognising them
    as merged and starts reporting them as ahead), and `gh stack submit` would
    then be handed branches whose PRs are closed and whose remote refs are
    gone.

    Only the run at the **bottom** goes. A finished PR above an open one is
    somebody's odd state, not history, and dropping it would leave a hole in
    the chain of parents the replay reads. Returns what is kept and what is
    not, because the operator should be told a name is missing rather than left
    to notice.
    """
    kept = 0
    for pr in prs[: len(branches)]:
        if not pr or pr not in landed:
            break
        kept += 1
    return branches[kept:], branches[:kept]


def _upstream(source: Source, present: set[str] | None) -> tuple[str, list[str]]:
    """The branch the moved slice actually sits on, and what was skipped.

    `gh stack checkout <n>` records every branch a stack ever had but can only
    *pull* the ones the remote still has, and a merged PR's branch is usually
    deleted -- so a stack with 90 landed PRs is tracked as 93 branches of which
    three are in the checkout. The branch directly below the moved slice is
    then often not here at all, and since it is the rebase's upstream the move
    stopped dead: `branch 'OS-3345' does not exist here, so where 'OS-3346'
    sits cannot be worked out`.

    The nearest branch below that IS here is what the moved commits sit on.
    When none of them is, that is the trunk -- which is where a merged
    branch's commits are, by definition of merged.
    """
    skipped = []
    for branch in reversed(source.keep):
        if present is None or branch in present:
            return branch, skipped
        skipped.append(branch)
    return source.trunk, skipped


def build(
    source: Source,
    target: Target,
    landed: set[int] | None = None,
    present: set[str] | None = None,
) -> Plan:
    """Everything the four commands need, worked out before any of them runs.

    `landed` are the PRs that are merged or closed and `present` the branches
    this checkout actually has; without either nothing is trimmed and every
    branch is assumed to be here, which is what a stack with no history looks
    like anyway.
    """
    landed = landed or set()
    plan = Plan(source=source, target=target)
    plan.keep_init, below = still_going(source.keep, source.prs, landed)
    above, done = still_going(target.branches, target.prs, landed)
    if target.branches and not above:
        raise ToolError(
            f"every PR in {_named(target)} is merged or closed, so there is no stack "
            f"left to move onto; `--to {target.trunk or source.trunk}` is what that "
            "means"
        )
    plan.dest_init = [*above, *source.moving]
    plan.landed = [*done, *below]
    plan.dest_base = target.trunk or source.trunk
    plan.untrack_target = target.mode == STACK
    # The real branch below the moved slice, even when it is one of the landed
    # ones: that is where the moved commits actually sit, and it is the rebase's
    # upstream. Only the *declaring* leaves it out.
    plan.parent, plan.absent = _upstream(source, present)
    plan.steps = steps(plan)
    return plan


def _named(target: Target) -> str:
    return f"#{target.number}" if target.number else f"the stack of {target.head}"


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
    if plan.absent:
        lines.append(
            f"  off   {plan.parent}   ({plan.absent[0]} is not in this checkout, so "
            "that is what the moved branches sit on here)"
        )
    if plan.landed:
        # Named, not just counted: a branch silently missing from a plan is the
        # kind of thing that is only noticed after the commands have run.
        lines.append(
            f"  minus {len(plan.landed)} branch(es) whose PR is merged or closed"
            f": {_abbreviated(plan.landed)}"
        )
    lines.append("")
    lines.extend(f"  {n}. {step}" for n, step in enumerate(plan.steps, start=1))
    lines.append("")
    lines.append("  all local; `gsx submit --move` is what publishes it")
    return "\n".join(lines)


def _abbreviated(branches: list[str], most: int = 6) -> str:
    """A long list of names as its ends: ninety of them tell the operator less
    than the first, the last and the count do."""
    if len(branches) <= most:
        return " ".join(branches)
    return f"{branches[0]} .. {branches[-1]}"


# ------------------------------------------------------------- the moving
#: The stages a move goes through after the tracking has been rearranged. The
#: state file carries the one it is in, because that is what says what is left.
REBASE = "rebase"  # the branch that moved is being replayed
CASCADE = "cascade"  # ...and now the branches above it
PUBLISH = "publish"  # every branch replayed; `gsx submit --move` is what is left
STATE_FILE = "gsx-move"

#: The stages a `--continue` can act on: the replay is what it continues.
REPLAYING = (REBASE, CASCADE)


def snapshot(state: dict, shas: dict[str, str]) -> list[dict]:
    """Every tracked stack as it stands: its number, its trunk, and each branch
    with its PR and the commit it points at.

    Taken before the first change and kept in the session, because a
    rearrangement cannot be read backwards out of the result: once the move has
    run, nothing in the repository still says which stack a branch came from or
    what it pointed at. `--report` is what that is for, and `--abort` reads the
    same shas from `tips`.
    """
    stacks = []
    for stack in state.get("stacks") or []:
        entries = [item for item in stack.get("branches") or [] if item.get("branch")]
        stacks.append(
            {
                "number": stack.get("number"),
                "trunk": ((stack.get("trunk") or {}).get("branch")) or "",
                "branches": [
                    {
                        "branch": item["branch"],
                        "pr": (item.get("pullRequest") or {}).get("number"),
                        "sha": shas.get(item["branch"], ""),
                    }
                    for item in entries
                ],
            }
        )
    return stacks


class Stopped(ToolError):
    """A replay stopped on a conflict. The session is on disk, so the two ways
    out are two commands rather than a recipe."""


@dataclass
class Session:
    """A move in flight, as `<git-dir>/gsx-move` carries it.

    It holds what finishing needs (what is left to replay, and where to end up)
    and what undoing needs:

    * `tips`, the sha of **every branch the move involves** -- the ones moving,
      the ones staying, and the target stack's -- read from the refs before the
      first change. Not from gh-stack's recorded `head`, which can be stale,
      and not from the remote: a branch may hold commits that were never
      pushed, so restoring `origin/<branch>` would throw work away. An undo
      never fetches.
    * `tracking`, gh-stack's whole file as text, which is every stack's number,
      trunk, membership and recorded bases -- put back byte for byte, since a
      rearrangement cannot be run backwards.

    Its presence IS "a move is in progress", and a move is in progress until
    `gsx submit --move` publishes it -- not until its replay finishes. That is
    what the `publish` stage is: every branch is where it should be and GitHub
    has been told nothing. Keeping the file until then buys two things. A
    second move is refused throughout, so one unpublished rearrangement is all
    there can ever be to reason about; and `--abort` survives the end of the
    replay, where before it vanished at the moment the move became hardest to
    undo by hand.

    In the git dir rather than the work tree, so it cannot be committed by
    accident or turn up as a conflict of its own.
    """

    stage: str
    started_on: str
    moving: list[str]
    target: str
    onto: str
    upstream: str
    tips: dict[str, str]
    tracking: str | None
    remote: str = "origin"
    stacks: list[int] = field(default_factory=list)
    #: Every tracked stack as it was when the move started -- written once and
    #: never rewritten, since "as it was" is the whole of its value.
    before: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"version": 1, **self.__dict__}

    @property
    def bottom(self) -> str:
        return self.moving[0] if self.moving else ""

    @property
    def replaying(self) -> bool:
        return self.stage in REPLAYING

    def line(self) -> str:
        """What every gsx command says while this file exists.

        One sentence for the state and one for the way out of it, because the
        way out differs: a stopped replay is finished or undone, a finished one
        is published or undone. Named rather than counted -- the branches are
        the fact the operator has to hold in their head.
        """
        what = f"a move of {' '.join(self.moving)} onto {self.target}"
        if self.replaying:
            return (
                f"{what} is stopped in the {self.stage}: `tdd gsx move --continue` "
                "to finish it, `tdd gsx move --abort` to put every branch and both "
                "stacks back"
            )
        return (
            f"{what} is done here and not published: `tdd gsx submit --move` "
            "completes it, `tdd gsx move --abort` puts every branch and both stacks "
            "back. No other move can start until one of those"
        )


def state_path(runner: gh.Runner):
    return gh.git_dir(runner) / STATE_FILE


def load(runner: gh.Runner) -> Session | None:
    """The move in progress, or None. A file that cannot be read is fatal: it
    is the only record of how to put things back."""
    path = state_path(runner)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ToolError(
            f"cannot read the move in progress ({path}): {error} -- it records how to "
            "undo the move, so it is worth repairing rather than deleting"
        ) from error
    payload.pop("version", None)
    try:
        return Session(**payload)
    except TypeError as error:
        raise ToolError(
            f"{path} is not a move this gsx understands: {error}"
        ) from error


def save(runner: gh.Runner, session: Session) -> None:
    """A temporary file and one rename, so an interrupted write cannot leave
    half a record of how to undo a move."""
    if runner.dry_run:
        runner.out.debug(f"[dry-run] write {state_path(runner)}")
        return
    path = state_path(runner)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(session.to_json(), indent=2), encoding="utf-8")
    temporary.replace(path)


def clear(runner: gh.Runner) -> None:
    if not runner.dry_run:
        state_path(runner).unlink(missing_ok=True)


def stopped(session: Session, why: str) -> Stopped:
    """A conflict, and the two commands out of it.

    Both are `gsx move`'s now: only it knows what the move still has to do
    after the rebase finishes, and only it can put gh-stack's tracking back.
    """
    return Stopped(
        f"{why}. Resolve it, `git add` the files (or commit them), then\n"
        "      tdd gsx move --continue   # finish the move\n"
        "      tdd gsx move --abort      # put every branch and both stacks back\n"
        "  nothing has been pushed, so GitHub still holds the old arrangement "
        "either way"
    )


def _continue_rebase(runner: gh.Runner, session: Session, out) -> None:
    """Hand the stopped rebase back to whoever owns it, and refuse to go on if
    it is still stopped afterwards."""
    if not gh.rebase_in_progress(runner):
        return
    if gh.rebase_stopped(runner):
        gh.stack_rebase_continue(runner)
    else:
        gh.rebase_continue(runner)
    if gh.rebase_in_progress(runner):
        raise stopped(session, "the rebase is still stopped")
    out.info("the rebase finished")


def resume(runner: gh.Runner, session: Session, out, steps_counter) -> dict:
    """`--continue`: pick the move up from the stage it stopped in."""
    _continue_rebase(runner, session, out)
    if session.stage == REBASE:
        _cascade(runner, session, steps_counter)
    return _finish(runner, session, steps_counter)


def unwind(runner: gh.Runner, session: Session, out) -> dict:
    """`--abort`: put the branches and both stacks back where they were.

    The tracking file goes back to the bytes the session snapshotted, which is
    the only complete undo of a rearrangement -- `unstack --local` and `init`
    cannot be run backwards. The branches go back to the tips recorded before
    the first replay. Nothing was pushed, so this is the whole of it.
    """
    if gh.rebase_in_progress(runner):
        if gh.rebase_stopped(runner):
            gh.stack_rebase_abort(runner)
        else:
            gh.rebase_abort(runner)
        out.info("aborted the rebase that was stopped")
    if session.started_on:
        try:
            gh.checkout(runner, session.started_on)
        except ToolError as error:
            out.warn(f"could not check out {session.started_on!r} ({error})")
    restored = []
    for branch, tip in (session.tips or {}).items():
        if not tip or gh.sha(runner, f"refs/heads/{branch}") == tip:
            continue
        try:
            if branch == session.started_on:
                gh.reset_hard(runner, tip)
            else:
                gh.set_branch(runner, branch, tip)
            restored.append(branch)
        except ToolError as error:
            out.warn(f"could not put {branch!r} back on {tip[:8]} ({error})")
    gh.write_state(runner, session.tracking)
    clear(runner)
    return {
        "restored": restored,
        "tracking": "restored" if session.tracking else "removed",
        "stacks": session.stacks,
        "on": session.started_on,
    }


def run(runner: gh.Runner, plan: Plan, out, steps_counter) -> dict:
    """Drive the move: rearrange the tracking, then replay what moved.

    The session is written before the first of those, so an `--abort` at any
    point afterwards can put both the branches and the tracking back. Every
    command here is gh-stack's or git's, and every one of them is local.
    """
    source, target = plan.source, plan.target
    shas = gh.head_shas(runner)
    # "If it is not there already": the original state is written once. A
    # second move cannot start while the file exists, so today this is only
    # belt and braces -- but the day one can, the *first* move's state is the
    # one an undo and a report both need.
    standing = load(runner)
    session = Session(
        stage=REBASE,
        started_on=source.current,
        moving=list(source.moving),
        target=target.head,
        onto=target.head,
        upstream=plan.upstream or plan.parent,
        # Every branch the move touches or declares, not just the ones it means
        # to rewrite: the tips are what `--abort` puts back, and a surprise is
        # exactly what an undo is for. Read from the refs (one for-each-ref for
        # the whole repository), never from gh-stack's recorded `head` (which
        # can be stale) and never from the remote -- a branch may hold commits
        # that were never pushed, and restoring `origin/<branch>` would throw
        # them away.
        tips={
            branch: shas.get(branch, "")
            for branch in dict.fromkeys(
                [*source.branches, *plan.dest_init, *plan.keep_init]
            )
        },
        tracking=gh.state_text(runner),
        remote=plan.remote,
        stacks=[number for number in (source.number, target.number) if number],
        before=(standing.before if standing and standing.before else None)
        or snapshot(gh.read_state(runner), shas),
    )
    save(runner, session)

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

    # The one branch whose parent changed is replayed off the branch it used to
    # sit on, with plain git. Not from the base `gh stack init` recorded: that
    # is the merge-base with the parent it was just DECLARED to have, which is
    # the trunk for a branch being put on the trunk -- replaying from there
    # brings along every commit of whatever it used to sit on. Measured: a
    # one-commit branch came out with 37.
    try:
        gh.rebase_onto(runner, session.onto, session.upstream, session.bottom)
    except ToolError as error:
        raise stopped(
            session, f"the replay of {session.bottom} onto {session.onto} stopped"
        ) from error
    steps_counter.step(f"replayed {session.bottom} onto {target.head}", stage="rebase")
    _cascade(runner, session, steps_counter)
    return _finish(runner, session, steps_counter)


def _cascade(runner: gh.Runner, session: Session, steps_counter) -> None:
    """The branches above the one that moved, which are gh-stack's to replay.

    Each still sits on the branch below it, whose recorded base is that
    branch's own old tip, so the cascade's ranges are right. `--upstack` from
    the bottom moved branch keeps it to exactly those: without it the cascade
    starts at the bottom of the whole stack.
    """
    if len(session.moving) < 2:
        return
    session.stage = CASCADE
    save(runner, session)
    gh.checkout(runner, session.bottom)
    try:
        gh.stack_rebase_upstack(runner)
    except ToolError as error:
        raise stopped(
            session, f"the replay of what sits above {session.bottom} stopped"
        ) from error
    steps_counter.step(
        f"replayed {len(session.moving) - 1} more onto {session.bottom}",
        stage="rebase-rest",
    )


def _finish(runner: gh.Runner, session: Session, steps_counter) -> dict:
    """Back where the operator started, and the session kept.

    Kept, not cleared: the move is not over until `gsx submit --move`
    publishes it, and until then this file is both the reason a second move is
    refused and the only record of how to put this one back. `submit --move`
    removes it, at the moment the dissolve makes an undo impossible.
    """
    gh.checkout(runner, session.started_on)
    steps_counter.step(f"back on {session.started_on}", stage="checkout")
    session.stage = PUBLISH
    save(runner, session)
    return {
        "moved": session.moving,
        "onto": session.target,
        "stacks": session.stacks,
        "pushed": False,
        "stage": PUBLISH,
        "next": "gsx submit --move",
    }


# ------------------------------------------------------------- the report
def _tag(number) -> str:
    """A stack's number, or the mark for one `gh stack init` gave none."""
    return f"#{number}" if number else "#-"


def _rows(stacks: list[dict], was: dict[str, str] | None) -> list[str]:
    """One indented block per stack, one line per branch.

    `was` turns the second block into a comparison rather than a second thing
    to read: a branch is unchanged, rewritten, or new to the tracking, and
    which of the three is the only reason to print two blocks at all.
    """
    lines = []
    for stack in stacks:
        lines.append(f"    {_tag(stack.get('number')):<7} {stack.get('trunk') or ''}")
        for branch in stack.get("branches") or []:
            sha = (branch.get("sha") or "")[:7] or "-------"
            pr = f"#{branch['pr']}" if branch.get("pr") else "  -"
            mark = ""
            if was is not None:
                before = was.get(branch["branch"])
                if before is None:
                    mark = "  (new here)"
                elif before != branch.get("sha"):
                    mark = f"  (was {before[:7]})"
            lines.append(f"            {branch['branch']:<12} {pr:<8} {sha}{mark}")
    return lines or ["    (none)"]


def _flat(stacks: list[dict]) -> dict[str, str]:
    return {
        branch["branch"]: branch.get("sha") or ""
        for stack in stacks
        for branch in stack.get("branches") or []
    }


def report(runner: gh.Runner, session: Session) -> tuple[str, dict]:
    """`--report`: the two states, and what is different between them.

    The state at the start comes out of the session -- nothing in the
    repository still holds it once the move has run -- and the state now is
    read fresh. Branches that were tracked and are not any more are named
    last: they are the easiest thing to lose track of, since no row of the
    second block can show them.
    """
    now = snapshot(gh.read_state(runner), gh.head_shas(runner))
    started, current = _flat(session.before), _flat(now)
    lines = [
        "Move report",
        f"  {session.line()}",
        "",
        f"  at the start   ({len(session.before)} stack(s))",
        *_rows(session.before, None),
        "",
        f"  now   (on {gh.current_branch(runner)}, stage {session.stage})",
        *_rows(now, started),
    ]
    gone = [branch for branch in started if branch not in current]
    if gone:
        lines += ["", f"  no longer tracked here: {' '.join(gone)}"]
    rewritten = [
        branch
        for branch, sha in current.items()
        if branch in started and started[branch] != sha
    ]
    return "\n".join(lines), {
        "stage": session.stage,
        "moving": session.moving,
        "onto": session.target,
        "before": session.before,
        "now": now,
        "rewritten": rewritten,
        "untracked": gone,
        "pushed": False,
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

        It does not say "a move is in progress", which is what an earlier
        version said and is a different thing: a move in progress is a move
        stopped half way, and it has its own session file and its own two
        commands out. This is what a *finished* local move leaves behind -- the
        two sides disagree and nothing is running -- so it leads with the
        disagreement and names the move only as the likely cause, since a
        rearrangement by hand reads exactly the same from here.
        """
        stacks = sorted(set(self.prs.values()))
        which = ", ".join(f"#{number}" for number in stacks)
        prs = ", ".join(f"#{pr}" for pr in sorted(self.prs))
        return (
            f"stack {which} on GitHub no longer holds its PRs ({prs}) the way this "
            "checkout does -- most likely a `gsx move` that has not been published; "
            "`gsx submit --move` dissolves it and relinks them from here, "
            "`gh stack checkout <n>` re-imports what GitHub has instead"
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
