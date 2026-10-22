#
# Copyright 2026 Tabsdata Inc.
#

"""Batch D/E/F: the guard, landed PRs, and edges."""

from harness import *


def merge_stacked(who, pr):
    """A PR in a stack cannot go through `gh pr merge`: GitHub wants the
    stack merge API, which `gh stack merge <pr>` drives -- everything up to
    and including that PR, atomically. Then wait for the branch to be gone."""
    rc, o = gs(who, "merge", str(pr), "--yes", "--squash", check=False)
    expect(rc == 0, f"gh stack merge {pr} failed:\n{o[-800:]}")
    for _ in range(30):
        p = pr_of_number(pr)
        if p and p["state"].upper() == "MERGED":
            break
        time.sleep(2)
    else:
        raise Fail(f"PR #{pr} did not reach MERGED")
    fetch(who)


def pr_of_number(n):
    data = gh_json(
        "pr", "view", str(n), "--repo", REPO, "--json", "number,state,headRefName"
    )
    return data


# ================================================================== D: guard
@scenario("D1: a squash of pushed commits is refused; the override lets it through")
def d1(steps):
    make_stack("alice", "D1", 2)
    write_commit("alice", "D1-2", "[D1-2] second")
    gsx("alice", "sync", "--push")
    git("alice", "checkout", "-q", "D1-2")
    git("alice", "reset", "-q", "--soft", "HEAD~2")
    git("alice", "commit", "-q", "-m", "[D1-2] squashed")
    rc, o = git("alice", "push", "--force-with-lease", "origin", "D1-2", check=False)
    expect(rc != 0 and "append-only" in o, f"squash not refused:\n{o[-600:]}")
    fetch("alice")
    expect(
        subjects("alice", "origin/D1-1..origin/D1-2")
        == ["[D1-2] second", "[D1-2] initial"],
        "remote changed",
    )
    steps.append("squash refused, remote intact")
    rc, o = git("alice", "push", "--force-with-lease", "origin", "D1-2", check=False)
    rc, o = sh(
        "alice",
        ["git", "push", "--force-with-lease", "origin", "D1-2"],
        check=False,
        env={"GIT_ALLOW_OVERWRITE": "1"},
    )
    expect(rc == 0, f"override did not work:\n{o[-400:]}")
    steps.append("GIT_ALLOW_OVERWRITE=1 lets it through")


@scenario(
    "D2: gh stack sync from a STALE clone after a restructure is refused by the guard"
)
def d2(steps):
    na = make_stack("alice", "D2A", 3)[1]
    nb = make_stack("alice", "D2B", 2)[1]
    track("bob", na)
    git("alice", "checkout", "-q", "D2A-2")
    gsx("alice", "move", "--to", f"#{nb}", "--yes")
    gsx("alice", "submit", "--move")
    steps.append("alice moved D2A-2..3 onto B and published")
    write_commit("bob", "D2A-3", "[D2A-3] bob on the old layout", "bob.txt")
    gs("bob", "sync", check=False, input="n\n")
    fetch("bob")
    expect(
        is_ancestor("bob", "origin/D2B-2", "origin/D2A-2"),
        "remote D2A-2 no longer on D2B-2: CLOBBERED",
    )
    expect(is_ancestor("bob", "origin/D2B-2", "origin/D2A-3"), "remote D2A-3 clobbered")
    steps.append("guard held: the published restructure survived bob's gh stack sync")
    gsx("bob", "checkout", f"#{nb}", "--adopt")
    git("bob", "checkout", "-q", "D2A-3")
    gsx("bob", "sync", "--push")
    fetch("bob")
    expect_present_once("bob", "D2A-3", ["[D2A-3] bob on the old layout"])
    steps.append("bob --adopt, then sync: his commit landed on the new arrangement")


@scenario(
    "D3: an unguarded clone is refused by every pushing command, not by the readers"
)
def d3(steps):
    num = make_stack("alice", "D3", 2)[1]
    track("carol", num)
    # unguard by pointing git away from .githooks; deleting the committed hook
    # file would dirty the tree and refuse for the wrong reason
    git("carol", "config", "--unset", "core.hooksPath")
    try:
        for cmd in (["sync"], ["submit"], ["move", "--to", "main"]):
            rc, o = gsx("carol", *cmd, check=False)
            expect(
                rc != 0 and "guard is not installed" in o,
                f"{cmd} ran unguarded:\n{o[-500:]}",
            )
        rc, o = gsx("carol", "stack", "--short", "--no-fetch")
        expect(rc == 0, "stack should read regardless")
        rc, o = gsx("carol", "sync", check=False, env={"GSX_NO_GUARD": "1"})
        expect(rc == 0, f"escape did not work:\n{o[-500:]}")
        steps.append("sync/submit/move refused; stack reads; GSX_NO_GUARD=1 runs")
    finally:
        git("carol", "config", "core.hooksPath", ".githooks")


