<!--
Copyright 2026 Tabsdata Inc.
-->

# gsx

`tdd gsx create|update|checkout|submit|apply|approve|purge`: GitHub issues + `gh stack`, the way
`gtx` does Jira + Graphite -- for a repository that uses neither. One command turns the pending
changes into an issue, a stack branch and a commit; another pushes the stack, opens its PRs and
labels them. Ported from the standalone `~/gsx` (1.5.0).

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
  validation, the edit engine), `purge` (which branches are leftovers), `commands` (the seven
  bodies), `config` (the repo tables in `<tdd_dir>/gsx.toml`), `progress` (the `[n/N]` counter),
  `version`.

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

The commands that repeat themselves -- `submit`, `apply`, `approve`, `purge` -- number the
units of their work. It is `tdd xp`'s Reporter thinking without the parts gsx has no use for
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

- **The total is the one that is known before the first unit runs.** `apply`, `approve` and
  `purge` know theirs (the snapshot; approvers x PRs; the candidate branches) and print
  `[n/N]`; `submit` may be opening the very PRs it
  is about to label, so it prints `[n]` and offers no denominator rather than guess one. Its push
  and its `--sync` are units of it too -- they are the slowest thing gsx does.
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
repositories' tables, every `default_*`, and every option the reader set under `[options]`. The version is the devtools
version, from the installed distribution's metadata: one number for the whole repo (invariant
10).

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
   chain, which is why `checkout` hands gh the URL for `#N` rather than the number.

## Differences from the standalone gsx

- **Exit codes are 0 and 1**, the guidelines' -- not the old 0/1/2/3. Every command in tdd exits
  that way, and the shared runner enforces it; what went wrong is in the error event's message.
- **`-v` is `--verbose` and `-V` is `--version`**, as everywhere in tdd; the standalone had them
  the other way round.
- **No `--help ai`**: what it said -- the ordered side effects, what is irreversible -- lives in
  each subcommand's `--help` epilog and in this document.
- **Config**: `<tdd_dir>/gsx.toml`, TOML rather than `~/.gsx` INI, and shared with the option
  defaults every command keeps. TOML was rejected in the standalone because `/usr/bin/python3`
  (3.9) has no `tomllib`; inside tdd the tool runs in its own toolset venv, where it does.
- **Output is events**, so nothing is printed directly: `--format json` gives one JSON object per
  line, and `--dry-run` announces each mutating command as an `info` event while read-only
  commands still run, so a dry run still validates against the real repository.
