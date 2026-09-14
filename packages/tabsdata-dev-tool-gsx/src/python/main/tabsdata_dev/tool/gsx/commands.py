#
# Copyright 2026 Tabsdata Inc.
#

"""The eight subcommands. Each returns (message, fields) for one ok event."""

from __future__ import annotations

import os
import re
import sys

from tabsdata_dev.common.core import cli, proc, render
from tabsdata_dev.common.core.errors import ToolError

from . import approve as approve_mod
from . import config as config_mod
from . import gh
from . import hooks as hooks_mod
from . import labels as labels_mod
from . import move as move_mod
from . import progress
from . import prune as prune_mod
from . import purge as purge_mod
from . import sync as sync_mod
from .args import Extras

TRAILER_RE = re.compile(r"^\s*(?:closes|fixes|resolves)\s+#(\d+)\s*$", re.IGNORECASE)


#: Any `Token: value` line -- what git itself calls a trailer, and what the
#: commit-msg hook adds: `Change-Id: I...`.
TRAILER_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:\s+\S")


def is_trailer(line: str) -> bool:
    return bool(TRAILER_RE.match(line) or TRAILER_LINE_RE.match(line.strip()))


def build_message(
    tag: str, summary: str, body: str | None, issue: int, trailers: str = ""
) -> str:
    """The commit message: `[tag] summary`, the body, `Closes #issue`, and then
    every other trailer handed in -- as a paragraph of its own.

    The others are what `update` found on the commit it is about to amend: the
    `Change-Id:` the commit-msg hook gave it, a `Signed-off-by:`. Dropping them
    would hand the hook a message without its Change-Id, and the amended commit
    would get a new one -- a new identity for the same change, the one thing
    the trailer exists to prevent. The closes-family line is regenerated rather
    than kept, so the issue number is always the one the branch belongs to.

    Its own paragraph, because `Closes #N` is not a trailer to git -- no `:`
    -- and a paragraph mixing it with `Change-Id:` is not a trailer block to
    `git interpret-trailers --parse`, which is how the hook looks for one. It
    then finds none and adds a second: measured in the sandbox, two Change-Ids
    on one amended commit. Apart is how the hook lays it out itself.
    """
    kept = [
        line.strip()
        for line in trailers.splitlines()
        if line.strip() and not TRAILER_RE.match(line)
    ]
    parts = [f"[{tag}] {summary}"]
    if body:
        parts.append(body.strip())
    parts.append(f"Closes #{issue}")
    if kept:
        parts.append("\n".join(kept))
    return "\n\n".join(parts) + "\n"


