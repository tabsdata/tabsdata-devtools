<!--
Copyright 2026 Tabsdata Inc.
-->

# mexe

`tdd mexe --dirs DIR[,DIR...] [--execution parallel|serial] [--on-error continue|abort]
[--output immediate|on-completion] [--] COMMAND [ARG...]`: run the same command in several
directories -- `git status` across checkouts, `"uv sync && pytest"` across packages -- with
every output line prefixed `[DIR]`.

## Shape

- Toolset `launchers`: no third-party package needed; depends on `deps-launchers`,
  `common-core`. Entry point `mexe = ...:main`. No `bin-reqs.txt` (see below).
- State: `<tdd_dir>/mexe.toml`, the `config` action's, from the shared layer -- `--dirs` can be
  preset there like any option.

## How it works

- **Everything after mexe's options is the command**, its own options included (`git log
  --oneline -3`, no quotes), so mexe's options come first; `--` ends them explicitly. Several
  words are one command, each quoted for the shell that runs it (`shlex.join`; single quotes and
  `&` for pwsh) so `-m "a message"` stays one argument. **One argument is a shell line**, kept
  verbatim: quoting is how a pipe, a redirection, `&&` or `;` gets past the calling shell.
- **The shell is the family, not the OS**: `pwsh -NoProfile -NonInteractive -Command` when the
  PowerShell loader exported `_TDD_SHELL_FAMILY=powershell` (macOS, Linux or Windows) or on
  Windows with no family exported, else `$SHELL -c`, else `sh -c`. No rc file or profile on
  either side: a command meant for several directories must not depend on the interactive setup.
  pwsh's command is prefixed with `[Console]::OutputEncoding = UTF8`: on Windows it writes a pipe
  in the console code page, and the runner reads UTF-8.
- **The environment is the caller's, minus tdd's own venv**: the toolset `bin/` the dispatcher put
  first comes back off PATH and `_TDD_TOOL` is dropped, so `python` is the user's. The venv the
  launchers would pick -- the last activated, managed or not (`managedvenv.select`), so `tdd mexe
  -- tdd tdk` runs where `tdd tdk` would -- goes first on PATH as activation puts it -- `bin/`,
  `Scripts\` for a venv built on Windows, conda's three directories there -- with `VIRTUAL_ENV`
  or `CONDA_PREFIX`. A named venv that cannot be resolved is an error, not a silent fallback.
- **Output lines go to stdout**: in view each `[DIR] line` is written there as it arrives, so
  `tdd mexe ... | grep` sees it; progress, per-dir failures and the summary stay events. In json
  they are `info` events (`dir`, `line` fields; the `ok`/`error` carries per-dir status, exit
  code, failed command, seconds). stderr is merged into stdout per directory, keeping its order
  and never leaving a pipe unread; stdin is `/dev/null`, since parallel commands cannot share a terminal.
- **The run is `batch.execute`, streamed** (no `spawn`): one task per directory, its `cwd` the
  directory, `heaviest_first=False` so `serial` is the order given, `workers` 1 for `serial` and
  `TDD_PARALLELISM` (default 10) for `parallel`, `kill_on_fail` for `--on-error abort`, and a
  `Reporter` subclass for the `[DIR]` rows. `final=False`: mexe writes its own summary.
  `on-completion` prints a directory's lines as one uninterrupted block when it finishes.

## Decisions

- **A Python tool, not a shell command**: it changes nothing in the calling shell, and one
  implementation serves both families -- the family only picks which shell runs the commands.
- **The shell is not declared in bin-reqs and not run through `proc.run`**: it is the one the
  user is in, known only at run time, and bin-reqs names a fixed binary. It cannot be missing.
- **The runner is common-core's, not mexe's own** (user decision: "extend batch.execute and use
  it in mexe"). mexe first carried its own threads because `batch.execute` could only collect a
  child's output at its end, could not stop a running child, and reordered by weight; batch
  gained a streamed mode, `kill_on_fail`, `heaviest_first`, `workers` and a `Reporter`, and the
  `spawn` path system/domain use is unchanged.
- **A streamed child is a tree, stopped as one** (`batch.Tree`), so `--on-error abort` kills the
  whole pipeline: killing only the shell of `a | b` orphans `a` and `b`, which keep the pipe open
  and the reader waiting. POSIX: a session of its own, the group sent SIGTERM, SIGKILL 5s later.
  Windows: a job object (ctypes, kernel32 -- no `taskkill`, which would be an undeclared binary),
  terminated. The cost is that Ctrl-C no longer reaches the children, so the batch joins its
  threads with a timeout, catches it and stops every tree. Untested on Windows so far.
- **In view the output lines bypass the renderer**, the one place mexe prints: the commands'
  output is the result, and the result belongs on stdout, but the renderer keeps stdout for the
  single `ok`, which would hold every line until the end. Same standing as a launcher passing its
  program's output through. Rejected: an `info` on stderr (a pipe sees nothing) and a stdout
  flag on the shared renderer (a contract change in both twins for one tool).
- **Words, not one quoted argument per command** (user decision: "if doing a single one, even
  with options, it should be desired not to use \"\""). It replaced COMMAND [COMMAND...], each
  argument its own shell run: that forced quotes on every command with an argument, and
  several commands in sequence are `"a && b"` anyway. The word/line split is by count, the one
  signal left once the caller's shell has removed the quotes.
- **tdd's presets would land inside the command.** `tdd` appends `mexe.toml`'s `[options]` to
  the argument list, which after a free-form command is the command's. Two fixes: tdd's merge
  now puts defaults before a `--` and does not count names after it as typed (a generic rule:
  after `--` nothing is an option); without `--`, mexe peels off exactly the tokens tdd appended,
  from the end in the table's order (`split_presets`). The residue: a command whose own options
  share mexe's names (`git log --output x`) makes tdd think `--output` was typed and skip that
  preset -- `--` avoids it. Under PowerShell a bare `--` never arrives: pwsh's binder takes it
  as its own end-of-parameters for any function, `tdd` included, so there it is typed `'--'`. `--dirs` is not `required=True` for the same reason: a preset one
  arrives after the command.
- **Every directory is checked before anything runs**: a typo found after half the directories
  ran leaves half a run to undo.
