<!--
Copyright 2026 Tabsdata Inc.
-->

# Stacks that several people work on

A design for making `gh stack` safe when more than one person touches a stack, and for making
`gsx move` publishable without destroying anybody's work. The problem statement is
`~/Downloads/HANDOFF.md` (a restructure in `tabsdata-os` left every other clone able to overwrite
the rebased branches); this is the answer to it.

Everything marked **verified** was reproduced with real commands -- the transcripts are in
`.claude/VERIFIED.md`. Everything else is a decision or a prediction, and says so.

## 1. The model we are designing for

The rules of the road, as the team wants to work:

1. **A PR is a branch, and its commits are append-only once submitted.** No amending, no
   squashing, no dropping of a commit that is already on the remote.
2. **You change a PR by adding a commit to it.** Including in the middle of a stack, and
   including interleaving a new commit among a branch's existing ones.
3. **Two people may add commits to the same PR**, from different clones, without coordinating.
4. **Sync means: take what the remote has, keep what I have, push the union.** Never "mine wins".
5. **A move is local until it is published.** `gsx move` rearranges here; `gsx submit --move`
   is what GitHub sees. Publishing must refuse to run over an unreconciled branch, and syncing
   must not undo the move.

Rule 1 is a *policy*; rules 3-5 are *data safety*. They need different mechanisms, and the
difference matters: policy is worth a refusal with an override, data loss is worth a refusal
with a very loud one.

## 2. Why `gh stack` cannot give this as shipped

**Stacking by rebase rewrites history, so every restack is a forced update.** That is not a bug;
it is what keeps branch N sitting exactly on branch N-1. The bug is what gh-stack does with it.

Three paths, all verified (`HANDOFF.md` §3, re-checked here):

- **`gs sync` rebases from your local copies and then force-pushes.** The leases are
  `--force-with-lease=refs/heads/<b>:<sha>` where the sha comes from a fetch seconds earlier, so
  **they always pass** -- the lease protects nothing. If your copy of a branch is missing a
  teammate's commit, the rebase drops it and the push publishes the loss.
- **The explicit `ref:sha` lease form disables git's own `--force-if-includes`** (git-push docs),
  so the one git feature that would have caught this cannot.
- **A stack that was dissolved and re-linked gives no prompt at all.** Sync finds its tracked
  stack id 404s, skips reconciliation silently, and proceeds to rebase and push. This is exactly
  the state a `gsx move` leaves in every *other* clone.

And one API fact that shapes everything below: **there is no way to remove a PR from a stack.**
`POST .../stacks/{n}/unstack` takes no body and dissolves the whole stack; `link` refuses a PR
that belongs to another one. So a move is always dissolve-and-relink, and that is why it is
irreversible and why it must be a deliberate, separate step.

## 3. The finding this design rests on

**Reconcile before you restack, and the steady state needs no force push at all.**

Per branch, bottom-up, before anything is rebased or pushed:

| local vs `origin/B` | what to do |
|---|---|
| `origin/B` is an ancestor of `B` | nothing: you already have everything |
| `B` is an ancestor of `origin/B` | fast-forward `B` to `origin/B` |
| diverged | `git rebase origin/B` -- replay *your* commits on top of *theirs* |

After that third case the branch **descends from `origin/B`**, so the push is a plain
fast-forward. **Verified**: two clones, a teammate's commit on `B2` and on `B3`, the local clone
holding its own commit on `B3` -- reconcile made both branches fast-forward, both people's
commits survived, and `git push` needed no force flag at all.

The cascade restack is then only needed where you hold commits the remote does not, below a
branch that moved. **Verified**: local commits on `B2` *and* `B3` with the remote rewritten under
both -- reconcile, then restack `B3` onto the new `B2`, and all four commits are present; the
push of `B3` is a genuine forced update and the guard in §4 allows it, because reconciling put
`origin/B3` into `B3`'s history first.

That is the whole design. `gs sync` does steps in the order rebase-then-push and never
reconciles the branch against its own remote copy; doing that one thing first turns the dangerous
operation into an ordinary one.

**The one exception, and it cost a bug to find:** a branch this clone has *moved* must not be
reconciled with a plain rebase, because `<remote>/<branch>` still carries the old parent chain and
the rebase drags all of it back in. Run in the sandbox, a moved branch that should have carried 3
commits over its new parent came back carrying 8 -- the extra 5 belonging to the two PRs it had
just been moved away from, which would then have shown up in its PR diff. A moved branch takes
only the remote's *own* commits, measured from the PR's base as GitHub has it, and cherry-picks
them onto where the branch now sits. `packages/tabsdata-dev-tool-gsx/DESIGN.md` has the commands.

**What reconcile does not fix:** a commit you never had cannot be preserved by a rebase that runs
before you fetch. Hence the guard, which is the backstop for every tool that skips this.

## 4. The guard: a pre-push hook

