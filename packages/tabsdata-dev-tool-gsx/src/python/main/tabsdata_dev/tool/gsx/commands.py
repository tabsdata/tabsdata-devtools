#
# Copyright 2026 Tabsdata Inc.
#

"""The eight subcommands. Each returns (message, fields) for one ok event."""

from __future__ import annotations

import re
import sys

from tabsdata_dev.common.core import render
from tabsdata_dev.common.core.errors import ToolError

from . import approve as approve_mod
from . import config as config_mod
from . import gh
from . import labels as labels_mod
from . import progress
from . import purge as purge_mod
from .args import Extras

TRAILER_RE = re.compile(r"^\s*(?:closes|fixes|resolves)\s+#(\d+)\s*$", re.IGNORECASE)


def build_message(tag: str, summary: str, body: str | None, issue: int) -> str:
    parts = [f"[{tag}] {summary}"]
    if body:
        parts.append(body.strip())
    parts.append(f"Closes #{issue}")
    return "\n\n".join(parts) + "\n"


def split_message(message: str) -> tuple[str, str, str]:
    """A commit message as (subject, body, trailers)."""
    lines = message.rstrip("\n").split("\n")
    subject = lines[0] if lines else ""
    rest = lines[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    trailers: list[str] = []
    while rest and (TRAILER_RE.match(rest[-1]) or not rest[-1].strip()):
        candidate = rest.pop()
        if candidate.strip():
            trailers.insert(0, candidate.strip())
    return subject, "\n".join(rest).strip(), "\n".join(trailers).strip()


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
        "  not pushed yet: use `tdd gsx submit` to push the stack and open the PR",
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
    new_message = build_message(tag, new_summary, new_body, issue)

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


def checkout(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """`gh stack checkout` by branch name or `#<PR>`, and nothing else."""
    # Parsed before anything is asked of gh: a target gsx will not accept is a
    # usage error, and it costs no child process to say so.
    kind, value = parse_checkout_target(args.target) if args.target else ("", "")

    gh.require_tools(runner)
    argv = ["gh", "stack", "checkout"]
    if kind == "pr":
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
    argv.extend(extras.passthrough.get("c", []))
    runner.run(argv, capture=False)
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
def submit(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Push the stack, open its PRs, then apply the label/reviewer ops."""
    gh.require_tools(runner)
    repo = labels_mod.Repo(runner, out)

    # How many PRs there will be is not known until they have been pushed --
    # the first submit of a stack opens them -- so this run counts [n] and
    # never a denominator it would have to guess. The push and the sync are
    # units of it too: they are the slowest thing gsx does.
    steps = progress.Counter(out)

    if args.sync or extras.passthrough.get("s"):
        runner.run(
            ["gh", "stack", "sync", *extras.passthrough.get("s", [])], capture=False
        )
        steps.step("synced the stack with the remote", stage="sync")

    argv = ["gh", "stack", "submit", "--auto"]
    if not args.draft:
        argv.append("--open")
    argv.extend(extras.passthrough.get("p", []))
    runner.run(argv, capture=False)
    steps.step("pushed the stack and opened its PRs", stage="push")

    changed, failures = 0, []
    ops = labels_mod.with_defaults(repo, extras.lr_ops, args.no_defaults)
    if ops or extras.passthrough.get("e"):
        out.info(f"applying {len(ops)} label/reviewer op(s)")
        changed, failures = labels_mod.apply(
            runner, repo, ops, extras.passthrough.get("e", []), out, steps
        )
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


# ------------------------------------------------------------------ stacks
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


def stack_rows(state: dict, current: str = "", sync: dict | None = None) -> list[dict]:
    """Every locally tracked stack, bottom-up, as `{number, trunk, branches}`.

    Straight out of gh-stack's own state file: no API call, so this answers
    while offline and cannot disagree with what the other subcommands read. A
    stack with no number yet (never submitted) keeps `None`, which prints `#-`.
    Each branch carries how it stands against the remote (`sync`), which is
    what the symbol and the colour in front of its name say, and the number of
    its PR (`pr`, `None` for a branch that has none yet).
    """
    sync = sync or {}
    rows = []
    for stack in state.get("stacks") or []:
        branches = [
            {
                "name": entry["branch"],
                "pr": (entry.get("pullRequest") or {}).get("number"),
                "sync": sync.get(entry["branch"], gh.NO_LOCAL),
                "current": bool(current) and entry["branch"] == current,
            }
            for entry in stack.get("branches") or []
            if entry.get("branch")
        ]
        rows.append(
            {
                "number": stack.get("number"),
                "trunk": ((stack.get("trunk") or {}).get("branch")) or "?",
                "branches": branches,
                "current": any(branch["current"] for branch in branches),
            }
        )
    return rows


def _no_paint(name: str, text: str) -> str:
    return text


def stack_lines(rows: list[dict], paint=_no_paint) -> str:
    """One line per stack, every name aligned across all of them:

            [#34]  main <- =insync   <-[+ahead]
             #40   main <- -behind   <- xdiverged
             #-    main <- +unpushed <- ?gone

        Each branch carries one symbol saying how it stands against the remote --
        `=` in sync, `+` ahead, `-` behind, `x` diverged, `?` no local branch --
        and takes that state's colour.

        **White square brackets** mark what is current: the stack holding the
        checked-out branch, the one `submit` and `apply` act on without being told
        which, and that branch. Brackets rather than a colour, because every colour
        here already means a sync state; and one convention for both, because they
        are the same fact said at two scales.

    Every cell reserves one slot on each side for a
        bracket, and those two slots are the spaces around `<-` -- so a bracketed
        cell is exactly as wide as a plain one, a name is at the same offset on
        every line whether it is bracketed or not, and the brackets cost the column
        nothing. Widths are the widest symbol-and-name; a row's own last cell is
        left unpadded, so no line carries trailing blanks.

        Painted per CELL rather than per row: a paint ends in a reset, so one
        coloured branch would otherwise leave everything after it plain.
    """
    tags = ["#" + (str(row["number"]) if row["number"] else "-") for row in rows]
    tag_width = max((len(tag) for tag in tags), default=0)
    # (text, paint, current) per cell, the trunk first and unmarked
    grid = [
        [
            (row["trunk"], "", False),
            *(
                (
                    f"{MARKS[branch['sync']][0]}{branch['name']}",
                    MARKS[branch["sync"]][1],
                    branch["current"],
                )
                for branch in row["branches"]
            ),
        ]
        for row in rows
    ]
    widths = [
        max(len(cells[column][0]) for cells in grid if len(cells) > column)
        for column in range(max((len(cells) for cells in grid), default=0))
    ]
    lines = []
    for tag, row, cells in zip(tags, rows, grid):
        if row["current"]:
            head = f"{paint('white', '[')}{tag:<{tag_width}}{paint('white', ']')}"
        else:
            head = f" {tag:<{tag_width}} "
        parts = [head, "  "]
        for index, (text, color, current) in enumerate(cells):
            last = index == len(cells) - 1
            painted = paint(color, text) if color else text
            if index:
                # `<-` carries no space of its own: the brackets' two slots are
                # the spaces around it, which is what keeps a bracketed cell
                # exactly as wide as a plain one.
                parts.append("<-" + (paint("white", "[") if current else " "))
            cell = painted + (paint("white", "]") if current else "")
            if not last:
                pad = " " * (widths[index] - len(text))
                cell += pad if current else pad + " "
            parts.append(cell)
        lines.append("".join(parts))
    return "\n".join(lines)


def stack_summary(rows: list[dict], titles: dict, paint=_no_paint) -> str:
    """One line per branch, with its PR number and title beside it:

        [#34]  main
                =insync   #21  the loader
               [+ahead]   #22  wire it up

    The stack's own line names it and its trunk; each branch sits under it with
    the same symbol, colour and brackets the one-line form uses, so the two
    views never disagree about what a branch is. Columns are measured across
    every stack being shown, not per stack, so the numbers and titles line up
    down the whole page.
    """
    tags = ["#" + (str(row["number"]) if row["number"] else "-") for row in rows]
    tag_width = max((len(tag) for tag in tags), default=0)
    cells = [
        f"{MARKS[branch['sync']][0]}{branch['name']}"
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
    indent = " " * (tag_width + 3)
    blocks = []
    for tag, row in zip(tags, rows):
        if row["current"]:
            head = f"{paint('white', '[')}{tag:<{tag_width}}{paint('white', ']')}"
        else:
            head = f" {tag:<{tag_width}} "
        lines = [f"{head}  {row['trunk']}"]
        for branch in row["branches"]:
            symbol, color = MARKS[branch["sync"]]
            text = f"{symbol}{branch['name']}"
            painted = paint(color, text) if color else text
            pad = " " * (name_width - len(text))
            if branch["current"]:
                cell = paint("white", "[") + painted + paint("white", "]") + pad
            else:
                cell = " " + painted + pad + " "
            ref = refs[id(branch)]
            title = titles.get(branch["pr"], "") if branch["pr"] else ""
            lines.append(f"{indent}{cell} {ref:<{ref_width}}  {title}".rstrip())
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def legend(rows: list[dict], remote: str, paint=_no_paint, fetched: bool = True) -> str:
    """One line under the listing saying what the symbols and colours mean.

    Each symbol is printed in its own colour, so the legend demonstrates the
    thing it is explaining rather than describing it twice. `?` earns its place
    only when a row actually uses it. Not fetching first IS said, because every
    symbol is then a claim about the remote as it was rather than as it is.
    """
    states = list(LEGEND)
    if any(branch["sync"] == gh.NO_LOCAL for row in rows for branch in row["branches"]):
        states.append(gh.NO_LOCAL)
    marks = [
        f"{paint(MARKS[state][1], MARKS[state][0])} {WORDS[state]}" for state in states
    ]
    # the two `*` markers, explained where the eye already is rather than on a
    # line of their own
    marks.append(f"{paint('white', '[]')} current")
    line = f"  {'  '.join(marks)}"
    # The remote is not named -- it is `git config gh-stack.remote` and the
    # reader knows their own. Staleness is another matter: with --no-fetch
    # every symbol is about the remote as it WAS, and that has to be said.
    return line if fetched else f"{line}   (as of the last fetch)"


def _painter(out):
    """How `stacks` paints, given where its ok event is going.

    json carries the message as data, so an escape in it would be data too --
    the fields say how every branch stands, and a machine reads those. On view
    `render.paint` still checks the stream and NO_COLOR itself.
    """
    if out.fmt != "view":
        return _no_paint
    return lambda name, text: render.paint(name, text, out.out)


def stack(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """The stack you are on, or every stack with `--all`."""
    # gh-stack's extension is never needed; `gh` itself only for the PR titles
    # the default prints, which `--short` does not ask for.
    gh.require_repo(runner)
    remote = gh.stack_remote(runner)
    if not args.no_fetch:
        # Unannounced: it is a precondition of the answer, not a step of its
        # own, and a line about it would be the first thing on every run.
        gh.fetch(runner, remote)
    current = gh.current_branch(runner)
    every = stack_rows(gh.read_state(runner), current)
    if not every:
        return ("no stacks are tracked in this repository", {"stacks": []})
    rows = every if args.all else [row for row in every if row["current"]]
    if not rows:
        # Asked about "my stack" while standing outside every one of them: an
        # answer, and the useful half of it is that --all would show them.
        return (
            f"{current!r} is not in a tracked stack; --all lists the "
            f"{len(every)} there {'is' if len(every) == 1 else 'are'}",
            {"stacks": [], "remote": remote, "fetched": not args.no_fetch},
        )
    # Only the branches actually being shown are compared against the remote,
    # so the default costs one `rev-list` per out-of-sync branch of one stack.
    sync = gh.branch_sync(
        runner,
        [branch["name"] for row in rows for branch in row["branches"]],
        remote,
    )
    for row in rows:
        for branch in row["branches"]:
            branch["sync"] = sync.get(branch["name"], gh.NO_LOCAL)
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
    header = f"{len(rows)} stack(s):\n" if args.all else ""
    return (
        header
        + body
        # a blank line on each side: the legend is a key to what is above it,
        # not another row of it
        + "\n\n"
        + legend(rows, remote, paint, fetched=not args.no_fetch)
        + "\n",
        {"stacks": rows, "remote": remote, "fetched": not args.no_fetch},
    )
