#
# Copyright 2026 Tabsdata Inc.
#

"""Batch A/B: baseline collaboration and the cascade family."""

# ruff: noqa: F403, F405 -- the harness is the scenario vocabulary, imported whole
from harness import *


# =============================================================== A: baseline
@scenario("A1: two users, different PRs of one stack, both sync")
def a1(steps):
    names, num = make_stack("alice", "A1", 3)
    steps.append(f"alice: stack #{num} {names}")
    track("bob", num)
    write_commit("bob", "A1-1", "[A1-1] bob adds to the bottom")
    rc, o = gsx("bob", "sync")
    expect_not_in(o, "CONFLICT")
    steps.append("bob: commit on A1-1, sync")
    write_commit("alice", "A1-3", "[A1-3] alice adds to the top")
    rc, o = gsx("alice", "sync")
    expect_not_in(o, "CONFLICT")
    steps.append("alice: commit on A1-3, sync (must integrate bob's)")
    fetch("alice")
    expect_present_once(
        "alice",
        "A1-3",
        ["[A1-1] bob adds to the bottom", "[A1-3] alice adds to the top"],
    )
    expect_no_dups("alice", "A1-3")
    expect_stacked("alice", names)
    expect(stack_map().get(num) == names, f"stack #{num} changed: {stack_map()}")
    rc, o = gsx("bob", "sync")
    fetch("bob")
    expect_local_equals_remote("bob", names)
    steps.append("bob: sync brings everything down; local == remote")


@scenario("A2: two users append to the SAME middle PR; second to sync integrates")
def a2(steps):
    names, num = make_stack("alice", "A2", 3)
    track("bob", num)
    write_commit("bob", "A2-2", "[A2-2] bob's change", "bob.txt")
    gsx("bob", "sync")
    write_commit("alice", "A2-2", "[A2-2] alice's change", "alice.txt")
    rc, o = gsx("alice", "sync")
    expect_not_in(o, "CONFLICT")
    steps.append("bob then alice, both on A2-2")
    fetch("alice")
    expect_present_once(
        "alice", "A2-2", ["[A2-2] bob's change", "[A2-2] alice's change"]
    )
    expect_present_once(
        "alice", "A2-3", ["[A2-2] bob's change", "[A2-2] alice's change"]
    )
    expect_no_dups("alice", "A2-3")
    expect_stacked("alice", names)


@scenario("A3: interleave a commit into a branch's own history, sync, teammate syncs")
def a3(steps):
    names, num = make_stack("alice", "A3", 3)
    write_commit("alice", "A3-2", "[A3-2] second")
    gsx("alice", "sync")
    track("bob", num)
    # alice inserts a commit between A3-2's two commits
    git("alice", "checkout", "-q", "A3-2")
    first = out("alice", "rev-list", "--reverse", "A3-1..A3-2").splitlines()[0]
    git("alice", "checkout", "-q", first)
    (ROOT / "alice" / "mid.txt").write_text("mid\n")
    git("alice", "add", "-A")
    git("alice", "commit", "-q", "-m", "[A3-2] interleaved")
    mid = sha("alice", "HEAD")
    git("alice", "checkout", "-q", "A3-2")
    git("alice", "rebase", "-q", "--onto", mid, first, "A3-2")
    rc, o = gsx("alice", "sync")
    expect_not_in(o, "REFUSING")
    steps.append("alice interleaved on A3-2, sync forced A3-2 and A3-3")
    fetch("alice")
    expect(
        subjects("alice", "origin/A3-1..origin/A3-2")
        == ["[A3-2] second", "[A3-2] interleaved", "[A3-2] initial"],
        f"order wrong: {subjects('alice', 'origin/A3-1..origin/A3-2')}",
    )
    expect_stacked("alice", names)
    rc, o = gsx("bob", "sync")
    expect_not_in(o, "CONFLICT")
    fetch("bob")
    expect_local_equals_remote("bob", names)
    steps.append("bob syncs cleanly onto the rewritten history")


# ================================================================ B: cascades
@scenario("B1: trunk moves; a 5-branch stack restacks once each, no duplicates")
def b1(steps):
    names, num = make_stack("alice", "B1", 5)
    write_commit("bob", "main", "[main] landed by bob")
    git("bob", "push", "-q", "origin", "main")
    steps.append("bob landed on main")
    git("alice", "checkout", "-q", "B1-5")
    rc, o = gsx("alice", "sync")
    expect_not_in(o, "CONFLICT")
    expect_in(o, "5 restacked")
    fetch("alice")
    for n in names:
        expect_no_dups("alice", n)
        expect(
            is_ancestor("alice", "origin/main", f"origin/{n}"), f"{n} not on new main"
        )
    expect_stacked("alice", names)
    steps.append("alice sync: 5 restacked, all on new main, no dups")


