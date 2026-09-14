<!--
Copyright 2026 Tabsdata Inc.
-->

# Working on stacked PRs

The developer guide: how to set a repository up, how to prepare a clone, and how to do each
everyday task -- **by hand with `git`/`gh`/`gs`, and with `gsx`, side by side**.

`docs/stack-collaboration.md` is the design behind it and argues *why*; this is the *how*.
`gs` is `gh stack`.

The rules of the road it assumes:

1. **A submitted PR is append-only.** You change it by adding a commit, never by amending or
   squashing one that is already on the remote.
2. **Two people may add commits to the same PR.** Sync takes both.
3. **A move is local until you publish it**, and publishing is the one irreversible step.

---

## 1. Once per repository -- the GitHub configuration

Do this once, as a repository admin.

### 1.1 Protect the trunk, and only the trunk

```bash
gh api -X POST repos/{owner}/{repo}/rulesets --input - <<'JSON'
{
  "name": "protect-trunk",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
  "rules": [{"type": "non_fast_forward"}, {"type": "deletion"}]
}
JSON
```

`non_fast_forward` blocks rewriting `main`; `deletion` blocks deleting it. **This costs nothing**:
stacking never force-pushes the trunk, so nothing legitimate is blocked. Add
`{"type": "pull_request"}` if you also want to require a PR to land on `main`.

Watch out for one thing when you test it: **`non_fast_forward` is about the shape of the update,
not about the `--force` flag.** `git push --force` of a commit added on top still succeeds,
because that is a fast-forward. Only a genuine rewrite is declined.

### 1.2 What you must *not* try to configure

**Do not block force pushes on the stack branches.** Restacking *is* a forced update -- it is how
branch N is kept sitting exactly on branch N-1 -- so a rule against it stops all normal work. The
server cannot tell a safe restack from a clobber, because the difference lives in the pusher's
reflog, which the server never sees. GitHub.com has no custom pre-receive hooks either.

That is why the branch-level protection is **client-side**, in §2. The split is worth remembering:
*the trunk is protected on the server; the stack branches are protected in each clone.*

A ruleset on the stack branches is still useful for one thing -- a **temporary freeze** right
after a big restructure, with whoever did it in the bypass list, until everyone has adopted the
new layout. Remove it afterwards.

### 1.3 Commit the guard

Once (see §2), so the hook arrives with the code:

```bash
tdd gsx init            # writes .githooks/pre-push and sets core.hooksPath
git add .githooks/pre-push && git commit -m "add the gsx pre-push guard"
```

---

## 2. Once per clone -- the guard

`.git/hooks` is **never cloned**, by design: a hook is code the clone's owner runs. So there is no
arrangement in which a teammate is protected without doing anything, and every clone runs one
command.

| by hand | with gsx |
|---|---|
| `cp .githooks/pre-push .git/hooks/pre-push` | `tdd gsx init` |
| `chmod +x .git/hooks/pre-push` | |
| *or* `git config core.hooksPath .githooks` | *or* `tdd gsx init --clone` for this clone only |
| `gh extension install github/gh-stack` | (checked and reported by `init`) |

`tdd gsx init --check` reports what is in place without writing anything. When gsx ships a newer
guard, `tdd gsx init --force` in one clone plus a commit upgrades everyone -- a differing hook is
refused otherwise, since it might be yours.

**What the guard refuses**, for a branch the remote already has:

| | |
|---|---|
| **rewrite** | a forced update whose remote tip was never in your branch's history -- someone else rewrote it and you would discard their work |
| **drop** | a push that loses a commit the remote branch has *of its own* (a squash, a deleted commit) -- matched by patch-id, then by subject. Its old parents' commits are not its own, so a move passes |

Fast-forwards, new branches, deletions and rewrites of *your own* history all pass, so ordinary
restacking and interleaving are untouched. `GIT_ALLOW_OVERWRITE=1 <command>` overrides either,
for the times you mean it.

**`gsx submit`, `sync`, `prune` and `move` refuse to run until the guard is installed.** A clone
without it is the one case the design cannot protect: measured, `gh stack sync` from an unguarded
stale clone overwrote an entire restructure, and the same clone with the guard was refused.
`GSX_NO_GUARD=1` exists for a checkout where the hook genuinely cannot be installed.

---

## 3. The everyday tasks

### 3.1 Start a stack: the first PR

