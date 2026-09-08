<!--
Copyright 2026 Tabsdata Inc.
-->

# pypi

`tdd pypi generate|promote|push|fetch|check|serve|cache-clean|aws-check`: build and publish
`pypi.tabsdata.com`, a public, anonymous-read Python index serving only Tabsdata's own wheels --
static HTML on S3 behind CloudFront, no server, nothing to patch. Ported from `tdi-pypi` in
`tabsdata-infra/pypi`, which was a standalone package with a venv of its own and two verifier
scripts beside it. The system it publishes is designed in that repo's `docs/`; this document is
the tool.

## Shape

- Toolset `pypi` (`deps-pypi`: boto3, pyyaml, packaging). Its own rather than `systems`, which
  pins every SQL dialect in the shop: three small libraries should not share a resolution with
  `oracledb` and `polars`.
- Entry point `tabsdata_dev.tool.pypi:main`. State is the meta repository, not the tdd dir; the
  only thing under `<tdd_dir>` is `pypi.toml`.
- `bin-reqs`: `aws tofu uv git curl jq openssl dig` -- what `tools-verify.sh` checked. Only `git`
  is shelled out to (`git.py`, the prod gate, through `proc.run` so the declaration is enforced
  rather than remembered); the rest are the workflow's, declared so a gap refuses the command
  instead of surfacing at step 6 of a 10-step publish. `aws-check` reports each one's version.
- Modules. The tree: `model` (the `Dist` record, PEP 503 normalization), `dist` (read a wheel),
  `indexhtml` (pages), `tree` (raw and lane trees, the root index), `yanked`. The frame: `config`
  (`lanes.yaml` + `POLICY`), `repo` (the guard), `git` (the release gate). The S3 engines: `plan`
  (plan/report/execute, shared by every lane of push), `pull` (shared by every lane of fetch).
  The verbs: `generate`, `promote`, `check`, `cache`, `push`, `push_raw`, `fetch`, `aws_check`.
- Every subcommand also takes the common options, so `--pypi-repo`, `--format` and `--verbose`
  work on either side of the subcommand word (argparse only accepts a top-level option before it;
  the guidelines say everything after the command word belongs to the command). `SUPPRESS` on the
  pre-subcommand copies, so an unused one does not overwrite what was already given.

## The pipeline

```
raw-wheels/<VERSION>/       the wheels + a MANIFEST        gitignored, yours
     │ generate
     ▼
pypi-wheels/staging/        the local staging tree         committed, minus *.whl
     │ push --lane staging  -> s3://td-pypi-staging
     │ promote
     ▼
pypi-wheels/prod/           the local prod tree            committed, minus *.whl
     │ push --lane prod     -> s3://td-pypi-prod    two gates: git pushed, raw archived
     ▼
https://pypi.tabsdata.com/simple/

raw-wheels/  ⇄  push/fetch --lane raw  ⇄  s3://td-raw-wheels   the archive
```

One direction, and every arrow rebuilds its target from scratch. `serve` runs `http.server` on a
local tree, so the index can be tested with a real pip before any credential is involved.

## Three ideas the rest follows from

- **`raw-wheels/` is the source of truth.** Everything downstream is a function of it and can be
  deleted and rebuilt. Nothing is ever edited in place: you change `raw-wheels/` and run the
  pipeline again.
- **Every tree ends with `index.json`, written last** -- by `generate` and `promote` on disk, by
  `push` in the bucket, and taken last by `fetch`. So no half-built tree ever looks complete, and
  `check --lane L --local|--remote` is one question: is the index there (locally it also asserts
  that every file the index lists is on disk, without hashing any of them). `serve`, `promote`,
  `push` and `check` all refuse a tree without it, with a message saying what to run.
- **Every object carries its sha256.** `push` stamps `x-amz-meta-sha256` on every put and reads it
  back with one HEAD per object. That is how a push knows what to skip, replace and delete without
  downloading anything or trusting an ETag, and how the prod gate compares bytes rather than sizes.

## The guard

`repo.py`. The meta lives in a repository of its own whose root holds `config/`, `raw-wheels/` and
`pypi-wheels/`. Its remote is `pypi-repo` in `<tdd_dir>/pypi.toml`, defaulting to
`git@github.com:tabsdata/tabsdata-pi.git` -- there is exactly one of them, so a fresh install works
before it is configured -- and every subcommand runs at the root of a clone of it. It runs before
any path is resolved, since `--raw` and `--tree` are relative and name the wrong directory
anywhere else. Three questions in the order a reader would ask them -- a repository? its root? a
clone of the right one? -- each with its own message. It compares **remotes, not paths**: a path is
one machine's, and remotes normalize to `host/org/repo` (no scheme, no user, no port, no `.git`,
lower-cased), so the ssh and https spellings agree while two different repositories still do not
collide. Every remote counts, not just `origin`, so a fork whose `upstream` is the real one passes.
`tdi-pypi` said "run from `pypi/`" in a docstring and found out at the first missing file.

