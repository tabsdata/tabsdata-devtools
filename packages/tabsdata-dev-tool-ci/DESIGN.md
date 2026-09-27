<!--
Copyright 2026 Tabsdata Inc.
-->

# ci

`tdd ci download --action N [--repo ORG/REPO] [--workflow NAME] [--parallel P] [--dir PATH]
[--unzip]`: every unexpired artifact of GitHub Actions run #N, each into `PATH/<artifact>` (PATH
defaults to the current directory), P at a time (default 8); `--unzip` unpacks the archives
each one holds. The repo defaults to `tabsdata/tabsdata-ee`.

## Shape

- Toolset `launchers`: it needs no third-party package; depends on `deps-launchers`,
  `common-core`. Entry point `ci = tabsdata_dev.tool.ci:main`. Subcommand `download`; the word
  is `ci` so other Actions chores (re-run, logs, cancel) have somewhere to go.
- `bin-reqs`: `gh`. State: only `<tdd_dir>/ci.toml`, the shared `config` action's.

## How it works

- A shell script's three steps, in Python: `gh run list --json` finds the run's id from its
  number (the API addresses runs by id; `gh` has no filter by number, so the latest 1000 runs
  are searched, and a number two workflows share is refused with both named until `--workflow`
  picks one); `gh api .../runs/<id>/artifacts --paginate --jq` lists the artifacts, one JSON
  line each, filtered here rather than in jq so expired ones can be reported, not silently
  dropped; `gh run download -n NAME -D DIR/NAME` per artifact on a bounded thread pool
  (`common.core.parallel`).

## Decisions

- **`gh` for everything, no token handling.** `gh auth` is already how the team reaches
  GitHub, and it covers the API, pagination and the zip download; a REST client would have to
  find and store a token the tool has no business holding.
- **`--action` is the run number**, the `#N` the Actions page and a PR's checks show, not the
  database id -- that is what a person has in hand.
- **`--unzip` is about what is inside.** GitHub serves every artifact as a zip and `gh run
  download` always extracts it, so there is no zip left to open at that level; what a person
  still has to open is what the workflow packed -- the tarball of logs, a zip of reports. The
  top-level archives in each artifact's folder (`.zip`, `.tar[.gz|.bz2|.xz]`, `.tgz`, `.gz`) are
  unpacked there and removed, as gunzip does; nested archives are left, since unpacking
  recursively is a guess about what the workflow meant. Members that would land outside the
  folder are refused (tar's `data` filter; zip names checked). A failed unpack fails that
  artifact like a failed download.
- **A failed download does not stop the others.** Artifacts are independent; the run ends in one
  error naming the failures (each one's `gh` output in the failure log), with what did download
  listed in the event, rather than leaving a half-fetched set and no word of which half.
