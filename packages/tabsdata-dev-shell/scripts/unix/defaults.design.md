<!--
Copyright 2026 Tabsdata Inc.
-->

# defaults

`tdd defaults [--command <name>]`: what `default-opts/` adds to a command -- its built-in option
values in white against the user's customizations in blue, grouped by action, with the file each
came from -- plus an audit of the directory (files without `.txt`, files naming no command or
action, lines carrying two options), so a preset that silently does nothing gets noticed.

- Built-ins come from `tdd_defaults_<name>()` for shell commands (`sub|--option|value` lines);
  a Python tool's live in argparse, so only its customized file is shown.
- The merge itself is `tdd-exe --defaults` (stdlib, unit-tested); this command only explains it.