## The trees

**`raw-wheels/<VERSION>/MANIFEST` is an allowlist, one wheel filename per line.** Listed and
present is processed; present but not listed is ignored *and reported*, because "I dropped it in
and it did not ship" is otherwise a silent surprise; listed but absent is a hard error, which is
what makes an incomplete release a failure rather than something to notice in a diff. Duplicates
within one, or a filename claimed by two releases, are refused. `generate` reads and validates
every MANIFEST **before deleting anything**, so a typo in one release does not leave staging empty.

**A lane tree is `files/` (each wheel plus its `.metadata` sidecar), `simple/**/index.html`, a
root `index.html` and `index.json`.** Everything but the wheels is committed, so the commit diff
*is* the release record. `index.json` carries `format`, `generated_at`, the releases, and one
record per file: `filename, release, project, version, sha256, size, requires_python,
core_metadata_sha256, added_at, yanked`. Records are read back as `Dist(**f)`, so a new field
without a default is a breaking change for every index already in git.

Wheels are **hardlinked** between trees, with a copy fallback across filesystems -- 6 GB of wheels
should not be duplicated three times to publish once. `clear_tree` unlinks the index first, so a
tree being rebuilt never looks complete while it is half gone, and keeps `yanked.yaml`.

**Yanking is a file, not a command.** Each tree's `yanked.yaml` holds masks --
`<PACKAGE>-<VERSION>-<OS>`, `*` meaning all for that element, shell patterns in each, the project
name in either spelling -- read by `generate` (staging) and `promote` (prod) and written by
nothing but a human. A missing one is created with its header so there is always something to
edit; an existing one is never touched. It survives the from-scratch rebuilds, is not part of
`tree_files` and so is never pushed, fetched or pruned -- it is the operator's instruction for
producing the tree, not the tree. Each tree's list is its own: `promote` clears staging's yanks
before applying prod's, so a yank flows through the same generate -> staging -> promote -> commit
-> prod path as a release, with the same gates.

## What pip needs

Two levels of PEP 503 HTML, rendered by `indexhtml` -- pure, no AWS, no filesystem, no clock.
**Deterministic**: the same records must produce byte-identical pages, because the push plan's
"unchanged" verdict depends on it. That is where the correctness risk lives (normalization,
escaping, relative hrefs, sort order), so it is the module with real unit tests.

- **Relative hrefs**, `../../files/<name>#sha256=...`, never absolute -- the same tree works at
  `localhost`, on a vanilla CloudFront domain and at the custom domain, which is what makes
  local -> staging -> prod one tree promoted rather than three regenerations. Unaffected by the
  distribution's origin path.
- `data-requires-python` (HTML-escaped), `data-core-metadata` (PEP 658/714, so a resolver reads a
  few KB instead of a 30 MB wheel), `data-yanked` (PEP 592: pip keeps resolving a yanked file for
  anyone pinning that exact version and refuses to select it otherwise), and
  `<meta name="pypi:repository-version" content="1.0">` (PEP 629).
- Files sort **version-aware**, so `0.9.10` follows `0.9.5` and diffs stay additive. Parseable and
  unparseable versions are tagged `0`/`1` in the sort key so they are never compared to each other.
- A one-line landing page at the tree root, because the distribution's default root object resolves
  to `<base_path>/index.html` and the bare domain would otherwise be a 404.

## Lanes, and where policy lives

`config/lanes.yaml` answers only *where*: account, region, `release_ref`, the archive, and per lane
its bucket, `base_path`, distribution, vanilla and custom domain (`-` for none).
**Safety is code.**
`POLICY` in `config.py` holds `require_archived`, `require_pushed` and `require_yes` per lane, so
weakening one takes a review rather than a one-line YAML edit. A lane in the YAML with no entry in
`POLICY` is a hard error, so a new lane cannot get prod-like reach with staging-like safety; a
`POLICY` lane missing from the YAML is one too. `raw` is a lane on the command line only -- no
distribution, no policy, write-once by construction.

## push

`plan.py` is the dry-run engine every lane of push shares: plan (a list of `Action`s) -> report ->
execute.
Nothing is written that was not printed first, and `--dry-run` stops between the second and third.

