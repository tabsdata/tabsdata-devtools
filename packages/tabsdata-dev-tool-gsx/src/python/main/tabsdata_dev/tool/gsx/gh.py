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
import pathlib
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
    ("git", "rev-list"),
    ("git", "config"),
    # A fetch writes only remote-tracking refs, and everything that reads them
    # afterwards depends on it: skipping it under --dry-run would answer from
    # whatever was last pulled, which is the opposite of what the flag is for.
    ("git", "fetch"),
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


#: `git config KEY` reads it, `git config KEY VALUE` sets it -- and these say
#: outright that they are writing.
GIT_CONFIG_WRITES = {
    "--add",
    "--unset",
    "--unset-all",
    "--replace-all",
    "--remove-section",
    "--rename-section",
    "--edit",
    "-e",
}


def is_read_only(argv: list[str]) -> bool:
    if argv[:2] == ["git", "branch"] and GIT_BRANCH_WRITES.intersection(argv[2:]):
        return False
    if argv[:2] == ["git", "config"]:
        if GIT_CONFIG_WRITES.intersection(argv[2:]):
            return False
        return len([token for token in argv[2:] if not token.startswith("-")]) <= 1
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


# ------------------------------------------------- gh-stack's local state
def git_dir(runner: Runner) -> pathlib.Path:
    return pathlib.Path(runner.run(["git", "rev-parse", "--git-dir"])).resolve()


def read_state(runner: Runner) -> dict:
    """gh-stack's local tracking file, `<git-dir>/gh-stack`.

    The stacks it tracks, whom they sit on and which PR each branch carries.
    A checkout with no such file has no stacks, which is an empty answer rather
    than an error -- what to make of that is the caller's to decide.
    """
    path = git_dir(runner) / "gh-stack"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ToolError(f"cannot read {path}: {error}") from error


#: How a local branch stands against its copy on the remote. The words are
#: what `--format json` carries; `commands.MARKS` gives each one its symbol
#: and its colour.
#: `in-sync` is about content: after an upstream rebase the two sides can hold
#: the same changes under different shas, and that is not a difference worth a
#: symbol of its own.
IN_SYNC = "in-sync"
AHEAD = "ahead"
BEHIND = "behind"
DIVERGED = "diverged"
NO_LOCAL = "no-local-branch"


def rebase_stopped(runner: Runner) -> str:
    """The branch a `gh stack rebase` is stopped on, or `""`.

    gh-stack keeps its own session in `<git-dir>/gh-stack-rebase-state` --
    every branch's original ref, the branch that conflicted, what is left to
    replay -- and `gh stack rebase --continue|--abort` is what finishes or
    unwinds it. `move` drives that rebase, so this is how anything else knows
    the operator is in the middle of one.
    """
    path = git_dir(runner) / "gh-stack-rebase-state"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "?"
    return payload.get("conflictBranch") or payload.get("originalBranch") or "?"


def modify_in_progress(runner: Runner) -> bool:
    """`gh stack modify` keeps a session of its own, and it restructures the
    same things a move does."""
    return (git_dir(runner) / "gh-stack-modify-state").is_file()


def rebase_in_progress(runner: Runner) -> bool:
    root = git_dir(runner)
    return (root / "rebase-merge").exists() or (root / "rebase-apply").exists()


def dirty(runner: Runner) -> bool:
    """Uncommitted changes to TRACKED files; untracked ones do not survive a
    rebase any differently and are not a move's business."""
    return bool(
        runner.run(["git", "status", "--porcelain", "--untracked-files=no"]).strip()
    )


def pull_requests(runner: Runner, numbers: list[int]) -> dict:
    """The state of several PRs in ONE call, keyed by number.

    A field per PR under an alias (`p42:`), because `move` needs the state,
    merge-queue and auto-merge of every PR it is about to move before it writes
    anything, and that is one round trip whether it is two PRs or twenty.
    """
    if not numbers:
        return {}
    fields = "number state isInMergeQueue autoMergeRequest{enabledAt}"
    parts = " ".join(
        f"p{n}: pullRequest(number:{n}){{ {fields} }}" for n in sorted(set(numbers))
    )
    query = (
        "query($o:String!,$r:String!){ repository(owner:$o,name:$r){ " + parts + " } }"
    )
    owner, _, name = repo_slug(runner).partition("/")
    payload = runner.json(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"o={owner}",
            "-F",
            f"r={name}",
        ]
    )
    repository = ((payload or {}).get("data") or {}).get("repository") or {}
    return {
        number: repository[f"p{number}"]
        for number in set(numbers)
        if isinstance(repository.get(f"p{number}"), dict)
    }


