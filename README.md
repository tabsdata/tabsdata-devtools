<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-devtools

**One command, `tdd`, in front of every Tabsdata dev tool -- each tool in its own isolated
environment, so tool dependencies never touch a project's dependencies.**

Python tools live in per-toolset virtualenvs and are dispatched into them; shell commands (the
ones that must change *your* shell, like entering a venv) are sourced functions. `tdd` routes to
whichever half owns the word. Nothing is installed globally; nothing has to be active.

## Install

You need [`uv`](https://docs.astral.sh/uv/) and [`cargo-make`](https://github.com/sagiegurari/cargo-make);
no Python, no venv.

```bash
git clone <this repo> && cd tabsdata-devtools
./install.sh                  # builds ~/.tdd and writes every command's config file
cargo make install                  # the envs only; `-- --editable` links this checkout
source ~/.tdd/tdd-source.sh
echo 'source ~/.tdd/tdd-source.sh' >> ~/.zshrc   # .zshrc, not .zprofile: tdd is a shell function
```

## Then

```bash
tdd --help              # everything there is; tdd info, tdd doctor, tdd --reqs
tdd venv --help         # managed pyenv/uv/conda venvs; activation exports _TDD_VENV
tdd env --help          # this shell's variables: crypto key and secrets from 1Password, TD_*, Python indexes
tdd system --help       # external systems for testing: databases in docker, object stores, services
tdd domain --help       # domains inside those systems: schemas, generated data, change sets
tdd tdk --help          # run tabsdata's tdk (also tdkserver, km) inside the venv _TDD_VENV names
tdd xp --help           # the bundled tabsdata example suites: list-suites, one-shot --suite <type>/<name>
tdd pycache --help      # purge tabsdata from the uv/pip caches
tdd venv config --show       # a command's option defaults: built-in vs yours
scripts/tabsdata-km-smoke.sh --help   # fresh venv + tabsdata + tdkserver + xp suites, end to end
scripts/tabsdata-eks-smoke.sh --help  # the same run against an EKS cluster (rds/s3 domains, port-forward)
cargo make help         # every build task; `cargo make uninstall` removes ~/.tdd
```

Preset a command's options in `~/.tdd/<command>.toml` (`[options]`, or `[options.<action>]`)
(one `--name value` per line); what you type wins. Every command takes `--help`, `--verbose` and
`--format json|view`.

## Tests

```bash
cargo make test          # every package's tests, each inside the toolset venv its code ships with
cargo make check         # what CI runs: ruff lint + tests + `tdd --reqs` (fails on a missing declared binary)
cargo make fmt           # ruff format, at the version pinned in Makefile.toml
```

Both need an initialized tdd dir (`cargo make install` or `dev`; `~/.tdd` unless `TDD_DIR` or
`-- --dir PATH` says otherwise). In an editable install (`cargo make dev`) source edits are
tested live; in a wheels install run `cargo make install` first so the envs carry the change.
To run one package's tests directly, use its toolset's interpreter, e.g.
`~/.tdd/tdd-venvs/systems/bin/python -m pytest packages/tabsdata-dev-tool-xp/src/python/test -q`.

## Docs

| | |
|---|---|
| [docs/design.md](docs/DESIGN.md) | how it works and why, with an index of every tool's design doc |
| [docs/building-a-python-command.md](docs/building-a-python-command.md) | add a Python tool |
| [docs/building-a-shell-command.md](docs/building-a-shell-command.md) | add a sourced shell command |
| [docs/command-cli-guidelines.md](docs/command-cli-guidelines.md) | options, exit codes and output every command must have |
| [CLAUDE.md](CLAUDE.md) | the working contract and invariants for anyone (or anything) editing this repo |
