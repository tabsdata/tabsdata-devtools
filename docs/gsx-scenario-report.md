<!--
Copyright 2026 Tabsdata Inc.
-->

# gsx scenario campaign

Multi-clone scenarios run against a real GitHub repository, replaying the situations that
produced close calls in `tabsdata-os`: several people creating, syncing, modifying and moving
PRs and stacks from different clones. Every scenario drives the real `gsx`, `gh stack` and `git`
and asserts what each user ends up with -- on GitHub and in every clone.

**Where:** `tabsdata/gsx-scenarios` (private, org Team plan, ruleset `protect-trunk`, branch
deletion on merge), three clones `alice`, `bob`, `carol`, each prepared with `tdd gsx init`; the
guard is committed in `.githooks/pre-push`.

**How:** a Python harness (`packages/tabsdata-dev-tool-gsx/scenarios/`) builds each scenario's stacks under its own branch prefix, performs the users'
actions in the respective clones, asserts the outcome, and cleans up on GitHub and in every clone
-- before a scenario as well as after, since a run killed mid-rebase leaves a checked-out branch
`git branch -D` refuses.

**What is asserted, per scenario:** every user's commit present exactly once on the remote
branch; no duplicate subjects above the trunk; each branch of a stack sits on the one below it and
the bottom on the trunk; the stack objects on GitHub hold what they should; PR bases point where
they should; after a sync, local equals remote; and where a refusal is the point, that it happened
**and that nothing irreversible happened before it**.

## What the campaign found

Six defects in gsx, all in code the unit tests had passed, all found by real repository state.
Each was fixed and the matrix replayed until clean.