The hook from `HANDOFF.md` §7, unchanged in its rule: **refuse a forced update whose remote tip
was never reachable from any past tip of the local branch.** Fast-forwards, new branches,
deletions and rewrites of your own history pass. It reads only the reflog -- no network, no API,
no stack awareness -- and because gh-stack shells out to `git push`, it covers `gs sync`,
`gs push` and `gs submit` as well as everything gsx does.

**Verified**: the clobbering push of §2 is refused with the remote unchanged; the
reconcile-then-restack push of §3 is allowed.

### 4.1 A second rule, for the append-only policy

Rule 1 of §1 is not data safety -- squashing your own commits passes the hook above, because it
is your own history. Enforcing it needs a different test:

> **Every commit `origin/B` has *of its own* must still be present in the pushed branch**,
> matched by patch-id, or failing that by subject line. "Of its own" is above the trunk and not
> carried, by patch, by any other remote branch that is not `B`'s descendant -- so the parents a
> branch sat on do not count, and a move, which leaves them behind, is not a drop.

Patch-id survives a rebase onto a new parent, so ordinary restacking passes. A squash collapses N
commits into one with a new patch and usually a new subject, so it is caught. The subject
fallback is what keeps a *conflict-resolved* commit -- whose patch legitimately changed -- from
reading as a dropped one.

**It will still have false positives**: a conflict resolution that also changes the subject, or a
commit deliberately dropped because its change landed in the trunk another way. So it names the
missing commits and points at the override. It is a policy rule; it should argue, not block
forever.

Both rules share one override, `GIT_ALLOW_OVERWRITE=1`, which is deliberately ugly to type.

### 4.2 Distribution -- the question `HANDOFF.md` §7.5 left open

Hooks live in `.git/hooks`, which is never cloned. Three answers, and we take the first two:

1. **Repo-tracked**: `.githooks/pre-push` committed, `git config core.hooksPath .githooks` once
   per clone. Shareable, reviewable, and the hook arrives with the code. The per-clone command is
   the price, and there is no way around it -- git will not let a repository configure its own
   hooks, by design.
2. **This clone only**: `.git/hooks/pre-push`, nothing committed. For a clone of a repository you
   do not own or do not want to change.
3. Global `core.hooksPath` or `init.templateDir` -- fine for one person, invisible to the team.

`gsx hooks --install` writes either, from a copy that ships inside the package. The gap is
honest and worth stating plainly: **a clone where nobody ran it is unprotected**, and no
client-side mechanism can close that.

## 5. What GitHub itself can and cannot do

| Want | Possible? |
|---|---|
| Block force-push on `main` | **Yes** -- ruleset, and it costs nothing: gh-stack never force-pushes the trunk |
| Block branch deletion | **Yes** -- ruleset, same scope |
| Require a PR to change `main` | **Yes** |
| Block force-push on stack branches | **No, not while stacking by rebase.** A restack *is* a forced update; the server cannot tell a safe one from a clobber, because the difference is in the pusher's reflog, which the server never sees |
| A server-side pre-push check | **No.** github.com has no custom pre-receive hooks |
| Prevent a squash server-side | **No**, for the same reason |
| Remove a PR from a stack | **No** -- the API has no such call (§2) |

One thing rulesets *are* good for: a **freeze** immediately after a restructure -- block force
pushes on the stack's branch patterns, with the person doing the restructure in the bypass list,
until everyone has adopted the new layout. Temporary by design.

So the honest summary: **the trunk is protectable on the server; the stack branches are
protectable only on the client.** That asymmetry is why the hook matters.

## 6. By hand

What the tooling has to amount to. `R` is the gh-stack remote (`git config gh-stack.remote`,
else `origin`), `T` the trunk.

**Sync a stack, safely:**

```sh
git fetch R                                  # trunk + every stack branch
git checkout T && git merge --ff-only R/T    # trunk first; it is everyone's base
for B in <branches, bottom-up>; do
  git checkout "$B"
  git merge-base --is-ancestor "R/$B" "$B" && continue   # nothing of theirs to take
  git merge-base --is-ancestor "$B" "R/$B" && { git merge --ff-only "R/$B"; continue; }
  git rebase "R/$B"                          # diverged: their commits, then mine
done
for B in <branches, bottom-up>; do           # now, and only now, restack
  P=<parent of B, or T>
  git merge-base --is-ancestor "$P" "$B" && continue
  git rebase --onto "$P" "$(git merge-base "$P" "$B")" "$B"
done
git push --atomic R <fast-forwarded branches>
git push --atomic --force-with-lease R <rewritten branches>
```

**Move a slice of a stack onto another one** (local, nothing published) -- four gh-stack commands
plus the cascade, which is what `gsx move` already does:

```sh
gh stack unstack --local                              # forget the stack you are in
gh stack checkout <target top> && gh stack unstack --local
git checkout T && gh stack init --base T <kept...>
git checkout T && gh stack init --base <base> <target...> <moved...>
git rebase --onto <target top> <old parent> <bottom moved branch>
git checkout <bottom moved> && gh stack rebase --upstack --no-trunk
```

