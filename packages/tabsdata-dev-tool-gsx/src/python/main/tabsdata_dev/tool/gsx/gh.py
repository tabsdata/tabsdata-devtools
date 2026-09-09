#
# Copyright 2026 Tabsdata Inc.
#

"""Everything gsx asks of `git`, `gh` and the gh-stack extension.

One place runs the child processes, so `--dry-run` and `--verbose` are decided
once: a read-only command always runs (validation must be exercised even in a
dry run), a mutating one is announced and skipped. Every fact below was
verified against the real tools -- see DESIGN.md for the ones that are not
obvious from their help.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass

from tabsdata_dev.common.core import proc
from tabsdata_dev.common.core.errors import ToolError

# Commands with no side effect: run even under --dry-run, so the run still
# validates against the real repository.
READ_ONLY_PAIRS = {
    ("git", "rev-parse"),
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "branch"),
    ("git", "for-each-ref"),
    ("git", "ls-files"),
    ("gh", "repo"),
    ("gh", "auth"),
    ("gh", "extension"),
    ("gh", "label"),
    ("gh", "api"),
}
READ_ONLY_TRIPLES = (
    ["gh", "stack", "view"],
    ["gh", "pr", "view"],
    ["gh", "pr", "list"],
)

#: `git branch` with no flags lists, which is why it is in the pairs above --
#: but the same word deletes and renames, and a dry run that skipped the
#: listing while running the delete would be the one mistake it exists to
#: prevent. Flags, not subcommands, decide here.
GIT_BRANCH_WRITES = {
    "-d",
    "-D",
    "--delete",
    "-m",
    "-M",
    "--move",
    "-c",
    "-C",
    "--copy",
    "-u",
    "--set-upstream-to",
    "--unset-upstream",
    "--edit-description",
}


def is_read_only(argv: list[str]) -> bool:
    if argv[:2] == ["git", "branch"] and GIT_BRANCH_WRITES.intersection(argv[2:]):
        return False
    return tuple(argv[:2]) in READ_ONLY_PAIRS or argv[:3] in READ_ONLY_TRIPLES


def join(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


@dataclass
class Runner:
    """Runs the tools, and is the only thing that knows about --dry-run."""

    out: object
    dry_run: bool = False

    def run(
        self,
        argv: list[str],
        *,
        capture: bool = True,
        check: bool = True,
        stdin_text: str | None = None,
        dry_value: str = "",
        env: dict | None = None,
    ) -> str:
        if self.dry_run and not is_read_only(argv):
            self.out.info(f"[dry-run] {join(argv)}", dry_run=True, argv=argv)
            if stdin_text:
                self.out.info(f"[dry-run] stdin:\n{stdin_text.rstrip()}")
            return dry_value
        self.out.debug(f"$ {join(argv)}")
        if stdin_text:
            self.out.debug(f"| {stdin_text.rstrip()}")
        try:
            result = proc.run(
                argv,
                capture_output=capture,
                text=True,
                input=stdin_text,
                check=check,
                **({"env": env} if env is not None else {}),
            )
        except FileNotFoundError as error:
            raise ToolError(f"command not found: {argv[0]} ({error})") from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or "").strip()
            raise ToolError(
                f"`{join(argv)}` failed (exit {error.returncode})"
                + (f": {detail}" if detail else "")
            ) from error
        return (result.stdout or "").strip() if capture else ""

    def json(self, argv: list[str]) -> dict | list | None:
        """A read-only JSON command; None when it fails, so a caller can treat
        "no answer" and "not applicable" alike."""
        self.out.debug(f"$ {join(argv)}")
        result = proc.run(argv, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None


def require_binaries() -> None:
    """git and gh. `bin-reqs.txt` covers both before the command runs; this is
    the check for a subcommand that needs them without needing gh-stack."""
    for binary in ("git", "gh"):
        if shutil.which(binary) is None:
            raise ToolError(f"`{binary}` is not on PATH")


def require_tools(runner: Runner) -> None:
    """git, gh and the gh-stack extension. bin-reqs.txt covers the first two
    before the command runs; the extension is a gh install, not a binary."""
    require_binaries()
    extensions = runner.run(["gh", "extension", "list"], check=False)
    if "gh-stack" not in extensions:
        raise ToolError(
            "the `gh stack` extension is not installed: "
            "gh extension install github/gh-stack"
        )


def require_repo(runner: Runner) -> None:
    runner.run(["git", "rev-parse", "--git-dir"])


def repo_name(runner: Runner) -> str:
    payload = runner.run(["gh", "repo", "view", "--json", "name"])
    try:
        return json.loads(payload)["name"]
    except (json.JSONDecodeError, KeyError) as error:
        raise ToolError(
            f"could not read the repository name from gh: {payload}"
        ) from error


def repo_slug(runner: Runner) -> str:
    payload = runner.run(["gh", "repo", "view", "--json", "nameWithOwner"])
    try:
        return json.loads(payload)["nameWithOwner"]
    except (json.JSONDecodeError, KeyError) as error:
        raise ToolError(f"could not read the repository from gh: {payload}") from error


def repo_url(runner: Runner) -> str:
    """The repository's web URL, from gh rather than composed, so an enterprise
    host is right too."""
    payload = runner.run(["gh", "repo", "view", "--json", "url"])
    try:
        return json.loads(payload)["url"].rstrip("/")
    except (json.JSONDecodeError, KeyError, AttributeError) as error:
        raise ToolError(
            f"could not read the repository URL from gh: {payload}"
        ) from error


def repo_postfix(name: str) -> str:
    """`tabsdata-conn-gcs` -> `GCS`; a name without `-` is used whole."""
    tail = name.rsplit("-", 1)[-1] if "-" in name else name
    postfix = re.sub(r"[^A-Za-z0-9]", "", tail).upper()
    if not postfix:
        raise ToolError(f"cannot derive a branch prefix from repository name {name!r}")
    return postfix


def current_branch(runner: Runner) -> str:
    return runner.run(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def stack_state(runner: Runner) -> dict | None:
    state = runner.json(["gh", "stack", "view", "--json"])
    return state if isinstance(state, dict) else None


def in_stack(runner: Runner) -> bool:
    """True when HEAD is a stack branch to layer on top of.

    Standing on the trunk reads as "no stack": `gh stack view` succeeds there
    once any stack exists, so the exit code alone would make a second stack
    impossible -- it would add onto the first.
    """
    state = stack_state(runner)
    if state is None:
        return False
    return state.get("currentBranch") != state.get("trunk")


def current_pr(runner: Runner) -> int | None:
    payload = runner.json(["gh", "pr", "view", "--json", "number"])
    try:
        return int(payload["number"]) if payload else None
    except (KeyError, TypeError, ValueError):
        return None


def pr_body_footer(runner: Runner, number: int) -> str:
    """The `---` footer gh-stack appends to a PR body, so an edit keeps it."""
    payload = runner.json(["gh", "pr", "view", str(number), "--json", "body"])
    body = (payload or {}).get("body") or "" if isinstance(payload, dict) else ""
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[index:])
    return ""


def stack_pr_snapshot(runner: Runner) -> list[dict]:
    """Every stack branch with an open PR, bottom of the stack first.

    One `gh pr list` supplies the metadata; the stack supplies the order,
    which `gh pr list` does not know.
    """
    state = stack_state(runner) or {}
    order = [branch.get("name") for branch in state.get("branches", [])]
    listing = (
        runner.json(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                "number,headRefName,author,labels,reviewRequests",
            ]
        )
        or []
    )
    by_branch = {pull.get("headRefName"): pull for pull in listing}
    snapshot: list[dict] = []
    for branch in order:
        pull = by_branch.get(branch)
        if not pull:
            continue
        snapshot.append(
            {
                "branch": branch,
                "number": int(pull["number"]),
                "author": (pull.get("author") or {}).get("login", ""),
                "labels": [item["name"] for item in pull.get("labels") or []],
                "reviewers": [
                    item.get("login") or item.get("slug", "")
                    for item in pull.get("reviewRequests") or []
                ],
            }
        )
    return snapshot


def me(runner: Runner) -> str:
    return runner.run(["gh", "api", "user", "--jq", ".login"], check=False)


def fetch_labels(runner: Runner) -> list[str]:
    listing = (
        runner.json(["gh", "label", "list", "--limit", "500", "--json", "name"]) or []
    )
    return sorted({item.get("name", "") for item in listing if item.get("name")})


def fetch_reviewers(runner: Runner, slug: str) -> list[str]:
    """Collaborators plus assignable users.

    The two overlap but neither contains the other: `collaborators` needs push
    access and can 403, `assignableUsers` is what GitHub's own reviewer picker
    offers. Union them, so a valid login is never rejected for coming from the
    list gsx did not ask for.
    """
    found: set[str] = set()
    owner, _, name = slug.partition("/")
    listing = runner.json(
        ["gh", "api", f"repos/{owner}/{name}/collaborators", "--paginate"]
    )
    for item in listing or []:
        if isinstance(item, dict) and item.get("login"):
            found.add(item["login"])
    graph = runner.json(
        [
            "gh",
            "api",
            "graphql",
            "--paginate",
            "-f",
            "query=query($owner:String!,$name:String!,$endCursor:String){"
            "repository(owner:$owner,name:$name){assignableUsers(first:100,after:$endCursor)"
            "{nodes{login} pageInfo{hasNextPage endCursor}}}}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
        ]
    )
    if isinstance(graph, dict):
        nodes = (
            graph.get("data", {})
            .get("repository", {})
            .get("assignableUsers", {})
            .get("nodes", [])
        )
        for node in nodes:
            if node.get("login"):
                found.add(node["login"])
    return sorted(found)


def pending_paths(runner: Runner, paths: list[str]) -> list[str]:
    """What git would commit: the given paths, or everything pending."""
    argv = ["git", "status", "--porcelain", "--untracked-files=all"]
    if paths:
        argv.append("--")
        argv.extend(paths)
    return [line[3:] for line in runner.run(argv).splitlines() if line.strip()]


# --------------------------------------------------------------- purge
def fetch_prune(runner: Runner) -> None:
    """`git fetch --prune`. Not what tells purge a PR is done with -- that comes
    from the API, live -- so it is hygiene, which is why skipping it under
    --dry-run costs the run no accuracy."""
    runner.run(["git", "fetch", "--prune"])


def default_branch(runner: Runner) -> str:
    """The repository's default branch, or `""` when gh cannot say.

    Read rather than assumed, because `main` is a convention and the trunk is
    a fact; `""` is safe because the names that are never candidates are a
    separate list.
    """
    payload = runner.json(["gh", "repo", "view", "--json", "defaultBranchRef"])
    ref = (payload or {}).get("defaultBranchRef") or {} if payload else {}
    return ref.get("name") or ""


def local_branches(runner: Runner) -> list[str]:
    """Every local branch, in git's own order."""
    listing = runner.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"]
    )
    return [line.strip() for line in listing.splitlines() if line.strip()]


