<!--
Copyright 2026 Tabsdata Inc.
-->

# jq

`tdd jq ARGS...`: run the machine's `jq ARGS`, stdin, stdout and stderr passed through, and hand
its status back.

## Shape

- Toolset `launchers` (it needs no package); depends on `deps-launchers`, `common-core`. Entry
  point `common.core.launcher.run_program("jq", "jq", pinned=False)`.
- `bin-reqs`: `jq`. `launcher = true`: every argument is the program's, so no options, no
  `jq.toml`, no `config`.

## Decisions

- **The machine's jq, not a pinned one.** PyPI's `jq` is bindings to libjq with no command-line
  program, and every other candidate is a different program (`jaq`, `yq`'s wrapper around the
  same binary). The POSIX shell half already declares jq, so every tdd machine has it.
- **PATH is searched without this venv's scripts dir.** Under tdd that dir is first on PATH and
  holds this tool's own entry point, also called `jq`: found there, the launcher would run
  itself forever.
- A non-zero exit is one error event carrying `status`, and tdd exits 1, with no failure log:
  the launcher contract (`tdk`'s). `jq -e`'s distinction between 1 and 5 lives in `status`, not the exit code.
