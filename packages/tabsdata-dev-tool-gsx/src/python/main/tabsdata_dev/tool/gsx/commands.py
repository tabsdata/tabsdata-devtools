#
# Copyright 2026 Tabsdata Inc.
#

"""The six subcommands. Each returns (message, fields) for one ok event."""

from __future__ import annotations

import re
import sys

from tabsdata_dev.common.core.errors import ToolError

from . import config as config_mod
from . import gh
from . import labels as labels_mod
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
def checkout(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """`gh stack checkout` by branch, PR number, PR URL or stack number."""
    gh.require_tools(runner)
    target = args.target
    out.info(f"checking out {target or 'a stack (interactive picker)'}")
    argv = ["gh", "stack", "checkout"]
    if target:
        argv.append(target)
    argv.extend(extras.passthrough.get("c", []))
    runner.run(argv, capture=False)
    if runner.dry_run:
        return ("checked out nothing (dry run)", {"dry_run": True})
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

    if args.sync or extras.passthrough.get("s"):
        out.info("syncing the stack with the remote")
        runner.run(
            ["gh", "stack", "sync", *extras.passthrough.get("s", [])], capture=False
        )

    out.info("pushing the stack and opening PRs")
    argv = ["gh", "stack", "submit", "--auto"]
    if not args.draft:
        argv.append("--open")
    argv.extend(extras.passthrough.get("p", []))
    runner.run(argv, capture=False)

    changed, failures = 0, []
    ops = labels_mod.with_defaults(repo, extras.lr_ops, args.no_defaults)
    if ops or extras.passthrough.get("e"):
        out.info(f"applying {len(ops)} label/reviewer op(s)")
        changed, failures = labels_mod.apply(
            runner, repo, ops, extras.passthrough.get("e", []), out
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
            "or set default_labels/default_reviewers in the config "
            "(tdd gsx auto-config --help)"
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


# ------------------------------------------------------------- auto-config
def auto_config(args, out, runner: gh.Runner, extras: Extras) -> tuple[str, dict]:
    """Refresh this repository's valid labels and reviewers in the config."""
    gh.require_tools(runner)
    repo = labels_mod.Repo(runner, out)
    entry = repo.refresh()
    return (
        f"{len(entry.get('labels', []))} label(s), "
        f"{len(entry.get('reviewers', []))} reviewer(s) for {repo.slug}\n"
        f"  config     {config_mod.path()}\n"
        f"  repo       {repo.slug}",
        {
            "config": str(config_mod.path()),
            "repo": repo.slug,
            "labels": len(entry.get("labels", [])),
            "reviewers": len(entry.get("reviewers", [])),
        },
    )