def is_ancestor(runner: Runner, older: str, newer: str) -> bool:
    """Whether `older` is in `newer`'s history. `proc.run` directly, because
    the answer is the exit code and a non-zero one is an answer, not a
    failure."""
    runner.out.debug(f"$ git merge-base --is-ancestor {older} {newer}")
    result = proc.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def sha(runner: Runner, ref: str) -> str:
    """The sha `ref` resolves to, or `""` -- never a raise: half these lookups
    are asking whether a ref exists at all."""
    return runner.run(["git", "rev-parse", "-q", "--verify", ref], check=False).strip()


def stack_remote(runner: Runner) -> str:
    """The remote gh-stack pushes to: its own config key, else `origin`."""
    configured = runner.run(["git", "config", "gh-stack.remote"], check=False).strip()
    return configured or "origin"


def branch_sync(
    runner: Runner,
    branches: list[str],
    remote: str,
    trunks: dict[str, str] | None = None,
) -> dict[str, str]:
    """Each branch against `<remote>/<branch>`: in sync, ahead, behind, or both.

    Read from the remote-tracking refs, so the caller fetches first.

    Commits are compared by their **change, not their sha** (`--cherry-pick`,
    which drops any commit whose patch already exists on the other side). In a
    stacking workflow the remote copy of a branch is rewritten constantly --
    `gh stack` rebases everything above a branch that moved and force-pushes it
    -- so a raw sha comparison calls that divergence and nearly every branch
    would read `x`. Judged by content it is what it actually is: behind by
    whatever the remote genuinely gained. `x` then means the two sides hold
    different work, which is worth stopping for.

    And **the trunk's commits are not the branch's** (`--not <trunk>`): a
    branch whose local copy has been rebased onto a newer trunk carries commits
    its remote copy does not, and every one of them belongs to the trunk. Ten
    branches of a real stack read `+` for that reason with nothing local about
    them -- the two "unpushed" commits were `[TD-3364] Edition gate` and
    `[TD-3363] New tdkserver subcommand` off main. Excluding what the trunk
    already has leaves the question the symbol is meant to answer: how does
    this branch's own work compare with the copy on the remote.

    One `for-each-ref` collects every sha that could be needed, and only a
    branch whose two shas differ costs a second call. A branch with nothing on
    the remote is `AHEAD`: there is no remote copy for it to be behind.
    """
    listing = runner.run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/heads",
            f"refs/remotes/{remote}",
        ]
    )
    shas = {}
    for line in listing.splitlines():
        ref, _, sha = line.partition(" ")
        if ref and sha.strip():
            shas[ref] = sha.strip()
    # One ref per trunk, resolved once: the remote's copy is the shared
    # baseline, and the local one is the fallback for a trunk never pushed.
    bases: dict[str, str] = {}
    for trunk in set((trunks or {}).values()):
        if not trunk:
            continue
        ref = f"refs/remotes/{remote}/{trunk}"
        bases[trunk] = ref if shas.get(ref) else f"refs/heads/{trunk}"
    state = {}
    for branch in branches:
        local = shas.get(f"refs/heads/{branch}")
        tracked = shas.get(f"refs/remotes/{remote}/{branch}")
        if not local:
            state[branch] = NO_LOCAL
        elif not tracked:
            state[branch] = AHEAD
        elif local == tracked:
            state[branch] = IN_SYNC
        else:
            base = bases.get((trunks or {}).get(branch, ""), "")
            counted = runner.run(
                [
                    "git",
                    "rev-list",
                    "--left-right",
                    "--cherry-pick",
                    "--count",
                    f"{local}...{tracked}",
                    *(["--not", base] if base else []),
                ],
                check=False,
            ).split()
            ahead, behind = (
                (int(counted[0]), int(counted[1])) if len(counted) == 2 else (0, 0)
            )
            state[branch] = (
                DIVERGED
                if ahead and behind
                else AHEAD
                if ahead
                else BEHIND
                if behind
                else IN_SYNC
            )
    return state


