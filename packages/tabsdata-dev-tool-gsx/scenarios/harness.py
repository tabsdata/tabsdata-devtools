#
# Copyright 2026 Tabsdata Inc.
#

"""Scenario harness: drives real gsx/gh/git in three clones of one GitHub repo
and asserts what every user ends up with. Each scenario uses its own branch
prefix and cleans up after itself, so they can run in any order and be replayed.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time
import traceback

#: Where the clones live -- outside the checkout, since they are throwaway
#: repositories of their own. The repo they clone is throwaway too.
ROOT = pathlib.Path(os.environ.get("GSX_SCENARIOS_DIR", "/tmp/gsx-scenarios")).resolve()
TDD = os.path.expanduser(os.environ.get("TDD_EXE", "~/.tdd/tdd-venvs/tdd/bin/tdd-exe"))
REPO = os.environ.get("GSX_SCENARIOS_REPO", "tabsdata/gsx-scenarios")
CLONES = ["alice", "bob", "carol"]
ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GH_PROMPT_DISABLED": "1",
    "NO_COLOR": "1",
}


class Fail(Exception):
    pass


# ----------------------------------------------------------------- running
def sh(who, argv, check=True, timeout=420, env=None, input=None):
    cwd = ROOT / who if who else ROOT
    r = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**ENV, **(env or {})},
        input=input,
    )
    out = (r.stdout or "") + (r.stderr or "")
    LOG.append(f"$ [{who}] {' '.join(str(a) for a in argv)}\n{out}")
    if check and r.returncode != 0:
        raise Fail(f"[{who}] {' '.join(argv)} -> exit {r.returncode}\n{out[-2500:]}")
    return r.returncode, out


def git(who, *args, check=True):
    return sh(who, ["git", *args], check=check)


def out(who, *args):
    return git(who, *args)[1].strip()


def gsx(who, *args, check=True, env=None, input=None):
    rc, o = sh(who, [TDD, "gsx", *args], check=check, env=env, input=input)
    return rc, o


def gs(who, *args, check=True, input=None):
    return sh(who, ["gh", "stack", *args], check=check, input=input)


def gh_json(*args):
    rc, o = sh(None, ["gh", *args], check=True)
    return json.loads(o)


# ------------------------------------------------------------- repo state
def sha(who, ref):
    rc, o = git(who, "rev-parse", "--verify", "--quiet", ref, check=False)
    return o.strip() if rc == 0 else ""


def subjects(who, rng):
    return [line for line in out(who, "log", "--format=%s", rng).splitlines() if line]


def fetch(who):
    git(who, "fetch", "-q", "origin", "--prune")


def is_ancestor(who, a, b):
    return git(who, "merge-base", "--is-ancestor", a, b, check=False)[0] == 0


def write_commit(who, branch, subject, filename=None, content=None):
    """Append a line to a file on `branch` and commit it as `subject`."""
    git(who, "checkout", "-q", branch)
    filename = filename or f"{branch}.txt"
    p = ROOT / who / filename
    with open(p, "a") as f:
        f.write((content or subject) + "\n")
    git(who, "add", "-A")
    git(who, "commit", "-q", "-m", subject)
    return sha(who, branch)


def stacks_on_github():
    rc, o = sh(None, ["gh", "api", "--paginate", f"repos/{REPO}/stacks?per_page=100"])
    data = json.loads(o)
    if data and isinstance(data[0], list):
        data = [s for page in data for s in page]
    return [s for s in data if s.get("open")]


def stack_map():
    """open stack number -> [head refs bottom-up]"""
    return {
        s["number"]: [
            p["head"]["ref"] for p in s["pull_requests"] if p["state"].lower() == "open"
        ]
        for s in stacks_on_github()
    }


def pr_of(branch):
    data = gh_json(
        "pr",
        "list",
        "--repo",
        REPO,
        "--head",
        branch,
        "--state",
        "all",
        "--json",
        "number,baseRefName,state",
    )
    return data[0] if data else None


def pr_base(branch):
    p = pr_of(branch)
    return p["baseRefName"] if p else None


# --------------------------------------------------------------- building
def make_stack(who, prefix, n, base="main", submit=True):
    """prefix-1 <- prefix-2 <- ... each with one commit; gh stack init; submit."""
    git(who, "checkout", "-q", base)
    names = []
    for i in range(1, n + 1):
        name = f"{prefix}-{i}"
        git(who, "checkout", "-q", "-b", name)
        write_commit(who, name, f"[{name}] initial")
        names.append(name)
    git(who, "checkout", "-q", base)
    gs(who, "init", "--base", base, *names)
    number = None
    if submit:
        git(who, "checkout", "-q", names[-1])
        # --open, as gsx submit does: a draft cannot be merged by `gh stack merge`
        rc, o = gs(who, "submit", "--auto", "--open")
        m = re.search(r"stack #(\d+)", o)
        number = int(m.group(1)) if m else None
    return names, number


def track(who, number):
    """gh stack checkout <number> in another clone."""
    git(who, "checkout", "-q", "main")
    gs(who, "checkout", str(number))


# -------------------------------------------------------------- asserting
def expect(cond, msg):
    if not cond:
        raise Fail("EXPECT: " + msg)


def expect_present_once(who, branch, wanted_subjects, on="origin"):
    ref = f"origin/{branch}" if on == "origin" else branch
    subs = subjects(who, f"origin/main..{ref}")
    for s in wanted_subjects:
        c = subs.count(s)
        expect(c == 1, f"{ref}: expected {s!r} exactly once, found {c}; have {subs}")


def expect_no_dups(who, branch, on="origin"):
    ref = f"origin/{branch}" if on == "origin" else branch
    subs = subjects(who, f"origin/main..{ref}")
    dups = {s for s in subs if subs.count(s) > 1}
    expect(not dups, f"{ref}: duplicate subjects {dups}")


def expect_stacked(who, names, on="origin", trunk="main"):
    """each branch sits on the previous one, and the bottom on the trunk."""
    prev = f"origin/{trunk}" if on == "origin" else trunk
    for n in names:
        ref = f"origin/{n}" if on == "origin" else n
        expect(is_ancestor(who, prev, ref), f"{ref} does not sit on {prev}")
        prev = ref


def expect_local_equals_remote(who, names):
    for n in names:
        a, b = sha(who, n), sha(who, f"origin/{n}")
        expect(a == b, f"{n}: local {a[:8]} != origin {b[:8]}")


def expect_in(text, needle):
    expect(needle in text, f"expected {needle!r} in output:\n{text[-1500:]}")


def expect_not_in(text, needle):
    expect(needle not in text, f"did NOT expect {needle!r} in output:\n{text[-1500:]}")


# --------------------------------------------------------------- cleanup
def cleanup(prefix):
    """close PRs, delete remote+local branches, drop local tracking, for prefix."""
    prs = gh_json(
        "pr",
        "list",
        "--repo",
        REPO,
        "--state",
        "open",
        "--limit",
        "200",
        "--json",
        "number,headRefName",
    )
    for p in prs:
        if p["headRefName"].startswith(prefix):
            sh(
                None,
                [
                    "gh",
                    "pr",
                    "close",
                    str(p["number"]),
                    "--repo",
                    REPO,
                    "--delete-branch",
                ],
                check=False,
            )
    for who in CLONES:
        git(who, "checkout", "-q", "main", check=False)
        git(who, "rebase", "--abort", check=False)
        git(who, "cherry-pick", "--abort", check=False)
        git(who, "reset", "-q", "--hard", check=False)
        fetch(who)
        git(who, "merge", "-q", "--ff-only", "origin/main", check=False)
        for b in out(who, "branch", "--format=%(refname:short)").splitlines():
            if b.startswith(prefix):
                git(who, "branch", "-D", b, check=False)
        # local tracking: drop stacks holding prefixed branches
        p = ROOT / who / ".git" / "gh-stack"
        if p.is_file():
            d = json.loads(p.read_text())
            d["stacks"] = [
                s
                for s in d.get("stacks", [])
                if not any(
                    b.get("branch", "").startswith(prefix)
                    for b in s.get("branches", [])
                )
            ]
            p.write_text(json.dumps(d))
        # gsx's own state -- a move or a sync session a scenario left behind
        for f in ("gsx/move.json", "gsx/sync.json", "gsx-move"):
            (ROOT / who / ".git" / f).unlink(missing_ok=True)
        # remote branches with the prefix, in case a PR never existed
        for b in out(who, "branch", "-r", "--format=%(refname:short)").splitlines():
            b = b.replace("origin/", "")
            if b.startswith(prefix):
                git(who, "push", "-q", "origin", "--delete", b, check=False)
        fetch(who)


# ---------------------------------------------------------------- report
REPORT = []
LOG: list[str] = []
LOGDIR = ROOT / "logs"


def scenario(name):
    def deco(fn):
        fn._scenario = name
        return fn

    return deco


def run_all(fns, only=None):
    for fn in fns:
        name = fn._scenario
        if only and not any(o in name for o in only):
            continue
        prefix = name.split(":")[0]
        t0 = time.time()
        entry = {"name": name, "steps": [], "result": "PASS", "detail": ""}
        LOG.clear()
        try:
            cleanup(prefix)  # a previous run may have died mid-scenario
            fn(entry["steps"])
        except Fail as e:
            entry["result"] = "FAIL"
            entry["detail"] = str(e)
        except Exception as e:  # noqa
            entry["result"] = "ERROR"
            entry["detail"] = traceback.format_exc()[-3000:]
        finally:
            try:
                cleanup(prefix)
            except Exception as e:  # noqa
                entry["detail"] += f"\n(cleanup: {e})"
        entry["secs"] = round(time.time() - t0)
        LOGDIR.mkdir(exist_ok=True)
        (LOGDIR / (prefix + ".log")).write_text("\n".join(LOG))
        REPORT.append(entry)
        print(f"{entry['result']:5} {entry['secs']:4}s  {name}", flush=True)
        if entry["result"] != "PASS":
            print(
                "      " + entry["detail"].replace("\n", "\n      ")[:2500], flush=True
            )
        # machine-readable, for the report: rewritten after every scenario so a
        # killed run still leaves what it finished
        tag = pathlib.Path(sys.argv[0]).stem
        (ROOT / f"report_{tag}.json").write_text(json.dumps(REPORT, indent=1))
    return REPORT
