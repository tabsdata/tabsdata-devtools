<!--
Copyright 2026 Tabsdata Inc.
-->

# pycache

`tdd pycache clean [--package-prefixes P[,P...]] [--all]`: purge packages from the uv and pip
caches by name prefix (default `tabsdata`), so a rebuilt wheel of the same version or a
republished index package is never served stale.

## Shape

- Toolset `launchers`, because the tool needs no third-party package at all and that bundle pins
  only pytest; depends on `deps-launchers`, `common-core`. Entry point `pycache = ...:main`.
- `bin-reqs`: `uv`. State: `<tdd_dir>/pycache.toml`, the `config` action's, from the shared layer.

## How it works

- `uv cache clean` wants exact names and there is no `uv cache list`, so they are derived from the
  versioned entries the cache holds: `<prefix>*-<digit>...`, case-insensitive, the version and
  whatever follows it dropped, then normalized the way uv normalizes (lower-case, `-` for `_`).
  Requiring the version is what keeps a wheel's top-level import package (`tabsdata_dev/`) from
  posing as a distribution called `tabsdata-dev`.
- Editable and path builds are keyed by the hash of their source directory, so a name-keyed clean
  skips them and `uv cache prune` calls them in use. They are what a devtools developer most wants
  gone, so they are swept by hand: the per-source shard under `sdists-v*/<kind>/`, and any
  `archive-v*/<id>` whose top level is a matching `.dist-info`. An archive holding a whole
  environment has no `.dist-info` at its top level and is uv's to prune; entries inside one
  (`.../lib/python3.12/site-packages/...`) are reported, never removed.
- One walk of the cache answers all three questions -- which distributions to name, which shards to
  sweep, what is left afterwards -- where the shell half ran a `find` per prefix per question.
- The pip half is by name too: `pip cache remove <prefix>*` per prefix, tried in both the `-` and
  `_` spellings since pip stores wheels under the filename's, and `pip cache purge` for `--all`.

## Decisions

- **It was a shell command until 2026-09-18** and had no reason to be: a shell command exists to
  change the calling shell, and this changes nothing there -- its own header said it sat beside
  `venv` "in this shell's toolbox". As a tool it gets real tests against a cache tree instead of
  string assertions on a script, loses the `find`/`awk`/`sed` pipeline and the BSD-versus-GNU and
  zsh word-splitting workarounds, and builds its JSON through the renderer. Its `[options.clean]`
  table and every event and field are unchanged, so `pycache.toml` and the smoke scripts' `tdd
  pycache clean` carry over untouched.
- **pip is not in `bin-reqs.txt` and does not go through `proc.run`.** A declared binary is
  refused *before* the tool starts when it is missing, so declaring pip would turn the one case
  this command is built to survive -- no pip on the machine -- into a refusal to run at all. The
  declare-or-refuse model has no way to say "optional", so `_pip_run` calls `subprocess` directly
  and says why. Nothing is guessed in exchange: the binary is whatever `pip_command()` resolved on
  the user's own PATH.
- **pip is looked for, and run, on the user's PATH without tdd's own venv bin.** `tdd` puts the
  toolset's `bin/` first, and that venv is tdd's, not the user's: it carries a `python3` with no
  pip. Everything after it is the user's PATH, the active managed venv's `bin/` included, which is
  the pip whose cache the user means. Choosing the binary is not enough -- the child gets that PATH
  too. A pyenv shim re-resolves `python3` by name from what it is handed, so a child given the
  inherited PATH execs tdd's interpreter and a machine with pip is told it has none. Found by
  running it: `tdd pycache clean` said "no pip found" on a machine whose `python3 -m pip` works.
