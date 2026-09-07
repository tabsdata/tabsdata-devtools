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
git clone git@github.com:tabsdata/tabsdata-dt.git && cd tabsdata-dt
./install.sh 
source ~/.tdd/tdd-source.sh
echo '' >> ~/.zshrc
echo '#Tabsdata DevTools' >> ~/.zshrc
echo 'source ~/.tdd/tdd-source.sh' >> ~/.zshrc
echo '' >> ~/.zshrc
```

## Then

```bash
tdd --help
```

Smoke test scripts using `tdd`:

```bash
scripts/tabsdata-km-smoke.sh --help   # fresh venv + tabsdata + tdkserver + xp suites, end to end
scripts/tabsdata-eks-smoke.sh --help  # the same run against an EKS cluster (rds/s3 domains, port-forward)
cargo make help         # every build task; `cargo make uninstall` removes ~/.tdd
```

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
