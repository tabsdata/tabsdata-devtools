#
# Copyright 2026 Tabsdata Inc.
#

"""Batch C: moves -- the family every real bug came from."""

# ruff: noqa: F403, F405 -- the harness is the scenario vocabulary, imported whole
from harness import *


def resolve_all(who, keep="both"):
    """Resolve every conflicted file by keeping both sides' lines (appends
    never really conflict in meaning), then git add."""
    files = [
        line[3:]
        for line in out(who, "status", "--porcelain").splitlines()
        if line[:2] in ("UU", "AA")
    ]
    for f in files:
        p = ROOT / who / f
        text = p.read_text()
        text = re.sub(
            r"<<<<<<<[^\n]*\n(.*?)=======\n(.*?)>>>>>>>[^\n]*\n",
            r"\1\2",
            text,
            flags=re.S,
        )
        p.write_text(text)
        git(who, "add", f)
    return files


@scenario(
    "C1: move the top branch onto another stack; sync while pending; publish; bob adopts"
)
def c1(steps):
    a, na = make_stack("alice", "C1A", 3)
    b, nb = make_stack("alice", "C1B", 2)
    track("bob", na)
    track("bob", nb)
    git("alice", "checkout", "-q", "C1A-3")
    rc, o = gsx("alice", "move", "--to", f"#{nb}", "--yes")
    expect_in(o, "moved")
    steps.append(f"alice: C1A-3 -> #{nb}")
    # bob appends to the moved branch on the OLD arrangement and pushes
    write_commit("bob", "C1A-3", "[C1A-3] bob after the move", "bob.txt")
    rc, o = gsx("bob", "sync", "--push")
    steps.append("bob pushed to C1A-3 (still on its old base for him)")
    # alice syncs during the pending move: takes bob's commit, keeps the move, pushes nothing
    rc, o = gsx("alice", "sync")
    expect_in(o, "took 1 commit")
    expect_in(o, "submit --move")
    steps.append("plain sync is local: reconciled and restacked, nothing pushed")
    rc, o = gsx("alice", "sync", "--push")
    expect_in(o, "nothing was pushed")
    expect(is_ancestor("alice", "C1B-2", "C1A-3"), "move undone by sync")
    expect(
        subjects("alice", "C1B-2..C1A-3")
        == ["[C1A-3] bob after the move", "[C1A-3] initial"],
        f"moved branch carries wrong commits: {subjects('alice', 'C1B-2..C1A-3')}",
    )
    steps.append("alice sync: took bob's commit, move intact, no push")
    rc, o = gsx("alice", "submit", "--move")
    expect_not_in(o, "REFUSING")
    steps.append("alice published the move")
    sm = stack_map()
    expect(sm.get(nb) == ["C1B-1", "C1B-2", "C1A-3"], f"target stack wrong: {sm}")
    expect(pr_base("C1A-3") == "C1B-2", f"PR base of C1A-3 = {pr_base('C1A-3')}")
    remainder = [n for n, v in sm.items() if v == ["C1A-1", "C1A-2"]]
    expect(remainder, f"remainder stack not found: {sm}")
    steps.append(f"GitHub: #{nb} grew, remainder is #{remainder[0]}")
    # bob is stale: gh stack sync must be refused by the guard, gsx checkout --adopt recovers
    git("bob", "checkout", "-q", "C1A-2")
    write_commit("bob", "C1A-2", "[C1A-2] bob stale work", "bob2.txt")
    rc, o = gs("bob", "sync", check=False, input="n\n")
    expect(
        rc != 0 or "REFUSING" in o or "Push failed" in o,
        f"gh stack sync from stale clone was not refused:\n{o[-1200:]}",
    )
    fetch("bob")
    expect(
        subjects("bob", "origin/main..origin/C1A-3")[0] == "[C1A-3] bob after the move",
        "remote C1A-3 clobbered",
    )
    steps.append("bob's gh stack sync refused by the guard; remote intact")
    rc, o = gsx("bob", "checkout", f"#{nb}", check=False)
    expect(
        rc != 0 and "restructured" in o,
        f"expected the restructure refusal:\n{o[-800:]}",
    )
    rc, o = gsx("bob", "checkout", f"#{nb}", "--adopt")
    rc, o = gsx("bob", "checkout", f"#{remainder[0]}", "--adopt", check=False)
    git("bob", "checkout", "-q", "C1A-2")
    rc, o = gsx("bob", "sync", "--push")
    expect_not_in(o, "CONFLICT")
    fetch("bob")
    expect_present_once("bob", "C1A-2", ["[C1A-2] bob stale work"])
    steps.append("bob adopted both stacks; his stale commit survived and was pushed")