**Publish the move** -- the irreversible part:

```sh
# every branch must already descend from its remote copy: reconcile first, or stop
gh stack unstack <n>                     # dissolve the old stack ON GITHUB
gh api repos/{owner}/{repo}/stacks/<n>   # 404 = it really let go, before pushing anything
gh stack submit --auto --open            # push, fix PR bases, grow the target's stack
# and the remainder, as a new stack with a new number
```

## 7. The gsx commands

| gsx | what it runs | new? |
|---|---|---|
| `gsx sync [--all] [--push] [--continue] [--abort]` | the whole first block of §6, in git alone; local unless `--push` | **new** |
| `gsx init [--repo\|--clone] [--check] [--force]` | writes the guard and Gerrit's commit-msg hook, sets `core.hooksPath` | **new** |
| `gsx move --to ...` | unchanged: four local `gh stack` commands + the cascade | no |
| `gsx submit --move` | unchanged, **plus** a reconciliation check that refuses and names `gsx sync` | changed |
| `gsx submit --sync` | `gsx sync`'s own engine, not `gh stack sync` | changed |
| `gsx stack` | unchanged: it already shows `=`/`+`/`-`/`x` per branch, which is this state | no |

**`gsx sync` never touches a stack object and never calls the stacks API.** That is the whole
reason it exists rather than wrapping `gs sync`: every destructive path in §2 is in the
reconciliation of the *stack object*, and none of it is needed to move commits between clones.
The stack object is `gsx submit`'s business, and it is the one place a dissolve can happen.

**It keeps a session only while it is stopped.** The tip of every branch it is about to touch is
recorded in `<git-dir>/gsx/sync.json` before the first change -- the fork points need those shas
anyway -- and the file is gone when the run completes. A conflict stops it; `--continue` finishes
after the resolution and `--abort` puts every touched branch back, not only the one the rebase
stopped on. The first design had no session and said "resolve and rerun"; the campaign showed a
cascade that had already rewritten the branches below the conflict, which a rerun does not undo
(scenario B6 in the report).

**It refuses on a dirty tree**, because every rebase below it would refuse anyway, and finding
that out halfway through a cascade is worse than being told at the start.

**During an unpublished move it reconciles and restacks but does not push**, and says why: half
an arrangement is not a thing to publish, and `gsx submit --move` is the step that makes the
other half true.

**`gsx submit` refuses, with or without `--move`, when any branch it is about to push is not
reconciled** -- `origin/B` not an ancestor of `B`, with a remote `B` that exists. This is the check that turns
rule 5 into something the tool enforces rather than something the operator remembers.

## 8. How this gets tested

A throwaway public repo on GitHub, two clones (`dummy1`, `dummy2`), the hook installed in both:

1. **Append-only, two people, one PR.** dummy1 and dummy2 both add a commit to the same middle
   PR. Second one to sync reconciles; both commits survive; the push is a fast-forward.
2. **Interleaving.** A commit inserted in the middle of a branch's own history, restacked above,
   pushed. Allowed by both hook rules.
3. **The clobber.** dummy2 skips the fetch and force-pushes a stale branch. Hook refuses; remote
   unchanged. Then the same push after `gsx sync`: allowed, and the teammate's commit is there.
4. **The squash.** dummy1 squashes two already-pushed commits. Rule 2 refuses and names them;
   `GIT_ALLOW_OVERWRITE=1` lets it through.
5. **The move.** `gsx move --to` in dummy1, `gsx stack` shows it unpublished, `gsx sync` keeps it
   and pushes nothing, `gsx submit --move` publishes. Meanwhile dummy2, holding the old layout,
   runs `gs sync` -- and is refused by the hook rather than clobbering the restructure.
6. **`gsx submit --move` with an unreconciled branch**: refused, names `gsx sync`.
7. **The trunk ruleset**: a force push to `main` is refused by the server, in a clone with no
   hook at all.

All seven were run against `tabsdata/gsx-stack-sandbox` on 2026-09-13; the transcripts and what
they changed are in `.claude/VERIFIED.md`. Three things the run changed in this design:

- the moved-branch reconcile above, which the first draft did not have;
- `unreconciled()` judging a moved branch by patch rather than by ancestry -- the ancestry test
  called every correctly reconciled move unreconciled, and `submit --move` refused a branch that
  held everything;
- `sync` telling a stale clone to adopt rather than to publish: the first draft gave a bare
  divergence the same "run `gsx submit --move`" line as a real session, and following it would
  have published the stale layout over the restructure.

Two limits that testing confirmed rather than removed. **A clone with no hook is unprotected** --
`gh stack sync` from one would still have clobbered the restructure, and only the hook stopped
it. And **the append-only rule has false positives** by construction: a conflict resolution that
rewrites a commit's subject reads as a drop, and the override is the answer.
