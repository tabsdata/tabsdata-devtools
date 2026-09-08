<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-shell

The sourced half: `tddsrc.sh`, the template `tdd-install` bakes into `<tdd_dir>/tdd-source.sh`,
and one script per shell command under `scripts/unix/`. Shell commands exist only for what an
executable cannot do -- change the calling shell (venvs, variables, prompt).

## Shape

- No Python logic: `tabsdata_dev.shell` only locates the shell files (`scripts_dir()`,
  `source_template()`), which sit at the package root in an editable install and beside the
  module in a wheel. Installed into `<tdd_dir>/tdd-venvs/shells`.
- Each command: `<name>.sh` (registers with `tdd_fn_register`, defines `tddfn_<name>`, declares
  `tdd_defaults_<name>`, which is also the `config` action's template), optional
  `<name>.bin-reqs.txt`, and `<name>.design.md`.
- `common.sh` is the shared layer every command sources through `$_TDD_COMMON_SH`: option
  parsing, the event model rendered with `jq`, colours, the failure log, `_tdd_help_text`
  (argparse-layout help), `_tdd_ps1_wrap` (prompt colours), and the `config` action
  (`_tdd_config_action`), whose `--show` paints every row the way `common.core.config.show` does.
  `common.bin-reqs.txt` (`jq`, `awk`) is folded into every command's requirements.

## How it works

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
- A colour is decided where fd 1 is still the command's stdout: inside `$(...)` it is the capture
  pipe, so `[ -t 1 ]` there always says "no terminal". `_tdd_color` therefore takes the answer as
  an argument.
- `tddsrc.sh` is not live in an editable install (it is copied at install); the command files are.
