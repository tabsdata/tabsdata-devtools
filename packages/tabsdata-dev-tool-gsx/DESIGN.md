<!--
Copyright 2026 Tabsdata Inc.
-->

# gsx

`tdd gsx create|update|checkout|submit|apply|auto-config`: GitHub issues + `gh stack`, the way
`gtx` does Jira + Graphite -- for a repository that uses neither. One command turns the pending
changes into an issue, a stack branch and a commit; another pushes the stack, opens its PRs and
labels them. Ported from the standalone `~/gsx` (1.5.0).

## Shape

- Toolset `launchers` (`deps-launchers` pins only pytest): gsx is standard library only, so it
  needs no pins of its own and joins an existing env rather than adding a sixth.
- `bin-reqs`: `git`, `gh`. The `gh stack` extension (github/gh-stack) is a gh install rather than
  a binary, so it is checked at run time, before anything is written.
- Modules: `args` (the two grammars argparse cannot express), `gh` (every child process),
  `labels` (config lookup, validation, the edit engine), `commands` (the six bodies), `config`
  (`<tdd_dir>/gsx.toml`), `version`.

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

Values are validated against the config first, refreshing it once when one is missing, because
**`gh pr edit` is not atomic**: given a bad add and a good remove, the remove lands and the add
fails, so a `replace` with a typo would strip the labels it meant to overwrite. Reviewers
starting `@` (`@copilot`, `@me`) or containing `/` (`org/team`) are never in a collaborator list
and pass through unchecked.

## Config

`<tdd_dir>/gsx.toml`, named after the command like every command's config, and user state --
`tdd-install` never writes or removes it. Keyed per repository (labels and collaborators differ
per repo; a flat list would validate one repo's names against another's), holding `labels`,
`reviewers`, `fetched` and the two `default_*` lists. `version` is the devtools version, from the
installed distribution's metadata: one number for the whole repo (invariant 10). A version that
differs from the running gsx forces one refresh, so the file's comments stay true.

`auto-config` rewrites the file whole -- this repository's two lists, `fetched`, the version and
every comment -- carrying over other repositories' tables and every `default_*` untouched. The
defaults are injected by `submit`/`apply` as leading `new`-scope ops, so an explicit op still
wins; `--no-defaults` skips them.

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

## Differences from the standalone gsx

- **Exit codes are 0 and 1**, the guidelines' -- not the old 0/1/2/3. Every command in tdd exits
  that way, and the shared runner enforces it; what went wrong is in the error event's message.
- **`-v` is `--verbose` and `-V` is `--version`**, as everywhere in tdd; the standalone had them
  the other way round.
- **No `--help ai`**: what it said -- the ordered side effects, what is irreversible -- lives in
  each subcommand's `--help` epilog and in this document.
- **Config**: `<tdd_dir>/gsx.toml`, TOML rather than `~/.gsx` INI. TOML was rejected in the
  standalone because `/usr/bin/python3` (3.9) has no `tomllib`; inside tdd the tool runs in its
  own toolset venv, where it does.
- **Output is events**, so nothing is printed directly: `--format json` gives one JSON object per
  line, and `--dry-run` announces each mutating command as an `info` event while read-only
  commands still run, so a dry run still validates against the real repository.
