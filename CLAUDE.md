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
tdd            shell function (loaded from <tdd_dir>/tdd-source.sh or .ps1) -> front door over both halves
tdd-exe        executable in <tdd_dir>/tdd-venvs/tdd -> dispatches Python tools; help, doctor, info, --reqs
tdd-fn         shell function -> commands that change the current shell (venv, env, tdd-env)
tdd-install    executable -> the only way to build a tdd dir (`cargo make install [-- --editable]`)
```

The shell half exists **twice**, once per family: `scripts/unix/*.sh` (POSIX sh, bash 3.2 and
zsh) and `scripts/powershell/*.ps1` (PowerShell 7). A family is the shell the user is in, not the
OS they are on -- pwsh runs on macOS, Linux and Windows -- and `tdd-install` writes both loaders
into every tdd dir. The same commands with the same summaries, enforced by the generator.

Packages, all `tabsdata-dev-*` under the `tabsdata_dev` namespace: `-tdd` (stdlib only),
`-shell` (shell files as data), `-common-*` (shared code, third-party ranges), `-deps-*`
(pins; its name is the toolset), `-tool-*` (one tool; exactly one `-deps-*`), `-toolset-*`
(**generated**, committed `uv.lock`). Tools: `system`, `domain`, `domain-sf` (hidden), `xp`,
`gsx` (disabled), `tdk`, `tdkserver`, `km`, `pqt` (parquet-tools), `jq`, `pycache`, `mexe` (shell commands across `--dirs`), `smoke` (the end-to-end scripts: `tdd smoke
run --script NAME ...`, or exported with `tdd smoke export-scripts --dir DIR`), `apidoc` (tdx-apidocgen's
port: `tdd apidoc generate --out FILE`, its bundled spec exported with `tdd apidoc export-spec
--dir DIR`); shell: `venv`,
`env`, `tdd-env`; samples. Details: the design docs.

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
   A tree that is *edited* stays where it is edited and is `force-include`d into the wheel —
   the shell scripts, `<repo>/smoke-tool/`, `<repo>/xp-tool/` (xp's suites and connections);
   `force-include` does nothing for an editable install, so each locates both layouts.
6. **All envs are relocatable** (`_make_venv()`: `--relocatable`, `UV_LINK_MODE=copy`);
   `tdd-source.sh` locates itself; never bake an absolute `TDD_DIR`.
7. **A tool depends on exactly one `-deps-*`.** That is what assigns its toolset.
8. **`-toolset-*` packages and `catalog.json` are generated.** Never hand-edit; `cargo make gen`.
9. **Layout is `src/python/main/` + `src/python/test/`** with hatchling `only-include` + `sources`.
10. **`VERSION` at the repo root is the only version.** Every `pyproject.toml` is `dynamic`;
    `-tdd` force-includes it; `tdd-install` stamps `<tdd_dir>/VERSION`.
11. **`[tool.tdd] hidden|launcher|disabled = true` are explicit markers**: hidden is a listing
    concern only (the tool still dispatches); a launcher owns no options, so it has no config
    file; disabled comments the tool out -- the generator treats the package as absent. A tool
    whose name starts with `_` is plumbing by convention and hidden without the marker; `tdd -x`
    lists every hidden tool.
12. **A `-deps-*` may pin its interpreter** with `[tool.tdd] python = "3.12"`.
13. **Generic code goes in `common-core`, family code in a `common-<family>`.**
14. **Variables**: `TDD_*` public (`TDD_DIR`, `TDD_PARALLELISM`), `_TDD_*` private
    to the tool chain (`_TDD_TOOL`, `_TDD_VENV`/`_TDD_VENV_ACTIVATED`, `_TDD_COMMON_SH`, `_TDD_CRYPTO_KEY`, `_TDD_SYSTEMS`,
    `_TDD_XP_*`), `TD_*` tabsdata's, `<SYSTEM>__<KEY>` a system's config.
15. **A shell command is written in both families**, with the same name, summary, options,
    events and JSON fields: `scripts/unix/<name>.sh` and `scripts/powershell/<name>.ps1`, each
    over its family's shared layer (`common.sh` / `common.ps1`). The generator refuses to build
    when the two drift. In PowerShell, status travels in `$_TDD_RC`, never as a return value --
    a function's success-stream output *is* its return value there.
16. **Every command speaks events** through the shared layer of its side (`common.sh`;
    `common.core.cli.run()`/`render`; `tabsdata_dev.tdd.render`, the byte-identical twin —
    edit both). Commands never print; the tests check it.
17. **`tdd-install` never touches user state in the tdd dir.** It rebuilds only
    `tdd-venvs/` and rewrites `catalog.json`/`VERSION`/ both `tdd-source` loaders;
    `data/` (system/domain descriptors), `managed-venvs/` (`tdd venv` environments) and
    every `<command>.toml` are the user's and survive every re-init (a test pins this).

## Commands

```bash
cargo make help                  # every task with its options
cargo make install               # wheels + locks -> <dir>/wheels, build the envs from them
cargo make dev                   # = install -- --editable: every env linked to this checkout
cargo make lock                  # re-resolve every toolset's uv.lock in one pass (upgrade)
cargo make check                 # lint + test + reqs — the gate; must pass before a commit
./install.sh               # install + a config file for every command (--dir, --editable, --force)
cargo make test                  # every package's tests, each in the env it ships with
cargo make fmt                   # ruff format; run after editing (stale string patches fail otherwise)
```

Requires only `uv` and `cargo-make`. `install`/`dev`/`uninstall` take `-- --dir PATH`; `test`,
`check` and `reqs` read `TDD_DIR` only (default `~/.tdd`) and need an initialized tdd dir there --
in wheels mode, a reinstall to see source changes.

## Conventions

- Every file starts with the house header — `#`, `# Copyright 2026 Tabsdata Inc.`, `#` (an HTML
  comment in Markdown). Exceptions are parsed data or machine-owned: `VERSION`, `catalog.json`,
  `uv.lock`, the model data files (`.csv`, `.ddl`), the bundled xp suites.
- A new tool or shell command comes with its design doc (a test enforces it); keep every doc
  short and complete; `docs/design.md` stays the mechanics, not a tour.
- Comments explain **why**, not what; docstrings on modules and non-obvious functions.
- Tests live in `src/python/test/` and run inside the toolset venv the code ships with.
- `ruff format` and `ruff check` must pass at the version pinned in `Makefile.toml`.
- Every command owns `<tdd_dir>/<command>.toml`: its `[options]` defaults (`[options.<action>]`
  for one action, merged under what was typed) and whatever else it keeps. The `config` action
  (`--show`/`--default`/`--create [--force]`) comes from the shared layer on both sides and is
  built from the command's own options; writes are a temporary file and one rename. User state:
  `tdd-install` never writes or removes it. There is no shared config file.
- Commit only when asked.
