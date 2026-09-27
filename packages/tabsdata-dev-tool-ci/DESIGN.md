<!--
Copyright 2026 Tabsdata Inc.
-->

# ci

`tdd ci download --action N [--repo ORG/REPO] [--workflow NAME] [--parallel P] [--dir PATH]
[--expand]`: every unexpired artifact of GitHub Actions run #N, extracted straight into PATH
(default: the current directory), P at a time (default 8). `--expand` also expands the archives
an artifact's zip holds: a zip holding a tar.gz is expanded twice, and PATH is left with the
tar's contents. The repo defaults to `tabsdata/tabsdata-ee`.

## Shape

- Toolset `launchers`: it needs no third-party package; depends on `deps-launchers`,
  `common-core`. Entry point `ci = tabsdata_dev.tool.ci:main`. Subcommand `download`; the word
  is `ci` so other Actions chores (re-run, logs, cancel) have somewhere to go.
- `bin-reqs`: `gh`. State: only `<tdd_dir>/ci.toml`, the shared `config` action's.

## How it works

- A shell script's three steps, in Python. The run's id from its number: the API addresses runs
  by id and has no filter by number, so `gh api .../actions/runs?per_page=100&page=N` is paged
  newest first and the search stops at the first page holding the number (at most 1000 runs).
  `gh run list --limit 1000` fetched all ten pages every time -- twenty-odd seconds of silence
  for a run from this morning. Two runs #N on that page (two workflows) are refused with both
  named until `--workflow` (a workflow's name or file name) picks one; otherwise the newest wins
  and its workflow is named. Then `gh api .../runs/<id>/artifacts --paginate --jq` lists the
  artifacts, one JSON line each, filtered here rather than in jq so expired ones can be
  reported, not silently dropped; then each artifact on a bounded thread pool (`common.core.parallel`): `gh api
  .../artifacts/<id>/zip` streamed into `PATH/.<name>.zip.part` (`proc.popen`), extracted into
  `PATH/.<name>.staging`, its archives expanded there with `--expand`, then its files moved
  into PATH and the zip and the staging dir removed.
- **Progress.** Nothing is silent for more than a moment. Each lookup says what it is looking for
  before it starts and what it found (the run's id; how many artifacts, how big), since paging
  through a thousand runs takes seconds. Each artifact says how long its download took and at what
  rate, and each archive `--expand` opened, once done -- no line announces a start. What is
  still under way is only a progress line, one per piece in flight -- `NAME: downloading 45% (110.2 MiB of 241.9 MiB, 4.4 MiB/s)`, then
  `extracting`, then `expanding X.tar.gz`: on a terminal a status block redrawn in place twice a
  second (`Renderer.live`), elsewhere (a pipe, a log, JSON) info events every 5s. Downloads and extraction count the bytes written; a tar or gz reports
  how far into the compressed file its reader is. In JSON each line carries `artifact`,
  `phase`, `done`, `total`. All events go out under one lock, so parallel lines never mix.

## Decisions

- **`gh` for everything, no token handling.** `gh auth` is already how the team reaches
  GitHub, and it covers the API, pagination and the zip download; a REST client would have to
  find and store a token the tool has no business holding.
- **`gh api`, not `gh run download`.** `gh run download` says nothing until it is done, and a
  release run's three 250 MiB assemblies kept it silent for minutes -- it read as hung. `gh api`
  on the artifact's zip URL streams the same bytes to stdout, so they can be counted against
  the size the listing already gave, and gh still holds the login. The extraction it did is a
  few lines of `zipfile`, with the same outside-the-folder refusal `--expand` applies.
- **`--action` is the run number**, the `#N` the Actions page and a PR's checks show, not the
  database id -- that is what a person has in hand.
- **No folder per artifact.** An artifact's files land in PATH itself. `gh run download -D
  PATH/NAME` made a folder per artifact, but the artifacts this is for already say what they
  are in their files' names -- a release run's assemblies are a tar.gz each of platform wheels
  with no top-level dir -- and a folder named after the artifact
  (`tabsdata-2.2.0-enterprise-linux-x86-64-assembly-2026.09.26@22.38.02`) is one more level to
  step through for nothing.
- **`--expand` is the second expansion.** GitHub serves every artifact as a zip and the
  download always extracts it; what a person still has to open is what the workflow packed --
  the tarball of wheels, a zip of reports. With `--expand` the archives that came out of the zip
  (`.zip`, `.tar[.gz|.bz2|.xz]`, `.tgz`, `.gz`) are expanded too and removed, as gunzip does: a
  zip holding a tar.gz is expanded twice and PATH is left with the tar's contents. Archives
  inside those are left, since expanding recursively is a guess about what the workflow meant.
  Members that would land outside the dir are refused (tar's `data` filter; zip names
  checked). A failed expansion fails that artifact like a failed download.
- **Each artifact is staged apart, and two cannot share a file.** Artifacts are extracted in
  parallel into one dir, and the ones this is for collide: every assembly of a release run
  ships its own `tabsdata-assembly-devpi.tar.gz`. So each is extracted (and expanded) in a
  staging dir of its own and only then moved into PATH -- the three tars never meet, and the
  wheels they hold are distinct. A file another artifact of the same run already put in PATH
  fails the later artifact, naming the earlier one, rather than being silently overwritten;
  without `--expand` that is what a release run's three same-named tars do. A file left in PATH
  by an earlier run is replaced.
- **A failed download does not stop the others.** Artifacts are independent; the run ends in one
  error naming the failures (each one's `gh` output in the failure log), with what did download
  listed in the event, rather than leaving a half-fetched set and no word of which half.
