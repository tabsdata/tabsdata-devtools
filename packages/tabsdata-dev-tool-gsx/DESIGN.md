<!--
Copyright 2026 Tabsdata Inc.
-->

# gsx

`tdd gsx create|update|checkout|submit|apply|approve|purge|move|stack`: GitHub issues +
`gh stack`, the way `gtx` does Jira + Graphite -- for a repository that uses neither. One command
turns the pending changes into an issue, a stack branch and a commit; another pushes the stack,
opens its PRs and labels them. Ported from the standalone `~/gsx` (1.5.0).

## Shape

- Toolset `launchers` (`deps-launchers` pins only pytest): gsx is standard library only, so it
  needs no pins of its own and joins an existing env rather than adding a sixth.
- `bin-reqs`: `git`, `gh`. The `gh stack` extension (github/gh-stack) is a gh install rather than
  a binary, so it is checked at run time, before anything is written -- but only by the
  subcommands that drive a stack. `purge` asks for `git` and `gh` alone (`gh.require_binaries`):
  a leftover branch is a leftover whether a stack put it there or not, and demanding the
  extension would refuse a repository that never used one.
- Modules: `args` (the two grammars argparse cannot express), `options` (the parser, which the
  config template is derived from), `gh` (every child process), `labels` (config lookup,
  validation, the edit engine), `purge` (which branches are leftovers), `move` (where a sub-stack
  is going, and what GitHub has not been told), `commands` (the nine bodies), `config` (the repo
  tables in `<tdd_dir>/gsx.toml`), `progress` (the `[n/N]` counter), `version`.

## Naming

Branch `<POSTFIX>-<ISSUE>`, where POSTFIX is the repository name's last dash-segment,
non-alphanumerics dropped, uppercased: `tabsdata-conn-gcs` -> `GCS`, `tabsdata` -> `TABSDATA`.
Issue 15 in `tabsdata-foo` -> branch `FOO-15`, commit `[FOO-15] <summary>`, trailer `Closes #15`.
GitHub numbers issues and PRs from one counter, so they interleave; the branch always carries the
**issue** number.

## The two grammars argparse cannot express

Both leave argv before the shared runner parses what is left (`args.split`), so `--help`,
`--format` and `--verbose` stay argparse's:

- **passthrough** `--<char>:<flag> [VALUE]` forwards a flag to one of the native `gh` commands a
  subcommand drives (`create` `--i:` issue create, `--s:` stack init/add; `update` `--i:` issue
  edit, `--e:` pr edit; `checkout` `--c:`; `submit` `--p:` stack submit, `--s:` stack sync,
  `--e:` pr edit; `apply` `--e:`). The char names the *operation*, so a letter can mean different
  things in different subcommands. Arity is inferred -- a following token that does not start
  with `-` is the value -- and `--i:name=value` is unambiguous. A flag gsx derives itself is
  **refused** unless `--override/-o`, which appends yours last so gh's last-wins applies.
- **label/reviewer ops** `--label:<scope>[:<mode>] LIST` / `--reviewer:...` (`--l:`/`--r:`),
  scope `new|top|all|mine` (default `new`), mode `replace|add` (default `replace`), repeatable,
  applied in argv order so a later op wins on PRs they share. `""` removes all.

## The engine

Ops fold into **one desired label/reviewer set per PR**, then one `gh pr edit` per *changed* PR
carries the difference. Three consequences, all deliberate: a PR already in the desired state
gets no call; two ops touching one PR cost one call; every PR is attempted even when one fails
(the failures are collected and reported together -- aborting at the first left stacks
half-labelled). `new` is judged on the snapshot taken before anything is written, so an earlier
op cannot erase a later one's targets.

Every PR the engine takes up is one numbered unit of progress (below), the ones already in the
desired state included.

A value that is not valid is refused with **the valid ones listed beside it** (and the aliases,
when a reviewer was the problem), because the next thing the reader needs is the spelling.

Values are validated against the config first, refreshing it once when one is missing, because
**`gh pr edit` is not atomic**: given a bad add and a good remove, the remove lands and the add
fails, so a `replace` with a typo would strip the labels it meant to overwrite. Reviewers
starting `@` (`@copilot`, `@me`) or containing `/` (`org/team`) are never in a collaborator list
and pass through unchecked.

## Progress

The commands that repeat themselves -- `submit`, `apply`, `approve`, `purge`, `move` -- number
the units of their work. It is `tdd xp`'s Reporter thinking without the parts gsx has no use for
(`progress.Counter`, some 40 lines: no scratch dir, no timings, no report):

```
[1/3] updated #6: +label run-ci
[2/3] #7 already as asked
[3/3] #8 could not be updated: gh: could not edit it
```

One unit is **one PR the command takes up** -- for `approve`, one PR per approver, since each
reviews every one; for `purge`, one candidate branch, kept ones included, because the reason a
branch survived is the half of the report a reader cannot get anywhere else. The unit is
reported *as it finishes*, as an `info` event (`warn` when it failed) whose message carries the
counter and whose fields carry the step (`n`, `total`, `pr`, `outcome`, and the
`edits`/`approver`/`branch` behind it), so `--format json` reads the same progress without the
brackets. Two rules keep it honest:

- **The total is the one that is known before the first unit runs.** `apply`, `approve`, `purge`
  and `move` know theirs (the snapshot; approvers x PRs; the candidate branches; the plan's
  steps) and print `[n/N]`; `submit` may be opening the very PRs it is about to label, so it
  prints `[n]` and offers no denominator rather than guess one. Its push, its `--sync` and the
  dissolve of a `--move` are units of it too -- they are the slowest thing gsx does.
- **Every unit spends its number**, including a PR already in the desired state, a PR its own
  author was asked to approve, and one that fails -- gsx attempts every PR and reports the
  failures together, so a skip that consumed nothing would leave the last line short of the
  total. What happened to that PR is what the line says.