def fetch(runner: Runner, remote: str) -> None:
    """Refresh the remote-tracking refs the sync symbols are read from."""
    runner.run(["git", "fetch", "-q", remote])


def stacks(runner: Runner, path: str = "repos/{owner}/{repo}/stacks") -> list[dict]:
    """Every stack GitHub has for this repository, from the stacks REST API.

    `gh api` fills in `{owner}` and `{repo}` from the checkout itself, so this
    costs one round trip and needs no `gh repo view` before it. A stack comes
    back as `{number, base: {ref}, open, pull_requests: [...]}` with the PRs in
    stack order, bottom-up, each `{number, state, merged_at, head: {ref, sha}}`
    -- verified against a real repository; see DESIGN.md.

    This is the only thing `stack` cannot read from the tracking file: what
    GitHub has that the file does not. A closed stack is still returned, so the
    caller filters on `open`.
    """
    payload = runner.json(["gh", "api", "--paginate", f"{path}?per_page=100"])
    if isinstance(payload, list):
        # --paginate concatenates pages; a single page is already a list
        if payload and isinstance(payload[0], list):
            return [stack for page in payload for stack in page]
        return payload
    raise ToolError(f"could not list the stacks of {path}")


def pr_titles(runner: Runner, numbers: list[int]) -> dict[int, str]:
    """The title of each PR, for `stack --summary`.

    gh-stack's state file carries a branch's PR number and url but not its
    title, so this is the one part of `stack` that needs the network. One
    listing answers a normal repository; a number it did not reach -- a PR
    older than the limit, which a long-lived stack can have -- is asked for on
    its own. An answer that cannot be had is left out rather than fatal: the
    numbers are still worth printing.
    """
    if not numbers:
        return {}
    wanted = set(numbers)
    found: dict[int, str] = {}
    listing = runner.json(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "200",
            "--json",
            "number,title",
        ]
    )
    for pull in listing if isinstance(listing, list) else []:
        if pull.get("number") in wanted and pull.get("title"):
            found[pull["number"]] = pull["title"]
    for number in sorted(wanted - set(found)):
        payload = runner.json(["gh", "pr", "view", str(number), "--json", "title"])
        if isinstance(payload, dict) and payload.get("title"):
            found[number] = payload["title"]
    return found


# `move` drives these four, and every one of them is LOCAL: gh-stack's own
# commands, writing branches and its own tracking file and nothing else.
# `gsx submit --move` is what reaches GitHub, and it is a separate decision.
def checkout(runner: Runner, branch: str) -> None:
    runner.run(["git", "checkout", "-q", branch])


def stack_checkout(runner: Runner, branch: str) -> None:
    """gh-stack's checkout, which switches branch AND makes that stack the
    active one -- which is what `unstack --local` then acts on."""
    runner.run(["gh", "stack", "checkout", branch], capture=False)


def stack_unstack_local(runner: Runner) -> None:
    """Drop the active stack's LOCAL tracking. `--local` is the whole point:
    the same command without it dissolves the stack on GitHub."""
    runner.run(["gh", "stack", "unstack", "--local"], capture=False)


def stack_init(runner: Runner, branches: list[str], base: str = "") -> None:
    """Track `branches` (bottom-up) as a stack on `base`, adopting them as they
    are.

    Local: it opens no PR and pushes nothing, and it records each branch's base
    as the tip its commits really sit on -- which is what makes the rebase that
    follows replay the right range. It refuses a branch that is already in a
    tracked stack, which is why the old stacks are forgotten first.
    """
    argv = ["gh", "stack", "init"]
    if base:
        argv += ["--base", base]
    runner.run([*argv, *branches], capture=False)