**The plan makes the bucket exactly the tree**: index deleted first, orphans deleted, new and
changed put, unchanged skipped, index put last. Changed is decided by the stamped sha256; for an
object written before this tool, or by `aws s3 cp`, `object_differs` falls back to size (free from
the listing) and then to the ETag, which is the content MD5 because every put is a single
`put_object` -- an ETag carrying a part count is not an MD5 at all, so size has to stand alone. A
push that changes nothing leaves the index alone too: taking it down and putting it back would make
the lane look incomplete, and cost an invalidation, for nothing. `--full` skips the comparison
entirely -- delete everything, index first; upload everything, index last.

**Execution keeps the order that matters and ignores the order that does not.** Consecutive actions
of one verb form a batch that runs `--parallel` at a time (default 32), biggest first so the long
uploads start immediately and the small ones fill in around them; the index is marked `alone`, a
barrier of its own. A failure finishes its batch, reports every failure in it together, and stops
there -- so the index, always last and alone, never lands over a push that did not complete, and
the lane correctly reports incomplete until the push is re-run.

`files/` goes up `immutable` for a year, everything else at 60 s. After a push that wrote, `/`,
`/index.html`, `/index.json` and `/simple/*` are invalidated, and `/files/*` only when a `files/`
object was deleted or overwritten. Viewer paths, not S3 keys: with `base_path: pypi` the object is
`pypi/simple/index.html` but the path is `/simple/*`. A push that wrote nothing invalidates
nothing. `cache-clean` is the same for doubt: `/*`, everything the distribution holds, with the
bucket untouched.

**Prod's two gates run before anything is listed or written.** The git gate: nothing uncommitted
under `pypi-wheels/` or `config/` (`--porcelain` reports untracked files too, so a sidecar that was
never added is caught), the remote fetched first so being offline fails rather than letting a stale
ref pass, and HEAD reachable from `release_ref` -- ancestry, not equality, so a ref that moved on
while the release was being verified still passes. The archive gate: every wheel the tree's index
lists exists in the archive with the same sha256. Git is the release record, and prod must never
serve bytes that are not archived durably.

**`--yes` is never inferred from a non-tty.** That would let a CI run satisfy the prod lane's
`require_yes` without anyone typing it. The prompt is the one thing a command may put on the
terminal directly -- a question is not an event, and in `--format json` there is no terminal to
ask.

**`push --lane raw` is write-once.** A filename already archived with different bytes is refused,
every one of them listed, with the reason: a hash someone recorded at install time can no longer be
checked if the archive moves under it, so release the fix as a new version. `--force` overwrites
exactly those keys. Archived objects not in a MANIFEST here are left alone unless `--sync`, which
warns by name before deleting a whole version.

## fetch

The mirror backwards, into `raw-wheels/` or a lane tree. The local index is removed first and taken
last, so an interrupted fetch leaves a tree that says so. `pull.py` downloads to a `.part` and
renames, so a truncated file never appears under a real name for `generate` or `push` to trust, and
verifies what landed against the listing; downloads run in parallel, biggest first, and one failure
does not stop the others -- the caller decides what a partial result means. `--sync` lists what it
would delete and asks before pruning. For the raw lane a missing `MANIFEST` is recreated from the
listing (`push --lane raw` uploads exactly the MANIFEST entries and never the file itself, so the
listing *is* the manifest); one already on disk is the author's and is kept, reported as
`kept (differs)` when it disagrees.

## aws-check

`aws-verify.sh` as a subcommand, over boto3 rather than the `aws` CLI: the tool has one way of
talking to AWS, so what the check proves and what a push does cannot drift. Five sections in the
order a reader needs them -- identity, read access, provisioning (`tofu apply`'s permissions),
runtime (push's, on the buckets and distributions the config names), and what already exists,
including whether the serving buckets are SSE-S3, which the ETag fallback depends on. Live read
probes come first, because a denial there is a fact rather than a prediction; the writes are
`iam:SimulatePrincipalPolicy`. A simulation reflects identity policies and SCPs only -- a resource
policy, a permission boundary or a session policy can still deny at call time -- and when the
simulator is itself denied its sections are **skipped, never passed**. It changes nothing.

## Ported, with the house rules applied

Everything that printed now speaks events: the push plan is one `info` per action, which in
`--format json` is a line each, as a printed table never was. Every `SystemExit` became a
`ToolError`, so the failure log and exit 1 come from the shared layer, and `main` sets
`AWS_RETRY_MODE=standard` unless the environment already said otherwise. The one thing still
printed is the interactive confirm in `plan.confirm`, above.
