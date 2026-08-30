<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-devtools

Python dev tools in isolated environments behind one entry point, so tool dependencies never
reach a project's dependencies. This file is the working contract; the design lives in the docs.

## Read first

- [docs/design.md](docs/DESIGN.md) — how it works and why, in a few screens, with the index of
  every tool's design doc: `packages/tabsdata-dev-<pkg>/DESIGN.md`, and for shell commands
  `packages/tabsdata-dev-shell/scripts/unix/<name>.design.md`. **Read the one for the tool you
  are about to touch** — it holds the decisions the code does not show.
- [docs/building-a-python-command.md](docs/building-a-python-command.md) and
  [docs/building-a-shell-command.md](docs/building-a-shell-command.md) — the how-tos; both end
  in writing the design doc.
- [docs/command-cli-guidelines.md](docs/command-cli-guidelines.md) — the contract every
  command's CLI meets: long `--options`, `--help`/`--verbose`/`--format json|view`, exit 0/1,
  a failure log in `/tmp`, events never prints.
- `.claude/DECISIONS.md` (every decision, why, what was rejected — do not relitigate without a
  reason), `.claude/VERIFIED.md` (proven facts; re-testing is waste), `.claude/OPEN.md` (gaps).

## Shape

```
tdd            shell function (sourced from <tdd_dir>/tdd-source.sh) -> front door over both halves
tdd-exe        executable in <tdd_dir>/tdd-venvs/tdd -> dispatches Python tools; help, doctor, info, --reqs
tdd-fn         shell function -> commands that change the current shell (venv, env, tdd-env, pycache, defaults)
tdd-install    executable -> the only way to build a tdd dir (`cargo make install [-- --editable]`)
```

Packages, all `tabsdata-dev-*` under the `tabsdata_dev` namespace: `-tdd` (stdlib only),
`-shell` (shell files as data), `-common-*` (shared code, third-party ranges), `-deps-*`
(pins; its name is the toolset), `-tool-*` (one tool; exactly one `-deps-*`), `-toolset-*`
(**generated**, committed `uv.lock`). Tools: `system`, `domain`, `domain-sf` (hidden), `xp`,
`tdk`, `tdkserver`, `km`; shell: `venv`, `env`, `tdd-env`, `pycache`, `defaults`; samples
`demo-exe1/2`, `demo-fn1/2`. Details: the design docs.

Never run the real `tdk`/`tdkserver` from an agent session: `tdk` refuses under an AI agent
(only when the user asks, run it with `CLAUDECODE` unset) and `tdkserver` is a server that never
returns — test the launchers with a fake program in a scratch venv. Prefer a scratch tdd dir
(`cargo make dev -- --dir PATH`) over the user's `~/.tdd` for experiments; `~/.tdd/data/`
holds the user's system and domain descriptors.

## Invariants — do not break these

1. **`tabsdata-dev-tdd` has zero third-party dependencies.** Standard library only, forever.
   It reaches Python through `uv`. Need YAML or similar? Change the data format instead.
2. **`uv` is a hard requirement.** Fail with exactly `uv is a hard requirement, install it`
   via `paths.require_uv()`. Never degrade gracefully.
3. **No uv workspace.** Each `-toolset-*` is an independent project with its own committed
   `uv.lock`; a workspace forces one resolution and breaks the point.
4. **No absolute paths in `catalog.json`.** Names only; paths are composed from the tdd dir.
5. **Every resource ships inside its package** and is found with `importlib.resources` —
   never an OS location, the cwd or `__file__` arithmetic. External binaries are the one
   exception: declared in `bin-reqs.txt` (package root; `<file>.bin-reqs.txt` beside a shell
   script), reported by `tdd --reqs`, refused before a command runs (`--help` excepted).
6. **All envs are relocatable** (`_make_venv()`: `--relocatable`, `UV_LINK_MODE=copy`);
   `tdd-source.sh` locates itself; never bake an absolute `TDD_DIR`.
7. **A tool depends on exactly one `-deps-*`.** That is what assigns its toolset.
8. **`-toolset-*` packages and `catalog.json` are generated.** Never hand-edit; `cargo make gen`.
9. **Layout is `src/python/main/` + `src/python/test/`** with hatchling `only-include` + `sources`.
10. **`VERSION` at the repo root is the only version.** Every `pyproject.toml` is `dynamic`;
    `-tdd` force-includes it; `tdd-install` stamps `<tdd_dir>/VERSION`.
11. **Demo/hidden is an explicit marker** (`[tool.tdd] demo|hidden = true`,
    `tdd_fn_register --demo`), a listing concern only.
12. **A `-deps-*` may pin its interpreter** with `[tool.tdd] python = "3.12"`.
13. **Generic code goes in `common-core`, family code in a `common-<family>`.**
14. **Variables**: `TDD_*` public (`TDD_DIR`, `TDD_VENV`, `TDD_PARALLELISM`), `_TDD_*` private
    to the tool chain (`_TDD_TOOL`, `_TDD_COMMON_SH`, `_TDD_CRYPTO_KEY`, `_TDD_SYSTEMS`,
    `_TDD_XP_*`), `TD_*` tabsdata's, `<SYSTEM>__<KEY>` a system's config.
15. **Every command speaks events** through the shared layer of its side (`common.sh`;
    `common.core.cli.run()`/`render`; `tabsdata_dev.tdd.render`, the byte-identical twin —
    edit both). Commands never print; the tests check it.

## Commands

```bash
cargo make help                  # every task with its options
cargo make install               # wheels + locks -> <dir>/wheels, build the envs from them
cargo make dev                   # = install -- --editable: every env linked to this checkout
cargo make check                 # lint + test + reqs — the gate; must pass before a commit
cargo make test                  # every package's tests, each in the env it ships with
cargo make fmt                   # ruff format; run after editing (stale string patches fail otherwise)
```

Requires only `uv` and `cargo-make`; all honour `TDD_DIR` and `-- --dir PATH`; `test` and
`check` need an initialized tdd dir and, in wheels mode, a reinstall to see source changes.

## Conventions

- Every file starts with the house header — `#`, `# Copyright 2026 Tabsdata Inc.`, `#` (an HTML
  comment in Markdown). Exceptions are parsed data or machine-owned: `VERSION`, `catalog.json`,
  `uv.lock`, the model data files (`.csv`, `.ddl`), the bundled xp suites.
- A new tool or shell command comes with its design doc (a test enforces it); keep every doc
  short and complete; `docs/design.md` stays the mechanics, not a tour.
- Comments explain **why**, not what; docstrings on modules and non-obvious functions.
- Tests live in `src/python/test/` and run inside the toolset venv the code ships with.
- `ruff format` and `ruff check` must pass at the version pinned in `Makefile.toml`.
- Commit only when asked; the smoke scripts under `scripts/` stay uncommitted until asked.