@scenario(
    "C2: move a 3-branch SLICE onto another stack; teammate pushes to the middle of the slice; sync; publish"
)
def c2(steps):
    a, na = make_stack("alice", "C2A", 5)
    b, nb = make_stack("alice", "C2B", 2)
    track("bob", na)
    git("alice", "checkout", "-q", "C2A-3")
    rc, o = gsx("alice", "move", "--to", f"#{nb}", "--yes")
    expect_in(o, "moved")
    steps.append("alice: C2A-3..5 -> #%d" % nb)
    # the middle of the moved slice gets a teammate commit on the old arrangement
    write_commit("bob", "C2A-4", "[C2A-4] bob mid-slice", "bob.txt")
    gsx("bob", "sync", "--push")
    rc, o = gsx("alice", "sync")
    expect_in(o, "submit --move")
    expect_not_in(o, "CONFLICT")
    # the taint: C2A-4 and C2A-5 must be treated as moved too, not rebased onto their remote copies
    expect(
        is_ancestor("alice", "C2B-2", "C2A-3")
        and is_ancestor("alice", "C2A-3", "C2A-4")
        and is_ancestor("alice", "C2A-4", "C2A-5"),
        "slice no longer sits on C2B-2 after sync",
    )
    expect(
        subjects("alice", "C2B-2..C2A-5")
        == [
            "[C2A-5] initial",
            "[C2A-4] bob mid-slice",
            "[C2A-4] initial",
            "[C2A-3] initial",
        ],
        f"slice carries wrong commits: {subjects('alice', 'C2B-2..C2A-5')}",
    )
    steps.append(
        "alice sync: bob's commit taken into the slice, old chain NOT dragged back"
    )
    rc, o = gsx("alice", "submit", "--move")
    sm = stack_map()
    expect(
        sm.get(nb) == ["C2B-1", "C2B-2", "C2A-3", "C2A-4", "C2A-5"],
        f"target wrong: {sm}",
    )
    expect(
        pr_base("C2A-3") == "C2B-2" and pr_base("C2A-4") == "C2A-3", "PR bases wrong"
    )
    fetch("alice")
    expect_present_once("alice", "C2A-5", ["[C2A-4] bob mid-slice"])
    expect_no_dups("alice", "C2A-5")
    steps.append("published; bases and contents correct")


@scenario(
    "C3: move an UNSUBMITTED single-PR branch from the trunk onto a stack top, with a conflict (the OS-3512 case)"
)
def c3(steps):
    a, na = make_stack("alice", "C3A", 3)
    # a lone PR off main that touches shared.txt, like OS-3512 did
    git("alice", "checkout", "-q", "main")
    git("alice", "checkout", "-q", "-b", "C3S-1")
    write_commit("alice", "C3S-1", "[C3S-1] lone change", "shared.txt", "lone line")
    git("alice", "checkout", "-q", "main")
    gs("alice", "init", "--base", "main", "C3S-1")
    git("alice", "checkout", "-q", "C3S-1")
    gs("alice", "submit", "--auto")  # one PR, no stack on GitHub
    expect(pr_base("C3S-1") == "main", "lone PR should target main")
    # the stack touches the same file, so the move will conflict
    write_commit(
        "alice", "C3A-3", "[C3A-3] stack touches shared", "shared.txt", "stack line"
    )
    gsx("alice", "sync", "--push")
    git("alice", "checkout", "-q", "C3S-1")
    rc, o = gsx("alice", "move", "--to", "C3A-3", "--yes", check=False)
    expect(
        rc != 0 and "stopped" in o,
        f"expected the move to stop on a conflict:\n{o[-800:]}",
    )
    steps.append("move stopped on a conflict in shared.txt")
    resolve_all("alice")
    rc, o = gsx("alice", "move", "--continue")
    expect_in(o, "moved")
    steps.append("resolved, --continue finished the move")
    # THE close call: sync during the pending move must (a) detect the move though its base is the trunk,
    # (b) not re-apply the superseded remote copy whose patch the resolution changed
    rc, o = gsx("alice", "sync")
    expect_in(o, "submit --move")
    expect_not_in(o, "CONFLICT")
    expect(is_ancestor("alice", "C3A-3", "C3S-1"), "sync undid the move")
    expect(
        subjects("alice", "C3A-3..C3S-1") == ["[C3S-1] lone change"],
        f"moved branch wrong: {subjects('alice', 'C3A-3..C3S-1')}",
    )
    steps.append("sync during the pending move: no-op, move intact")
    rc, o = gsx("alice", "submit", "--move")
    sm = stack_map()
    expect(sm.get(na) == ["C3A-1", "C3A-2", "C3A-3", "C3S-1"], f"stack wrong: {sm}")
    expect(pr_base("C3S-1") == "C3A-3", f"base = {pr_base('C3S-1')}")
    steps.append("published: lone PR joined the stack, base fixed")