`create`, `update` and `checkout` have no counter: they act on one issue and one PR, in a fixed
short sequence each step of which already says what it is doing, and a number over that adds no
information.

## checkout

`checkout` takes **a branch name or `#<PR>`, and nothing else**. `gh stack checkout` also accepts
a bare number and a PR URL, and resolves a bare number by trying it as a stack number, then a
locally tracked PR, then a PR it discovers on GitHub, and only then a branch -- so `42` means
whichever of those exists when it runs, and the answer can change under a target that did not.
A number that does not say what it counts is refused, with the spelling that would have worked
(`42` -> "write #42 for pull request 42, or give the branch name"); a URL is refused the same way,
pointing at the `#N` it contains. Every refusal is settled before gh is asked anything, since a
target gsx will not accept is a usage error and costs no child process to report.

`#42` reaches gh **as the PR URL**, composed from `gh repo view --json url` (from gh, so an
enterprise host is right too). That is the one shape gh cannot read as a stack number, and it is
what makes `#42` mean pull request 42 rather than stack 42 -- the URL is refused as input and used
as output, which is not a contradiction: what a person types has to be unambiguous to *read*, and
what gh is handed has to be unambiguous to *resolve*. A branch name goes through as typed, so gh
never sees a number at all. No target still opens gh's interactive picker.

**A branch name gh cannot resolve is retried as its PR.** `gh stack checkout BRANCH` only knows
the branches of a stack *this checkout already tracks*; for any other branch it exits 2 with "no
locally tracked stack found" and the advice to use the PR number instead. In a fresh clone that
is every branch, which made `gsx checkout OS-3348` fail on the one repository where it was most
obviously the right thing to type. So the refusal is taken as advice: one `gh pr view BRANCH`
turns the branch into its PR and the URL pulls the whole stack down. The failing call goes first
on purpose -- the tracked case is the common one and pays nothing for the fallback -- and a branch
with no PR at all is not a stack branch, so it is named as git's business (`git switch BRANCH`)
rather than retried. `#N` is never retried: a branch name has a second reading and a PR number
does not.

## approve

`approve --approvers NAME[,NAME...]` with `--pr N,...`, `--down-stack` or `--stack`. Each approver
is impersonated: their review token comes from 1Password **by GitHub username** (vault `dev_ci`,
item `GitHub`, field `<login>.review.pat`; all three are `[approver-credentials]`), one
fetch per approver for the whole run, and `gh pr review --approve` runs with it in `GITHUB_TOKEN`.
A `[reviewer-aliases]` name is resolved to the login first, so it names the token too.

A PR the approver wrote is **skipped, not failed** -- GitHub refuses a self-approval, and that is
not the run's problem. It is skipped without a call when the stack snapshot already names the
author, and on gh's own error otherwise (a PR named with `--pr` need not be in this stack, so its
author is not always known). Every PR is attempted; failures are collected and reported together.

