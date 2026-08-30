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
- A shell command only to sit beside `venv` in this shell's toolbox; it changes nothing in the
  shell. `bin-reqs`: `uv`.