def split_message(message: str) -> tuple[str, str, str]:
    """A commit message as (subject, body, trailers).

    The trailers are the last paragraph, when every line of it is one -- git's
    own notion, near enough -- so a body whose paragraph happens to end in
    `Note: ...` stays a body. Consecutive all-trailer paragraphs are taken
    together, which is the shape an earlier gsx wrote.
    """
    lines = message.rstrip("\n").split("\n")
    subject = lines[0] if lines else ""
    rest = lines[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    trailers: list[str] = []
    while rest:
        while rest and not rest[-1].strip():
            rest.pop()
        start = len(rest)
        while start > 0 and rest[start - 1].strip():
            start -= 1
        paragraph = rest[start:]
        if not paragraph or not all(is_trailer(line) for line in paragraph):
            break
        trailers = [line.strip() for line in paragraph] + trailers
        del rest[start:]
    return subject, "\n".join(rest).strip(), "\n".join(trailers)


def read_body(value: str | None) -> str | None:
    """`-` reads stdin; anything else is verbatim."""
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read().strip() or None
    return value.strip() or None


def _pr_lines(snapshot: list[dict]) -> str:
    return "\n".join(
        f"  pr      #{pull['number']}  {pull['branch']}" for pull in snapshot
    )


# ------------------------------------------------------------------ create
def create(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """A GitHub issue, a stack branch and a commit. Nothing is pushed."""
    summary = (args.summary or "").strip()
    if not summary:
        raise ToolError("--summary/-s is required")
    body = read_body(args.message)

    gh.require_tools(runner)
    gh.require_repo(runner)

    changes = gh.pending_paths(runner, args.paths)
    if not changes:
        where = f" under {', '.join(args.paths)}" if args.paths else ""
        raise ToolError(f"nothing to commit{where}")

    name = gh.repo_name(runner)
    tag_prefix = gh.repo_postfix(name)

    out.info(f"creating a GitHub issue in {name}")
    issue_argv = ["gh", "issue", "create", "--title", summary, "--body", body or ""]
    issue_argv.extend(extras.passthrough.get("i", []))
    issue_url = runner.run(
        issue_argv, dry_value=f"https://github.com/OWNER/{name}/issues/0"
    )
    issue_url = issue_url.splitlines()[-1].strip() if issue_url else ""
    matched = re.search(r"/issues/(\d+)", issue_url)
    if not matched:
        raise ToolError(
            f"could not read the issue number from gh output: {issue_url!r}"
        )
    issue = int(matched.group(1))
    out.info(f"created issue #{issue}: {issue_url}")

    branch = f"{tag_prefix}-{issue}"
    message = build_message(branch, summary, body, issue)
    try:
        out.info(f"staging {len(changes)} change(s)")
        if args.paths:
            runner.run(["git", "add", "--", *args.paths])
        else:
            runner.run(["git", "add", "--all"])
        stacked = gh.in_stack(runner)
        # `gh stack add BRANCH` with no flags creates and checks out the branch
        # without committing and leaves the index alone, which is what makes a
        # subset commit (git add PATHS -> stack add -> git commit) one path.
        verb = "add" if stacked else "init"
        out.info(f"{'adding to' if stacked else 'initializing'} the stack as {branch}")
        runner.run(
            ["gh", "stack", verb, branch, *extras.passthrough.get("s", [])],
            capture=False,
        )
        out.info("committing")
        runner.run(["git", "commit", "--file", "-"], stdin_text=message)
    except ToolError as error:
        raise ToolError(
            f"{error}. Issue #{issue} was already created ({issue_url}); close it, "
            "or re-run after fixing and reuse it manually"
        ) from error

    return (
        f"created issue #{issue} and stack branch {branch}\n"
        f"  issue   #{issue}  {issue_url}\n"
        f"  branch  {branch}\n"
        f"  commit  [{branch}] {summary}\n"
        "  not pushed yet: use `tdd gsx submit` to push the stack and create the PR",
        {"issue": issue, "issue_url": issue_url, "branch": branch, "summary": summary},
    )


# ------------------------------------------------------------------ update
def update(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Reword the issue, the commit, and the PR that reads from it."""
    summary = args.summary.strip() if args.summary else None
    body = read_body(args.message)
    if summary is None and body is None:
        raise ToolError("give --summary/-s, --message/-m, or both")

    gh.require_tools(runner)
    branch = gh.current_branch(runner)
    old_subject, old_body, old_trailers = split_message(
        runner.run(["git", "log", "-1", "--format=%B"])
    )

    issue: int | None = None
    for line in old_trailers.splitlines():
        found = TRAILER_RE.match(line)
        if found:
            issue = int(found.group(1))
    if issue is None:
        branch_match = re.fullmatch(r"[A-Z0-9]+-(\d+)", branch)
        if branch_match:
            issue = int(branch_match.group(1))
    if issue is None:
        raise ToolError(
            f"cannot tell which issue branch {branch!r} belongs to: no `Closes #N` "
            "trailer on HEAD and the branch is not named <PREFIX>-<NUMBER>"
        )

    tag_match = re.match(r"^\[([^\]]+)\]\s*(.*)$", old_subject)
    tag = tag_match.group(1) if tag_match else branch
    new_summary = (
        summary
        if summary is not None
        else (tag_match.group(2) if tag_match else old_subject)
    )
    new_body = body if body is not None else (old_body or None)
    new_message = build_message(tag, new_summary, new_body, issue, old_trailers)

    out.info(f"updating issue #{issue}")
    issue_argv = ["gh", "issue", "edit", str(issue)]
    if summary is not None:
        issue_argv.extend(["--title", new_summary])
    if body is not None:
        issue_argv.extend(["--body", body])
    issue_argv.extend(extras.passthrough.get("i", []))
    if len(issue_argv) > 4:
        runner.run(issue_argv)
    else:
        out.warn("nothing to change on the issue; skipped")

    out.info("amending the commit (the PR takes its text from here)")
    runner.run(["git", "commit", "--amend", "--file", "-"], stdin_text=new_message)

    # `gh stack submit` force-pushes an amended commit but only ever sets a
    # PR's title and body at creation, so an existing PR is edited here or it
    # keeps the pre-amend wording forever.
    pr = gh.current_pr(runner)
    if pr is not None:
        out.info(f"updating PR #{pr} to match the commit")
        pr_body = "\n\n".join(part for part in (new_body, f"Closes #{issue}") if part)
        footer = gh.pr_body_footer(runner, pr)
        if footer:
            pr_body = f"{pr_body}\n\n{footer}"
        runner.run(
            [
                "gh",
                "pr",
                "edit",
                str(pr),
                "--title",
                f"[{tag}] {new_summary}",
                "--body",
                pr_body,
                *extras.passthrough.get("e", []),
            ]
        )

    return (
        f"updated issue #{issue}, the commit on {branch}"
        + (f" and PR #{pr}" if pr is not None else "")
        + f"\n  subject  [{tag}] {new_summary}\n"
        "  the commit was rewritten: run `tdd gsx submit` to force-push it, and "
        "`gh stack sync` if branches sit above this one",
        {"issue": issue, "branch": branch, "pr": pr, "summary": new_summary},
    )


# ---------------------------------------------------------------- checkout
#: A checkout target that names a pull request: `#42`, GitHub's own notation.
CHECKOUT_PR_RE = re.compile(r"#(\d+)")


def parse_checkout_target(target: str) -> tuple[str, str]:
    """``("pr", "42")`` for ``#42``, ``("branch", "GCS-15")`` for a name.

    `gh stack checkout` takes four shapes and resolves a bare number by trying
    it as a stack number, then a locally tracked PR, then a PR it discovers on
    GitHub, and only then a branch. So `15` means whichever of those matches
    first, and which one that is depends on what stacks happen to exist when it
    runs -- the answer can change under a target that did not. gsx accepts the
    two shapes a person actually types and makes the number say what it counts:
    `#42` is the pull request, anything else is a branch name.
    """
    text = target.strip()
    if not text:
        raise ToolError(
            "checkout needs a branch name or #<PR>; omit the target for the picker"
        )
    matched = CHECKOUT_PR_RE.fullmatch(text)
    if matched:
        return "pr", matched.group(1)
    if text.startswith("#"):
        raise ToolError(f"{text!r} is not a pull request: #N takes digits, as in #42")
    if "://" in text:
        tail = text.rstrip("/").rsplit("/", 1)[-1]
        hint = f"#{tail}" if tail.isdigit() else "#<PR>"
        raise ToolError(
            f"a PR URL is not a checkout target: write {hint} for the pull "
            "request, or the branch name"
        )
    if text.isdigit():
        raise ToolError(
            f"{text!r} is ambiguous -- gh would try it as a stack number, then a "
            f"pull request, then a branch: write #{text} for pull request {text}, "
            "or give the branch name"
        )
    return "branch", text


def _stackless(runner: gh.Runner, out, number: int) -> bool:
    """Whether GitHub really has no open stack holding this PR.

    Asked only after a stack checkout has failed, and asked of the **listing**
    rather than of the error text. gh says "✗ PR #486 is not part of a stack on
    GitHub" (exit 2), but that goes to the terminal and not into the exception
    -- the call is `capture=False` so gh's own progress stays visible -- and a
    message is a worse thing to depend on than a fact anyway. Any other failure
    (no network, no auth, a stack this checkout cannot reach) has to keep
    failing, because taking the branch alone would leave a one-branch stack
    that misrepresents GitHub. A listing that cannot be read therefore answers
    "no": the original failure is the honest one to report.
    """
    try:
        listing = gh.stacks(runner)
    except ToolError as error:
        out.debug(f"could not list the stacks on GitHub ({error})")
        return False
    return not any(
        stack.get("open")
        and any(
            pull.get("number") == number for pull in stack.get("pull_requests") or []
        )
        for stack in listing
    )


def _checkout_alone(runner: gh.Runner, out, number: int, branch: str) -> None:
    """A PR that is in no stack: the branch on its own, tracked as one here.

    **This is the asymmetry gsx has to absorb.** A stack on GitHub needs two
    PRs, so a single-branch stack submits as a PR and no stack -- while every
    `gh stack checkout` path is stack-shaped and answers "PR #486 is not part
    of a stack on GitHub". The branch is then reachable only with plain git,
    which is what `gh pr checkout` does.

    A stack of one IS legal locally, though: `gh stack init --base main
    UI-485` adopts it and finds its PR ("Found PRs for 1 of 1 branch"), which
    is the same state `gsx create` leaves before a second branch exists. So
    the checkout ends the way a stacked one does -- on the branch, with the
    stack tracked here -- and `gsx stack`, `gsx create` on top and `gsx
    submit` all behave from there. Without that last step this would leave a
    branch gh-stack has never heard of, which is the asymmetry moved rather
    than absorbed.
    """
    out.info(
        f"PR #{number} is in no stack on GitHub -- a stack needs two PRs; "
        f"checking {branch} out on its own"
    )
    if gh.sha(runner, f"refs/heads/{branch}"):
        gh.checkout(runner, branch)
    else:
        gh.pr_checkout(runner, number)
    if move_mod.stack_of(gh.read_state(runner), branch) is None:
        gh.stack_init(runner, [branch], base=gh.default_branch(runner))
        out.info(f"tracked {branch} here as the stack of one it is")


def _checkout_by_pr(runner: gh.Runner, branch: str, extra: list[str], out) -> None:
    """Check out a branch this checkout does not track, through its PR.

    A branch gh-stack has never heard of is reachable only as a pull request --
    that is what makes the stack come down with it -- and a branch with no PR
    at all is not a stack branch, so it is git's business rather than this
    command's, and saying so is more use than a second failure.
    """
    pulls = gh.branch_prs(runner, branch)
    number = (pulls[0] if pulls else {}).get("number")
    if not number:
        raise ToolError(
            f"{branch!r} is not in a stack tracked here and gh knows no PR for it; "
            f"`git switch {branch}` if the branch itself is what you want"
        )
    state = (pulls[0].get("state") or "").upper()
    out.info(
        f"{branch} is not in a stack tracked here; pulling it down by PR #{number}"
        + (f" ({state.lower()})" if state and state != "OPEN" else "")
    )
    try:
        runner.run(
            ["gh", "stack", "checkout", f"{gh.repo_url(runner)}/pull/{number}", *extra],
            capture=False,
        )
    except ToolError as error:
        if not _stackless(runner, out, int(number)):
            raise
        out.debug(str(error))
        _checkout_alone(runner, out, int(number), branch)


def stale_tracking(state: dict, target: dict) -> list[dict]:
    """The locally tracked stacks that stand in the way of adopting `target`.

    A local stack is in the way when it tracks any of the target's branches
    and is not the target itself -- the state every other clone is left in by
    a `gsx move`, where the branches now live in a stack of another number, or
    of no number at all after a rebuild. gh-stack's own `checkout` meets that
    by prompting, and one of the three things it offers is to **dissolve the
    stack on GitHub**, which is the last thing an adopting clone means to do.
    So gsx decides it beforehand and never lets the prompt happen.

    "Is the target itself" is judged on the target's OPEN branches in order: a
    tracked stack keeps every branch it ever had, so its merged ones are not a
    difference worth dropping the tracking over.
    """
    wanted = [
        ((pull.get("head") or {}).get("ref"))
        for pull in target.get("pull_requests") or []
        if (pull.get("head") or {}).get("ref") and not _finished(pull)
    ]
    stale = []
    for stack in state.get("stacks") or []:
        names = [
            entry["branch"]
            for entry in stack.get("branches") or []
            if entry.get("branch")
        ]
        if not set(names) & set(wanted):
            continue
        if (
            stack.get("number") == target.get("number")
            and [name for name in names if name in wanted] == wanted
        ):
            continue
        stale.append({"number": stack.get("number"), "branches": names})
    return stale


def _target_stack(runner: gh.Runner, kind: str, value: str, listing: list[dict]):
    """The open stack the target names, or the one holding it."""
    live = [stack for stack in listing or [] if stack.get("open")]
    if kind == "stack":
        return next((s for s in live if str(s.get("number")) == str(value)), None)
    for stack in live:
        for pull in stack.get("pull_requests") or []:
            if kind == "pr" and str(pull.get("number")) == str(value):
                return stack
            if kind == "branch" and ((pull.get("head") or {}).get("ref")) == value:
                return stack
    return None


def _adopt(runner: gh.Runner, out, target: dict, stale: list[dict]) -> list[str]:
    """Drop the tracking that is in the way, then take the target's branches up
    to their remote copies.

    Lossless by construction, which is what makes `--force` a word about the
    *arrangement* rather than about anybody's commits: the by-hand recipe for
    this is `git branch -f <b> origin/<b>` per branch, which silently discards
    unpushed work, and this reconciles instead -- a branch with commits of its
    own is rebased onto its remote copy and keeps them.
    """
    # Numbered stacks first: `unstack <n> --local` names them directly, and
    # once they are gone a branch shared with an unnumbered one has a single
    # holder left, which is what "the active stack" then resolves to.
    for stack in sorted(stale, key=lambda s: s["number"] is None):
        number = stack["number"]
        if number is not None:
            runner.run(
                ["gh", "stack", "unstack", str(number), "--local"], capture=False
            )
            out.info(f"dropped the local tracking of stack #{number}", stack=number)
            continue
        # A stack with no number -- rebuilt by a move here, or one whose id
        # gh-stack cleared when GitHub answered 404 for it, which is what a
        # stale clone's `gh stack sync` leaves behind. `unstack` cannot name
        # it, but it can drop the ACTIVE stack, and standing on one of its
        # branches makes it that. Measured: bob's gh stack sync after alice's
        # published move left exactly this, and `gh stack checkout` then
        # refused with "local stack composition differs from remote".
        here = gh.current_branch(runner)
        standing = next(
            (b for b in stack["branches"] if gh.sha(runner, f"refs/heads/{b}")), None
        )
        if standing is None:
            out.warn(
                "a stack tracked here has no number and none of its branches "
                f"exist: {' '.join(stack['branches'][:4])}... -- left as it is"
            )
            continue
        gh.checkout(runner, standing)
        try:
            runner.run(["gh", "stack", "unstack", "--local"], capture=False)
        finally:
            if here and here != standing:
                gh.checkout(runner, here)
        out.info(
            "dropped the local tracking of an unnumbered stack: "
            + " ".join(stack["branches"][:6])
            + (" ..." if len(stack["branches"]) > 6 else ""),
            stack=None,
        )
    return [
        ((pull.get("head") or {}).get("ref"))
        for pull in target.get("pull_requests") or []
        if (pull.get("head") or {}).get("ref") and not _finished(pull)
    ]


def _restructured(stale: list[dict], target: dict) -> str:
    """The refusal, which has to say what is in the way and what -f will do."""
    rows = "\n".join(
        f"  #{stack['number'] if stack['number'] else '-'}   "
        + " ".join(stack["branches"][:8])
        + (" ..." if len(stack["branches"]) > 8 else "")
        for stack in stale
    )
    return (
        f"stack #{target.get('number')} has been restructured since this checkout "
        "last saw it: its branches are tracked here under "
        + ", ".join(f"#{s['number'] if s['number'] else '-'}" for s in stale)
        + ", which GitHub no longer has that way.\n"
        + rows
        + "\n  `tdd gsx checkout --adopt` replaces that tracking with what GitHub "
        "has. No commit of yours is lost: a branch with work of its own is "
        "rebased onto its remote copy, never reset to it"
    )


def checkout(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """`gh stack checkout` by branch name or `#<PR>`, and nothing else."""
    # Parsed before anything is asked of gh: a target gsx will not accept is a
    # usage error, and it costs no child process to say so.
    kind, value = parse_checkout_target(args.target) if args.target else ("", "")

    gh.require_tools(runner)
    # One listing answers two questions: whether `#N` is a stack rather than a
    # PR, and whether adopting the target means dropping tracking this clone
    # still holds. Unreachable, and both fall back to what gh alone would do --
    # a repository whose stacks API is down can still be worked in.
    listing = []
    try:
        listing = gh.stacks(runner)
    except ToolError as error:
        out.warn(
            f"could not list the stacks on GitHub ({error}); checking out without "
            "the restructure check"
        )
    if kind == "pr" and any(
        stack.get("open") and str(stack.get("number")) == value for stack in listing
    ):
        # GitHub numbers stacks and PRs from ONE counter, so a number is a
        # stack or a PR and never both -- verified against two repositories.
        # That is what lets `#N` mean either without bringing back the
        # ambiguity a bare `42` was refused for: the answer is a fact about
        # the repository, not a guess about what the typist meant.
        kind = "stack"
    target = _target_stack(runner, kind, value, listing)
    stale = stale_tracking(gh.read_state(runner), target) if target else []
    if stale and not args.adopt:
        raise ToolError(_restructured(stale, target))
    wanted: list[str] = []
    if stale:
        wanted = _adopt(runner, out, target, stale)

    argv = ["gh", "stack", "checkout"]
    if kind == "stack":
        argv.append(str(value))
        what = f"stack #{value}"
    elif kind == "pr":
        # The URL is the one shape gh cannot read as a stack number, so this is
        # what makes `#42` mean pull request 42 and not stack 42.
        argv.append(f"{gh.repo_url(runner)}/pull/{value}")
        what = f"PR #{value}"
    elif kind == "branch":
        argv.append(value)
        what = f"branch {value}"
    else:
        what = "a stack (interactive picker)"
    out.info(f"checking out {what}")
    extra = extras.passthrough.get("c", [])
    argv.extend(extra)
    try:
        runner.run(argv, capture=False)
    except ToolError as error:
        if kind == "pr" and _stackless(runner, out, int(value)):
            # The same asymmetry reached by its other name: `#486` resolves to
            # the PR, and the PR is in no stack. A PR gh cannot name a branch
            # for is a different problem -- most likely it does not exist -- so
            # that keeps the failure it already had.
            alone = gh.pr_branch(runner, int(value))
            if alone:
                out.debug(str(error))
                _checkout_alone(runner, out, int(value), alone)
                return _where(runner)
        if kind != "branch":
            raise
        # `gh stack checkout BRANCH` only resolves a branch of a stack this
        # checkout already tracks; for any other branch it exits 2 and says to
        # use the PR number instead. So take its advice: one lookup turns the
        # branch into its PR, and a PR URL pulls the whole stack down. The
        # failing call is left first because the tracked case is the common one
        # and costs nothing extra.
        _checkout_by_pr(runner, value, extra, out)
    if wanted:
        # After gh has the branches -- it creates the missing ones and adopts
        # the ones already here AS THEY ARE, which for an adopting clone means
        # the old contents. This is the step that makes them current, and the
        # step the by-hand recipe does with `git branch -f`, losing work.
        remote = gh.stack_remote(runner)
        gh.fetch(runner, remote)
        here = gh.current_branch(runner)
        live = [name for name in wanted if gh.sha(runner, f"refs/heads/{name}")]
        sync_mod.reconcile(runner, live, remote, out)
        if gh.current_branch(runner) != here:
            gh.checkout(runner, here)
    return _where(runner)


def _where(runner: gh.Runner) -> tuple[str, dict]:
    """Where a checkout ended up, which is the whole of what it reports."""
    if runner.dry_run:
        # No `dry_run` field: the shared runner puts one on every ok event, and
        # returning it here made `checkout --dry-run` raise TypeError from
        # `ok()` getting the keyword twice.
        return ("checked out nothing (dry run)", {})
    branch = gh.current_branch(runner)
    pr = gh.current_pr(runner)
    return (
        f"on {branch}" + (f", PR #{pr}" if pr is not None else ""),
        {"branch": branch, "pr": pr},
    )


# ------------------------------------------------------------------ submit
def _moved_locally(runner: gh.Runner, out) -> move_mod.Pending:
    """What a local `gsx move` has done that GitHub has not been told about.

    Read rather than remembered: the tracking file and GitHub's own listing
    disagree in one particular way after a move -- a stack whose PRs now sit in
    two local stacks -- and that is a fact about the two sides, not a note this
    tool left itself. A listing that cannot be had answers "nothing known",
    since a submit should not be blocked by an unreachable API.
    """
    try:
        listing = gh.stacks(runner)
    except ToolError as error:
        out.debug(f"could not list the stacks on GitHub ({error})")
        return move_mod.Pending()
    return move_mod.pending(gh.read_state(runner), listing)


def _publish_move(args, out, runner: gh.Runner, moved: move_mod.Pending, steps) -> None:
    """The one irreversible part of a move: take the old stacks apart on GitHub.

    It has to come first and it has to be a dissolve. The API cannot remove a
    PR from a stack (unstack takes no body) and `gh stack link` rejects a PR
    that belongs to another one, so the moved PRs cannot join their new stack
    while the old one still holds them. The target keeps its number -- link
    appends -- so only the stack a move took apart is dissolved.

    Verified before anything is pushed: GitHub leaves a queued or auto-merging
    PR stacked and then keeps the whole stack, and `move` refuses those, but
    the state can change in between.
    """
    for number in moved.dissolve:
        gh.stack_unstack(runner, number)
        steps.step(f"dissolved stack #{number} on GitHub", stage="unstack")
    if runner.dry_run:
        return
    still = {
        int(stack["number"])
        for stack in gh.stacks(runner)
        if stack.get("open") and stack.get("number")
    }
    left = [number for number in moved.dissolve if number in still]
    if left:
        raise ToolError(
            "GitHub kept stack(s) "
            + ", ".join(f"#{number}" for number in left)
            + " -- a queued or auto-merging PR is left stacked and then the whole "
            "stack is kept. Nothing has been pushed; sort that PR out and retry"
        )


def _stack_here(runner: gh.Runner) -> tuple[str, list[str], dict[str, int]]:
    """The trunk, branches and PR numbers of the stack being stood in."""
    state = gh.read_state(runner)
    stack = move_mod.stack_of(state, gh.current_branch(runner))
    if not stack:
        return "", [], {}
    trunk = ((stack.get("trunk") or {}).get("branch")) or "main"
    live = [
        entry
        for entry in stack.get("branches") or []
        if entry.get("branch") and gh.sha(runner, f"refs/heads/{entry['branch']}")
    ]
    return (
        trunk,
        [entry["branch"] for entry in live],
        {
            entry["branch"]: (entry.get("pullRequest") or {}).get("number")
            for entry in live
            if (entry.get("pullRequest") or {}).get("number")
        },
    )


def _require_reconciled(runner: gh.Runner, out, moving: bool = False) -> None:
    """Refuse to publish a move over a branch the remote is ahead of.

    The one check that turns "sync before you publish" from a thing the
    operator remembers into a thing the tool enforces. It matters here more
    than anywhere else: `submit --move` dissolves a stack on GitHub before it
    pushes, so a push refused by the guard -- or worse, one that goes through
    and drops a teammate's commit -- happens with the old arrangement already
    gone.
    """
    trunk, branches, prs = _stack_here(runner)
    if not branches:
        return
    remote = gh.stack_remote(runner)
    gh.fetch(runner, remote)
    bases, landed = _pr_info(runner, prs, out)
    branches = [b for b in branches if b not in landed]
    behind = sync_mod.unreconciled(runner, branches, remote, bases, trunk)
    if behind:
        raise ToolError(
            f"{remote} has commits these branch(es) do not: "
            + ", ".join(behind)
            + " -- `tdd gsx sync` reconciles them first"
            + (
                ". Publishing a move dissolves the old stack before it pushes, "
                "so this has to be settled beforehand"
                if moving
                else ""
            )
        )


def _preflight_guard(runner: gh.Runner, out, moved: move_mod.Pending) -> None:
    """Ask the installed pre-push guard, before the dissolve, whether it would
    let every branch this publish is about to push through.

    `submit --move` dissolves the old stack on GitHub and THEN pushes, so a
    push the guard refuses leaves the arrangement dissolved on one side and
    unpublished on the other -- measured three times in one afternoon, on
    three different moves, before this existed. The guard's own script is what
    is asked, fed the same lines git would feed it (local sha, remote sha per
    branch), so the two cannot disagree about what would happen. What is pushed
    is the stack being stood in and, by `_submit_the_rest`, every other local
    stack a dissolved one left behind.
    """
    found = hooks_mod.state(runner)
    if not found["protected"]:
        return  # `_require_guard` refused already; this is belt and braces
    hook = hooks_mod.target(runner)
    here = gh.current_branch(runner)
    _, mine, _ = _stack_here(runner)
    pushing = list(mine)
    for branches in moved.stacks:
        if branches and here not in branches:
            pushing.extend(b for b in branches if b not in pushing)
    remote = gh.stack_remote(runner)
    lines = []
    for branch in pushing:
        local = gh.sha(runner, f"refs/heads/{branch}")
        tracked = gh.sha(runner, f"refs/remotes/{remote}/{branch}")
        if local and tracked:
            lines.append(f"refs/heads/{branch} {local} refs/heads/{branch} {tracked}")
    if not lines:
        return
    url = (
        runner.run(["git", "remote", "get-url", remote], check=False).strip() or remote
    )
    out.debug(f"$ sh {hook} {remote} {url}  # pre-flight, {len(lines)} branch(es)")
    result = proc.run(
        ["sh", str(hook), remote, url],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    if result.returncode != 0:
        raise ToolError(
            "the pre-push guard would refuse this publish, so nothing has been "
            "dissolved:\n" + (result.stderr or result.stdout).strip()
        )


def _sync_before_submit(runner: gh.Runner, out) -> None:
    """What `--sync` means now: gsx's own reconcile and restack, no push.

    The push is the submit's own, a moment later, so a second one here would
    be the same branches twice -- and `gh stack submit` is what fixes the PR
    bases and the stack object, which this deliberately never touches.
    """
    trunk, branches, prs = _stack_here(runner)
    if not branches:
        out.warn("--sync: not in a tracked stack, nothing to reconcile")
        return
    remote = gh.stack_remote(runner)
    gh.fetch(runner, remote)
    current = gh.current_branch(runner)
    _forward_trunk(runner, trunk, remote, current, out)
    bases, landed = _pr_info(runner, prs, out)
    branches = [b for b in branches if b not in landed]
    before = sync_mod.tips(runner, branches)
    sync_mod.reconcile(runner, branches, remote, out, bases, trunk)
    after = sync_mod.tips(runner, branches)
    sync_mod.restack(runner, branches, trunk, out, before, after)
    if gh.current_branch(runner) != current:
        gh.checkout(runner, current)


def submit(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Push the stack, open its PRs, then apply the label/reviewer ops."""
    gh.require_tools(runner)
    session = move_mod.load(runner)
    if session is not None and session.replaying:
        # Half a rearrangement is not a thing to publish, and the branches are
        # mid-rebase: whatever this pushed would be neither arrangement.
        raise ToolError(f"{session.line()} -- publish it after that")
    if session is not None and not args.move:
        raise ToolError(session.line())
    moved = _moved_locally(runner, out)
    if moved and not args.move:
        raise ToolError(f"{moved.line()} -- or `--move` to publish it now")
    if args.move and not moved:
        out.warn(
            "--move was passed but nothing has moved here that GitHub does not "
            "already have; submitting the stack as it is"
        )
    repo = labels_mod.Repo(runner, out)

    # How many PRs there will be is not known until they have been pushed --
    # the first submit of a stack opens them -- so this run counts [n] and
    # never a denominator it would have to guess. The push and the sync are
    # units of it too: they are the slowest thing gsx does.
    steps = progress.Counter(out)

    if args.sync or extras.passthrough.get("s"):
        if extras.passthrough.get("s"):
            # `--s:` names flags of `gh stack sync`, which this no longer runs.
            raise ToolError(
                "`--s:` forwards flags to `gh stack sync`, which gsx does not "
                "run any more: `tdd gsx sync` reconciles each branch with its "
                "own remote copy first, and takes no gh-stack flags"
            )
        _sync_before_submit(runner, out)
        steps.step("synced the stack with the remote", stage="sync")
    # Every publish, not only a move's: sync is local now, and a submit that
    # pushed over a branch the remote had moved on from is the thing the whole
    # design exists to prevent. Refused with the command that fixes it.
    _require_reconciled(runner, out, moving=bool(args.move and moved))

    if args.move and moved:
        _preflight_guard(runner, out, moved)
        out.warn(
            "publishing a move: stack(s) "
            + ", ".join(f"#{number}" for number in moved.dissolve)
            + " are dissolved on GitHub and their PRs relinked from what is tracked "
            "here. This is the one step that cannot be undone."
        )
        _publish_move(args, out, runner, moved, steps)

    if args.move and session is not None:
        # The dissolve has happened, so there is nothing to go back to: an
        # `--abort` from here would reset local branches while GitHub holds the
        # new arrangement. The session goes at the moment it stops being an
        # undo and starts being a trap -- and with it the guard, so the next
        # move may start.
        move_mod.clear(runner)
        out.info(
            f"{len(session.moves) or 1} move(s) published; the session file is gone"
        )

    argv = ["gh", "stack", "submit", "--auto"]
    if not args.draft:
        argv.append("--open")
    argv.extend(extras.passthrough.get("p", []))
    runner.run(argv, capture=False)
    steps.step("pushed the stack and created or refreshed its PRs", stage="push")
    _grow_stack(runner, out, steps)

    changed, failures = 0, []
    ops = labels_mod.with_defaults(repo, extras.lr_ops, args.no_defaults)
    if ops or extras.passthrough.get("e"):
        out.info(f"applying {len(ops)} label/reviewer op(s)")
        changed, failures = labels_mod.apply(
            runner, repo, ops, extras.passthrough.get("e", []), out, steps
        )
    if args.move and moved:
        _submit_the_rest(runner, out, args, moved, steps)
    snapshot = gh.stack_pr_snapshot(runner)
    if failures:
        raise ToolError(
            f"pushed, but {len(failures)} PR(s) could not be updated: "
            + "; ".join(failures)
        )
    return (
        f"pushed the stack; {changed} PR(s) updated\n" + _pr_lines(snapshot),
        {"updated": changed, "prs": [pull["number"] for pull in snapshot]},
    )


def _grow_stack(runner: gh.Runner, out, steps) -> None:
    """Add to the stack on GitHub any open PR of the local stack it is missing.

    `gh stack submit` grows a stack only when the local stack lists every PR
    the GitHub one has -- and a GitHub stack keeps its merged PRs for ever,
    while a stack re-declared here after a move carries only what is open. So
    a move onto a stack with landed history pushed the branches and fixed the
    PR base, and then stopped short of the stack object with "A stack on
    GitHub already contains #454, which is not in your local stack" --
    measured. The API accepts the missing PRs directly, provided each one's
    base is the previous one's head, which the submit has just made true.
    Non-fatal: the push is done, and a warning naming the endpoint is better
    than an error saying the submit failed.
    """
    trunk, branches, prs = _stack_here(runner)
    if not prs:
        return
    _, landed = _pr_info(runner, prs, out)
    wanted = [prs[b] for b in branches if b in prs and b not in landed]
    if len(wanted) < 2:
        return  # a stack on GitHub needs two PRs; one is a PR and no stack
    try:
        listing = gh.stacks(runner)
    except ToolError as error:
        out.debug(f"could not list the stacks on GitHub ({error})")
        return
    live = {
        int(st["number"]): st for st in listing if st.get("open") and st.get("number")
    }
    same = _same_stack(set(branches), live)
    if same is None:
        return  # submit created it, or there is nothing to grow
    holding = {
        int(p["number"]) for p in same.get("pull_requests") or [] if p.get("number")
    }
    missing = [n for n in wanted if n not in holding]
    if not missing:
        return
    number = same.get("number")
    slug = gh.repo_slug(runner)
    argv = ["gh", "api", "-X", "POST", f"repos/{slug}/stacks/{number}/add"]
    for n in missing:
        argv += ["-F", f"pull_requests[]={n}"]
    try:
        runner.run(argv)
        steps.step(
            f"added {', '.join(f'#{n}' for n in missing)} to stack #{number} on GitHub",
            stage="grow",
        )
    except ToolError as error:
        out.warn(
            f"stack #{number} on GitHub is missing {', '.join(f'#{n}' for n in missing)} "
            f"and could not be grown ({error}); by hand: {' '.join(argv)}"
        )


def _submit_the_rest(runner: gh.Runner, out, args, moved: move_mod.Pending, steps):
    """Submit the other local stacks a move left behind.

    Dissolving the old stack on GitHub takes its remainder down with it, so
    what stayed below has to be submitted too -- as a new stack, with a new
    number, because that is all the API can do. Non-fatal: the half the
    operator was standing in is published by then, and a warning naming the two
    commands is more honest than an error saying the submit failed.
    """
    here = gh.current_branch(runner)
    elsewhere = [
        branches for branches in moved.stacks if branches and here not in branches
    ]
    for branches in elsewhere:
        top = branches[-1]
        try:
            gh.stack_checkout(runner, top)
            argv = ["gh", "stack", "submit", "--auto"]
            if not args.draft:
                argv.append("--open")
            runner.run(argv, capture=False)
            steps.step(
                f"submitted what stays below: {' '.join(branches)}", stage="rest"
            )
        except ToolError as error:
            steps.failed(
                f"could not submit {' '.join(branches)} ({error}); by hand: "
                f"gh stack checkout {top} && gh stack submit --auto",
                stage="rest",
            )
    if not elsewhere:
        return  # nothing was checked out, so there is nowhere to come back from
    try:
        gh.stack_checkout(runner, here)
    except ToolError as error:
        out.warn(f"could not return to {here!r} ({error})")


# ------------------------------------------------------------------- apply
def apply(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """The label/reviewer engine alone: no push, only PRs that already exist."""
    gh.require_tools(runner)
    repo = labels_mod.Repo(runner, out)
    ops = labels_mod.with_defaults(repo, extras.lr_ops, args.no_defaults)
    if not ops and not extras.passthrough.get("e"):
        raise ToolError(
            "nothing to apply: give at least one --label:... or --reviewer:... op, "
            "or set default_labels/default_reviewers for this repository in "
            f"{config_mod.path()}"
        )

    snapshot = gh.stack_pr_snapshot(runner)
    missing = [
        branch.get("name")
        for branch in (gh.stack_state(runner) or {}).get("branches", [])
        if branch.get("name") not in {pull["branch"] for pull in snapshot}
    ]
    if missing:
        out.warn(
            "skipping branch(es) with no open PR -- apply only touches what is "
            f"already on GitHub: {', '.join(missing)}; run `tdd gsx submit` first"
        )

    out.info(f"applying {len(ops)} label/reviewer op(s)")
    changed, failures = labels_mod.apply(
        runner, repo, ops, extras.passthrough.get("e", []), out
    )
    if failures:
        raise ToolError(
            f"{len(failures)} PR(s) could not be updated: " + "; ".join(failures)
        )
    snapshot = gh.stack_pr_snapshot(runner)
    return (
        f"updated {changed} PR(s)\n" + _pr_lines(snapshot),
        {"updated": changed, "prs": [pull["number"] for pull in snapshot]},
    )


# ----------------------------------------------------------------- approve
def _stack_selection(runner: gh.Runner, args, out) -> list[dict]:
    """The PRs to approve: the ones named, or a slice of the stack.

    `--down-stack` is the current PR and the ones it sits on, down to main --
    the set that has to be approved for the current one to merge. The snapshot
    is ordered trunk-first, so that is everything up to and including it.
    """
    snapshot = gh.stack_pr_snapshot(runner)
    if args.pr:
        wanted = [
            int(number.strip().lstrip("#"))
            for number in ",".join(args.pr).split(",")
            if number.strip()
        ]
        by_number = {pull["number"]: pull for pull in snapshot}
        chosen = []
        for number in wanted:
            found = by_number.get(number)
            # A PR named outright need not be in this stack: approving one from
            # a review is exactly what --pr is for.
            chosen.append(found or {"number": number, "branch": "", "author": ""})
        return chosen
    if not snapshot:
        raise ToolError("no open PRs on this stack; name them with --pr instead")
    if args.stack:
        return snapshot
    branch = gh.current_branch(runner)
    for index, pull in enumerate(snapshot):
        if pull["branch"] == branch:
            return snapshot[: index + 1]
    raise ToolError(
        f"the current branch {branch!r} has no open PR in this stack; "
        "name the PRs with --pr, or use --stack"
    )


def approve(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Approve PRs as one or more people, each with their own review token."""
    names = [
        name.strip() for name in ",".join(args.approvers).split(",") if name.strip()
    ]
    if not names:
        raise ToolError("--approvers needs at least one name")
    if args.stack and args.down_stack:
        raise ToolError("--stack and --down-stack are exclusive")
    if args.pr and (args.stack or args.down_stack):
        raise ToolError("--pr names the PRs; --stack and --down-stack find them")
    if not args.pr and not args.stack and not args.down_stack:
        raise ToolError("say which PRs: --pr N,... , --down-stack or --stack")

    gh.require_tools(runner)
    repo = labels_mod.Repo(runner, out)
    settings = config_mod.read()["approve"]
    approvers = approve_mod.resolve(names, repo.aliases())
    pulls = _stack_selection(runner, args, out)
    out.info(
        f"approving {len(pulls)} PR(s) as "
        + ", ".join(a.name for a in approvers)
        + f": {', '.join('#' + str(p['number']) for p in pulls)}"
    )

    # Every approver reviews every PR, so the whole of the work is known here.
    steps = progress.Counter(out, total=len(approvers) * len(pulls))
    failures: list[str] = []
    approved = skipped = 0
    for approver in approvers:
        # One fetch per approver serves every PR of the run.
        pat = approve_mod.token(runner, approver, settings)
        for pull in pulls:
            outcome = approve_mod.approve(runner, repo.slug, pull, approver, pat, steps)
            if outcome == approve_mod.APPROVED:
                approved += 1
            elif outcome == approve_mod.SKIPPED:
                skipped += 1
            else:
                failures.append(outcome)
    if failures:
        raise ToolError(f"{len(failures)} approval(s) failed: " + "; ".join(failures))
    who = ", ".join(a.login for a in approvers)
    return (
        f"{approved} approval(s) as {who}"
        + (f", {skipped} skipped (their own PRs)" if skipped else "")
        + "\n"
        + _pr_lines([p for p in pulls if p.get("branch")]),
        {
            "approvers": [a.login for a in approvers],
            "prs": [p["number"] for p in pulls],
            "approved": approved,
            "skipped": skipped,
        },
    )


# ------------------------------------------------------------------- purge
def _purge_lines(verdicts: list[purge_mod.Verdict]) -> str:
    """The deleted branches, listed under the summary. The kept ones already
    said why on their own progress line, and re-listing them would bury the
    one thing that changed."""
    return "\n".join(
        f"  gone    {verdict.branch}  ({verdict.reason})"
        for verdict in verdicts
        if verdict.outcome == purge_mod.DELETED
    )


def purge(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Delete the local branches whose PR is merged or closed on GitHub.

    Needs git and gh but not gh-stack: a leftover branch is a leftover whether
    a stack put it there or not.
    """
    gh.require_binaries()
    gh.require_repo(runner)

    if not args.no_fetch:
        out.info("git fetch --prune")
        gh.fetch_prune(runner)

    trunk = gh.default_branch(runner)
    current = gh.current_branch(runner)
    branches = gh.local_branches(runner)
    candidates = purge_mod.candidates(branches, trunk)
    if not candidates:
        held = ", ".join(sorted(set(branches) - set(candidates))) or "none"
        return (
            f"nothing to purge: no local branch besides {held}",
            {"deleted": [], "kept": [], "examined": 0},
        )

    # One listing answers most branches; the rest are asked for one at a time.
    listing = gh.prs_by_branch(runner)
    out.info(
        f"checking {len(candidates)} branch(es) against the PRs of "
        f"{trunk or 'this repository'}"
    )

    steps = progress.Counter(out, total=len(candidates))
    verdicts: list[purge_mod.Verdict] = []
    failures: list[str] = []
    for branch in candidates:
        pulls = listing.get(branch) or gh.branch_prs(runner, branch)
        verdict = purge_mod.classify(
            branch,
            pulls,
            merged_only=args.merged_only,
            checked_out=branch == current,
        )
        if verdict.outcome == purge_mod.DELETED:
            try:
                gh.delete_branch(runner, branch)
            except ToolError as error:
                verdict = purge_mod.Verdict(
                    branch, purge_mod.FAILED, str(error), verdict.pr, verdict.state
                )
        verdicts.append(verdict)
        if verdict.outcome == purge_mod.FAILED:
            failures.append(f"{branch}: {verdict.reason}")
            steps.failed(verdict.line(), branch=branch, outcome=verdict.outcome)
        else:
            steps.step(
                verdict.line(),
                branch=branch,
                outcome=verdict.outcome,
                pr=verdict.pr,
                state=verdict.state,
            )

    gone = [v.branch for v in verdicts if v.outcome == purge_mod.DELETED]
    kept = [v.branch for v in verdicts if v.outcome == purge_mod.KEPT]
    if failures:
        raise ToolError(
            f"{len(failures)} branch(es) could not be deleted: " + "; ".join(failures)
        )
    if not gone:
        # Not "none whose PR is merged or closed": a branch that is checked out
        # or spared by --merged-only has one and was kept anyway, and its own
        # line above already said which reason applied to it.
        return (
            f"nothing deleted: {len(candidates)} branch(es) examined, all kept",
            {"deleted": [], "kept": kept, "examined": len(candidates)},
        )
    return (
        f"deleted {len(gone)} branch(es), kept {len(kept)}\n" + _purge_lines(verdicts),
        {"deleted": gone, "kept": kept, "examined": len(candidates)},
    )


# ------------------------------------------------------------------- prune
def _prune_ready(runner: gh.Runner, out) -> None:
    """Everything that must be true before a stack is taken apart.

    An unpublished move is the one that matters and it is refused, not warned
    about: prune dissolves a stack on GitHub, and while a move is unpublished
    the two sides already disagree about which PRs live together -- publishing
    half of that by accident is exactly what `submit --move` exists to make
    deliberate. The rest are the same sessions `move` refuses to run into,
    because prune's last step is a `gh stack init` from the trunk and that
    needs a checkout.
    """
    gh.require_tools(runner)
    gh.require_repo(runner)
    session = move_mod.load(runner)
    if session is not None:
        raise ToolError(
            f"{session.line()} -- prune after that: it dissolves a stack on GitHub, "
            "and until the move is published the two sides disagree about which "
            "PRs live together"
        )
    stopped = gh.rebase_stopped(runner)
    if stopped:
        raise ToolError(
            f"a stack rebase is stopped on {stopped!r}: finish it with "
            "`gh stack rebase --continue`, or undo it with `gh stack rebase --abort`"
        )
    if gh.modify_in_progress(runner):
        raise ToolError("a `gh stack modify` is unfinished; finish or abort it first")
    if gh.dirty(runner):
        raise ToolError(
            "the working tree has uncommitted changes; commit or stash them first"
        )
    out.info("clean working tree, nothing else in progress")


def _relink(runner: gh.Runner, out, plan: prune_mod.Plan, steps) -> int | None:
    """Make the new stack on GitHub, and say which number it got.

    The number is read back from the listing rather than parsed out of what
    link printed: it is the one thing about the result the operator cannot
    predict, and the listing is the same source `gsx stack` answers from.
    """
    if not plan.links:
        out.warn(
            f"{len(plan.keep)} PR(s) left open, and a stack needs "
            f"{prune_mod.NEEDS}: #{plan.number} is dissolved and nothing is relinked"
        )
        return None
    gh.stack_link(runner, plan.prs)
    steps.step(f"linked {len(plan.prs)} open PR(s) into a new stack", stage="link")
    if runner.dry_run:
        return None
    try:
        for stack in gh.stacks(runner):
            names = {
                int(pull["number"])
                for pull in stack.get("pull_requests") or []
                if pull.get("number")
            }
            if stack.get("open") and set(plan.prs) <= names:
                return int(stack["number"])
    except ToolError as error:
        out.debug(f"could not read the new stack's number ({error})")
    return None


def _retrack(runner: gh.Runner, out, plan: prune_mod.Plan, steps, here: str) -> None:
    """Track what is left, here, as the stack it now is.

    Local only, and `gh stack init` adopts without rewriting a thing, so this
    costs no commits: it is the same rearrangement `move` does, for the same
    reason -- gh-stack's tracking file has to be told, and there is no command
    that edits it in place.
    """
    # Located by the branch the operator is standing on, not by what is kept:
    # a stack whose every PR has landed keeps nothing, and its local tracking
    # is exactly what should not be left behind.
    if move_mod.stack_of(gh.read_state(runner), here):
        gh.stack_unstack_local(runner)
        steps.step("forgot the old stack here", stage="untrack")
    if not plan.branches:
        out.warn("nothing is left to track here: every branch of it had landed")
        return
    gh.checkout(runner, plan.trunk)
    gh.stack_init(runner, plan.branches, base=plan.trunk)
    steps.step(f"tracked {' '.join(plan.branches)} here", stage="init")
    if here not in plan.branches:
        out.info(f"{here!r} is not in the pruned stack; leaving you on its top")
    gh.checkout(runner, here if here in plan.branches else plan.branches[-1])


def prune(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Dissolve the current stack on GitHub and relink only its open PRs.

    The one command besides `submit --move` that changes something on GitHub
    irreversibly, and the change is always the same: the stack number. Nothing
    is pushed, no PR number moves and no branch is rewritten.
    """
    _prune_ready(runner, out)
    current = gh.current_branch(runner)
    stack = move_mod.stack_of(gh.read_state(runner), current)
    if stack is None:
        raise ToolError(
            f"branch {current!r} is not in any stack tracked here; check out a "
            "branch of the stack to prune (`gh stack checkout <n>`)"
        )
    numbers = [
        (item.get("pullRequest") or {}).get("number")
        for item in stack.get("branches") or []
    ]
    states = _pr_states(runner, numbers)
    _refuse_stuck(states, [number for number in numbers if number])
    plan = prune_mod.build(stack, states)
    out.info(plan.text(), plan=True)
    if runner.dry_run:
        out.info("dry run: every check passed, nothing will be changed")
    else:
        cli.confirm(
            out,
            f"dissolve stack #{plan.number} on GitHub and relink "
            f"{len(plan.keep)} open PR(s)? #{plan.number} is lost either way",
            assume_yes=args.yes,
        )
    steps = progress.Counter(out, total=3)
    gh.stack_unstack(runner, plan.number)
    steps.step(f"dissolved stack #{plan.number} on GitHub", stage="unstack")
    made = _relink(runner, out, plan, steps)
    _retrack(runner, out, plan, steps, current)
    dropped = ", ".join(f"#{pr}" for _, pr in plan.drop)
    return (
        f"pruned stack #{plan.number}: "
        + (f"its open PRs are stack #{made} now" if made else "dissolved")
        + f"; {len(plan.drop)} merged or closed PR(s) dropped\n"
        + f"  dropped   {dropped}\n"
        + f"  kept      {' '.join(str(pr) for pr in plan.prs) or '(none)'}",
        {
            "was": plan.number,
            "stack": made,
            "kept": plan.prs,
            "dropped": [pr for _, pr in plan.drop],
            "branches": plan.branches,
        },
    )


# -------------------------------------------------------------------- move
def _move_ready(runner: gh.Runner, out) -> str:
    """Everything that must be true before a move is planned, and the trunk.

    Three of these are other people's sessions -- a stopped `gh stack rebase`,
    a `gh stack modify`, a plain `git rebase` -- and a move would drive its own
    rebase straight into them. The fourth is a dirty tree, which makes any
    replay unpredictable. All four are the operator's to resolve, and all four
    are checked in a dry run too: a dry run whose checks were skipped would
    report a plan that cannot be carried out.
    """
    gh.require_tools(runner)
    gh.require_repo(runner)
    session = move_mod.load(runner)
    if session is not None and session.replaying:
        # Only a stopped one: a half-replayed arrangement is not a thing to
        # move out of, and the session cannot describe two replays at once. A
        # move that is merely unpublished is joined rather than refused.
        raise ToolError(f"{session.line()} -- then move again")
    stopped = gh.rebase_stopped(runner)
    if stopped:
        raise ToolError(
            f"a stack rebase is stopped on {stopped!r}: finish it with "
            "`gh stack rebase --continue`, or undo it with `gh stack rebase --abort`"
        )
    if gh.modify_in_progress(runner):
        raise ToolError("a `gh stack modify` is unfinished; finish or abort it first")
    if gh.rebase_in_progress(runner):
        raise ToolError("a git rebase is in progress; finish or abort it first")
    if gh.dirty(runner):
        raise ToolError(
            "the working tree has uncommitted changes; commit or stash them first"
        )
    default = gh.default_branch(runner)
    out.info(f"trunk {default!r}, clean working tree, nothing else in progress")
    return default


#: A PR nothing can be done to any more.
LANDED = ("MERGED", "CLOSED")


def _pr_states(runner: gh.Runner, numbers: list[int | None]) -> dict:
    """Every PR the move involves, in one call.

    Both halves of the move want the same answer: the moved PRs decide whether
    it may run at all, and the ones below them decide which branches are still
    worth declaring to `gh stack init`. One round trip either way.
    """
    wanted = sorted({number for number in numbers if number})
    return gh.pull_requests(runner, wanted) if wanted else {}


def _landed(states: dict) -> set[int]:
    return {
        number
        for number, entry in states.items()
        if (entry.get("state") or "").upper() in LANDED
    }


def _refuse_stuck(states: dict, numbers: list[int]) -> None:
    """A PR GitHub will not let out of its stack, checked before anything runs.

    GitHub leaves a queued or auto-merging PR stacked and then **keeps the
    whole stack**, so any dissolve that has to happen later would silently do
    nothing. Both commands that dissolve -- `submit --move` and `prune` --
    depend on it, so both refuse these up front rather than leaving it to
    discover.
    """
    for number in numbers:
        entry = states.get(number) or {}
        if entry.get("isInMergeQueue"):
            raise ToolError(
                f"PR #{number} is in the merge queue, so GitHub will refuse to "
                "unstack it and `gsx submit --move` could not publish the move; "
                "wait for it to merge"
            )
        if entry.get("autoMergeRequest"):
            raise ToolError(
                f"PR #{number} has auto-merge enabled, so GitHub will refuse to "
                f"unstack it; disable it first (gh pr merge --disable-auto {number})"
            )


def _refuse_unmovable(states: dict, numbers: list[int]) -> None:
    """...and for a move, a PR that is finished as well.

    A move would rebase it and `submit` cannot restack it. `prune` is the
    opposite case, which is why this is not the same check: there a finished PR
    is the thing being dropped.
    """
    _refuse_stuck(states, numbers)
    for number in numbers:
        state = ((states.get(number) or {}).get("state") or "").upper()
        if state and state != "OPEN":
            raise ToolError(
                f"PR #{number} is {state}; a move would rebase it and submit cannot "
                "restack it -- drop that branch from the stack first "
                "(`gh stack modify`)"
            )


def _refuse_inconsistent(runner: gh.Runner, chain: list[str]) -> None:
    """Every branch in the moved slice has to contain its parent's tip.

    That is what makes a replay a replay of one branch's own commits. The
    cascade above the first moved branch reads the base `gh stack init`
    recorded, which is the merge-base with the parent the branch was DECLARED
    to have -- equal to that parent's tip when the branch contains it, and
    something much older when it does not. A real stack was in that state: one
    branch sat on an older trunk than the ten below it, and the cascade
    replayed twenty-four commits it already had into four conflicting files.
    Refusing here turns that into a sentence before anything changes.
    """
    stale = [
        f"{branch} does not contain {parent}"
        for parent, branch in zip(chain, chain[1:])
        if not gh.is_ancestor(runner, f"refs/heads/{parent}", f"refs/heads/{branch}")
    ]
    if stale:
        raise ToolError(
            "; ".join(stale)
            + " -- a slice of a stack can only move if the stack is consistent, so "
            "`gh stack rebase --no-trunk` on it first (resolving whatever comes up), "
            "then retry"
        )


def _in_flight(runner: gh.Runner, verb: str) -> move_mod.Session:
    """The move `--continue` and `--abort` act on. Neither invents one: with no
    session there is nothing to finish or undo, and saying so is more use than
    doing nothing."""
    session = move_mod.load(runner)
    if session is None:
        raise ToolError(
            f"no move is in progress ({move_mod.state_path(runner)} does not exist); "
            f"there is nothing to {verb}"
        )
    return session


def _move_continue(out, runner: gh.Runner) -> tuple[str, dict]:
    """Finish a move whose replay stopped on a conflict."""
    gh.require_tools(runner)
    gh.require_repo(runner)
    session = _in_flight(runner, "continue")
    if not session.replaying:
        raise ToolError(f"nothing to continue: {session.line()}")
    out.info(
        f"finishing the move of {' '.join(session.moving)} onto {session.target}, "
        f"stopped in the {session.stage}"
    )
    steps = progress.Counter(out)
    fields = move_mod.resume(runner, session, out, steps)
    return _moved(session.moving, session.target, fields)


def _move_abort(out, runner: gh.Runner) -> tuple[str, dict]:
    """Undo a move, whatever it had got to. Asks for none of the preflight: a
    stopped rebase leaves a dirty tree by definition, and refusing to clean
    that up would be the wrong way round."""
    gh.require_repo(runner)
    session = _in_flight(runner, "abort")
    out.info(f"undoing {len(session.moves)} move(s): {session.summary()}")
    fields = move_mod.unwind(runner, session, out)
    branches = fields.get("restored") or []
    put_back = (
        f"{len(branches)} branch(es) put back ({', '.join(branches)})"
        if branches
        else "every branch already on the tip it had"
    )
    stacks = ", ".join(f"#{number}" for number in fields.get("stacks") or [])
    return (
        f"move aborted: {put_back}, gh-stack's tracking {fields['tracking']}"
        + (f" ({stacks} as they were)" if stacks else ""),
        fields,
    )


def _moved(moving: list[str], onto: str, fields: dict) -> tuple[str, dict]:
    """What a finished replay says: nothing is published, and how much is not.

    The count matters once it is more than one: several moves are published or
    undone together, so "the move" stops being a thing the operator can point
    at and the sequence is what they are deciding about.
    """
    waiting = len(fields.get("moves") or [])
    sequence = (
        f"{waiting} local moves now, and `gsx submit --move` makes them all effective"
        if waiting > 1
        else "`gsx submit --move` publishes it"
    )
    return (
        f"moved {len(moving)} branch(es) onto {onto}, locally; {sequence}\n"
        + "\n".join(f"  moved   {branch}" for branch in moving),
        fields,
    )


def move(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Move the branch you are on, and everything above it, to another stack.

    Local, all of it: gh-stack's own commands and one git rebase, writing
    branches and gh-stack's tracking file and nothing else. `gsx submit --move`
    publishes it when you have looked at it.
    """
    asked = [bool(args.abort), bool(args.resume), bool(args.to), bool(args.report)]
    if sum(asked) != 1:
        raise ToolError(
            "move takes exactly one of --to #STACK|BRANCH, --continue, --abort "
            "or --report"
        )
    if args.abort:
        return _move_abort(out, runner)
    if args.resume:
        return _move_continue(out, runner)
    if args.report:
        gh.require_repo(runner)
        return move_mod.report(runner, _in_flight(runner, "report"))
    default = _move_ready(runner, out)
    joining = move_mod.load(runner)
    if joining is not None:
        out.info(
            f"joining {len(joining.moves)} unpublished move(s) ({joining.summary()}); "
            "`gsx submit --move` makes them all effective, `--abort` undoes them all"
        )
    current = gh.current_branch(runner)
    if not current or current == "HEAD":
        raise ToolError("detached HEAD; check out the branch you want to move")
    state = gh.read_state(runner)
    if not state.get("stacks"):
        raise ToolError(
            f"no stacks are tracked in this checkout ({gh.git_dir(runner)}/gh-stack); "
            "there is nothing to move out of"
        )
    source = move_mod.source_stack(state, current)
    out.info(
        f"{source.tag} on {source.trunk!r}: {len(source.branches)} branch(es), "
        f"{current!r} is #{source.index} from the bottom"
    )
    target = move_mod.resolve_target(runner, args.to, source, state, default, out)
    states = _pr_states(runner, [*source.prs, *target.prs])
    _refuse_unmovable(states, source.moving_prs)
    remote = gh.stack_remote(runner)
    unpushed = [
        branch
        for branch in source.moving
        if not gh.sha(runner, f"refs/remotes/{remote}/{branch}")
    ]
    if unpushed:
        out.warn(
            f"{', '.join(unpushed)} have no copy on {remote}: `gh stack rebase "
            "--abort` can still undo the replay, but there is nothing to fall back "
            "on afterwards"
        )

    plan = move_mod.build(
        source, target, landed=_landed(states), present=set(gh.head_shas(runner))
    )
    plan.remote = remote
    plan.upstream = gh.sha(runner, f"refs/heads/{plan.parent}")
    if not plan.upstream:
        raise ToolError(
            f"branch {plan.parent!r} does not exist here, so where "
            f"{source.moving[0]!r} sits cannot be worked out"
        )
    # The trunk is deliberately out of that chain -- a branch cut from an older
    # trunk is the ordinary case -- and the parent IS the trunk whenever the
    # branch below the moved slice is not in this checkout.
    below = [plan.parent] if plan.parent != source.trunk else []
    _refuse_inconsistent(runner, [*below, *source.moving])
    out.info(move_mod.text(plan), plan=plan.steps)
    if runner.dry_run:
        out.info("dry run: every check passed, nothing will be changed")
    else:
        cli.confirm(
            out,
            f"move {len(source.moving)} branch(es) out of {source.tag} onto "
            f"{target.head}? all local -- nothing is pushed",
            assume_yes=args.yes,
        )
    steps = progress.Counter(out, total=len(plan.steps))
    fields = move_mod.run(runner, plan, out, steps)
    return _moved(source.moving, target.head, fields)


# ------------------------------------------------------------------- stack
#: How a branch stands against the remote -> its symbol and its colour. The
#: symbol goes immediately before the name, so it reads as part of the arrow
#: into that branch: `<- =a1`.
MARKS = {
    gh.IN_SYNC: ("=", "green"),
    gh.AHEAD: ("+", "blue"),
    gh.BEHIND: ("-", "yellow"),
    gh.DIVERGED: ("x", "red"),
    gh.NO_LOCAL: ("?", ""),
}

#: What a branch carries when nothing was compared: `--local` and `--remote`
#: each show ONE side, and a symbol saying "behind" would be a claim about the
#: side they are not showing. `sync` is None there, and this is what it marks
#: the name with -- nothing, in no colour.
UNMARKED = ("", "")

#: And what a branch carries when the tracking file has never heard of it:
#: `?`, because there is nothing here, in magenta, because GitHub has it. It
#: is not a sync state -- nothing was compared -- so it is not in MARKS, and it
#: wins over one, since a comparison needs something on both sides.
REMOTE_MARK = ("?", "magenta")
REMOTE_WORD = "remote only"

#: And its mirror: `!`, because this checkout has it and GitHub's listing does
#: not -- a stack whose number no open stack on GitHub carries any more, or a
#: branch whose PR no stack there holds. Red, which `x` also is: they are never
#: the same character, and "GitHub does not have this" belongs to the same
#: family of alarm as "the two sides hold different work".
LOCAL_MARK = ("!", "red")
LOCAL_WORD = "local only"

#: The legend, in the order the symbols are worth learning: what is fine, what
#: you have to push, what you have to pull, what needs sorting out.
LEGEND = (gh.IN_SYNC, gh.AHEAD, gh.BEHIND, gh.DIVERGED)
WORDS = {
    gh.IN_SYNC: "in sync",
    gh.AHEAD: "ahead",
    gh.BEHIND: "behind",
    gh.DIVERGED: "diverged",
    gh.NO_LOCAL: "no local branch",
}

#: Where the rows come from. The default is BOTH, because the question behind
#: "what are my stacks" is usually "and what am I missing": a PR someone added
#: to your stack, or a stack you have never checked out, is invisible in the
#: tracking file and is exactly what you want to be told.
LOCAL = "local"  # gh-stack's tracking file, and nothing else
REMOTE = "remote"  # GitHub's own listing, and nothing else
BOTH = "both"  # the tracking file, plus whatever GitHub has that it does not

#: White `[]` round the name of what you are on. The brackets are the only
#: marker that is a shape rather than a colour, because the colours are spoken
#: for: each one is a state, and being checked out is not a state.
GUARDS = {"current": ("[", "]", "white")}


def _guard(item: dict) -> tuple[str, str, str]:
    """The brackets around one cell and their colour, or nothing."""
    return GUARDS["current"] if item.get("current") else ("", "", "")


def _mark(branch: dict) -> tuple[str, str]:
    """The symbol and colour in front of a branch's name.

    Being absent from the tracking file comes first: there is nothing here for
    a comparison to be about, so `?` in magenta says "GitHub has this one and
    you do not" and no sync symbol could say anything truer.

    Being absent from the LISTING comes next, and it does displace a sync
    symbol that could have been shown. That is the trade one symbol per branch
    forces, and it is the right way round: how this branch's commits compare
    with its remote copy is a question about a stack GitHub still has, and
    `!` says it does not. `--format json` keeps both.
    """
    if branch.get("remote_only"):
        return REMOTE_MARK
    if branch.get("local_only"):
        return LOCAL_MARK
    return MARKS.get(branch["sync"], UNMARKED)


def _stack_mark(row: dict) -> tuple[str, str]:
    """The symbol in a stack's own gutter, said of the stack rather than of
    one of its branches: `?` GitHub's alone, `!` this checkout's alone."""
    if row.get("remote_only"):
        return REMOTE_MARK
    if row.get("local_only"):
        return LOCAL_MARK
    return UNMARKED


def _cell(symbol: str, name: str, colour: str, guard: tuple, paint) -> str:
    """One branch: its symbol, then its brackets round the NAME -- `=[a2]`.

    The symbol says how the branch stands and the brackets say what the row is,
    so they are two facts about two different things and the brackets hold only
    the one they are about. The name therefore sits at the same column whether
    it is bracketed or not; it is the symbol that steps one column left, and a
    symbol is one character wherever it sits. An unguarded cell spends that
    column on a space instead, which is what keeps the two the same width.
    """
    opening, closing, guard_colour = guard
    painted = (paint(colour, symbol) if colour else symbol) + (
        paint(colour, name) if colour else name
    )
    if not opening:
        return " " + painted
    return (
        (paint(colour, symbol) if colour else symbol)
        + paint(guard_colour, opening)
        + (paint(colour, name) if colour else name)
        + paint(guard_colour, closing)
    )


def _finished(pull: dict) -> bool:
    """A PR that is merged or closed, as the stacks listing reports it.

    A stack keeps its merged PRs -- #3443 in tabsdata-os holds 90 of them under
    three open ones -- so this is the difference between a listing and a
    working set. `state` is `open`/`closed` and `merged_at` is set for a merge;
    a payload that carries neither is taken as open, since inventing a merge
    would hide a branch.
    """
    return (
        bool(pull.get("merged_at")) or (pull.get("state") or "open").lower() != "open"
    )


def finished_prs(listing: list[dict]) -> set[int]:
    """Every PR the listing says is done with, from every stack in it."""
    return {
        int(pull["number"])
        for stack in listing or []
        for pull in stack.get("pull_requests") or []
        if pull.get("number") and _finished(pull)
    }


def without_finished(rows: list[dict], finished: set[int]) -> tuple[list[dict], int]:
    """The rows with the done-with PRs taken out, and how many that was.

    Left out by default because a stack's merged PRs are its history, not its
    state: `gsx stack -a -s` on a real stack printed ninety `?OS-32xx` before
    the three branches that were still open, and the three were the answer.
    A stack with nothing left goes too -- its number is in `--all --merged`
    when it is wanted. What is left is honest about the shape it shows: the
    merged commits are in the trunk now, so the branch above them really does
    sit on it.
    """
    hidden = 0
    kept = []
    for row in rows:
        branches = []
        for branch in row["branches"]:
            if branch["pr"] and branch["pr"] in finished:
                hidden += 1
                continue
            branches.append(branch)
        if not branches:
            continue
        kept.append({**row, "branches": branches})
    return kept, hidden


def _remote_branches(
    listed: dict, tracked: set, current: str, extras_only: bool = False
) -> list[dict]:
    """A GitHub stack's open PRs as branch rows, in the order GitHub has them.

    Merged and closed PRs are left out: a stack keeps them, but a PR that is
    done with is not something you are missing. With `extras_only` the ones the
    tracking file already lists are dropped too, which is what the default view
    adds to a stack of its own -- appended at the top, which is where
    `gh stack sync` would put them.
    """
    rows = []
    for pull in listed.get("pull_requests") or []:
        name = ((pull.get("head") or {}).get("ref")) or ""
        if not name:
            continue
        if _finished(pull):
            continue
        known = name in tracked
        if extras_only and known:
            continue
        rows.append(
            {
                "name": name,
                "pr": pull.get("number"),
                "sync": gh.NO_LOCAL,
                "current": bool(current) and name == current,
                "remote_only": not known,
                "local_only": False,
            }
        )
    return rows


def stack_refs(stack: dict) -> set[str]:
    """The branch names of one stack, as the listing gives them.

    The key the two sides are matched on, because it is the one both always
    have: a number is missing from a rebuilt local stack and a PR number is
    missing from a branch that has no PR yet.
    """
    return {
        ((pull.get("head") or {}).get("ref"))
        for pull in stack.get("pull_requests") or []
        if (pull.get("head") or {}).get("ref")
    }


def _same_stack(names: set[str], listing: dict[int, dict]) -> dict | None:
    """The listed stack that is this local stack, by the branches they share.

    Not by number: `gh stack init` gives a rebuilt stack no number at all, so
    after a `gsx move` the local side of a stack GitHub knows as #3478 is `#-`.
    Matching on the number then showed the same branches twice -- once as the
    local stack and once as a "remote only" one -- and hid any PR the listing
    had added to it. The most-shared stack is the one, since a branch belongs
    to at most one stack on either side.
    """
    best, shared = None, 0
    for stack in listing.values():
        overlap = len(stack_refs(stack) & names)
        if overlap > shared:
            best, shared = stack, overlap
    return best


def stack_rows(
    state: dict,
    current: str = "",
    sync: dict | None = None,
    remote: list[dict] | None = None,
    source: str = BOTH,
    asked: bool = False,
) -> list[dict]:
    """The stacks, bottom-up, as `{number, trunk, branches}`.

    The tracking file (`<git-dir>/gh-stack`) is the local half: it needs no API
    call, so `--local` answers offline and cannot disagree with what the other
    subcommands read. `remote` is GitHub's own listing of the repository's
    stacks, and the two are put together as `source` asks: LOCAL ignores the
    listing, REMOTE is built from it alone, BOTH is the tracking file plus what
    the listing holds that it does not.

    A stack with no number yet (never submitted) keeps `None`, which prints
    `#-` -- and exists only locally, by definition. Each branch carries how it
    stands against the remote (`sync`), the number of its PR (`pr`, `None` for
    a branch that has none), whether it is the checked-out one (`current`),
    whether the tracking file is missing it (`remote_only`) and whether the
    listing is (`local_only`).

    `asked` is whether the listing was really had, and only then is anything
    called `local_only`: a listing that could not be read comes back empty,
    exactly like a repository whose stacks are all closed, and the difference
    between those two is the difference between a fact and a false alarm.
    """
    sync = sync or {}
    stacks = state.get("stacks") or []
    tracked_branches = {
        entry.get("branch")
        for s in stacks
        for entry in s.get("branches") or []
        if entry.get("branch")
    }

    listed = {
        int(s["number"]): s for s in remote or [] if s.get("open") and s.get("number")
    }
    # The mirror of `tracked_branches`, and matched the same way -- by name,
    # across every stack rather than within one: a PR that moved to another
    # stack on GitHub is still a PR GitHub's stacks have, and saying otherwise
    # would put `!` on half a repository the day someone reorganised it.
    listed_branches = {ref for stack in listed.values() for ref in stack_refs(stack)}
    # Only with the listing in hand. `--local` asks nobody, which is its point.
    known = asked and source == BOTH

    rows = []
    if source != REMOTE:
        for stack in stacks:
            branches = [
                {
                    "name": entry["branch"],
                    "pr": (entry.get("pullRequest") or {}).get("number"),
                    "sync": sync.get(entry["branch"], gh.NO_LOCAL),
                    "current": bool(current) and entry["branch"] == current,
                    "remote_only": False,
                    # A branch with no PR has not been submitted rather than
                    # been forgotten: `-` in the number column says so, and
                    # `+` says the remote has nothing of it either.
                    "local_only": bool(
                        known
                        and (entry.get("pullRequest") or {}).get("number")
                        and entry["branch"] not in listed_branches
                    ),
                }
                for entry in stack.get("branches") or []
                if entry.get("branch")
            ]
            number = stack.get("number")
            if source == BOTH:
                same = _same_stack({branch["name"] for branch in branches}, listed)
                if same:
                    branches += _remote_branches(
                        same, tracked_branches, current, extras_only=True
                    )
            rows.append(
                {
                    "number": number,
                    "trunk": ((stack.get("trunk") or {}).get("branch")) or "?",
                    "branches": branches,
                    "current": any(branch["current"] for branch in branches),
                    # Standing on the trunk is not standing in the stack --
                    # `submit` acts on neither -- but it IS drawn in this row,
                    # and the brackets are what answer "where am I".
                    "trunk_current": bool(current)
                    and current == (((stack.get("trunk") or {}).get("branch")) or "?"),
                    "remote_only": False,
                    # By its NUMBER, which is the claim the file is making: it
                    # says this checkout is tracking stack #N, and the listing
                    # has no open #N -- dissolved, closed, or re-linked under
                    # another number. Not by its branches: they may all sit in
                    # the stack that replaced this one, which is precisely the
                    # case a reader needs telling about. A stack with no number
                    # has never been submitted, and `#-` already says that.
                    "local_only": bool(known and number and number not in listed),
                }
            )
    # A listed stack is "elsewhere" when this checkout tracks none of its
    # branches: one that shares any of them is the same stack under another
    # name -- or under no name, after a move -- and is already a row above.
    elsewhere = sorted(
        number
        for number, stack in listed.items()
        if not stack_refs(stack) & tracked_branches
    )
    wanted = sorted(listed) if source == REMOTE else elsewhere if source == BOTH else []
    for number in wanted:
        branches = _remote_branches(listed[number], tracked_branches, current)
        for branch in branches:
            branch["sync"] = sync.get(branch["name"], gh.NO_LOCAL)
        rows.append(
            {
                "number": number,
                "trunk": ((listed[number].get("base") or {}).get("ref")) or "?",
                "branches": branches,
                "current": any(branch["current"] for branch in branches),
                "trunk_current": bool(current)
                and current == (((listed[number].get("base") or {}).get("ref")) or "?"),
                "remote_only": number in elsewhere,
                "local_only": False,
            }
        )
    # At most ONE stack is the one you are on. A branch can sit in several
    # tracked stacks -- leftovers do exactly that, and a stack GitHub no longer
    # has keeps its copy of the branch for ever -- and bracketing every row
    # holding it would say of each that it is the one `submit` and `apply` act
    # on, which only one of them is: the first in the file, because that is the
    # one every other subcommand takes (`move.stack_of`). The BRANCH keeps its
    # brackets in every row it appears in: it is the branch you are on wherever
    # it is listed, and seeing it twice is the news.
    on = next((row for row in rows if row["current"]), None)
    for row in rows:
        row["current"] = row is on
    return rows


def _no_paint(name: str, text: str) -> str:
    return text


def _gutter(rows: list[dict]) -> int:
    """One column left of the brackets, and only when something is in it.

    A stack's mark cannot share the bracket's slot the way a branch's does,
    because a branch wears its symbol *outside* its brackets and a number has
    nowhere to put one: a stack can be both the one you are on and one GitHub
    does not have, and that is exactly when it must be said. So the mark gets a
    column of its own -- which costs the whole table one space, and only on a
    page that has a mark to show.
    """
    return max((len(_stack_mark(row)[0]) for row in rows), default=0)


def _tag(row: dict, tag: str, width: int, paint, gutter: int = 0) -> str:
    """A stack's mark, then its number in its brackets or in their spaces."""
    symbol, colour = _stack_mark(row)
    flag = (paint(colour, symbol) if colour else symbol) + " " * (gutter - len(symbol))
    # the number takes the mark's colour, as a branch's name takes its own
    number = paint(colour, tag) if colour else tag
    opening, closing, guard_colour = _guard(row)
    if opening:
        pad = " " * (width - len(tag))
        return (
            flag
            + paint(guard_colour, opening)
            + number
            + paint(guard_colour, closing)
            + pad
        )
    return flag + " " + number + " " * (width + 1 - len(tag))


def stack_lines(rows: list[dict], paint=_no_paint) -> str:
    """One line per stack, every name aligned across all of them:

         [#34]  main <- =insync   <-+[ahead]
        ! #40   main <- -behind   <- xdiverged
        ? #41   main <- ?theirs
          #-    main <- +unpushed <- ?gone

    Each branch carries one symbol saying how it stands against the remote --
    `=` in sync, `+` ahead, `-` behind, `x` diverged, `?` no local branch -- and
    takes that state's colour.

    **White `[]` marks what is current** -- the stack holding the checked-out
    branch, the one `submit` and `apply` act on without being told which, and
    that branch. They hold the **name** alone, with the symbol outside
    (`=[a2]`), because the symbol is about how the branch stands and the
    brackets are about which row this is. **Magenta `?` marks what only GitHub
    has**, a stack or a PR the tracking file does not list: there is nothing
    here for a sync symbol to be about, so it takes the place of one -- and a
    **red `!`** marks the mirror, what only this checkout has: a stack whose
    number the listing no longer carries, a PR no stack on GitHub holds. A
    stack's mark sits in a column of its own, left of the brackets, because a
    stack can be both the one you are on and one GitHub does not have.

    Every cell reserves one slot on each side for its brackets, and those two
    slots are the spaces around `<-` -- so a bracketed cell is exactly as wide
    as a plain one and the brackets cost the column nothing. A **name** is then
    at the same offset on every line whether it is bracketed or not; it is the
    symbol that steps one column left when the brackets appear, and a symbol is
    one character either way. Widths are the widest symbol-and-name; a row's own
    last cell is left unpadded, so no line carries trailing blanks.

    Painted per CELL rather than per row: a paint ends in a reset, so one
    coloured branch would otherwise leave everything after it plain.
    """
    tags = ["#" + (str(row["number"]) if row["number"] else "-") for row in rows]
    tag_width = max((len(tag) for tag in tags), default=0)
    gutter = _gutter(rows)
    # (symbol, name, paint, guard) per cell, the trunk first and never guarded
    grid = [
        [
            ("", row["trunk"], "", _guard({"current": row.get("trunk_current")})),
            *(
                (
                    _mark(branch)[0],
                    branch["name"],
                    _mark(branch)[1],
                    _guard(branch),
                )
                for branch in row["branches"]
            ),
        ]
        for row in rows
    ]
    widths = [
        max(
            len(cells[column][0]) + len(cells[column][1])
            for cells in grid
            if len(cells) > column
        )
        for column in range(max((len(cells) for cells in grid), default=0))
    ]
    lines = []
    for tag, row, cells in zip(tags, rows, grid):
        # One space, because the trunk cell spends the other on its own
        # leading slot -- a space when it is plain, the opening bracket when
        # you are standing on it. Same arithmetic as every other cell.
        parts = [_tag(row, tag, tag_width, paint, gutter), " "]
        for index, (symbol, name, colour, guard) in enumerate(cells):
            last = index == len(cells) - 1
            if index:
                # `<-` carries no space of its own: the two slots either side
                # of it are the closing bracket and the next cell's leading
                # space-or-symbol, which is what keeps a bracketed cell exactly
                # as wide as a plain one.
                parts.append("<-")
            cell = _cell(symbol, name, colour, guard, paint)
            if not last:
                pad = " " * (widths[index] - len(symbol) - len(name))
                cell += pad if guard[0] else pad + " "
            parts.append(cell)
        lines.append("".join(parts))
    return "\n".join(lines)


def stack_summary(rows: list[dict], titles: dict, paint=_no_paint) -> str:
    """One line per branch, with its PR number and title beside it:

        [#34]  main
                =insync   #21  the loader
               +[ahead]   #22  wire it up
                ?theirs   #29  someone else's

    The stack's own line names it and its trunk; each branch sits under it with
    the same symbol, colour and brackets the one-line form uses, so the two
    views never disagree about what a branch is. Columns are measured across
    every stack being shown, not per stack, so the numbers and titles line up
    down the whole page.
    """
    tags = ["#" + (str(row["number"]) if row["number"] else "-") for row in rows]
    tag_width = max((len(tag) for tag in tags), default=0)
    gutter = _gutter(rows)
    cells = [
        f"{_mark(branch)[0]}{branch['name']}"
        for row in rows
        for branch in row["branches"]
    ]
    name_width = max((len(cell) for cell in cells), default=0)
    refs = {
        id(branch): (f"#{branch['pr']}" if branch["pr"] else "-")
        for row in rows
        for branch in row["branches"]
    }
    ref_width = max((len(ref) for ref in refs.values()), default=0)
    # the branch names hang one column left of the trunk's, so a bracket sits
    # in the same relation to its name as it does in the one-line form
    indent = " " * (tag_width + gutter + 3)
    blocks = []
    for tag, row in zip(tags, rows):
        opening, closing, guard_colour = _guard({"current": row.get("trunk_current")})
        trunk = (
            paint(guard_colour, opening) + row["trunk"] + paint(guard_colour, closing)
            if opening
            else row["trunk"]
        )
        lines = [
            f"{_tag(row, tag, tag_width, paint, gutter)}"
            + (" " if opening else "  ")
            + trunk
        ]
        for branch in row["branches"]:
            symbol, colour = _mark(branch)
            guard = _guard(branch)
            pad = " " * (name_width - len(symbol) - len(branch["name"]))
            cell = _cell(symbol, branch["name"], colour, guard, paint) + pad
            if not guard[0]:
                cell += " "
            ref = refs[id(branch)]
            title = titles.get(branch["pr"], "") if branch["pr"] else ""
            lines.append(f"{indent}{cell} {ref:<{ref_width}}  {title}".rstrip())
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def legend(
    rows: list[dict],
    remote: str,
    paint=_no_paint,
    fetched: bool = True,
    marked: bool = True,
) -> str:
    """One line under the listing saying what the symbols and colours mean.

    Each symbol is printed in its own colour, so the legend demonstrates the
    thing it is explaining rather than describing it twice. `?` and `()` earn
    their place only when a row actually uses them, and the sync symbols only
    when the view compared the two sides at all -- `--local` and `--remote`
    show one side, so there the legend is the brackets and nothing else. Not
    fetching first IS said, because every symbol is then a claim about the
    remote as it was rather than as it is.
    """
    states = list(LEGEND) if marked else []
    # Not for a remote-only branch: it has no local copy by definition and is
    # already wearing the magenta `?` for that, and the two entries side by
    # side read as one symbol explained twice ("? no local branch  ? remote
    # only"). A branch missing from a stack this checkout DOES track still
    # earns it.
    if marked and any(
        branch["sync"] == gh.NO_LOCAL
        and not branch.get("remote_only")
        and not branch.get("local_only")
        for row in rows
        for branch in row["branches"]
    ):
        states.append(gh.NO_LOCAL)
    marks = [
        f"{paint(MARKS[state][1], MARKS[state][0])} {WORDS[state]}" for state in states
    ]
    # the brackets, explained where the eye already is rather than on a line of
    # their own
    if any(
        row.get("remote_only") or any(b.get("remote_only") for b in row["branches"])
        for row in rows
    ):
        marks.append(f"{paint(REMOTE_MARK[1], REMOTE_MARK[0])} {REMOTE_WORD}")
    # next to its mirror, because the two are one fact read from either end
    if any(
        row.get("local_only") or any(b.get("local_only") for b in row["branches"])
        for row in rows
    ):
        marks.append(f"{paint(LOCAL_MARK[1], LOCAL_MARK[0])} {LOCAL_WORD}")
    marks.append(f"{paint('white', '[]')} current")
    line = f"  {'  '.join(marks)}"
    # The remote is not named -- it is `git config gh-stack.remote` and the
    # reader knows their own. Staleness is another matter: with --no-fetch
    # every symbol is about the remote as it WAS, and that has to be said. With
    # no symbols there is nothing it could be said about.
    return line if fetched or not marked else f"{line}   (as of the last fetch)"


def _painter(out):
    """How `stack` paints, given where its ok event is going.

    json carries the message as data, so an escape in it would be data too --
    the fields say how every branch stands, and a machine reads those. On view
    `render.paint` still checks the stream and NO_COLOR itself.
    """
    if out.fmt != "view":
        return _no_paint
    return lambda name, text: render.paint(name, text, out.out)


def _remote_listing(runner: gh.Runner, out, source: str) -> tuple[list[dict], bool]:
    """GitHub's own stacks, and whether they could be had.

    `--local` does not ask -- that is its point, and it is what keeps
    `--local --short` needing no `gh` at all. A listing that cannot be had is
    fatal only for `--remote`, where it IS the answer; otherwise the local view
    stands and a warning says what is missing from it.
    """
    if source == LOCAL:
        return [], False
    try:
        return gh.stacks(runner), True
    except ToolError as error:
        if source == REMOTE:
            raise ToolError(f"could not list the stacks on GitHub: {error}") from error
        out.warn(
            f"could not list the stacks on GitHub ({error}); showing what is "
            "tracked here, which may be missing PRs"
        )
        return [], False


#: What `--all` counts, per source: the number alone would not say of what.
COUNTED = {LOCAL: " tracked here", REMOTE: " on GitHub", BOTH: ""}

#: And what "there are none" means, per source.
BLANK = {
    LOCAL: "no stacks are tracked in this repository",
    REMOTE: "GitHub has no open stacks in this repository",
    BOTH: "no stacks are tracked here, and GitHub has none open either",
}


def stack(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """The stack you are on, or every stack with `--all`; as this checkout has
    it, as GitHub has it, or both."""
    # gh-stack's extension is never needed. `gh` itself is, for the PR titles
    # the default prints and for GitHub's own listing of the stacks -- neither
    # of which `--local --short` asks for.
    gh.require_repo(runner)
    if args.remote and args.local:
        raise ToolError(
            "stack takes at most one of --remote and --local; without either it "
            "shows what is tracked here plus what only GitHub has"
        )
    source = REMOTE if args.remote else LOCAL if args.local else BOTH
    # One side of the fence is one side: --local and --remote compare nothing,
    # so they carry no sync symbols and there is nothing for a fetch to freshen.
    compared = source == BOTH
    fetched = compared and not args.no_fetch
    remote = gh.stack_remote(runner)
    if fetched:
        # Unannounced: it is a precondition of the answer, not a step of its
        # own, and a line about it would be the first thing on every run.
        gh.fetch(runner, remote)
    current = gh.current_branch(runner)
    # An unfinished move is announced for every command, before any of them
    # runs (`gsx._say_if_moving`), so it is not said again here.
    unfinished = move_mod.load(runner)
    if unfinished is None and gh.rebase_stopped(runner):
        out.warn(
            f"a stack rebase is stopped on {gh.rebase_stopped(runner)!r}: "
            "`gh stack rebase --continue` when it is resolved, or "
            "`gh stack rebase --abort` to put it back"
        )
    listing, asked = _remote_listing(runner, out, source)
    state = gh.read_state(runner)
    if listing and unfinished is None:
        # The rows below say where each branch stands; this says the arrangement
        # itself is half-published, which no row can show. Only when no session
        # is open: that line has already said the same thing, and better --
        # this one is for a divergence nothing local accounts for.
        unpublished = move_mod.pending(state, listing)
        if unpublished:
            out.warn(unpublished.line())
    every = stack_rows(state, current, remote=listing, source=source, asked=asked)
    if not args.merged:
        # The listing is the only thing that knows a PR is merged, so --local
        # shows everything: it asks nobody, which is its point.
        every, hidden = without_finished(every, finished_prs(listing))
        if hidden:
            out.info(f"{hidden} merged or closed PR(s) left out; --merged shows them")
    if not every:
        blank = BLANK[source] if asked or source != BOTH else BLANK[LOCAL]
        return (blank, {"stacks": [], "source": source})
    rows = every if args.all else [row for row in every if row["current"]]
    if not args.all:
        elsewhere = [
            row for row in every if row.get("remote_only") and not row["current"]
        ]
        if elsewhere:
            out.info(
                f"{len(elsewhere)} stack(s) on GitHub are not tracked here; "
                "--all lists them"
            )
        # and the mirror, which is the one that costs something: a stack this
        # checkout still tracks and GitHub has no open stack for is a leftover,
        # and it would otherwise be invisible from the stack you are standing in
        ghosts = [row for row in every if row.get("local_only") and not row["current"]]
        if ghosts:
            out.info(
                f"{len(ghosts)} stack(s) tracked here are not open on GitHub; "
                "--all lists them"
            )
    if rows and not any(row["current"] or row.get("trunk_current") for row in rows):
        # Nothing is bracketed, so the brackets answer nothing -- and "where am
        # I" is the question a reader asks of this view first. Said rather than
        # drawn, because there is no cell to draw it on.
        out.info(
            f"on {current!r}, which is in none of the stacks below", branch=current
        )
    if not rows:
        # Asked about "my stack" while standing outside every one of them: an
        # answer, and the useful half of it is that --all would show them.
        return (
            f"{current!r} is not in a tracked stack; --all lists the "
            f"{len(every)} there {'is' if len(every) == 1 else 'are'}",
            {"stacks": [], "remote": remote, "fetched": fetched, "source": source},
        )
    # Only the branches actually being shown are compared against the remote,
    # so the default costs one `rev-list` per out-of-sync branch of one stack.
    sync = (
        gh.branch_sync(
            runner,
            [branch["name"] for row in rows for branch in row["branches"]],
            remote,
            {
                branch["name"]: row["trunk"]
                for row in rows
                for branch in row["branches"]
            },
        )
        if compared
        else {}
    )
    for row in rows:
        for branch in row["branches"]:
            branch["sync"] = sync.get(branch["name"], gh.NO_LOCAL) if compared else None
    paint = _painter(out)
    if args.short:
        body = stack_lines(rows, paint)
    else:
        numbers = [
            branch["pr"] for row in rows for branch in row["branches"] if branch["pr"]
        ]
        titles = gh.pr_titles(runner, numbers)
        missing = [number for number in numbers if number not in titles]
        if missing:
            out.warn(
                "could not read the title of "
                + ", ".join(f"#{number}" for number in missing)
                + " from gh; the numbers are still below"
            )
        body = stack_summary(rows, titles, paint)
    # The count orients a reader looking at several; over one stack it says
    # only what the single row already shows.
    header = f"{len(rows)} stack(s){COUNTED[source]}:\n" if args.all else ""
    return (
        header
        + body
        # a blank line on each side: the legend is a key to what is above it,
        # not another row of it
        + "\n\n"
        + legend(rows, remote, paint, fetched=fetched, marked=compared)
        + "\n",
        {"stacks": rows, "remote": remote, "fetched": fetched, "source": source},
    )


# ------------------------------------------------------------------ sync
def _stack_branches(runner: gh.Runner, state: dict, current: str, every: bool):
    """The stacks to sync, as `(trunk, [branch...])`, branches bottom-up.

    Only branches this checkout actually has: a stack keeps every branch it
    ever had, and a merged PR's branch is usually deleted on the remote and
    gone here -- there is nothing to reconcile or restack about those.
    """
    stacks = state.get("stacks") or []
    if not every:
        holding = move_mod.stack_of(state, current)
        stacks = [holding] if holding else []
    chosen = []
    for stack in stacks:
        trunk = ((stack.get("trunk") or {}).get("branch")) or "main"
        live = [
            entry
            for entry in stack.get("branches") or []
            if entry.get("branch") and gh.sha(runner, f"refs/heads/{entry['branch']}")
        ]
        names = [entry["branch"] for entry in live]
        known = {
            entry["branch"]
            for entry in stack.get("branches") or []
            if entry.get("branch")
        }
        prs = {
            entry["branch"]: (entry.get("pullRequest") or {}).get("number")
            for entry in live
            if (entry.get("pullRequest") or {}).get("number")
        }
        if names:
            chosen.append((trunk, names, prs, known))
    return chosen


def _pr_info(
    runner: gh.Runner, prs: dict[str, int], out
) -> tuple[dict[str, str], set[str]]:
    """Each branch's base branch as the PR on GitHub declares it, and the
    branches whose PR has landed.

    The base is the only thing that knows where a branch sat before this clone
    moved it: gh-stack's state file is rewritten by the move itself, so it
    agrees with the move and can never notice one. The landed set is what
    keeps `sync` from resurrecting history: a squash-merged bottom branch,
    deleted on GitHub, still exists here and in the tracking file, and a sync
    that treated it as unpublished restacked it onto the trunk and pushed it
    back -- `* [new branch] E1-1 -> E1-1`, measured. One GraphQL call for the
    whole stack; an answer that cannot be had leaves both empty and says so.
    """
    if not prs:
        return {}, set()
    try:
        payload = gh.pull_requests(runner, list(prs.values()))
    except ToolError as error:
        out.warn(
            f"could not read the PRs from GitHub ({error}); reconciling as "
            "though nothing has been moved here and nothing has landed"
        )
        return {}, set()
    bases: dict[str, str] = {}
    landed: set[str] = set()
    for branch, number in prs.items():
        pull = payload.get(number) or {}
        base = pull.get("baseRefName")
        if base:
            bases[branch] = base
        if (pull.get("state") or "OPEN").upper() in ("MERGED", "CLOSED"):
            landed.add(branch)
    return bases, landed


def _pr_bases(runner: gh.Runner, prs: dict[str, int], out) -> dict[str, str]:
    return _pr_info(runner, prs, out)[0]


def _forward_trunk(
    runner: gh.Runner, trunk: str, remote: str, current: str, out
) -> None:
    """Fast-forward the trunk, which is everyone's base and never rewritten.

    Checked out or not: `git fetch <remote> <trunk>:<trunk>` updates the ref
    in place and refuses anything but a fast-forward, which is exactly the
    guarantee wanted -- but it cannot touch the branch you are standing on,
    so that one case is a merge.
    """
    tracked = gh.sha(runner, f"refs/remotes/{remote}/{trunk}")
    local = gh.sha(runner, f"refs/heads/{trunk}")
    if not tracked or not local or tracked == local:
        return
    if not gh.is_ancestor(runner, local, tracked):
        # The trunk is not ours to rewrite, and a trunk that has diverged is
        # somebody's accident rather than this command's business.
        out.warn(
            f"{trunk} has diverged from {remote}/{trunk}; leaving it alone "
            "-- sort the trunk out before syncing a stack onto it"
        )
        return
    if current == trunk:
        runner.run(["git", "merge", "--ff-only", f"{remote}/{trunk}"], capture=False)
    else:
        runner.run(["git", "fetch", remote, f"{trunk}:{trunk}"], capture=False)
    out.info(f"{trunk}: fast-forwarded to {remote}/{trunk}", branch=trunk)


def sync(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Fetch, reconcile every branch with its own remote copy, restack; push
    only with --push."""
    gh.require_binaries()
    gh.require_repo(runner)
    continuing = getattr(args, "continue", False)
    if args.abort and continuing:
        raise ToolError("sync takes at most one of --abort and --continue")
    session = sync_mod.load_session(runner)
    if args.abort:
        if session is None:
            raise ToolError("no sync is stopped here; there is nothing to abort")
        restored = sync_mod.abort(runner, session)
        sync_mod.clear_session(runner)
        return (
            f"sync aborted: {len(restored)} branch(es) put back"
            + (": " + " ".join(restored) if restored else "")
            + f"; back on {gh.current_branch(runner)!r}",
            {"aborted": True, "restored": restored},
        )
    stopped = sync_mod.in_progress(runner)
    if continuing:
        if session is None:
            raise ToolError("no sync is stopped here; there is nothing to continue")
        if stopped:
            sync_mod.finish(runner, stopped)
    elif session is not None and stopped:
        raise ToolError(
            f"a sync is stopped in a {stopped}: resolve the conflict, `git add` "
            "the files, then `tdd gsx sync --continue`; or `tdd gsx sync --abort` "
            "puts every branch it touched back"
        )
    if gh.dirty(runner):
        raise ToolError(
            "the working tree has uncommitted changes; every rebase below "
            "would refuse, and finding that out halfway through a cascade is "
            "worse than being told now"
        )
    gh_stopped = gh.rebase_stopped(runner)
    if gh_stopped:
        raise ToolError(
            f"a stack rebase is stopped on {gh_stopped!r}: finish it with "
            "`gh stack rebase --continue`, or `gh stack rebase --abort`"
        )
    current = (session or {}).get("branch") or gh.current_branch(runner)
    state = gh.read_state(runner)
    chosen = _stack_branches(runner, state, current, args.all)
    if not chosen:
        sync_mod.clear_session(runner)
        return (
            "no stack to sync"
            + (
                ""
                if args.all
                else f": {current!r} is not in a tracked stack, --all syncs every one"
            ),
            {"stacks": 0, "pushed": []},
        )
    remote = gh.stack_remote(runner)
    gh.fetch(runner, remote)

    # A move is half an arrangement until `submit --move` publishes it, so
    # this reconciles and restacks -- which is what keeps the move sitting on
    # current work -- and holds the push whatever was asked.
    #
    # The two reasons to hold are NOT the same advice, and conflating them is
    # how a stale clone gets told to publish its staleness. A session says
    # THIS checkout moved something, and `submit --move` is the way out. A
    # bare disagreement with GitHub says the two sides differ for a reason
    # nothing here accounts for -- most often somebody else's restructure that
    # this clone has not adopted -- and publishing would overwrite it. The
    # second costs a listing, so it is asked only when a push was asked for.
    moving = move_mod.load(runner) is not None
    held = ""
    if moving:
        held = (
            "an unpublished move is in progress; `tdd gsx submit --move` publishes it"
        )
    elif args.push and _moved_locally(runner, out):
        held = (
            "GitHub and this checkout disagree about the stacks, and no move of "
            "this checkout's accounts for it -- `tdd gsx stack -a` shows how, and "
            "`gh stack checkout <n>` re-imports what GitHub has. Pushing now "
            "would publish this clone's older arrangement"
        )
    outcome = sync_mod.Outcome()
    live: list[tuple[str, list[str]]] = []
    # Every tip before anything moves -- the fork points below need it, and so
    # does --abort. A resumed run keeps the tips its first half took, since by
    # now some branches have already been rewritten.
    remembered = dict((session or {}).get("tips") or {})
    all_branches = [b for _, branches, _, _ in chosen for b in branches]
    before_all = {
        b: remembered.get(b) or sha
        for b, sha in sync_mod.tips(runner, all_branches).items()
    }
    sync_mod.save_session(runner, current, before_all, remote)
    try:
        for trunk, branches, prs, known in chosen:
            _forward_trunk(runner, trunk, remote, current, out)
            bases, landed = _pr_info(runner, prs, out)
            if landed:
                # History, not state: its commits are in the trunk, its branch
                # is gone from the remote, and the branch above it now sits on
                # the trunk. Left out of every step, the push included.
                out.info(
                    f"{len(landed)} landed branch(es) left out: "
                    + " ".join(b for b in branches if b in landed)
                )
                branches = [b for b in branches if b not in landed]
            live.append((trunk, branches))
            before = {b: before_all[b] for b in branches if b in before_all}
            outcome.reconciled.update(
                sync_mod.reconcile(runner, branches, remote, out, bases, trunk, known)
            )
            # ...and again after reconcile: a child reconciled onto a remote
            # copy forked from the parent as it stands HERE, before the
            # restack moves it.
            after = sync_mod.tips(runner, branches)
            outcome.restacked.extend(
                sync_mod.restack(runner, branches, trunk, out, before, after)
            )
    except ToolError as error:
        if sync_mod.in_progress(runner):
            raise ToolError(
                f"{error}\n  resolve it, `git add` the files, then `tdd gsx sync "
                "--continue`; or `tdd gsx sync --abort` puts every branch this "
                "sync touched back"
            ) from error
        raise
    # Back where the operator was: the cascade walks the stack and leaving
    # them on its top would be a side effect of asking a question.
    if gh.current_branch(runner) != current:
        gh.checkout(runner, current)
    sync_mod.clear_session(runner)

    every = [branch for _, branches in live for branch in branches]
    plain, forced, leases = sync_mod.push_args(runner, every, remote)
    outcome.fast_forward, outcome.forced = plain, forced
    fields = {
        "remote": remote,
        "to_push": outcome.touched,
        "forced": forced,
        **_sync_fields(outcome),
    }
    line = _sync_line(outcome, remote, pushed=False)
    if not outcome.touched:
        return (line + "\nthe remote already has it all", {"pushed": [], **fields})
    count = f"{len(outcome.touched)} branch(es) to push"
    if held:
        tail = (
            f"{count}, held: {held}" if not args.push else f"nothing was pushed: {held}"
        )
        return (line + "\n" + tail, {"pushed": [], "held": held, **fields})
    if not args.push:
        return (
            line + f"\n{count}: `tdd gsx sync --push`, or `tdd gsx submit`",
            {"pushed": [], **fields},
        )
    runner.run(
        ["git", "push", "--atomic", *leases, remote, *outcome.touched], capture=False
    )
    return (
        _sync_line(outcome, remote, pushed=True),
        {"pushed": outcome.touched, **fields},
    )


def _sync_fields(outcome) -> dict:
    return {
        "reconciled": {
            name: verdict
            for name, verdict in outcome.reconciled.items()
            if verdict in (sync_mod.BEHIND, sync_mod.DIVERGED)
        },
        "restacked": outcome.restacked,
    }


def _sync_line(outcome, remote: str, pushed: bool) -> str:
    """What the run amounted to, in the order a reader wants it: what came
    down, what moved here, what went up."""
    took = [
        name
        for name, verdict in outcome.reconciled.items()
        if verdict in (sync_mod.BEHIND, sync_mod.DIVERGED)
    ]
    parts = [
        f"{len(took)} branch(es) reconciled with {remote}",
        f"{len(outcome.restacked)} restacked",
    ]
    if pushed:
        parts.append(
            f"{len(outcome.touched)} pushed"
            + (f" ({len(outcome.forced)} forced)" if outcome.forced else "")
        )
    return "; ".join(parts)


# ------------------------------------------------------------------ init
def init(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Prepare this clone: install the guard and the Change-Id hook, check the
    tools."""
    gh.require_binaries()
    gh.require_repo(runner)
    # Said whatever the outcome, because a clone with the guard and without the
    # extension is half-prepared in a way that only shows up at submit time.
    extension = "gh-stack" in runner.run(["gh", "extension", "list"], check=False)
    if not extension:
        out.warn(
            "the `gh stack` extension is not installed: "
            "gh extension install github/gh-stack"
        )
    if args.check:
        found = hooks_mod.state(runner)
        return (_init_line(found, extension), {**found, "extension": extension})
    installed = hooks_mod.install(runner, args.force)
    root = hooks_mod.top_level(runner)

    def shown(path) -> str:
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)

    found = hooks_mod.state(runner)
    words = {
        hooks_mod.GUARD: "guard",
        hooks_mod.CHANGE_ID: f"Change-Id hook (Gerrit {hooks_mod.change_id_version()})",
    }
    lines = [
        f"{words[hook]} {'installed' if changed else 'already current'} at {shown(path)}"
        for hook, (path, changed) in installed.items()
    ]
    # Only what git does not track yet is asked for: in a repository that
    # committed the hooks long ago, init is the config key and nothing to
    # commit, and saying otherwise every time teaches people to skip it.
    to_commit = _untracked(runner, [shown(path) for path, _ in installed.values()])
    if to_commit:
        lines.append(
            f"commit {' and '.join(to_commit)} so "
            f"{'it arrives' if len(to_commit) == 1 else 'they arrive'} with the "
            "code; every clone still runs `tdd gsx init` once, because git never "
            "clones core.hooksPath"
        )
    if not extension:
        lines.append("the `gh stack` extension is still missing (above)")
    guard_path, guard_changed = installed[hooks_mod.GUARD]
    return (
        "\n".join(lines),
        {
            "path": str(guard_path),
            "changed": guard_changed,
            "hooks": {
                hook: {"path": str(path), "changed": changed}
                for hook, (path, changed) in installed.items()
            },
            "extension": extension,
            **found,
        },
    )


def _untracked(runner: gh.Runner, paths: list[str]) -> list[str]:
    """The ones of `paths` git does not track, in the order given."""
    tracked = set(
        runner.run(["git", "ls-files", "--", *paths], check=False).split("\n")
    )
    return [path for path in paths if path not in tracked]


def _init_line(found: dict, extension: bool) -> str:
    """What `--check` says, and the same words the refusal uses."""
    if found["protected"]:
        line = f"the guard is installed and active ({found['active']})"
        if found.get("change_id"):
            line += (
                f", and so is the Change-Id hook (Gerrit {found.get('gerrit_version')})"
            )
        else:
            line += "; the Change-Id hook is missing: `tdd gsx init` adds it"
        return line + ("" if extension else "; the `gh stack` extension is missing")
    if found["active"] == hooks_mod.ELSEWHERE:
        return (
            f"core.hooksPath is {found['hooks_path']!r}, which gsx did not set: "
            f"chain to {hooks_mod.DIRECTORY}/{hooks_mod.GUARD} and "
            f"{hooks_mod.DIRECTORY}/{hooks_mod.CHANGE_ID} from there, or "
            f"`tdd gsx init --force` to point git at {hooks_mod.DIRECTORY}"
        )
    if found["active"] == hooks_mod.REPO and found.get("guard") == "other":
        return (
            f"the guard at {hooks_mod.DIRECTORY}/{hooks_mod.GUARD} is not the one gsx "
            "ships; `tdd gsx init --force` replaces it"
        )
    return "the guard is NOT active here; `tdd gsx init` installs it"