1. **The cascade's fork point** (`sync`). The restack upstream was `git merge-base <parent>
   <child>`, which falls below the parent's own commits once the parent has been rewritten; then
   the parent's pre-run tip, which is wrong when the parent already carried a local commit the
   child was not built on (bob commits to B3-3 then syncs); then the later of the two, which is
   still wrong when the child was reconciled onto a remote copy sitting on the parent's remote
   version (alice's B2-5 met bob's B2-4). It is now the **latest merge-base over three states of
   the parent** -- before the run, after reconcile, now.
2. **git's rebase dedup cannot be leaned on** (a fact, not a gsx defect, but it is why 1 had to be
   exact): `rebase --onto` drops an identical-patch commit only while the file it adds is untouched
   afterwards on the onto side; a later append to that file turns the duplicate into an add/add
   conflict. Measured on a three-commit repository.
3. **An interleave was silently undone** (`sync`). A commit inserted mid-history left the branch
   diverged by sha with the remote holding nothing new; `git rebase <remote>/<branch>` then
   restored the remote's order. The first fix -- "the remote has nothing I lack above the trunk" --
   was too broad and left branches a teammate had merely restacked on the old trunk, to be
   rewritten and force-pushed over good ones on every sync. The rule is now the guard's own: **a
   divergence is a rewrite of ours only if the remote tip was once a tip of this branch** (the
   reflog).
4. **The guard refused every published move -- after the dissolve** (the pre-push hook and
   `submit --move`). Rule 2 counted every commit above the trunk as the branch's own, so a move
   "dropped" its old parents' commits; rule 1 could not see that a cherry-pick had integrated a
   teammate's push. Rule 2 now counts only commits **no other remote branch carries by patch**
   (descendants excluded); `sync` records the remote tip in the reflog after integrating it by
   cherry-pick; and `submit --move` **runs the installed guard itself, on the exact lines git will
   feed it, before dissolving anything**. The earlier sandbox had passed these only because its
   guard turned out to be silently uninstalled -- which is itself defect 6.
5. **`sh` was an undeclared requirement.** The pre-flight shells out to the hook the way git does;
   this codebase refuses any binary not in `bin-reqs.txt`, and the declared set is read from the
   installed catalog, so the fix is one line plus `cargo make gen` / `cargo make dev`.
6. **`init --clone` reported success for a guard git would never run** when `core.hooksPath` was
   set (found earlier in the same work, kept here because the campaign leaned on it): it now
   refuses and says what to do; and **upgrading a committed guard is `init --force`**, since a
   differing hook is refused on purpose.

After the first clean run, three changes were made on the user's decision and the matrix was
replayed once more: **`gsx sync` is local by default and `--push` publishes** (so `submit` now
refuses over an unreconciled branch for every publish, not only a move's); **a stopped sync is
finishable and cancellable** (`--continue`, `--abort`, the pre-run snapshot kept in
`<git-dir>/gsx/sync.json`, every touched branch put back -- not just the one the rebase stopped
on); and **gsx's state moved under `.git/gsx/`**. Scenario B6 was added for the first two.

Three harness mistakes are worth recording because they look like tool failures until read: two
users appending to the *same file* at the same spot is a genuine conflict, not a sync failure; a
PR that is in a stack cannot be merged with `gh pr merge` -- GitHub demands the stack merge API
(`gh stack merge <pr> --squash --yes`), and a **draft** PR cannot be merged at all; and a
leftover checked-out branch from a killed run gets *adopted* by `gh stack checkout` and produces
conflicts from another universe.

## Results
**25 of 25 scenarios pass.**

| # | scenario | result | time |
|---|---|---|---|
| A1 | two users, different PRs of one stack, both sync | **PASS** | 65s |
| A2 | two users append to the SAME middle PR; second to sync integrates | **PASS** | 57s |
| A3 | interleave a commit into a branch's own history, sync, teammate syncs | **PASS** | 61s |
| B1 | trunk moves; a 5-branch stack restacks once each, no duplicates | **PASS** | 66s |
| B2 | teammate adds to the bottom; alice holds local commits on three upper branches | **PASS** | 79s |
| B3 | trunk moved AND bob pushed to the middle AND alice has local work on top | **PASS** | 81s |
| B4 | 12-branch stack, trunk moves twice, two users alternate syncs | **PASS** | 157s |
| B5 | sync stops on a REAL conflict; resolve; git rebase --continue; sync again | **PASS** | 61s |
| B6 | a sync stops mid-cascade; --abort puts every touched branch back; plain sync is local | **PASS** | 75s |
| C1 | move the top branch onto another stack; sync while pending; publish; bob adopts | **PASS** | 136s |
| C2 | move a 3-branch SLICE onto another stack; teammate pushes to the middle of the slice; sync; publish | **PASS** | 134s |
| C3 | move an UNSUBMITTED single-PR branch from the trunk onto a stack top, with a conflict (the OS-3512 case) | **PASS** | 91s |
| C4 | move a slice onto the TRUNK (a stack of its own); publish | **PASS** | 87s |
| C5 | move, then --abort: every branch and both stacks back exactly | **PASS** | 70s |
| C6 | submit --move refuses over an unreconciled branch, BEFORE dissolving anything | **PASS** | 111s |
| C7 | two moves queued (A top -> B, then B top -> C), one publish | **PASS** | 112s |
| D1 | a squash of pushed commits is refused; the override lets it through | **PASS** | 43s |
| D2 | gh stack sync from a STALE clone after a restructure is refused by the guard | **PASS** | 119s |
| D3 | an unguarded clone is refused by every pushing command, not by the readers | **PASS** | 41s |
| E1 | the bottom PR is squash-merged; both users sync; nothing recreates the landed branch | **PASS** | 76s |
| E2 | gsx stack hides landed PRs; --merged shows them | **PASS** | 51s |
| E3 | move onto a stack whose bottom has landed (the finished-run logic) | **PASS** | 108s |
| F1 | sync --all with two stacks both needing work; dirty tree refused first | **PASS** | 65s |
| F2 | checkout '#N' resolves a stack or a PR from the repository; a bare number is refused | **PASS** | 41s |
| F3 | the gsx create/submit path: issue, branch, commit, stack, labels | **PASS** | 51s |


### A. Baseline collaboration

**A1 — two users, different PRs of one stack, both sync** · PASS

- alice: stack #626 ['A1-1', 'A1-2', 'A1-3']
- bob: commit on A1-1, sync
- alice: commit on A1-3, sync (must integrate bob's)
- bob: sync brings everything down; local == remote

**A2 — two users append to the SAME middle PR; second to sync integrates** · PASS

- bob then alice, both on A2-2

**A3 — interleave a commit into a branch's own history, sync, teammate syncs** · PASS

- alice interleaved on A3-2, sync forced A3-2 and A3-3
- bob syncs cleanly onto the rewritten history


### B. Cascades: the trunk moves, parents grow, several users

**B1 — trunk moves; a 5-branch stack restacks once each, no duplicates** · PASS

- bob landed on main
- alice sync: 5 restacked, all on new main, no dups

**B2 — teammate adds to the bottom; alice holds local commits on three upper branches** · PASS

- both people's commits present once each; stack intact

**B3 — trunk moved AND bob pushed to the middle AND alice has local work on top** · PASS

- all three sources integrated, once each

**B4 — 12-branch stack, trunk moves twice, two users alternate syncs** · PASS

- 12 branches, two trunk moves, alternating users: consistent

**B5 — sync stops on a REAL conflict; resolve; git rebase --continue; sync again** · PASS

- genuine conflict on shared.txt, sync stopped
- resolved, --continue, sync again: idempotent

**B6 — a sync stops mid-cascade; --abort puts every touched branch back; plain sync is local** · PASS

- sync stopped on B6-3 with B6-2 already rewritten; both ways out named
- --abort: all four branches back to their pre-run tips, on B6-4, clean tree
- --continue finished the cascade; nothing pushed; the summary names --push
- --push published it; both people's commits present once


### C. Moves: local until published, then published

**C1 — move the top branch onto another stack; sync while pending; publish; bob adopts** · PASS

- alice: C1A-3 -> #681
- bob pushed to C1A-3 (still on its old base for him)
- plain sync is local: reconciled and restacked, nothing pushed
- alice sync: took bob's commit, move intact, no push
- alice published the move
- GitHub: #681 grew, remainder is #682
- bob's gh stack sync refused by the guard; remote intact
- bob adopted both stacks; his stale commit survived and was pushed

**C2 — move a 3-branch SLICE onto another stack; teammate pushes to the middle of the slice; sync; publish** · PASS

- alice: C2A-3..5 -> #691
- alice sync: bob's commit taken into the slice, old chain NOT dragged back
- published; bases and contents correct

**C3 — move an UNSUBMITTED single-PR branch from the trunk onto a stack top, with a conflict (the OS-3512 case)** · PASS

- move stopped on a conflict in shared.txt
- resolved, --continue finished the move
- sync during the pending move: no-op, move intact
- published: lone PR joined the stack, base fixed

**C4 — move a slice onto the TRUNK (a stack of its own); publish** · PASS

- two stacks on GitHub, bases correct

**C5 — move, then --abort: every branch and both stacks back exactly** · PASS

- abort restored shas and tracking; sync is a no-op

**C6 — submit --move refuses over an unreconciled branch, BEFORE dissolving anything** · PASS

- refused; both stacks untouched on GitHub
- after sync, published with bob's commit intact

**C7 — two moves queued (A top -> B, then B top -> C), one publish** · PASS

- both moves published in one submit


### D. The guard

**D1 — a squash of pushed commits is refused; the override lets it through** · PASS

- squash refused, remote intact
- GIT_ALLOW_OVERWRITE=1 lets it through

**D2 — gh stack sync from a STALE clone after a restructure is refused by the guard** · PASS

- alice moved D2A-2..3 onto B and published
- guard held: the published restructure survived bob's gh stack sync
- bob --adopt, then sync: his commit landed on the new arrangement

**D3 — an unguarded clone is refused by every pushing command, not by the readers** · PASS

- sync/submit/move refused; stack reads; GSX_NO_GUARD=1 runs


### E. Landed history

**E1 — the bottom PR is squash-merged; both users sync; nothing recreates the landed branch** · PASS

- PR #742 (E1-1) squash-merged, branch deleted on GitHub
- alice: E1-2..4 restacked onto the squash, E1-1 not pushed back
- bob synced and purged the landed branch

**E2 — gsx stack hides landed PRs; --merged shows them** · PASS

- landed PR hidden by default, back with --merged

**E3 — move onto a stack whose bottom has landed (the finished-run logic)** · PASS

- moved onto a stack with landed history; landed branch stays gone


### F. Edges and the create path

**F1 — sync --all with two stacks both needing work; dirty tree refused first** · PASS

- dirty refused; --all restacked both stacks onto the new trunk

**F2 — checkout '#N' resolves a stack or a PR from the repository; a bare number is refused** · PASS

- #766 -> stack, #764 -> PR, 766 refused

**F3 — the gsx create/submit path: issue, branch, commit, stack, labels** · PASS

- create x2 -> SCENARIOS-767 <- SCENARIOS-768; submit opened both PRs in one stack