@scenario("C4: move a slice onto the TRUNK (a stack of its own); publish")
def c4(steps):
    a, na = make_stack("alice", "C4A", 4)
    git("alice", "checkout", "-q", "C4A-3")
    rc, o = gsx("alice", "move", "--to", "main", "--yes")
    expect_in(o, "moved")
    expect(
        is_ancestor("alice", "main", "C4A-3")
        and not is_ancestor("alice", "C4A-2", "C4A-3"),
        "slice not on trunk",
    )
    rc, o = gsx("alice", "sync")
    expect_in(o, "submit --move")
    expect(
        not is_ancestor("alice", "C4A-2", "C4A-3"), "sync dragged the old chain back"
    )
    rc, o = gsx("alice", "submit", "--move")
    sm = stack_map()
    expect(["C4A-3", "C4A-4"] in sm.values(), f"new stack not found: {sm}")
    expect(["C4A-1", "C4A-2"] in sm.values(), f"remainder not found: {sm}")
    expect(pr_base("C4A-3") == "main", f"base = {pr_base('C4A-3')}")
    steps.append("two stacks on GitHub, bases correct")


@scenario("C5: move, then --abort: every branch and both stacks back exactly")
def c5(steps):
    a, na = make_stack("alice", "C5A", 3)
    b, nb = make_stack("alice", "C5B", 2)
    before = {n: sha("alice", n) for n in a + b}
    state_before = (ROOT / "alice" / ".git" / "gh-stack").read_text()
    git("alice", "checkout", "-q", "C5A-2")
    gsx("alice", "move", "--to", f"#{nb}", "--yes")
    expect(sha("alice", "C5A-2") != before["C5A-2"], "move did nothing")
    rc, o = gsx("alice", "move", "--abort")
    expect_in(o, "aborted")
    after = {n: sha("alice", n) for n in a + b}
    expect(
        after == before,
        f"branches not restored: { {k: (before[k][:7], after[k][:7]) for k in before if before[k] != after[k]} }",
    )
    expect(
        (ROOT / "alice" / ".git" / "gh-stack").read_text() == state_before,
        "tracking not restored byte for byte",
    )
    rc, o = gsx("alice", "sync")
    expect_in(o, "the remote already has it all")
    steps.append("abort restored shas and tracking; sync is a no-op")


@scenario(
    "C6: submit --move refuses over an unreconciled branch, BEFORE dissolving anything"
)
def c6(steps):
    a, na = make_stack("alice", "C6A", 3)
    b, nb = make_stack("alice", "C6B", 2)
    track("bob", na)
    git("alice", "checkout", "-q", "C6A-3")
    gsx("alice", "move", "--to", f"#{nb}", "--yes")
    write_commit("bob", "C6A-3", "[C6A-3] bob meanwhile", "bob.txt")
    gsx("bob", "sync", "--push")
    rc, o = gsx("alice", "submit", "--move", check=False)
    expect(rc != 0 and "gsx sync" in o, f"expected the reconcile refusal:\n{o[-800:]}")
    sm = stack_map()
    expect(
        sm.get(na) == a and sm.get(nb) == b,
        f"a stack was dissolved before the refusal: {sm}",
    )
    steps.append("refused; both stacks untouched on GitHub")
    gsx("alice", "sync")
    rc, o = gsx("alice", "submit", "--move")
    expect(
        stack_map().get(nb) == ["C6B-1", "C6B-2", "C6A-3"], "publish failed after sync"
    )
    fetch("alice")
    expect_present_once("alice", "C6A-3", ["[C6A-3] bob meanwhile"])
    steps.append("after sync, published with bob's commit intact")


