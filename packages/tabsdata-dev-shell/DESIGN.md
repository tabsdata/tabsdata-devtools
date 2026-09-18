<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-shell

The sourced half, in two shell families: `tddsrc.sh` and `tddsrc.ps1`, the templates
`tdd-install` bakes into `<tdd_dir>/tdd-source.sh` and `<tdd_dir>/tdd-source.ps1`, and one script
per command per family under `scripts/unix/` (POSIX sh) and `scripts/powershell/` (PowerShell 7).
Shell commands exist only for what an executable cannot do -- change the calling shell (venvs,
variables, prompt).

A family is the shell the user is in, not the operating system they are on: pwsh runs on macOS,
Linux and Windows, so both families are every developer's. Both loaders are written into every
tdd dir, always, because which shell someone will open is not the installer's to guess.

## Shape

- No Python logic: `tabsdata_dev.shell` only locates the shell files (`scripts_dir(family)`,
  `source_template(family)`), which sit at the package root in an editable install and beside the
  module in a wheel. Installed into `<tdd_dir>/tdd-venvs/shells`.
- Each command: `<name>.sh` (registers with `tdd_fn_register`, defines `tddfn_<name>`, declares
  `tdd_defaults_<name>`, which is also the `config` action's template), optional
  `<name>.bin-reqs.txt`, and `<name>.design.md`. Help is one document per subcommand as well as
  one for the command, since `-h` after a subcommand word answers about that subcommand -- which
  is what lets the listing be one line each, as argparse's is.
- `common.sh` is the shared layer every command sources through `$_TDD_COMMON_SH`: option
  parsing, the event model rendered with `jq`, colours, the failure log, `_tdd_help_text`
  (argparse's page, laid out and painted -- `positional arguments:` with the subcommands
  nested under `SUBCOMMAND`, then `options:` with the three every command shares supplied), `_tdd_ps1_wrap` (prompt colours), and the `config` action
  (`_tdd_config_action`), whose `--show` paints every row the way `common.core.config.show` does.
  `common.bin-reqs.txt` (`jq`, `awk`) is folded into every command's requirements.
- `common.ps1` is the same layer for PowerShell, function for function and name for name, and is
  what a `.ps1` dot-sources through `$env:_TDD_COMMON_PS1`. It needs **no** external binary:
  `ConvertTo-Json` builds the events and the help layout is written out rather than handed to
  awk, so there is no `common.bin-reqs.txt` beside it -- which is the whole of the difference
  between the two families' requirements. A command's own `bin-reqs.txt` is identical in both,
  because what it shells out to is the command's business, not the shell's.

## How it works

- `tdd -h` is the front door's own help, built here rather than by `tdd-exe`, and laid out by
  `_tdd_help_text` like every command's: the commands, then `options:` (`--dir`, `--version`,
  `--reqs`, plus the three the engine supplies for everyone). Nothing about a command's config
  file: `config` is an action each command has, not one the front door takes.
  `tdd --help full` prints that page and then every command's, skipping the launchers, which
  own no options and would hand the `-h` to the program they run; which those are comes from
  the catalog, never from a list kept here.
  Going through the engine rather than painting by hand is what keeps the front door from
  looking like a different program; it is **printed, never captured**, since `[ -t 1 ]` inside a
  `$(...)` sees the capture pipe. The options block matters at all because the front door is a
  shell function -- nothing else documents what it takes before the command word.
- `tdd-source.sh` locates itself (so `TDD_DIR` follows a moved dir), loads `common.sh`, sources
  every command file and builds a `name|summary|kind|reqs` registry -- a string, so bash 3.2 and
  zsh both work; summaries may not contain `|`. Sourcing never fails and checks nothing; in an
  interactive shell it ends with `tdd <version> installed at <dir> -- tdd -h for help`, a blank
  line either side (silent otherwise:
  scp/rsync over ssh read the rc too).
- The `tdd` function routes: registry hit -> `tdd-fn` (checks the command's bin-reqs first,
  `--help` excepted), else `tdd-exe` through a wrapper that keeps that env off `PATH`. It applies
  `<tdd_dir>/<command>.toml` via `tdd-exe --defaults`, warns off and unsets a `_TDD_TOOL` found in the shell,
  and recomputes `_TDD_COMMON_SH` when `--dir`/`TDD_DIR` changed.
- Aliases: sourcing also defines the aliases section -- currently `gsx` for `tdd gsx` -- as
  functions, since a shell alias is not expanded in a non-interactive shell; the command keeps
  every option, default and event.
- Prompt: sourcing puts a red `* ` first (replacing the marker of an earlier source, remembered
  in `_TDD_PROMPT_MARK`); `venv` inserts its green `(<type>/<python>/<name>)` after it.
- Everything runs unmodified in bash 3.2 and zsh: no arrays, quoted expansions, `_tdd_`
  temporaries unset before return, `return` never `exit`, and `${var}` braces wherever text
  follows a variable -- `$var[options]` is an array subscript in zsh, and a bad one is a fatal
  "bad math expression".
- **PowerShell: status never travels as a return value.** Everything a function writes to the
  success stream *is* its return value there, so a `return 1` beside an ok message would put a
  stray `1` in the caller's output, and `$x = tdd venv list` would swallow the message with it.
  The ok message is the only thing on that stream; status goes in `$_TDD_RC`, which the
  dispatcher copies to `$LASTEXITCODE` on the way out, and a call site reads through
  `_tdd_failed`. Everything else that differs is platform, not shell: `Join-Path` rather than
  `/`, `[IO.Path]::PathSeparator` rather than `:`, and `_tdd_venv_bin`/`_tdd_venv_exe` for a
  venv's executables, since Windows keeps them in `Scripts\` and calls the interpreter
  `python.exe`. Those two helpers ask the venv rather than the platform, so a tdd dir built under
  WSL and opened from Windows still finds what is actually there.
- The prompt differs in kind, not in intent: a POSIX shell edits `PS1` as a string, PowerShell
  redefines a `prompt` function. So the loader keeps the session's own prompt in
  `_TDD_PROMPT_ORIGINAL` and wraps it, restoring before re-wrapping when the file is loaded
  again -- the same thing `PS1="${PS1/"$_TDD_PROMPT_MARK"/}"` does on the other side.
- The generator holds the families to each other: the same commands, with the same summaries
  (`discover.shell_commands`), because `tdd help` has to read the same in either shell. The
  catalog records each family's file and requirements separately, and `tdd --reqs` checks the
  family named by `_TDD_SHELL_FAMILY`, which each loader exports.
- A colour is decided where fd 1 is still the command's stdout: inside `$(...)` it is the capture
  pipe, so `[ -t 1 ]` there always says "no terminal". `_tdd_color` therefore takes the answer as
  an argument.
- `tddsrc.sh` is not live in an editable install (it is copied at install); the command files are.
