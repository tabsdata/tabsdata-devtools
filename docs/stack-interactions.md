<!--
Copyright 2026 Tabsdata Inc.
-->

# What gsx runs, per interaction

For each kind of interaction a developer has with stacked PRs: the `git`/`gh` operations gsx
performs, with their options, in order -- and one short paragraph on why it is done that way
where the why is not obvious. `docs/stack-workflow.md` is the how-to; this is the ledger.

Conventions: `R` is the gh-stack remote (`git config gh-stack.remote`, else `origin`); `T` the
trunk (`main`); `B` a branch, `P` its parent in the stack; `<base>` a PR's base branch *as GitHub
records it*. Every command gsx runs is also printed by `--verbose`, and `--dry-run` prints the
mutating ones instead of running them.

Two things run before every gsx command and are not repeated below: the **guard check** (a file
read and `git config core.hooksPath`; `submit`, `sync`, `prune` and `move` refuse if the pre-push
guard is not installed) and the **move-session notice** (`<git-dir>/gsx/move.json`, read; a warning if
a move is unpublished).

---

## 1. No outstanding stacks or PRs: create and submit the first PR

`tdd gsx create -s "summary" [-m body] [-- PATH...]`, then `tdd gsx submit`

| step | command |
|---|---|
| the issue | `gh issue create --title "summary" --body "body"` → `#N` |
| stage | `git add --all` (or `git add -- PATH...`) |
| the branch, tracked | `gh stack init --base T <POSTFIX>-N` (not in a stack yet) |
| the commit | `git commit --file -` with `[<POSTFIX>-N] summary` and trailer `Closes #N` |
| — submit — | |
| the listing | `gh api repos/{owner}/{repo}/stacks` (is anything here an unpublished move? no) |
| push and PR | `gh stack submit --auto --open`; `--draft` drops `--open`, which is gh-stack's *ready for review* for the whole stack: without it new PRs are drafts and existing drafts stay drafts, with it every draft in the stack is marked ready |
| grow the stack object | `gh api repos/{owner}/{repo}/stacks` again; nothing to add for one PR |
| labels, reviewers | `gh pr edit N --add-label ... --add-reviewer ...`, one per PR that changes |

`init` rather than `add` because there is no stack to add to; `gh stack add` would refuse.
Nothing is pushed by `create` -- a branch and a commit are local until `submit`, which is the
one publishing verb. **A single PR is a PR and no stack** on GitHub: a stack object needs two, so
`gsx stack` shows it `!` (local only) until a second PR joins it; that is GitHub's shape, not a
gsx state.

## 2. Outstanding stacks exist: create a PR on top of the one you are on

`tdd gsx create -s "summary"` while standing on a stack branch

| step | command |
|---|---|
| the issue | `gh issue create --title ... --body ...` |
| stage | `git add --all` |
| the branch, tracked | `gh stack add <POSTFIX>-N` (creates the branch on top of the current one and switches to it) |
| the commit | `git commit --file -` |

`gh stack add` is used *before* the commit and with the index left alone, so that a subset
commit (`git add PATHS` → `stack add` → `commit`) is one path. To start a **new, unrelated stack**
while others exist, `git checkout T` first: `create` then takes the `init` path of §1.

## 3. An unrelated stack landed (the trunk moved): sync, no conflicts

`tdd gsx sync`

| step | command |
|---|---|
| fetch | `git fetch -q R` |
| the trunk | `git fetch R T:T` (or `git merge --ff-only R/T` when standing on `T`) |
| PR facts | one GraphQL: per PR `state`, `baseRefName`, `headRefName` |
| landed branches | left out of everything below (a branch whose PR is `MERGED`/`CLOSED`) |
| snapshot | `git rev-parse` per branch: every tip **before** anything moves |
| reconcile, per branch bottom-up | `git rev-parse R/B`; `git merge-base --is-ancestor` both ways → here: `R/B` already in `B`, nothing to take |
| snapshot again | every tip after reconcile |
| restack, per branch bottom-up | `git merge-base --is-ancestor P B` → no; fork point = latest of `git merge-base <P before> B`, `git merge-base <P after reconcile> B`, `git merge-base P B`; then `git checkout B && git rebase --onto P <fork> B` |
| session | `<git-dir>/gsx/sync.json` written before the first change (every tip, where you stood); removed when the run completes |
| push | **only with `--push`**: `git push --atomic --force-with-lease=refs/heads/B:<fetched sha> ... R B...` -- forced, because every branch was rewritten. Without it: "N branch(es) to push: `tdd gsx sync --push`, or `tdd gsx submit`" |