@scenario(
    "D4: the guard knows a commit by its Change-Id: rewritten patch and subject pass, a drop is refused"
)
def d4(steps):
    num = make_stack("alice", "D4", 2)[1]
    track("bob", num)
    write_commit("bob", "D4-1", "[D4-1] bob's commit", "bob.txt")
    gsx("bob", "sync", "--push")
    cid = change_id_of("bob", "D4-1")
    expect(cid.startswith("I"), f"bob's commit has no Change-Id: {cid!r}")
    steps.append(f"bob pushed a commit to D4-1, stamped {cid[:12]}")
    gsx("alice", "sync")
    git("alice", "checkout", "-q", "D4-1")
    expect(
        change_id_of("alice", "D4-1") == cid,
        "sync did not bring bob's commit to the tip",
    )
    rewrite_tip("alice", "bob.txt", "[D4-1] bob's commit, reworded and changed", cid)
    rc, o = git("alice", "push", "--force-with-lease", "origin", "D4-1", check=False)
    expect(
        rc == 0,
        f"rewritten in patch and subject, Change-Id kept, and refused:\n{o[-700:]}",
    )
    fetch("alice")
    ids = change_ids_of("alice", "origin/main..origin/D4-1")
    expect(ids.count(cid) == 1, f"{cid} not exactly once on origin/D4-1: {ids}")
    expect_present_once("alice", "D4-1", ["[D4-1] bob's commit, reworded and changed"])
    steps.append(
        "alice rewrote its patch AND subject keeping the Change-Id: the guard let it through"
    )
    git("alice", "reset", "-q", "--hard", "HEAD~1")
    rc, o = git("alice", "push", "--force-with-lease", "origin", "D4-1", check=False)
    expect(
        rc != 0 and "append-only" in o and "reworded" in o and cid in o,
        f"dropping it was not refused, or the refusal did not name it:\n{o[-700:]}",
    )
    git("alice", "reset", "-q", "--hard", "origin/D4-1")
    steps.append(
        "dropping it (the Change-Id gone) is refused; the refusal names commit and Change-Id"
    )


# ========================================================== E: landed history
@scenario(
    "E1: the bottom PR is squash-merged; both users sync; nothing recreates the landed branch"
)
def e1(steps):
    names, num = make_stack("alice", "E1", 4)
    track("bob", num)
    pr = pr_of("E1-1")["number"]
    merge_stacked("alice", pr)
    steps.append(f"PR #{pr} (E1-1) squash-merged, branch deleted on GitHub")
    git("alice", "checkout", "-q", "E1-4")
    o = gsx("alice", "sync", "--push")[1]
    expect_not_in(o, "CONFLICT")
    fetch("alice")
    expect(
        sha("alice", "origin/E1-1") == "", "E1-1 was RECREATED on the remote by sync"
    )
    for n in names[1:]:
        expect(
            is_ancestor("alice", "origin/main", f"origin/{n}"),
            f"{n} not on the new main",
        )
        expect_no_dups("alice", n)
    expect_stacked("alice", names[1:])
    steps.append("alice: E1-2..4 restacked onto the squash, E1-1 not pushed back")
    o = gsx("bob", "sync", "--push")[1]
    expect_not_in(o, "CONFLICT")
    fetch("bob")
    expect(sha("bob", "origin/E1-1") == "", "bob's sync recreated E1-1")
    expect_local_equals_remote("bob", names[1:])
    o = gsx("bob", "purge")[1]
    expect(sha("bob", "E1-1") == "", "purge kept the landed branch")
    steps.append("bob synced and purged the landed branch")


@scenario("E2: gsx stack hides landed PRs; --merged shows them")
def e2(steps):
    make_stack("alice", "E2", 3)
    pr = pr_of("E2-1")["number"]
    merge_stacked("alice", pr)
    git("alice", "checkout", "-q", "E2-3")
    o = gsx("alice", "stack", "--short", "--no-fetch")[1]
    expect("E2-1" not in o and "left out" in o, f"landed PR still shown:\n{o}")
    o = gsx("alice", "stack", "--short", "--no-fetch", "--merged")[1]
    expect("E2-1" in o, "--merged did not bring it back")
    steps.append("landed PR hidden by default, back with --merged")