@scenario(
    "B2: teammate adds to the bottom; alice holds local commits on three upper branches"
)
def b2(steps):
    names, num = make_stack("alice", "B2", 5)
    track("bob", num)
    write_commit("bob", "B2-1", "[B2-1] bob at the bottom")
    gsx("bob", "sync")
    for n in ("B2-3", "B2-4", "B2-5"):
        write_commit("alice", n, f"[{n}] alice local")
    git("alice", "checkout", "-q", "B2-5")
    rc, o = gsx("alice", "sync")
    expect_not_in(o, "CONFLICT")
    fetch("alice")
    expect_present_once(
        "alice",
        "B2-5",
        [
            "[B2-1] bob at the bottom",
            "[B2-3] alice local",
            "[B2-4] alice local",
            "[B2-5] alice local",
        ],
    )
    expect_no_dups("alice", "B2-5")
    expect_stacked("alice", names)
    steps.append("both people's commits present once each; stack intact")
    gsx("bob", "sync")
    fetch("bob")
    expect_local_equals_remote("bob", names)


@scenario(
    "B3: trunk moved AND bob pushed to the middle AND alice has local work on top"
)
def b3(steps):
    names, num = make_stack("alice", "B3", 5)
    track("bob", num)
    write_commit("carol", "main", "[main] carol landed")
    git("carol", "push", "-q", "origin", "main")
    write_commit("bob", "B3-3", "[B3-3] bob mid")
    gsx("bob", "sync")
    write_commit("alice", "B3-5", "[B3-5] alice top")
    git("alice", "checkout", "-q", "B3-5")
    rc, o = gsx("alice", "sync")
    expect_not_in(o, "CONFLICT")
    fetch("alice")
    expect_present_once("alice", "B3-5", ["[B3-3] bob mid", "[B3-5] alice top"])
    expect_no_dups("alice", "B3-5")
    expect_stacked("alice", names)
    expect(is_ancestor("alice", "origin/main", "origin/B3-1"), "not on new main")
    steps.append("all three sources integrated, once each")
    gsx("bob", "sync")
    fetch("bob")
    expect_local_equals_remote("bob", names)


@scenario("B4: 12-branch stack, trunk moves twice, two users alternate syncs")
def b4(steps):
    names, num = make_stack("alice", "B4", 12)
    track("bob", num)
    for round_ in (1, 2):
        write_commit("carol", "main", f"[main] round {round_}")
        git("carol", "push", "-q", "origin", "main")
        who = "alice" if round_ == 1 else "bob"
        write_commit(who, f"B4-{6 * round_}", f"[B4-{6 * round_}] {who} r{round_}")
        git(who, "checkout", "-q", names[-1])
        rc, o = gsx(who, "sync")
        expect_not_in(o, "CONFLICT")
        other = "bob" if who == "alice" else "alice"
        rc, o = gsx(other, "sync")
        expect_not_in(o, "CONFLICT")
    fetch("alice")
    expect_present_once("alice", "B4-12", ["[B4-6] alice r1", "[B4-12] bob r2"])
    expect_no_dups("alice", "B4-12")
    expect_stacked("alice", names)
    expect_local_equals_remote("alice", names)
    fetch("bob")
    expect_local_equals_remote("bob", names)
    steps.append("12 branches, two trunk moves, alternating users: consistent")


@scenario(
    "B5: sync stops on a REAL conflict; resolve; git rebase --continue; sync again"
)
def b5(steps):
    names, num = make_stack("alice", "B5", 3)
    track("bob", num)
    write_commit("bob", "B5-2", "[B5-2] bob line", "shared.txt", "bob's line")
    gsx("bob", "sync")
    write_commit("alice", "B5-2", "[B5-2] alice line", "shared.txt", "alice's line")
    git("alice", "checkout", "-q", "B5-2")
    rc, o = gsx("alice", "sync", check=False)
    expect(
        rc != 0 and "CONFLICT" in o, f"expected a conflict, got rc={rc}:\n{o[-800:]}"
    )
    steps.append("genuine conflict on shared.txt, sync stopped")
    p = ROOT / "alice" / "shared.txt"
    text = re.sub(
        r"<<<<<<<.*?=======\n(.*?)>>>>>>>.*?\n", r"\1", p.read_text(), flags=re.S
    )
    p.write_text(text + "alice's line\n")
    git("alice", "add", "-A")
    sh("alice", ["git", "rebase", "--continue"], env={"GIT_EDITOR": "true"})
    rc, o = gsx("alice", "sync")
    expect_not_in(o, "CONFLICT")
    steps.append("resolved, --continue, sync again: idempotent")
    fetch("alice")
    expect_present_once("alice", "B5-3", ["[B5-2] bob line", "[B5-2] alice line"])
    expect_stacked("alice", names)


SCENARIOS = [a1, a2, a3, b1, b2, b3, b4, b5]

if __name__ == "__main__":
    run_all(SCENARIOS, only=sys.argv[1:] or None)