The trunk is fast-forwarded through `fetch T:T` rather than checked out, so the operator stays
where they were; it refuses anything but a fast-forward, which is the guarantee wanted. **The
fork point is the latest of three merge-bases** because each of the parent's states this run --
before, after reconcile, now -- is the true fork in some case, and `git rebase --onto` cannot be
trusted to skip a duplicate whose file was edited later. The lease is pinned to the sha this run
fetched, so a remote that moved in between is a refusal rather than a loss; `--atomic` because
half a stack on the remote is worse than none.

## 4. An unrelated stack landed: sync, with a conflict

Same as §3 until a `git rebase --onto` stops:

| step | command |
|---|---|
| gsx stops | the rebase is left in progress; the error names the branch, the command, and both ways out |
| finish | resolve, `git add`; `tdd gsx sync --continue` = `git rebase --continue` (`GIT_EDITOR=true`), then the rest of the run with the session's pre-run tips |
| or undo | `tdd gsx sync --abort` = `git rebase --abort`, `git checkout <where you stood>`, then `git branch -f B <pre-run tip>` for every touched branch (`git reset --hard` for the checked-out one); session removed |
| a plain `sync` meanwhile | refused, naming both -- unless you already finished the rebase by hand, in which case it resumes |

The session exists for `--abort`: `git rebase --abort` undoes only the branch the rebase stopped
on, and the branches the cascade had already rewritten would stay rewritten. The trunk is not put
back; it was only ever fast-forwarded.

## 5. Sync, local only

`tdd gsx sync` -- the default. Everything in §3 except the push. While a **move is unpublished**
(`<git-dir>/gsx/move.json` exists) the summary points at `tdd gsx submit --move` instead of
`--push`.

## 6. Sync, local and remote

`tdd gsx sync --push` -- §3 with the last row. Only branches whose tip changed are pushed; a
branch whose remote copy is now an ancestor goes plain, a rewritten one goes with a lease; one
`push --atomic` carries both kinds. Held, with the reason said, while a move is unpublished or
while **GitHub and this checkout disagree about the stacks** with no move of this checkout's to
explain it (one `gh api .../stacks`, asked only when a push was asked for) -- pushing then would
publish an older arrangement.

## 7. Working on top of another user's PR; they push new commits to it

You: `tdd gsx create` on top of their branch `X` (§2). Later `tdd gsx sync`:

| step | command |
|---|---|
| reconcile `X` | `git merge-base --is-ancestor R/X X` → no; `--is-ancestor X R/X` → yes, they appended: `git checkout X && git rebase R/X` (a fast-forward) |
| reconcile yours `Y` | `R/Y` in `Y` → nothing |
| restack `Y` | `git merge-base --is-ancestor X Y` → no (X grew): fork = `git merge-base <X before> Y`; `git rebase --onto X <fork> Y` |
| push (`--push`, or `submit`) | `X` not pushed (unchanged from remote); `Y` forced with a lease |

Their commits come in **before** your branch is restacked, which is the whole point of the order:
restack first and their commit would be rebased away and then force-pushed over.

## 8. Two users append to the same PR

Each: `git commit` on `B`, then `tdd gsx sync`. The second to sync:

| step | command |
|---|---|
| classify | neither `R/B` in `B` nor `B` in `R/B` |
| a rewrite of ours? | `git log -g --format=%H refs/heads/B`; `git rev-list -n 1 R/B --not <those tips>` → not empty: the remote tip was never ours |
| reconcile | `git checkout B && git rebase R/B` -- theirs first, ours replayed on top; patches already present are dropped |
| push (`--push`, or `submit`) | plain: `R/B` is now an ancestor |

Both people's commits end up on `B`, in the order *theirs, then mine*; the push needs no force.
The reflog question is what tells this case from §9.

## 9. Modifying your own PR: append, or interleave