`--down-stack` is the current PR and the ones it sits on, down to main -- the set that has to be
approved for the current one to merge. Upstack and downstack are the usual stacking words (`gt`'s,
and `gtx`'s): downstack is towards the trunk. `--stack` is every PR of the stack.

## purge

`purge` deletes the local branches whose PR is finished with. Stacking leaves branches behind and
every one of them was a PR, so **GitHub decides, not the local graph**: a branch whose newest PR
is `MERGED` or `CLOSED` goes, one with any `OPEN` PR stays, one with no PR at all is left alone.
It replaces a `for` loop over `gh pr view` per branch, and differs from it in four ways that are
the point of having written it:

- **A branch's PRs are plural.** Reopened, or a second attempt after the first was closed -- so
  `purge` takes every PR of the branch and keeps it if *any* is open, rather than trusting the one
  answer `gh pr view` picks. That is the case where being wrong deletes live work.
- **One `gh pr list --state all` answers every branch**, instead of one call per branch;
  `gh pr view BRANCH` is the fallback for a branch the listing's limit left out, which on a
  repository with thousands of PRs is exactly the oldest merged ones whose branches linger.
- **What is never a candidate**: the trunk (read from `gh repo view`, because `main` is a
  convention and the trunk is a fact), `main` and `master` whatever the trunk turns out to be,
  and the branch that is checked out -- kept with the reason and the fix, since git's own refusal
  does not say which branch to switch off.
- **The delete is `git branch -D`.** `-d` refuses a branch that is not an ancestor of the trunk,
  which is every squash- and rebase-merged branch and every closed one, so it would refuse
  precisely what `purge` is for. `--dry-run` is the preview, and `--merged-only` keeps the
  branches whose PR was closed unmerged -- their commits live nowhere else.

The leading `git fetch --prune` is hygiene rather than a prerequisite: the PR states are read
live from the API, so `--dry-run` skipping the fetch (it writes remote-tracking refs) costs the
run no accuracy, and `--no-fetch` skips it outright. Every branch is attempted even when one
delete fails -- a worktree holding it, say -- and the failures are reported together at the end.

## prune

`prune` shrinks the stack you are standing in: it **dissolves it on GitHub and relinks only the
PRs that are still open**. A stack keeps its merged PRs for ever -- `checkout` imports every
branch it ever had, `view` lists them all, `sync --prune` deletes the local branches and keeps the
metadata -- so a long-lived stack grows without bound. One in tabsdata-os is 93 PRs of which 90
have landed, and every command that reads it pays for the history.

Dissolve-and-relink is not a choice: **there is no API for taking a PR out of a stack.**
`gh stack unstack` takes no body, so it is the whole stack or nothing, and `gh stack link` rejects
a PR that belongs to another stack. Hence the order, which is forced:

```
gh stack unstack <n>                      # on GitHub. The irreversible step
gh stack link <open pr> <open pr> ...     # a new stack of what is left
git checkout <trunk> && gh stack init --base <trunk> <kept branches...>   # track it here
```

**The cost is the stack number, and nothing else.** A relinked stack is a new one, so `#3443`
becomes `#3501`; no PR number changes, no branch is rewritten, nothing is pushed. That is said in
the plan and again in the confirmation, because it is the only thing the operator is trading.

Four things the steps turn on:

- **link is handed PR numbers, never branch names.** "Branch arguments are automatically pushed
  to the remote before creating or looking up PRs. For branches without PRs, new PRs are created
  automatically." Neither is something prune could want by accident, and numbers are looked up
  instead. `gh.stack_link` says so where it would be edited.
- **A stack needs two PRs.** With fewer than two still open there is nothing to link, so prune
  dissolves and stops -- the honest end for a stack with one open PR left, and it says so rather
  than failing at the link.
- **A branch with no PR is kept**, in the local tracking only. It is not history and not landed:
  it is work that has not been submitted, it cannot be linked (there is nothing on GitHub to
  link), and dropping it would lose the arrangement it is part of.
- **A PR the API did not answer for is kept.** prune drops what is *certainly* finished, and a
  missing answer is not certainty.

The preflight is the same set of other people's sessions `move` refuses to run into, plus one that
is stricter: **an unpublished move is refused, not warned about.** Prune dissolves a stack on
GitHub, and while a move is unpublished the two sides already disagree about which PRs live
together -- publishing half of that by accident is exactly what `submit --move` exists to make
deliberate. A queued or auto-merging PR anywhere in the stack is refused too, for the reason
`submit --move` refuses it: GitHub leaves such a PR stacked and then keeps the whole stack, so the
dissolve would silently do nothing. That check is shared (`_refuse_stuck`); the one about a
*finished* PR is not, because a finished PR is what prune is for.

It is not `purge`, which deletes local branches and touches nothing on GitHub. The two go
together after a long-lived stack has landed most of itself: `prune` shrinks the stack, `purge`
removes the branches it stopped tracking.

## move

`move --to #STACK|BRANCH` takes the branch you are standing on **and every branch above it** out
of its stack and puts them on top of another one. You move out of the stack you are in, so there
is no `--from`: being on the branch is the argument.

| `--to` | what happens |
|---|---|
| `#41`, a stack tracked here | the moved branches join it, above its top |
| the **top** branch of such a stack | the same thing, named the other way |
| a branch whose PR is in **no** stack | the two become one stack, that branch at the bottom |
| the trunk | the moved branches become a stack of their own |
| a stack that is **not tracked here** | refused: `gh stack checkout <n>` first |
| a branch that is **not the top** of its stack | refused: the moved branches go above it |

**Nothing in `move` reaches GitHub.** It is four `gh stack` commands, each of which only writes
local branches and gh-stack's own tracking file:

```
gh stack unstack --local                          # forget the stack you are in
gh stack checkout <top> && gh stack unstack --local   # ...and the target's
git checkout <trunk> && gh stack init --base <trunk> <kept...>
git checkout <trunk> && gh stack init --base <base> <target...> <moved...>
git rebase --onto <target> <old parent> <bottom moved branch>
git checkout <bottom> && gh stack rebase --upstack --no-trunk   # the rest
```

Each `init` runs **from the trunk**, because `gh stack init` refuses to run while the current
branch is in a stack -- including the one it has just made, since it leaves you on top of it.

**What is re-declared is only what is still open.** `gh stack checkout <n>` imports every branch
a stack ever had, so a stack that has landed 90 PRs arrives as 93 branches -- 90 of them pointing
at the trunk's tip, with no remote copy left. Handing those back to `gh stack init` made a
112-branch local stack out of a 22-branch move, and it is not merely noisy: `init` keeps a PR
association only where it can find an open PR, so the merged branches came back *unassociated*,
which is what made `gsx stack` stop filtering them as merged and start reporting all 90 as
ahead -- and `gh stack submit` would then have been handed branches whose PRs are closed and
whose remote refs are gone. So the **run of finished PRs at the bottom** of each stack is dropped
from both inits, named in the plan (`minus 90 branch(es) whose PR is merged or closed`), and their
states come from the one GraphQL call the move already makes for the PRs it is about to move.
Only the run at the bottom: a merged PR *above* an open one is somebody's odd state rather than
history, and dropping it would leave a hole in the chain of parents the cascade reads. A target
whose every PR has landed is refused, since `--to <trunk>` is what that means.

**And a tracked branch need not be in the checkout at all.** `checkout` *records* all 93 but can
only *pull* what the remote still has, and a merged PR's branch is usually deleted -- so #3443
arrives as 93 tracked branches of which three exist. The branch directly below the moved slice is
then often absent, and it is the rebase's upstream, so the move stopped dead on it: `branch
'OS-3345' does not exist here, so where 'OS-3346' sits cannot be worked out`. The upstream is now
the nearest branch below that **is** here, and the trunk when none of them is -- which is where a
merged branch's commits are, by definition of merged. The plan says so (`off main (OS-3345 is not
in this checkout ...)`), and the consistency check keeps ignoring the trunk, since a parent that
fell back to it would otherwise read as "OS-3346 does not contain main" for every branch cut from
an older trunk. When the parent *is* present it is used whatever its PR says -- the moved commits
do sit on top of it -- so only the declaring leaves it out.

**The replay is split, and the split is the heart of it.** Exactly one branch has a new parent:
the one you were standing on. Its own commits are `<old parent>..<branch>`, and only this command
knows what the old parent was, so that one rebase is plain git. Everything above it still sits on
the branch below it, whose recorded base is that branch's own old tip, so gh-stack's cascade has
those ranges right -- and `--upstack` from the bottom moved branch keeps it to them, since it
rebases what is *above* the current branch and not the branch itself.

Two measurements forced that shape, both on real stacks:

- **The recorded base is the merge-base with the parent a branch was DECLARED to have**, not the
  tip its commits sit on. For a branch being put on the trunk that is where it left the trunk, so
  replaying from there brings along every commit of whatever it used to sit on: a one-commit
  branch came out with 37. Hence plain git, with the old parent this command remembers.
- **The cascade without `--upstack` starts at the bottom of the whole stack.** On a 19-branch
  stack that meant rebasing 16 branches that had not moved, and on one whose lower half sat on a
  newer trunk than its upper half it replayed 24 commits it already had into four conflicting
  files. A move should touch what it moves.

The reason this works -- and the reason there is no rebase code here -- is that **`gh stack init`
records each branch's base as the tip its commits actually sit on**, not the parent it was just
declared to have. Measured on a real repository: a branch declared above another stack's top came
out with its old trunk's sha as its base. `gh stack rebase --no-trunk` then replays
`--onto <new parent> <recorded base> <branch>`, so every branch keeps exactly its own commits,
**only the branches whose parent really changed are rewritten** (seven of nine were left byte-
identical to `origin` in the test), and nothing is fetched or pushed -- it says so itself: "To
push up your changes, run `gh stack push`". `--no-trunk` is what keeps it offline; with the trunk
it pulls first.

**A conflict is answered by `--continue` or `--abort`, and that needs a session.** By the time
anything can conflict the tracking is already the new arrangement -- both old stacks forgotten,
both new ones written -- so "resolve and rerun" is not available, and neither is "just abort":
gh-stack's own `rebase --abort` restores the branches it was replaying but knows nothing about
the rearrangement, or about the branch this command replayed itself. So `<git-dir>/gsx-move`
holds what finishing needs (the stage it stopped in, what is left to replay, where to end up)
and what undoing needs:

- the sha of **every branch any of the moves involves** -- the ones moving, the ones staying and
  the target stack's -- read from the refs before the first change. Not from gh-stack's recorded
  `head`, which can be stale, and **never from the remote**: a branch may hold commits that were
  never pushed, so restoring `origin/<branch>` would throw work away. An undo never fetches. (The
  prose recipe this replaced did suggest `git branch -f <b> origin/<b>`, which had exactly that
  hazard.) The **earliest** sha recorded for a branch wins, since that is the one an undo of the
  whole sequence has to reach.
- gh-stack's whole tracking file **as text** as it was before the **first** move -- every stack's
  number, trunk, membership and recorded bases.
- **every tracked stack as it was**: its number, its trunk, and each branch with its PR number
  and the commit it pointed at, plus one entry per move in the sequence. Written once and never
  rewritten -- "as it was" is the whole of its value -- and the only place that arrangement
  survives at all: once a move has run, nothing in the repository still says which stack a branch
  came from or where it was.

Then:

- `gsx move --continue` hands the stopped rebase back to whoever owns it -- `git rebase
  --continue` for the branch that moved, `gh stack rebase --continue` for the cascade -- and runs
  what is left of the move afterwards. Resolving with `git add` or with `git commit` both work,
  because git accepts either before its own continue.
- `gsx move --abort` aborts that rebase, puts **every branch of every unpublished move** back on
  the tip the session recorded, and writes gh-stack's tracking file back byte for byte. Restoring
  the bytes is the only complete undo of a rearrangement: `unstack --local` and `init` cannot be
  run backwards.
- `gsx move --report` prints the arrangement before the first move beside the one there is now,
  with the moves in between,
  each branch with its PR and its commit, marking what was rewritten (`(was 999aaaa)`), what is
  new to the tracking, and what is not tracked here any more. It is the only way to see the
  before, and the only thing that can say a sha changed.
- while a move is **stopped**, another cannot start: a half-replayed arrangement is not a thing
  to move out of, and one session cannot describe two replays at once.

**Moves accumulate, and the sequence is what is published or undone.** A move is local from `gsx
move` until `gsx submit --move`, which is what the `publish` stage means: every branch is where
it should be and GitHub has been told nothing. A further move from there **joins** the ones
before it -- that is what the write-once fields are for -- so `submit --move` makes the whole
sequence effective and `--abort` undoes all of it, back to the tips and the tracking file from
before the first one. `--continue` is for one thing only: finishing the replay of the move that
stopped on a conflict.

Two consequences of keeping the file that long. What the operator is deciding about is the
sequence rather than "the move", so every message counts it (`2 local moves are not published (a2
onto b2; b1 b2 onto c1)`). And **`--abort` survives the end of a replay**, where before it
vanished at the very moment a move became hardest to undo by hand. `submit --move` removes the
file *at the dissolve* -- from there an abort would reset local branches while GitHub holds the
new arrangement, so the record of how to undo goes the moment it becomes a trap. A stopped move
is not published at all: half a rearrangement with the branches mid-rebase would push neither
arrangement.

**Every gsx command says so while that file exists**, before it does anything -- one wording, in
`gsx._say_if_moving`, rather than nine that can each forget. In that window any branch may be
somewhere the operator did not put it and GitHub knows nothing about, which is worth knowing
whichever command was reached for -- and after two or three moves, which branch went where is
exactly what stops being held in anyone's head. `move` is the exception, because it says more: `--to` refuses,
`--continue`/`--abort`/`--report` act on the session. Not being in a git repository is not an
error of the command that was asked for, so an unanswerable check says nothing.

It is in the git dir, not the work tree, so it cannot be committed by accident or turn up as a
conflict of its own. Verified on tabsdata-tucu with a real conflict, both ways: `--continue`
after committing the resolution finished the move; `--abort` on the same conflict put both
branches back and restored the tracking byte-identically (`#44` and `#36` as they were).

`move` also will not start while a rebase is stopped, a `gh stack modify` is unfinished, a `git
rebase` is in progress or the tree is dirty, because its own replay would drive straight into any
of them.

One check exists for the publish rather than the move: a **queued or auto-merging PR** anywhere
in the moved set is refused up front, because GitHub leaves such a PR stacked and then *keeps the
whole stack*, so the dissolve that `submit --move` needs would silently do nothing and the PR
would end up in two stacks at once.

And one exists for the replay: **every moved branch has to contain its parent's tip**. That is
what makes the cascade's recorded bases the parents' own tips rather than something older, and a
stack that fails it is the one that replays commits it already has. The trunk is deliberately not
in that chain -- a branch cut from an older trunk is the ordinary case, and `git rebase --onto X
<trunk> B` replays `<trunk>..B` whether or not B contains the trunk's tip.

### publishing it: `submit --move`

The old arrangement is still on GitHub until `gsx submit --move`, which is **the only step in
either command that cannot be undone**. It has to dissolve before it pushes:

1. `gh stack unstack <n>` on the stack the move took apart. Unavoidable: the API cannot remove a
   PR from a stack (unstack takes no body) and `gh stack link` rejects a PR that belongs to
   another one, so the moved PRs cannot join their new stack while the old one holds them.
2. Then GitHub is asked whether it really let go, before anything is pushed -- a queued PR would
   have left the stack standing.
3. `gh stack submit --auto` for the stack you are on: pushes the rewritten branches, fixes the PR
   bases, and grows the target's stack object. **The target keeps its number** -- link appends --
   so only the dissolved stack's number is lost.
4. Any other local stack the move left holding those PRs (what stayed below you) is submitted
   too, as a new stack with a new number, and non-fatally: the half you were standing in is
   published by then, and a warning naming the two commands is more honest than an error.

So the one thing to expect: **the stack number of what stays below you changes.** The PR numbers
do not.

`--move` is required rather than inferred, and `submit` **refuses without it** when it notices
one, because an irreversible step should never be a side effect. Noticing is `move.pending()`:
a GitHub stack is still fine while its PRs are the bottom of one local stack, in order, since
link can append it into place; a stack whose PRs are split across two local stacks, or now sitting
on top of another stack's, can only be reached by removing PRs from it, and that one has to be
dissolved. Prefixes are the whole test because a move can only make prefixes -- what stays below
you is a prefix, what arrives goes on top. PRs this checkout does not track are left out of the
comparison: someone else adding a PR to your stack is the *other* reason the two sides differ,
and it needs a sync, not a dissolve. It is a *second* signal, and the weaker one: the session
file is what says a move of this checkout's own is unpublished, so `gsx stack` prints this
finding only when there is no session -- otherwise the same thing would be said twice, once
worse. What it is for is a divergence nothing local accounts for -- an old clone, or somebody
else's rearrangement -- and it is printed as a disagreement between the two sides rather than as
"a move is in progress", since with no session there is no move of this checkout's to be in
progress. It is **one line for the finding, a row per stack, then the ways out** -- the fact and
the remedies are read at different moments, and a paragraph holding both had to be re-read to
find either:

```
GitHub and this checkout disagree about 2 stack(s) -- most likely an unpublished `gsx move`:
  #3478   TD-3219 (#3012) TD-3240 (#3013) TD-3220 (#3017) TD-3236 (#3019)
          TD-3262 (#3023) TD-3223 (#3028) TD-3274 (#3032) TD-3224 (#3065)
  #3495   OS-3346 (#3440) OS-3347 (#3441) OS-3348 (#3442)
  out:    `tdd gsx submit --move` makes it effective
          `tdd gsx move --abort` cancels it, if this checkout still has the move's session
          `gh stack checkout <n>` re-imports what GitHub has instead
```

Each row is that stack's own PRs in its own order, named by branch as well as number, because
"#3478 disagrees" is not something anyone can act on. The middle way out carries its condition,
because this finding is read off the two sides rather than out of the session file -- so it turns
up where there is no session, and an unconditional `--abort` would send the reader to "no move is
in progress".

## stack

`stack` shows the stack you are on: its PRs, what each is called, how each branch stands against
the remote, and **what only GitHub has**. `--all` shows every stack instead; `--short` trades the
per-PR lines for one line per stack; `--remote`/`-r` and `--local`/`-l` show one side each.

```
$ tdd gsx stack
[#34]  main
       =a1        #21  the loader
      +[a2]       #22  wire it up
       ?a3        #29  one someone else put in the stack

  = in sync  + ahead  - behind  x diverged  ? remote only  [] current

$ tdd gsx stack --all --short
3 stack(s):
[#34]  main <- =insync   <-+[ahead] <- ?a3
 #40   main <- -behind   <- xdiverged
?#41   main <- ?theirs

$ tdd gsx stack --remote --short        # GitHub's view, nothing compared
[#34]  main <- insync <- ahead <- ?a3

  ? remote only  [] current
```

**The two sides are matched on branch names**, not on stack numbers. A rebuilt local stack has no
number at all (`gh stack init` issues none), so after a move the local side of what GitHub calls
#3478 is `#-`; matching on the number showed those branches twice -- once as the local stack and
once as a "remote only" one -- and hid any PR the listing had added to it. Names are the one key
both sides always have: a number is missing from a rebuilt stack and a PR number from a branch
that has none yet. A listed stack sharing no branch with anything tracked here is the only kind
that gets a row of its own.

**Three sources, and the default is both.** gh-stack's tracking file (`<git-dir>/gh-stack`) is
the local half; GitHub's own listing (`gh api repos/{owner}/{repo}/stacks`) is the other. The
default puts them together: the tracked stacks, plus everything the listing holds that the file
does not -- a PR someone added to your stack, a stack you have never checked out. That is the
half a reader cannot get any other way, and the question behind "what are my stacks" is usually
"and what am I missing". `--local` is the file alone (no `gh`, no network, and with `--short` no
child process but git's); `--remote` is the listing alone, which is what to look at when local
and remote disagree and you want to see what GitHub thinks.

**A magenta `?`** marks what the tracking file does not have, in front of a branch's name and in
front of a stack's number alike. It takes the place of a sync symbol rather than sitting beside
one: nothing is here, so there is nothing for a comparison to be about, and `?` is what the
symbol set already says that with. The plain `?` (a tracked branch with no local copy) and the
magenta one are the same fact one step apart, which is why they are the same character; the
colour and the legend's words carry the step. **Only the one a row uses is explained**: a
remote-only branch has no local copy by definition, so it is not also counted as one -- both
entries at once ("? no local branch  ? remote only") read as one symbol explained twice.

Remote-only PRs are appended at the top of their stack, which is where `gh stack sync` would put
them when it pulls them down. A closed stack is skipped whole.

**A stack's merged PRs are its history, not its state, so they are left out** -- of both halves,
and how many is said. This was learned the hard way: `gsx stack -a -s` in a fresh clone of
tabsdata-os, with stack #3443 checked out, printed ninety `?OS-32xx` before the three branches
that were still open. Those ninety came from gh-stack's tracking file, which keeps every PR the
stack ever had, and the local half was reading it without asking what had become of them. The
three open ones were the whole answer. `--merged` brings them back; a stack with nothing else
left goes with them, and its number is in `--all --merged` when it is wanted. What remains is
honest about the shape it shows: those commits are in the trunk now, so the branch above them
really does sit on it.

The listing is the only thing that knows -- `state` plus `merged_at` per PR -- so **`--local`
cannot know and shows everything**. That is the price of asking nobody, and it is the one view
where a long tail of merged branches still appears.

**`--local` and `--remote` carry no sync symbol at all**, because each shows one side and "behind"
is a claim about the other one. They fetch nothing, compare nothing, and their legend is the
brackets alone -- and with nothing compared, `(as of the last fetch)` has nothing to be about
either.

**The per-PR view is the default** because it answers what a reader wants first -- which PRs,
called what, where each stands -- and `--short` is there for when the *shape* of the stack is the
question, which is the rarer one. Both carry the same symbols, colours and brackets, so they
cannot disagree about what a branch is, and both measure their columns across every stack shown
rather than per stack, so the numbers line up down the whole page. A branch with no PR yet gets
its line with `-` in the number column.

The titles need the network: gh-stack's state file carries a branch's PR number and url but not
its title, so they come from one `gh pr list --state all`, with a per-number lookup for anything
the limit left out (a long-lived stack can hold a PR older than that, and its branch is exactly
the one still lying around). A title gh cannot answer is named in a warning and left out -- the
numbers are worth printing whatever gh says. `--short` asks for none of them. **The gh-stack
extension is never needed** either way: a checkout can have stacks without it.

The default is the one stack, because that is the question `submit`, `apply` and a working day
are about; `--all` is the listing. Only the branches actually shown are compared against the
remote, so the default costs one `rev-list` per out-of-sync branch of one stack rather than of
all of them. The count line appears only with `--all`, and says which side it counted
(`on GitHub`, `tracked here`): over a single stack the row already says the rest. A stack GitHub
has that is not tracked here cannot be "the one you are on", so without `--all` it is named in
one line rather than shown. Standing outside every stack answers so and names `--all`. `#-` is a
stack that has never been submitted, so GitHub has given it no number yet -- and exists only
locally, by definition.

A listing that cannot be had is fatal only for `--remote`, where it *is* the answer; otherwise
it is a warning saying the local view may be missing PRs, because a repository whose stacks API
is unreachable can still be worked in.

**One symbol per branch, and it is also the colour.** `=` in sync (green), `+` ahead (blue), `-`
behind (yellow), `x` diverged (red), `?` no local branch (uncoloured -- nothing is claimed about
it). A branch with nothing on the remote reads `+`: there is no remote copy for it to be behind.
`?` and `()` are independent: a PR the tracking file lacks may still have its branch here.

**Commits are compared by their change, not their sha** (`git rev-list --cherry-pick`, which
drops any commit whose patch already exists on the other side). `gh stack` rebases everything
above a branch that moved and force-pushes it, so the remote copy of a branch is rewritten as a
matter of routine; by sha that is divergence, and nearly every branch would read `x`, which would
make `x` noise. By content it reads as what it is -- behind by whatever the remote genuinely
gained -- and `x` is kept for the case worth stopping for: both sides holding different work.
The same consequence at the other end: `=` means the same *changes*, which after an upstream
rebase may sit under different shas.

**And the trunk's commits are not the branch's** (`--not <trunk>` on the same rev-list). A branch
whose local copy has been rebased onto a newer trunk carries commits its remote copy does not,
and every one of them belongs to the trunk: ten branches of stack #3478 in tabsdata-os read `+`
for that reason with nothing local about them -- the two "unpushed" commits were `[TD-3364]
Edition gate` and `[TD-3363] New tdkserver subcommand`, both off main. What is left after
excluding them is the question the symbol is for: how this branch's own work compares with the
copy on the remote. The trunk excluded is the remote's copy of it, since that is the baseline
both sides share; a trunk never pushed falls back to the local one.

The symbol sits immediately before the name so it reads as part of the arrow into that branch,
and it is the *cell* that is painted -- the arrow and the gap are structure, not state.

**Brackets, not a colour, for what is current:** white `[]` round the stack holding the
checked-out branch -- the one `submit` and `apply` act on without being told which -- and round
that branch. A shape rather than a colour because the colours are spoken for: each one is a sync
state, and being checked out is not a state. It is the only marker drawn as a shape, and it is
the same shape at both scales, because it is the same fact said of a stack and of a branch.

**The brackets hold the name alone**, with the symbol outside: `=[a2]`, not `[=a2]`. The symbol
says how the branch stands and the brackets say which row this is -- two facts about two
different things, so the brackets hold only the one they are about. It also puts every **name**
at the same offset whether it is bracketed or not; the symbol is what steps one column left when
the brackets appear, and a symbol is one character either way.

Every cell reserves one slot on each side for a bracket, and those two slots are the spaces
around `<-` -- so a bracketed cell is exactly as wide as a plain one, a name is at the same
offset on every line whether it is bracketed or not, and the brackets cost the column nothing
(a bracketed cell therefore touches what follows it: `<-=[a2]<- ?a3`). Widths are the widest
symbol-and-name; a row's own last cell is left unpadded, so no line carries trailing blanks.
Painting is per **cell**: a paint ends in a reset, so one coloured branch would otherwise leave
everything after it plain.

**One line of legend, set off by a blank line on each side** -- it is a key to what is above it,
not another row of it -- with each symbol in its own colour, so it demonstrates what it explains
rather than describing it twice; `?` and `()` earn their place only when a row uses them, and the
sync symbols only when the view compared anything. Colour is never the only carrier -- the symbol
or the bracket says the same thing under `NO_COLOR`, in a pipe, and to anyone who does not
separate red from green.

**It fetches first**, because `=` is a *claim* about the remote and the remote-tracking refs are
only as fresh as the last fetch. This shipped the other way round for one afternoon and was wrong
within it: in a real checkout, `TUCU-45` read `=` in green while the server had moved three
commits past the tracking ref. A confidently wrong answer is worse than a slow one, and a stale
`=` is exactly the answer nobody would think to doubt. `--no-fetch` skips the round trip, and
the legend then ends `(as of the last fetch)` -- the symbols never quietly change what they are
about. The fetch itself is not announced: it is a precondition of the answer rather than a step
of its own, and a line about it would be the first thing on every run.

The remote is gh-stack's own (`git config gh-stack.remote`, else `origin`) and is not named on
the legend -- the reader knows their own remote -- but it is in the `remote` field for a machine.
After the fetch, one `git for-each-ref` collects every sha, and only a branch whose two shas
differ costs a second call.

The rows and the legend are the `ok` message, so they land on stdout and pipe; `--format json`
gets no escapes at all and carries, per branch, `sync` in words (`in-sync`, `ahead`, `behind`,
`diverged`, `no-local-branch`, or `null` where nothing was compared) and `remote_only`, plus the
`source` (`local`, `remote`, `both`) and the `remote` it compared against. A checkout with no
state file and a repository with no open stacks answers "none" and exits 0: asked what stacks
exist, "none" is an answer rather than a failure.

## Config

`<tdd_dir>/gsx.toml` -- every command's config file (`common.core.config`), so its `[options]`
table is what gsx's own options default to and the `config` action comes from the shared layer.
A fresh file carries gsx's own tables commented at their defaults, after the options, so a reader
can see they exist; gsx replaces that block with the real ones the first time it writes. Three
tables of its own:

- `[approver-credentials]` -- where `approve` reads a review token: `approve_vault`,
  `approve_item`, `approve_pat_suffix`, the field being `<login>` plus the suffix.
- `[repo] version` -- the gsx that last refreshed the tables below it. A version that differs
  from the running gsx forces one refresh, so what is cached is never older than the tool; it
  sits on `[repo]` because that is what it dates.
- `[reviewer-aliases]` -- `<alias> = "<login>"`, a name of your own for a reviewer, usable
  anywhere a `--reviewer:` value is and resolved before anything looks at the value (validation,
  the desired state, the `gh pr edit` argument all see the login). File-wide: a login is a person,
  not a property of one repository. **The team ships in code** (`ALIAS_DEFAULTS`), so an alias
  resolves before anyone has a config file; a file entry of the same name wins, exactly as the
  `approve_*` defaults work, and anything else you add sits beside them.
- `[repo."OWNER/NAME"]` -- **per repository**, always: `labels`, `reviewers`, `fetched`, and the
  two `default_*` lists. Labels and collaborators differ per repository (a flat list would
  validate one repository's names against another's), and so do the defaults: `default_labels` /
  `default_reviewers` are what `submit`/`apply` put on the PRs *of that repository* that have
  none yet. They are injected as leading `new`-scope ops, so an explicit op still wins;
  `--no-defaults` skips them.

gsx refreshes this repository's two lists and `fetched` itself -- when the file has nothing for
it, when another gsx wrote it, and once more when a value is missing, since the list may simply
be stale. There is no verb for it: nobody has to remember to run one. The write goes through the
shared writer, which re-renders the option template and carries the rest across: other
repositories' tables, every `default_*`, and every option the reader set under `[options]`. The
version is the devtools version, from the installed distribution's metadata: one number for the
whole repo (invariant 10).

## Verified `gh` / `gh-stack` behaviour

Facts that cost real testing; the code depends on them.

1. `gh stack add` has no `-- PATH...`, but `gh stack add BRANCH` with no flags creates and checks
   out the branch **without committing and leaves the index intact**. So a subset commit is
   `git add -- PATHS` -> `gh stack add BRANCH` -> `git commit`, and the all-files case is the
   same path.
2. `gh stack view --json` exits 0 **on the trunk** once any stack exists, so "am I in a stack" is
   `currentBranch != trunk`; on the trunk `create` runs `gh stack init`.
3. `gh stack submit` only sets a PR's title and body **at creation**. It force-pushes an amended
   commit but never re-titles an existing PR, so `update` calls `gh pr edit` itself, preserving
   the `---` footer gh-stack put in the body.
4. `gh pr edit` is not atomic (see above).
5. Reviewer sources: `gh api repos/O/N/collaborators` (needs push access, can 403) and GraphQL
   `assignableUsers` (what GitHub's own picker uses). Neither contains the other, so both are
   unioned.
6. `git branch` **lists** with no flags and **deletes** with `-D`, so the read-only set cannot key
   on the first two words alone: `is_read_only` looks at the flags (`GIT_BRANCH_WRITES`).
   Otherwise `--dry-run` would run `purge`'s deletes -- the one mistake the flag exists to
   prevent -- while skipping the listing.
7. `gh stack checkout`'s bare number is **a stack number first**, then a locally tracked PR, then
   a PR discovered from GitHub, then a branch (its own `--help` says so). A PR URL has no such
   chain, which is why `checkout` hands gh the URL for `#N` rather than the number. A **branch
   name** resolves only within a stack this checkout tracks: anything else is `✗ no locally
   tracked stack found for "X"` and exit 2, with "use the PR number" as the advice -- which is
   why `checkout` retries such a branch through its PR.
8. **A stack keeps its merged PRs, everywhere.** `gh stack checkout 3443` on tabsdata-os prints
   "Skipping merged branch" ninety times and then imports all 93 into `<git-dir>/gh-stack`;
   `gh stack view` lists all 93 (merged ones marked `✓`); the stack object on GitHub holds all 93
   PRs, and `sync --prune` deletes the local branches but says outright that "stack metadata is
   preserved so that rebase and display logic continue to work correctly". With no endpoint that
   removes one PR from a stack, only a dissolve and relink can shrink one -- so a display that
   wants the working set has to filter, which is what `stack` does.
9. **`gh stack init` records the merge-base with the parent a branch is DECLARED to have** -- the
   parent's own tip when the branch contains it, and something much older when it does not. It
   adopts without rewriting anything (measured: same sha before and after). `gh stack rebase`
   replays `--onto <new parent> <that base>`, so its ranges are right exactly while the stack is
   consistent; where it is not, it replays commits the target already has. And `--no-trunk`
   starts the cascade at the **bottom of the stack** unless `--upstack` scopes it, while
   `--upstack` excludes the branch you are standing on. Those three facts are why `move` replays
   its one re-parented branch with plain git and hands only the rest to the cascade. Measured on
   tabsdata-tucu and tabsdata-os; the `sync` error "could not determine the previous base"
   belongs to the cascade's rewritten-parent case and does not fire in this flow.
10. `gh stack rebase` keeps `.git/gh-stack-rebase-state` (every branch's original ref, the
   conflicting branch, what is left) and `--continue`/`--abort` finish or unwind it -- so a
   command that drives it needs no session of its own. `gh stack modify` keeps
   `gh-stack-modify-state` the same way.
11. `gh stack init` **refuses a branch that is already in a tracked stack** (`✗ branch "b" already
   exists in a stack`), which is why a move forgets both stacks locally first -- and it refuses
   just as hard when the **current branch** is in one (`✗ current branch "OS-3482" is already
   part of a stack`, exit 5), which the init before it guarantees by leaving you on top of the
   stack it just made. So every init in a move runs from the trunk. A real move died between its
   third and fourth step on this, with both stacks already forgotten.
12. The stacks listing (`gh api repos/{owner}/{repo}/stacks`) returns, per stack,
   `{number, base:{ref}, open, pull_requests:[{number, state, merged_at, head:{ref, sha}}]}`,
   the PRs in stack order bottom-up -- read off a real repository, and what `stack` builds its
   remote half from. `gh api` fills in `{owner}` and `{repo}` from the checkout, so that costs
   one round trip and no `gh repo view` before it.
13. `gh stack link` **pushes a branch argument and opens a PR for one that has none** -- "branch
   arguments are automatically pushed to the remote before creating or looking up PRs. For
   branches without PRs, new PRs are created automatically." It also appends to an existing stack
   ("if some of the PRs are already in a stack, the existing stack is updated ... existing PRs
   are never removed") and rejects a PR that belongs to a different one. Read off its `--help`;
   it is why `prune` and `submit --move` pass PR numbers only.

## Differences from the standalone gsx

- **Exit codes are 0 and 1**, the guidelines' -- not the old 0/1/2/3. Every command in tdd exits
  that way, and the shared runner enforces it; what went wrong is in the error event's message.
- **`-v` is `--verbose` and `-V` is `--version`**, as everywhere in tdd; the standalone had them
  the other way round.
- **Single-letter forms for its own frequently-typed options** -- `-s`/`-m` (create, update),
  `-a`/`-p` (approve), `-a`/`-s`/`-r`/`-l` (stack), `-o` (override) -- which the general
  contract in
  [command-cli-guidelines.md](../../docs/command-cli-guidelines.md) reserves for
  `-h`/`-v`/`-f`/`-y`/`-V` only. Inherited from the standalone, kept because gsx is typed dozens
  of times a day; the long forms are what `<tdd_dir>/gsx.toml` presets, so nothing else depends
  on them.
- **No `--help ai`**: what it said -- the ordered side effects, what is irreversible -- lives in
  each subcommand's `--help` epilog and in this document.
- **Config**: `<tdd_dir>/gsx.toml`, TOML rather than `~/.gsx` INI, and shared with the option
  defaults every command keeps. TOML was rejected in the standalone because `/usr/bin/python3`
  (3.9) has no `tomllib`; inside tdd the tool runs in its own toolset venv, where it does.
- **Output is events**, so nothing is printed directly: `--format json` gives one JSON object per
  line, and `--dry-run` announces each mutating command as an `info` event while read-only
  commands still run, so a dry run still validates against the real repository.