| by hand | with gsx |
|---|---|
| `gh issue create --title "the loader"` → `#15` | `tdd gsx create -s "the loader"` |
| `git checkout -b FOO-15 main` | |
| `git add -A && git commit -m "[FOO-15] the loader" -m "Closes #15"` | |
| `gh stack init --base main FOO-15` | |

gsx derives the branch name from the repository (`tabsdata-conn-gcs` → `GCS-15`), writes the
`Closes #15` trailer, and picks `init` or `add` depending on whether you are already in a stack.

### 3.2 Add another PR on top

| by hand | with gsx |
|---|---|
| `gh issue create --title "wire it up"` → `#16` | `tdd gsx create -s "wire it up"` |
| `git checkout -b FOO-16` | |
| `git add -A && git commit -m "[FOO-16] wire it up" -m "Closes #16"` | |
| `gh stack add FOO-16` | |

### 3.3 Push the stack and open the PRs

| by hand | with gsx |
|---|---|
| `gh stack submit --auto --open` | `tdd gsx submit` |
| `gh pr edit 21 --add-label run-ci --add-reviewer alice` | `tdd gsx submit --label:new run-ci --reviewer:new alice` |
| *(one `gh pr edit` per PR)* | *(one call per changed PR, the rest skipped)* |

### 3.4 Change a PR -- add a commit

The normal way to change anything already submitted. **Never amend or squash a pushed commit.**