@scenario("E3: move onto a stack whose bottom has landed (the finished-run logic)")
def e3(steps):
    na = make_stack("alice", "E3A", 3)[1]
    make_stack("alice", "E3B", 2)
    pr = pr_of("E3A-1")["number"]
    merge_stacked("alice", pr)
    git("alice", "checkout", "-q", "E3A-3")
    gsx("alice", "sync", "--push")
    git("alice", "checkout", "-q", "E3B-2")
    o = gsx("alice", "move", "--to", f"#{na}", "--yes")[1]
    expect_in(o, "moved")
    expect(is_ancestor("alice", "E3A-3", "E3B-2"), "not moved onto E3A-3")
    o = gsx("alice", "sync")[1]
    expect_in(o, "submit --move")
    o = gsx("alice", "submit", "--move")[1]
    sm = stack_map()
    expect(sm.get(na) == ["E3A-2", "E3A-3", "E3B-2"], f"stack wrong: {sm}")
    fetch("alice")
    expect(sha("alice", "origin/E3A-1") == "", "landed branch recreated")
    steps.append("moved onto a stack with landed history; landed branch stays gone")


# ================================================================== F: edges
@scenario("F1: sync --all with two stacks both needing work; dirty tree refused first")
def f1(steps):
    a = make_stack("alice", "F1A", 2)[0]
    b = make_stack("alice", "F1B", 2)[0]
    write_commit("carol", "main", "[main] carol lands")
    git("carol", "push", "-q", "origin", "main")
    (ROOT / "alice" / "shared.txt").write_text(
        "dirty\n"
    )  # tracked since the base commit
    rc, o = gsx("alice", "sync", "--all", "--push", check=False)
    expect(rc != 0 and "uncommitted" in o, "dirty tree not refused")
    git("alice", "checkout", "-q", "--", "shared.txt")
    rc, o = gsx("alice", "sync", "--all", "--push")
    expect_in(o, "4 restacked")
    fetch("alice")
    expect_stacked("alice", a)
    expect_stacked("alice", b)
    steps.append("dirty refused; --all restacked both stacks onto the new trunk")


@scenario(
    "F2: checkout '#N' resolves a stack or a PR from the repository; a bare number is refused"
)
def f2(steps):
    num = make_stack("alice", "F2", 2)[1]
    pr = pr_of("F2-1")["number"]
    rc, o = gsx("bob", "checkout", f"#{num}")
    expect(
        out("bob", "rev-parse", "--abbrev-ref", "HEAD") == "F2-2",
        "stack checkout did not land on top",
    )
    git("bob", "checkout", "-q", "main")
    rc, o = gsx("bob", "checkout", f"#{pr}")
    expect(
        out("bob", "rev-parse", "--abbrev-ref", "HEAD") == "F2-1",
        "PR checkout did not land on its branch",
    )
    rc, o = gsx("bob", "checkout", str(num), check=False)
    expect(rc != 0 and "#" in o, "bare number not refused")
    steps.append(f"#{num} -> stack, #{pr} -> PR, {num} refused")


@scenario("F3: the gsx create/submit path: issue, branch, commit, stack, labels")
def f3(steps):
    git("alice", "checkout", "-q", "main")
    (ROOT / "alice" / "F3-a.txt").write_text("a\n")
    o = gsx("alice", "create", "-s", "F3 first step")[1]
    branch = out("alice", "rev-parse", "--abbrev-ref", "HEAD")
    expect(branch.startswith("SCENARIOS-"), f"branch name {branch!r}")
    (ROOT / "alice" / "F3-b.txt").write_text("b\n")
    o = gsx("alice", "create", "-s", "F3 second step")[1]
    top = out("alice", "rev-parse", "--abbrev-ref", "HEAD")
    o = gsx("alice", "submit", "--no-defaults")[1]
    expect_in(o, "pushed the stack")
    sm = stack_map()
    expect([branch, top] in sm.values(), f"stack not on GitHub: {sm}")
    expect(pr_base(top) == branch, "second PR not based on the first")
    steps.append(f"create x2 -> {branch} <- {top}; submit opened both PRs in one stack")
    # cleanup by prefix will not see SCENARIOS-*, do it here
    for b in (top, branch):
        p = pr_of(b)
        if p:
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
    for i in gh_json(
        "issue", "list", "--repo", REPO, "--state", "open", "--json", "number"
    ):
        sh(
            None,
            ["gh", "issue", "close", str(i["number"]), "--repo", REPO],
            check=False,
        )
    git("alice", "checkout", "-q", "main")
    for b in (top, branch):
        git("alice", "branch", "-D", b, check=False)
    p = ROOT / "alice" / ".git" / "gh-stack"
    d = json.loads(p.read_text())
    d["stacks"] = [
        s
        for s in d["stacks"]
        if not any(x.get("branch", "").startswith("SCENARIOS-") for x in s["branches"])
    ]
    p.write_text(json.dumps(d))


SCENARIOS = [d1, d2, d3, d4, e1, e2, e3, f1, f2, f3]

if __name__ == "__main__":
    run_all(SCENARIOS, only=sys.argv[1:] or None)