@scenario("C7: two moves queued (A top -> B, then B top -> C), one publish")
def c7(steps):
    a, na = make_stack("alice", "C7A", 2)
    b, nb = make_stack("alice", "C7B", 2)
    c, nc = make_stack("alice", "C7C", 2)
    git("alice", "checkout", "-q", "C7A-2")
    gsx("alice", "move", "--to", f"#{nb}", "--yes")
    git("alice", "checkout", "-q", "C7A-2")  # now top of B's local stack
    gsx("alice", "move", "--to", f"#{nc}", "--yes")
    rc, o = gsx("alice", "sync")
    expect_in(o, "submit --move")
    expect(is_ancestor("alice", "C7C-2", "C7A-2"), "second move lost")
    rc, o = gsx("alice", "submit", "--move")
    sm = stack_map()
    expect(sm.get(nc) == ["C7C-1", "C7C-2", "C7A-2"], f"C wrong: {sm}")
    expect(pr_base("C7A-2") == "C7C-2", f"base {pr_base('C7A-2')}")
    steps.append("both moves published in one submit")


@scenario(
    "C8: a moved branch's commit, rewritten in patch and subject, is known by its Change-Id: sync takes nothing twice"
)
def c8(steps):
    xs, nx = make_stack("alice", "C8X", 2)
    ys, ny = make_stack("alice", "C8Y", 2)
    track("bob", nx)
    write_commit("bob", "C8X-2", "[C8X-2] bob's commit", "bob.txt")
    gsx("bob", "sync", "--push")
    cid = change_id_of("bob", "C8X-2")
    expect(cid.startswith("I"), f"bob's commit has no Change-Id: {cid!r}")
    gsx("alice", "sync", "--all")
    git("alice", "checkout", "-q", "C8X-2")
    gsx("alice", "move", "--to", f"#{ny}", "--yes")
    expect(is_ancestor("alice", "C8Y-2", "C8X-2"), "move did not put C8X-2 on C8Y-2")
    expect(
        change_id_of("alice", "C8X-2") == cid,
        "bob's commit is not the tip after the move",
    )
    rewrite_tip("alice", "bob.txt", "[C8X-2] bob's commit, reworded and changed", cid)
    steps.append(
        "alice moved C8X-2 onto Y (local) and rewrote bob's commit, patch and subject, Change-Id kept"
    )
    rc, o = gsx("alice", "sync", check=False)
    expect(rc == 0, f"sync stopped: the rewritten commit was taken again:\n{o[-900:]}")
    ids = change_ids_of("alice", "C8Y-2..C8X-2")
    expect(ids.count(cid) == 1, f"{cid} not exactly once on C8X-2 after sync: {ids}")
    subs = subjects("alice", "C8Y-2..C8X-2")
    expect(
        "[C8X-2] bob's commit" not in subs
        and "[C8X-2] bob's commit, reworded and changed" in subs,
        f"subjects after sync: {subs}",
    )
    steps.append("sync took nothing: the remote's copy is known by its Change-Id")
    rc, o = gsx("alice", "submit", "--move")
    expect(rc == 0, f"publish refused:\n{o[-900:]}")
    fetch("alice")
    expect_stacked("alice", ["C8Y-1", "C8Y-2", "C8X-2"])
    expect(
        change_ids_of("alice", "origin/main..origin/C8X-2").count(cid) == 1,
        "the remote holds the commit twice, or not at all",
    )
    sm = stack_map()
    expect(sm.get(ny) == ["C8Y-1", "C8Y-2", "C8X-2"], f"Y wrong: {sm}")
    steps.append(
        "published: the remote holds the rewritten commit once, under its Change-Id, on Y"
    )


SCENARIOS = [c1, c2, c3, c4, c5, c6, c7, c8]

if __name__ == "__main__":
    run_all(SCENARIOS, only=sys.argv[1:] or None)