| by hand | with gsx |
|---|---|
| `git checkout FOO-16` | `git checkout FOO-16` |
| `git add -A && git commit -m "[FOO-16] review fix"` | `git add -A && git commit -m "[FOO-16] review fix"` |
| `git fetch origin` | `tdd gsx sync` |
| `git rebase origin/FOO-16` *(take anyone else's commits first)* | |
| `git checkout FOO-17 && git rebase --onto FOO-16 $(git merge-base FOO-16 FOO-17) FOO-17` *(and each branch above)* | |
| `git push --atomic --force-with-lease origin FOO-16 FOO-17` | `tdd gsx submit` (or `tdd gsx sync --push`) |

This is the sequence `gsx sync` exists to get right, and the row order is the whole point:
**reconcile with `origin/<branch>` before restacking anything above it.** Do it in the other order
and the rebase silently drops a teammate's commit, then the force-push publishes the loss.

### 3.5 Change a PR in the middle of a stack

Exactly the same as §3.4 -- the branches above are what the cascade is for. `gsx sync` restacks
only the ones that actually need it; if a teammate already pushed the restack, your copy
fast-forwards onto theirs and nothing is rewritten at all.

### 3.6 Interleave a commit into a branch's own history

| by hand | with gsx |
|---|---|
| `git checkout FOO-16` | `git checkout FOO-16` |
| `git rebase -i FOO-15` *(insert your commit where you want it)* | `git rebase -i FOO-15` |
| `git push --force-with-lease origin FOO-16` | `tdd gsx sync`, then `tdd gsx submit` |
| *(then restack everything above, as in §3.4)* | |

Allowed by both guard rules: the patches all survive the rebase, so nothing looks dropped.

### 3.7 Fetch a stack someone else created

| by hand | with gsx |
|---|---|
| `gh api repos/{owner}/{repo}/stacks --jq '...'` *(find the number)* | `tdd gsx stack --remote --all --short` |
| `gh stack checkout 41` | `tdd gsx checkout '#41'` |
| `gh stack checkout FOO-16` | `tdd gsx checkout FOO-16` |

`gsx checkout` takes **a branch name, `#<PR>` or `#<STACK>`** and nothing else. A *bare* number is
refused, because `gh stack checkout 42` means stack 42, or PR 42, or the branch `42`, depending on
what exists that day. `#42` is safe because GitHub numbers stacks and PRs from **one counter**, so
a number is one or the other and never both -- gsx reads which off the repository rather than
guessing.

### 3.8 Sync -- take what the remote has, keep what you have; then publish

`gsx sync` is **local by default**: it fetches, integrates, restacks, and tells you how many
branches are ready to push. Publishing is `tdd gsx submit` -- or `tdd gsx sync --push` when you
want both in one step.

| by hand | with gsx |
|---|---|
| `git fetch origin` | `tdd gsx sync` |
| `git fetch origin main:main` *(fast-forward the trunk)* | |
| **per branch, bottom-up:** | |
| `git merge-base --is-ancestor origin/B B && continue` *(nothing of theirs)* | |
| `git checkout B && git rebase origin/B` *(take theirs, keep yours)* | |
| **then, per branch, bottom-up:** | |
| `git merge-base --is-ancestor <parent> B && continue` | |
| `git rebase --onto <parent> $(git merge-base <parent> B) B` | |
| `git push --atomic origin <fast-forwarded...>` | `tdd gsx sync --push` (or `tdd gsx submit`) |
| `git push --atomic --force-with-lease=refs/heads/B:<fetched sha> origin <rewritten...>` | |

**Do not use `gh stack sync` for this.** It rebases from your local copies and force-pushes with
leases taken from a fetch seconds earlier, so the leases always pass; if your copy of a branch is
missing a teammate's commit, it is rebased away and then overwritten. `gsx sync` reconciles first
and touches no stack object at all.

After a reconcile, most pushes are plain fast-forwards -- **in the steady state nothing is
forced.** `tdd gsx sync --all` does every stack.

**If a rebase conflicts**, the sync stops and names both ways out: resolve, `git add`, then
`tdd gsx sync --continue`; or `tdd gsx sync --abort`, which puts **every** branch the sync touched
back where it was -- not just the one the rebase stopped on, which is all `git rebase --abort`
would do.

**`tdd gsx submit` refuses if any branch is behind its remote copy** and says to sync first --
for every publish, not only a move's.

### 3.9 See where everything stands

| by hand | with gsx |
|---|---|
| `jq '.stacks[]' .git/gh-stack` | `tdd gsx stack` |
| `gh api repos/{owner}/{repo}/stacks --paginate` | `tdd gsx stack --all --short` |
| `git rev-list --left-right --cherry-pick --count B...origin/B --not origin/main` | |

Symbols: `=` in sync, `+` ahead, `-` behind, `x` diverged, `?` only GitHub has it, `!` only this
clone has it, `[]` what you are on.

### 3.10 Move PRs from one stack to another

You move the branch you are standing on **and everything above it**. Nothing reaches GitHub.

| by hand | with gsx |
|---|---|
| `gh stack unstack --local` *(forget the stack you are in)* | `tdd gsx move --to '#41'` |
| `gh stack checkout <target top> && gh stack unstack --local` | |
| `git checkout main && gh stack init --base main <kept...>` | |
| `git checkout main && gh stack init --base <base> <target...> <moved...>` | |
| `git rebase --onto <target top> <old parent> <bottom moved branch>` | |
| `git checkout <bottom moved> && gh stack rebase --upstack --no-trunk` | |

`--to` takes a stack number (`#41`), the top branch of a tracked stack, a branch whose PR is in no
stack, or the trunk (which makes the moved branches a stack of their own). `--dry-run` shows the
plan; `tdd gsx move --abort` undoes it while it is still unpublished.

### 3.11 Publish a move

**The one step that cannot be undone.**

| by hand | with gsx |
|---|---|
| *check every branch is reconciled first, or stop* | `tdd gsx submit --move` |
| `gh stack unstack <n>` *(dissolve the old stack on GitHub)* | |
| `gh api repos/{owner}/{repo}/stacks/<n>` *(404 = it really let go)* | |
| `gh stack submit --auto --open` *(the stack you are on)* | |
| `git checkout <the remainder> && gh stack submit --auto` *(as a new stack)* | |

Why dissolve at all: **the API cannot take a PR out of a stack.** `unstack` takes no body and
`link` refuses a PR that belongs to another stack, so the moved PRs cannot join their new stack
while the old one holds them.

What changes: **the stack number of whatever stayed below you.** The target keeps its number
(link appends), and no PR number ever changes.

`gsx submit --move` refuses to start if any branch is behind its remote copy, and says to run
`tdd gsx sync` -- because the dissolve happens *before* the push, and discovering the problem
mid-publish means the old arrangement is already gone.

### 3.12 Adopt a restructure someone else published

Somebody published a `gsx move`; your tracking file still describes the stacks it replaced.
Nothing here pushes.

| by hand | with gsx |
|---|---|
| `gh api repos/{owner}/{repo}/stacks --jq '...'` *(find the new number)* | `tdd gsx checkout '#7'` |
| `gh stack unstack <old#> --local` *(for each stale stack)* | ↑ *refused, naming the stacks in the way* |
| `git switch main && git fetch origin` | `tdd gsx checkout '#7' --adopt` |
| `git branch -f <b> origin/<b>` *(every branch -- **discards unpushed work**)* | |
| `gh stack checkout <new#>` | |

**`gsx checkout` refuses a restructured stack rather than adopting it silently**, and says which
local stacks are in the way. That is not caution for its own sake: `gh stack checkout` meets the
same situation with a prompt, and one of the three things it offers is *delete the stack on
GitHub* -- the last thing an adopting clone means to do. gsx decides it beforehand so the prompt
never appears.

**`--adopt` loses no commits**, and is deliberately not called `--force`. The by-hand column
resets each branch to its remote copy and throws away anything unpushed; `--adopt` **reconciles**
instead, so a branch with work of its own is rebased onto its remote copy and keeps it -- and the
next push is a fast-forward. What it replaces is your local *tracking*; the one thing it asks you
to acknowledge is that your local stacks are about to change. (`gsx init --force` is a real
overwrite -- it replaces a pre-push hook you wrote -- which is why that word is not spent here.)

`tdd gsx stack --all --short` shows the stale stacks first if you want to look before acting:
they wear a red `!`.

### 3.13 Housekeeping

| task | by hand | with gsx |
|---|---|---|
| drop merged branches | `gh pr list --state merged` + `git branch -D <b>` | `tdd gsx purge` |
| shrink a stack that has landed most of itself | `gh stack unstack <n>` + `gh stack link <open prs>` + `gh stack init` | `tdd gsx prune` |
| approve a stack | `gh pr review --approve` per PR | `tdd gsx approve --stack --approvers alice` |

---

## 4. When you are refused

| what you see | what it means | what to do |
|---|---|---|
| `pre-push: REFUSING to force-push B ... never part of your local B` | someone else rewrote that branch; this push would discard their work | `tdd gsx sync`, then push again |
| `pre-push: REFUSING to push B ... These commits are on origin/B and not in what you are pushing` | a squash or a dropped commit in a submitted PR | add a commit instead; `GIT_ALLOW_OVERWRITE=1` if you truly meant it |
| `the pre-push guard is not installed here` | this clone has never been prepared | `tdd gsx init` |
| `origin has commits these branch(es) do not ... publishing a move dissolves the old stack` | you are about to publish over a branch you have not reconciled | `tdd gsx sync`, then `tdd gsx submit --move` |
| `N branch(es) to push, held: an unpublished move is in progress` | expected: a half-made arrangement is not published | `tdd gsx submit --move` when ready |
| `a sync is stopped in a rebase` | a previous sync hit a conflict | resolve, `git add`, `tdd gsx sync --continue`; or `--abort` |
| `... held: GitHub and this checkout disagree ...` | somebody else's restructure that this clone has not adopted | §3.12 -- adopt it; do **not** publish |
| `stack #N has been restructured since this checkout last saw it` | the same thing, met by `checkout` | `tdd gsx checkout '#N' --adopt` |
| `GH013: Repository rule violations found for refs/heads/main` | you tried to rewrite the trunk | you almost certainly did not mean to |

---

## 5. Quick reference

Also `tdd gsx --quick-ref`, which prints exactly this (a test keeps the two identical).

```
prepare this clone                   tdd gsx init [--clone] [--check]
start a PR where you are             tdd gsx create -s "summary"
change a PR                          commit, tdd gsx sync, tdd gsx submit
push the stack, open its PRs         tdd gsx submit
take the remote's work, locally      tdd gsx sync [--all]          --continue | --abort after a conflict
...and publish it                    tdd gsx sync --push           or tdd gsx submit
see the stacks                       tdd gsx stack [--all] [--short] [--remote | --local]
fetch someone's PR or stack          tdd gsx checkout FOO-16 | '#22' | '#41'
adopt a restructured stack           tdd gsx checkout '#41' --adopt
move PRs onto another stack          tdd gsx move --to '#41'      a stack by number
                                     tdd gsx move --to FOO-16     or that stack's TOP branch
publish that move                    tdd gsx submit --move
labels and reviewers                 tdd gsx apply --label:<scope>[:<mode>] LIST
                                     tdd gsx apply --reviewer:<scope>[:<mode>] LIST
housekeeping                         tdd gsx purge    delete the branches whose PR has landed
                                     tdd gsx prune    drop a stack's landed history

  scope   new (default) | top | all | mine        n | t | a | m
  mode    replace (default) | add                 r | a
          --label:all:add run-ci       adds to every PR of the stack
          --reviewer:new alice,bob     replaces on the PRs this run creates

  every command takes --help, --verbose and --format json|view,
  and --dry-run wherever it writes.
```
