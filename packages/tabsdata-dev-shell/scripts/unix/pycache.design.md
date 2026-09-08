<!--
Copyright 2026 Tabsdata Inc.
-->

# pycache

`tdd pycache clean [--package-prefixes P[,P...]] [--all]`: purge packages from the uv and pip
caches by name prefix (default `tabsdata`), so a rebuilt wheel of the same version or a
republished index package is never served stale.

- `uv cache clean` wants exact names, so they are derived from the versioned entries the cache
  holds; editable/path builds (keyed by source hash) and their unpacked archives, which uv skips,
  are swept by hand. Entries inside cached environments uv still references are reported, not
  removed (`uv cache prune` or `--all`).
- The pip half is by name too: `pip cache remove <prefix>*` per prefix, tried in both the `-`
  and `_` spellings since pip stores wheels under the filename's, and `pip cache purge` for
  `--all`. No pip on `PATH` is a warning and a uv-only clean, not a failure -- pip is not this
  command's `bin-reqs`, and a machine without one still has a uv cache worth purging.
- A shell command only to sit beside `venv` in this shell's toolbox; it changes nothing in the
  shell. `bin-reqs`: `uv`.
- `config` (`--show`/`--default`/`--create [--force]`) comes from the shared layer, over the
  defaults `tdd_defaults_pycache` declares (`--package-prefixes tabsdata`, `--all false`).