Append: `git commit` on `B`, `tdd gsx sync` → a fast-forward push. Interleave: `git rebase -i P`
and insert the commit; `tdd gsx sync`:

| step | command |
|---|---|
| classify | diverged by sha |
| a rewrite of ours? | the remote tip **is** in `B`'s reflog (it is the tip you rewrote) → yes: the branch is left alone |
| restack above | each branch above `B`: `git rebase --onto B <fork> <child>` |
| push (`--push`, or `submit`) | `B` and its children forced, with leases |

The guard passes it: the remote tip is reachable from a past tip (rule 1), and every commit the
remote branch has of its own is still present by patch (rule 2). If a teammate pushed to `B`
concurrently, the reflog test fails and §8 applies instead -- the remote's order becomes the base
and the interleave's *order* is lost; the commits are not.

## 10. Moving PRs to another stack (local)

`tdd gsx move --to '#N' | <top branch> | T [--yes] [--dry-run]`, standing on the bottom of the slice

| step | command |
|---|---|
| preconditions | clean tree (`git status --porcelain --untracked-files=no`), no rebase stopped, no session open |
| PR facts | one GraphQL for the moved PRs: state, merge queue, auto-merge (a queued PR refuses the move) |
| forget the source | `gh stack unstack --local` |
| forget the target | `gh stack checkout <target top>` then `gh stack unstack --local` |
| re-declare what stays | `git checkout T && gh stack init --base T <kept...>` (minus the run of landed PRs at the bottom) |
| re-declare the target | `git checkout T && gh stack init --base <base> <target...> <moved...>` |
| replay the bottom of the slice | `git rebase --onto <target top> <old parent> <bottom moved>` |
| the rest of the slice | `git checkout <bottom moved> && gh stack rebase --upstack --no-trunk` |
| remember | `<git-dir>/gsx/move.json` written: the moves, and the tracking file's bytes before |

**Nothing reaches GitHub.** Each `init` runs from the trunk because `gh stack init` refuses while
the current branch is in a stack -- including the one it just made. The landed run at the bottom
is dropped from both inits because `init` keeps a PR association only where it can find an open
PR, and a 90-PR history would otherwise come back unassociated and be pushed. `--abort` restores
every branch from the session and the tracking file byte for byte.

## 11. Publishing a move

`tdd gsx submit --move`

| step | command |
|---|---|
| reconciled? | `git fetch R`; GraphQL for bases and states; per branch the §3 classify, or for a moved branch `git rev-list --reverse --right-only --cherry-pick B...R/B --not R/<base>` filtered by subject → anything missing **refuses**, naming `gsx sync` |
| the guard, first | `sh .githooks/pre-push R <url>` fed `refs/heads/B <local> refs/heads/B <remote>` for every branch about to be pushed → a refusal here **refuses before anything is dissolved** |
| dissolve | `gh stack unstack <n>` for each stack the move took PRs out of |
| really gone? | `gh api repos/{owner}/{repo}/stacks/<n>` → 404, else stop (a queued PR keeps a stack) |
| publish the stack you are on | `gh stack submit --auto --open`: pushes the rewritten branches, fixes each PR's base, grows the target |
| grow what gh-stack would not | `gh api -X POST repos/{owner}/{repo}/stacks/<n>/add -F pull_requests[]=...` for any open PR of the local stack the GitHub stack still lacks |
| the remainder | `gh stack checkout <its top> && gh stack submit --auto --open`, non-fatal; then back |
| the session | `<git-dir>/gsx/move.json` removed |

The dissolve is unavoidable -- the API cannot take a PR out of a stack -- and it is why every
check runs before it: a push refused *after* the dissolve leaves the arrangement dissolved on one
side and unpublished on the other. **The remainder gets a new stack number; PR numbers never
change.** The explicit `add` exists because `gh stack submit` grows a stack only when the local
stack lists every PR the GitHub one has, and a GitHub stack keeps its merged PRs for ever.

## 12. Adopting a restructure somebody else published

`tdd gsx checkout '#N'`, then `tdd gsx checkout '#N' --adopt`

