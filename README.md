<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-devtools

**One command, `tdd`, in front of every Tabsdata dev tool — each tool in its own isolated
environment, so tool dependencies never touch a project's dependencies.**

Python tools live in per-toolset virtualenvs and are dispatched into them; shell commands
(the ones that must change *your* shell, like entering a venv) are sourced functions. `tdd`
routes to whichever half owns the word. Nothing is installed globally; nothing has to be
active.

## Install

You need [`uv`](https://docs.astral.sh/uv/) and [`cargo-make`](https://github.com/sagiegurari/cargo-make).
No Python, no venv.

```bash
git clone <this repo> && cd tabsdata-devtools
cargo make install                  # builds ~/.tdd from wheels; add `-- --editable` to link this checkout
source ~/.tdd/tdd-source.sh
```

Make it permanent in **`~/.zshrc`** (not `~/.zprofile` — `tdd` is a shell function, and
functions do not survive into child shells):

```bash
echo 'source ~/.tdd/tdd-source.sh' >> ~/.zshrc
```

## Then

```bash
tdd --help        # everything there is; add --demo to see the sample commands
tdd info          # what this install is and where it lives
tdd --reqs        # external binaries the tools expect on your PATH
tdd venv --help   # managed pyenv/uv/conda venvs; also: tdd pycache --help, tdd vars --help
tdd system --help # external systems for testing (databases in docker, object stores, services)
tdd domain --help # domains inside those systems: schemas, generated data, change sets
tdd env set-crypto  # fetch TD_BACKENDS_CRYPTO_KEY from 1Password into this shell (needs `op`)
tdd defaults --command venv   # a command's option defaults: built-in vs your default-opts
```

Preset a command's options in `~/.tdd/default-opts/<command>.txt` or `<command>_<action>.txt`
(one `--name value` per line); `tdd` merges them in — what you type wins — and prints the resolved command line. Every
command takes `--help`, `--verbose` and `--format json|view`; `tdd --format json …` works too.

```bash
cargo make help   # every build task, with its options
```

`cargo make uninstall` removes `~/.tdd` again and tells you which `source` line to drop.

## Docs

| | |
|---|---|
| [docs/building-a-python-command.md](docs/building-a-python-command.md) | add a Python tool — to an existing toolset, or with a new one |
| [docs/building-a-shell-command.md](docs/building-a-shell-command.md) | add a sourced shell command |
| [docs/command-cli-guidelines.md](docs/command-cli-guidelines.md) | what every command's options, exit codes and output must look like |
| [docs/design.md](docs/design.md) | how it works and why it is shaped this way |
| [CLAUDE.md](CLAUDE.md) | the working contract and invariants for anyone (or anything) editing this repo |