def prs_by_branch(runner: Runner, limit: int = 500) -> dict[str, list[dict]]:
    """Every PR of the repository, indexed by the branch it was opened from.

    One call answers every branch of a normal repository, instead of the one
    call per branch the shell loop this replaces made. The value is a LIST
    because a branch can carry several PRs -- reopened, or a second attempt
    after the first was closed -- and which of them is the live one is the
    whole question purge has to answer.
    """
    listing = (
        runner.json(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--limit",
                str(limit),
                "--json",
                "number,headRefName,state",
            ]
        )
        or []
    )
    found: dict[str, list[dict]] = {}
    for pull in listing:
        branch = pull.get("headRefName")
        if branch:
            found.setdefault(branch, []).append(pull)
    return found


def branch_prs(runner: Runner, branch: str) -> list[dict]:
    """The PR of one branch, for a branch the bulk listing did not reach.

    A repository with more PRs than the listing's limit leaves its oldest out,
    and those are exactly the merged ones whose branches are still lying
    around. `gh pr view BRANCH` answers for one branch whatever its age.
    """
    payload = runner.json(["gh", "pr", "view", branch, "--json", "number,state"])
    if isinstance(payload, dict) and payload.get("state"):
        return [payload]
    return []


def delete_branch(runner: Runner, branch: str) -> None:
    """`-D`, not `-d`.

    `-d` refuses a branch whose commits are not ancestors of the trunk, which
    is every squash- and rebase-merged branch -- so it would refuse exactly the
    branches purge exists to remove, and every closed one besides. `--dry-run`
    is what shows the list before anything goes.
    """
    runner.run(["git", "branch", "-D", branch])
