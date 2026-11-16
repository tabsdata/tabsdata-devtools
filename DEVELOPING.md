<!--
Copyright 2026 Tabsdata Inc.
-->

<div align="center">
    <img src="assets/images/tabsdata-logo-for-light-theme.svg#gh-light-mode-only" alt="Tabsdata" width="500">
    <img src="assets/images/tabsdata-logo-for-dark-theme.svg#gh-dark-mode-only" alt="Tabsdata" width="500">
</div>

# Developing Tabsdata DevTools

This guide covers what is specific to developing **tdd** in this repository. Read it together
with [Developing Tabsdata](https://github.com/tabsdata/tabsdata/blob/main/DEVELOPING.md), which
this guide builds on.

## Contents

- [1. Prepare your machine](#1-prepare-your-machine)
- [2. Install from your checkout](#2-install-from-your-checkout)
- [3. Run the tests](#3-run-the-tests)
- [4. Find your way around the tasks](#4-find-your-way-around-the-tasks)
- [5. Learn how it works](#5-learn-how-it-works)

## 1. Prepare your machine

Follow steps 1 to 4 of
[Developing Tabsdata](https://github.com/tabsdata/tabsdata/blob/main/DEVELOPING.md#contents): install
the system software, clone the three repositories side by side, create the build environment and
install **tdd**. This repository is the one cloned into `tabsdata-dt`.

Run every task in this guide from `tabsdata-dt`. The tasks need only **uv** and **cargo-make**;
no virtual environment has to be active.

## 2. Install from your checkout

The **install** task builds wheels from your checkout and installs **tdd** from them, so a later
source edit takes effect only after you install again:

```bash
cargo make install
```

For development, install every environment editable from your checkout instead, so that source
edits take effect at once:

```bash
cargo make dev
```

Both install into the tdd folder, which is `~/.tdd` by default (`$HOME\.tdd` on Windows), or the folder in
the `TDD_DIR` environment variable. To install into another folder, pass it to the task, after
`--`, as every task of this repository expects its options.

macOS and Linux:

```bash
cargo make install -- --dir ~/tdd-scratch
```

Windows:

```powershell
cargo make install -- --dir $HOME\tdd-scratch
```

Remove an installation by moving its folder to the trash. The task also tells you what to stop
loading in your shell:

```bash
cargo make uninstall
```

## 3. Run the tests

The tests need an installed tdd folder (see step 2). After an editable install, they test your
source edits as they are; after a wheels install, install again first, so that the environments
carry your change.

Run every package's tests, each inside the toolset environment its code ships with:

```bash
cargo make test
```

Run what CI runs: the lint, the tests, and a check that every external program a tool declares
is on your `PATH`:

```bash
cargo make check
```

Format the code with the **ruff** version pinned in `make/requirements.txt`:

```bash
cargo make fmt
```

To run one package's tests directly, use the interpreter of its toolset.

macOS and Linux:

```bash
~/.tdd/tdd-venvs/systems/bin/python -m pytest packages/tabsdata-dev-tool-xp/src/python/test -q
```

Windows:

```powershell
& "$HOME\.tdd\tdd-venvs\systems\Scripts\python.exe" -m pytest packages\tabsdata-dev-tool-xp\src\python\test -q
```

## 4. Find your way around the tasks

| Task | What it does |
|---|---|
| `cargo make check` | Runs the lint<br>Runs the tests<br>Checks the external programs every tool needs |
| `cargo make clean` | Removes `target/wheels` and every cache |
| `cargo make dev` | Installs every environment editable from your checkout |
| `cargo make fmt` | Formats the code |
| `cargo make gen` | Regenerates the toolset packages and `catalog.json` |
| `cargo make install` | Builds the wheels<br>Installs every environment from them |
| `cargo make lint` | Checks the code with **ruff** |
| `cargo make lock` | Regenerates the lock file of every toolset |
| `cargo make test` | Runs the tests of every package |
| `cargo make uninstall` | Moves the tdd folder to the trash |
| `cargo make wheels` | Builds the wheels into `target/wheels` |

List every task, with its options:

```bash
cargo make help
```

## 5. Learn how it works

| Document | What it covers |
|---|---|
| [Tabsdata DevTools: Design](docs/DESIGN.md) | How it works and why<br>An index of every tool's design document |
| [Tabsdata DevTools: Building a Python Command](docs/building-a-python-command.md) | How to add a Python tool |
| [Tabsdata DevTools: Building a Shell Command](docs/building-a-shell-command.md) | How to add a command loaded into the shell |
| [Tabsdata DevTools: Command CLI Guidelines](docs/command-cli-guidelines.md) | The options, exit codes and output every command must have |
| [Tabsdata DevTools: Working Contract](CLAUDE.md) | The working contract and invariants for anyone, or anything, editing this repository |
