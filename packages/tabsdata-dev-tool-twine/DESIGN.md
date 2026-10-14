<!--
Copyright 2026 Tabsdata Inc.
-->

# twine

`tdd twine ARGS...`: run twine (`upload`, `check`) with every argument passed through, e.g.
`tdd env set --pypi-twine && tdd twine upload --repository-url URL dist/*`.

## Shape

- Toolset `twine`; depends on `deps-twine` alone (`twine==7.0.0`). No `bin-reqs`: the program
  is pinned and sits in the toolset's scripts dir.
- `launcher = true`: every argument is twine's, so no options, no `twine.toml`, no `config`.
- Credentials are twine's own variables, `TWINE_USERNAME`/`TWINE_PASSWORD`, which
  `tdd env set --pypi-twine` exports from 1Password.

## Decisions

- **The entry point is twine's own, `twine.__main__:main`.** tdd runs a tool as
  `<toolset venv>/bin/<name>`, and twine installs a `bin/twine` of its own into the same venv;
  of two different scripts with one name, the last installed silently wins (tried with uv: a
  tool module there never ran). Declaring the identical entry point makes the order irrelevant
  and keeps the name `twine`. The cost: twine's errors and exit status come back as twine
  prints them, not as the one error event a `run_program` launcher such as `pqt` emits. The
  package's module holds only `ENTRY_POINT`, which a test holds in step with twine's.
- **Its own toolset, not `pypi`.** twine 7 needs `packaging>=26.1` (`deps-pypi` pins 25.0) and
  brings requests, rich and keyring; the index builder should not share that resolution.
