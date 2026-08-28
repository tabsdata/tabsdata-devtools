<!--
Copyright 2026 Tabsdata Inc.
-->

# Building a shell command

A shell command is a function sourced into the caller's shell. Write one only for what an
executable fundamentally cannot do: change the current shell — enter or leave a venv, `cd`,
export a variable. Anything else is a Python command; it gets a real environment, real tests,
and does not have to be written for bash 3.2.

Each command is one file under `packages/tabsdata-dev-shell/scripts/unix/`, sourced by
`tdd-source.sh` at shell start-up. Copy `demo-fn1.sh`. Its options, exit codes and output
follow [command-cli-guidelines.md](command-cli-guidelines.md).

## 1. Register and define

```sh
#
# Copyright 2026 Tabsdata Inc.
#

# Why this is a shell command and not a Python tool, in a sentence.

tdd_fn_register gitroot "cd to the top of the current git checkout"

tddfn_gitroot() {
    _tdd_top="$(git rev-parse --show-toplevel)" || return 1
    cd "$_tdd_top" || return 1
    unset _tdd_top
    pwd
}
```

Two conventions, both checked by the shell package's tests: `tdd_fn_register <name> "<summary>"`
and a matching `tddfn_<name>()`. The name is the word after `tdd`; it may contain hyphens and
must not collide with a Python tool or a builtin (`list`, `doctor`, `info`, `help`) — the
generator rejects the collision. The summary must not contain `|`: the registry is
pipe-delimited and would truncate it.

Register with `--demo` — `tdd_fn_register --demo <name> "..."` — for a sample that should stay
out of `tdd help` unless `--demo` is passed. It still runs.

A file may register several commands; a group with sub-words is a single command that routes
on `$1` — see `tdd-env.sh`, which handles `activate --toolset <ts>` and `deactivate`.

## 2. Declare external binaries

If the function calls anything beyond shell builtins and the tdd envs, list it in
`<file>.bin-reqs.txt` beside the script, one bare name per line, `#` comments allowed. The
file applies to every command the script registers. Omit it if there is nothing to declare.

```
# gitroot.bin-reqs.txt -- external binaries gitroot needs on PATH.
git
```

The loader reads it while sourcing and stores the names in the registry; `tdd-fn` checks each
with `command -v` **before running the command** and refuses with the full list (exit 127) if
any is missing. `tdd --reqs` reports every declaration as `[ok]`/`[missing]` — shell commands
are marked `(shell)` — and `cargo make check` fails on a missing one. Sourcing itself never
fails: a missing binary must not break every shell that sources `tdd-source.sh`.

## 3. Write for both shells

`tdd-source.sh` and every command run unmodified in **bash 3.2** (macOS `/bin/bash`) and
**zsh**. In practice:

- No arrays, no associative arrays, no `local`-only idioms that differ, no `[[ ]]`-specific
  features you cannot do with `[ ]`, no process substitution.
- Prefix temporaries with `_tdd_` and `unset` them before returning — a sourced function's
  variables leak into the user's shell.
- Quote every expansion. zsh does not word-split an unquoted parameter, so `cmd $args`
  passes one word there and several in bash; build single tokens (`--dir=$x`) or use `"$@"`.
- Write errors to `>&2` and `return` a code; never `exit`, which would close the user's shell.
- Use `$TDD_DIR` for the tdd dir. It is exported by `tdd-source.sh` and follows the tree if
  the dir is moved.

## 4. Test and run

The shell package's tests (`packages/tabsdata-dev-shell/src/python/test/test_shell.py`)
check the conventions above statically: every file registers something, every registered name
has its `tddfn_`, no `|` in summaries, every `*.bin-reqs.txt` sits beside a script, and the
demo commands use what they declare. Add a case for your command if it has structure worth
pinning down. `cargo make test` runs them.

Scripts are read from the shells env, which in an editable install links this checkout — so a
saved edit is live for the next shell that sources `tdd-source.sh`. In the shell you already
have, re-source it:

```bash
source ~/.tdd/tdd-source.sh
tdd gitroot
tdd --reqs gitroot
```

Adding or renaming a file also needs `cargo make gen` (or any `cargo make install`) so the
catalog — which `tdd --reqs` and the collision check read — knows about it. In a wheels-mode
install, scripts are frozen into the `tabsdata-dev-shell` wheel and need a rebuild.