def state_text(runner: Runner) -> str | None:
    """gh-stack's tracking file exactly as it sits on disk, or None if there is
    none -- a snapshot `write_state` can put back byte for byte."""
    path = git_dir(runner) / "gh-stack"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ToolError(f"cannot read {path}: {error}") from error


def write_state(runner: Runner, text: str | None) -> None:
    """Put `<git-dir>/gh-stack` back to a snapshot of itself, and nothing else.

    gh-stack owns this file: every forward change goes through `gh stack init`
    and `gh stack unstack --local`, which record the bases and numbers this
    code has no business inventing. Restoring the exact text that was read from
    it is the one exception, and it is what lets `move --abort` put the stacks
    back together: a rearrangement cannot be run backwards, but it can be
    replaced by what was there before, down to the bytes. `None` means there
    was no file, so there is none after.
    """
    path = git_dir(runner) / "gh-stack"
    if runner.dry_run:
        runner.out.info(f"[dry-run] restore {path}", dry_run=True)
        return
    if text is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_suffix(".gsx-tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def rebase_continue(runner: Runner) -> None:
    """Carry on the rebase the operator has just resolved. GIT_EDITOR is off:
    `--continue` opens the commit message otherwise, and the message is the one
    the commit already had."""
    runner.run(["git", "rebase", "--continue"], env={"GIT_EDITOR": "true"})


def rebase_abort(runner: Runner) -> None:
    runner.run(["git", "rebase", "--abort"], check=False)


def stack_rebase_continue(runner: Runner) -> None:
    """gh-stack's own continue: it knows which branch of the cascade stopped
    and what is left of it."""
    runner.run(["gh", "stack", "rebase", "--continue"], capture=False)


def stack_rebase_abort(runner: Runner) -> None:
    """Restores every branch the cascade had replayed, from its own snapshot --
    but not one this command replayed before handing over."""
    runner.run(["gh", "stack", "rebase", "--abort"], capture=False, check=False)


def set_branch(runner: Runner, branch: str, commit: str) -> None:
    runner.run(["git", "branch", "-f", branch, commit])


def reset_hard(runner: Runner, commit: str) -> None:
    runner.run(["git", "reset", "-q", "--hard", commit])


def rebase_onto(runner: Runner, onto: str, upstream: str, branch: str) -> None:
    """Replay `upstream..branch` onto `onto`, with plain git.

    The one rebase gh-stack will not do: onto the TRUNK. `--no-trunk` skips it
    by name ("only the inter-branch rebases are performed") and the forms that
    include the trunk pull from the remote first, which a local command has no
    business doing -- it would also leave the moved branches on a newer trunk
    than everything around them. rerere is on, so a conflict the operator has
    resolved once elsewhere resolves itself.
    """
    runner.run(
        ["git", "-c", "rerere.enabled=true", "rebase", "--onto", onto, upstream, branch]
    )


def stack_rebase_upstack(runner: Runner) -> None:
    """Cascade-rebase everything ABOVE the current branch, trunk untouched.

    `--no-trunk` is what keeps it offline: with the trunk it fetches first.
    `--upstack` is what keeps it to the move's own business -- it rebases the
    branches above the one checked out and not that one, so standing on the
    branch the moved ones were put on top of makes the scope exactly what
    moved. Without it the cascade starts at the bottom of the stack, and on a
    stack whose lower branches were already inconsistent that means real,
    conflicting work that has nothing to do with the move.

    A conflict stops with `gh stack rebase --continue|--abort` as the two ways
    out, and gh-stack holds every branch's original ref for the abort.
    """
    runner.run(["gh", "stack", "rebase", "--upstack", "--no-trunk"], capture=False)


def stack_unstack(runner: Runner, number: int) -> None:
    """Dissolve a stack ON GITHUB, by number, from anywhere in the repository.

    The only command `gsx` runs that cannot be undone, and it is `submit
    --move` that runs it. Unstack takes no body -- it dissolves the whole stack
    or nothing -- and GitHub leaves a queued or auto-merging PR stacked, in
    which case it KEEPS the stack; the caller checks for that rather than
    assuming.
    """
    runner.run(["gh", "stack", "unstack", str(number)], capture=False)