| step | command |
|---|---|
| resolve `#N` | `gh api repos/{owner}/{repo}/stacks`: an open stack numbered N, else PR N |
| in the way? | the tracking file (read): any local stack holding branches of N that is not N → **refused**, naming them |
| `--adopt`: drop numbered ones | `gh stack unstack <old n> --local` |
| drop an unnumbered one | `git checkout <one of its branches> && gh stack unstack --local`, then back |
| take the stack | `gh stack checkout N` |
| bring the branches current | `git fetch R`; per branch the §3 reconcile (a branch with work of its own is rebased onto `R/B`, never reset) |

Refused rather than adopted silently because `gh stack checkout` meets the same state with a
prompt whose options include *delete the stack on GitHub*. `--adopt` loses no commits, which is
why it asks no confirmation. The unnumbered case is what a stale clone's `gh stack sync` leaves
behind: gh-stack clears a stack's number when GitHub answers 404 for it.

## 13. The bottom PR lands (squash-merged, branch deleted)

`tdd gsx sync` in any clone, then `tdd gsx purge`

| step | command |
|---|---|
| sync: PR facts | GraphQL says the bottom PR is `MERGED` → its branch is **left out of every step** |
| the branch above | `git merge-base --is-ancestor T B2` → no: `git rebase --onto T <fork> B2`, and the cascade above it |
| push | forced, with leases; the landed branch is **not** pushed |
| purge | `git fetch --prune`; `gh pr list --state all --json ...`; `git branch -D <landed>` |

A landed branch is history, not state: its commits are in the trunk and its remote copy is gone,
and a sync that read it as "unpublished" pushed it back to life -- measured.

## 14. A stale clone runs `gh stack sync` after somebody's restructure

Not a gsx command; the guard is what acts.

| step | command |
|---|---|
| gh-stack | fetches, finds its stack id 404s, skips reconciliation, cascade-rebases from the stale copies, `git push --force-with-lease=<ref>:<sha> --atomic` |
| the guard, rule 1 | `git log -g refs/heads/B` and `git rev-list -n 1 <remote tip> --not <tips>` → the remote tip was never here → **refused**; with `--atomic`, the whole push |
| gh-stack | prints "Push failed ... Run `gh stack push`" -- which the guard refuses the same way |

Then §12. This is the case the whole design exists for, and it is caught only in a clone where
`tdd gsx init` was run; nothing can protect a clone without the guard.

## 15. Checking out a PR or a stack

`tdd gsx checkout <branch> | '#PR' | '#STACK'`

| target | command |
|---|---|
| a branch of a tracked stack | `gh stack checkout <branch>` |
| a branch gh cannot resolve | `gh pr list --head <branch>` → `gh stack checkout <repo url>/pull/N` |
| `#N`, a stack | `gh stack checkout N` |
| `#N`, a PR | `gh stack checkout <repo url>/pull/N` |
| a PR in no stack | `git checkout <branch>` then `gh stack init --base T <branch>` |

`#N` is safe because GitHub numbers stacks and PRs from one counter -- a number is one or the
other, never both -- and gsx reads which from the listing. A bare number is refused: a *branch*
named `42` is not in that number space and nothing could tell them apart. The PR URL is used
where gh would otherwise read a number as a stack.

## 16. Shrinking a long-lived stack

`tdd gsx prune [--yes]`

| step | command |
|---|---|
| the listing | `gh api repos/{owner}/{repo}/stacks` (which PRs are still open) |
| dissolve | `gh stack unstack <n>` |
| relink what is open | `gh stack link <open pr> <open pr> ...` (a new number) |
| track it here | `git checkout T && gh stack init --base T <kept branches...>` |

Forced by the API: there is no way to take a PR out of a stack, so it is the whole stack or
nothing, and `link` gives the result a new number.

---

## Two questions, decided

**`sync` is local by default; `--push` publishes; `submit` refuses over an unreconciled branch.**
Every publishing act is then an explicit verb, a resolved conflict is looked at before it goes
anywhere, and skipping the sync is caught rather than trusted. `--push` rather than `--remote`,
because in `stack` that word means *show* that side.

**A stopped sync is finishable and cancellable** -- `--continue` and `--abort`, with the
pre-run snapshot kept in `<git-dir>/gsx/sync.json` until the run completes. See §4.

Both were run through the scenario campaign before landing (`docs/gsx-scenario-report.md`).
