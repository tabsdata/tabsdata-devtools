<!--
Copyright 2026 Tabsdata Inc.
-->

# _xp-execute

`tdd _xp-execute SCRIPT ARGS...`: run an xp suite's check script with the `tdd` module in reach
(`from tdd import tdd`). Plumbing (the leading `_`), driven by xp's `execute` stage.

## Shape

- Toolset `xp-execute`, its own; depends on `deps-xp-execute` (nothing but pytest) and
  `common-core`. `launcher = true`: every argument is the script's, so no options and no config.
- `tdd.py`, a resource of the package: `tdd(*args, out=None, check=True)` runs `tdd-exe ARGS`,
  returns its stdout (or writes it to `out`) and raises `TddError` -- status and output --
  when it fails. Standard library only (a test checks), since it runs in whatever venv a
  script asked for.

## Decisions

- **A venv of its own, bare.** A check script reaches every tool through `tdd` -- `tdd tdk`,
  `tdd pqt`, `tdd jq` -- so it needs none of xp's pins, and running it on xp's venv (as it did)
  made xp's dependencies the scripts' too. tdd-install builds this toolset like any other.
- **Libraries come per entry, in a one-off venv.** An execute entry's `requirements` (`[{name,
  version?}]`, an exact pin when a version is given) get a venv made for that run by `tdd _venv
  create --type uv`, named `tdd-xp-execute-<run>-<entry>`; xp installs them with `uv pip
  install` and names the venv to this tool in `_TDD_XP_EXECUTE_VENV`, which copies `tdd.py` into
  its site-packages and runs the script on its python. xp deletes it after the step, passed or
  failed; the prefix is what finds a killed run's leftovers (`tdd venv list`). Rejected: growing
  this toolset a pin per script -- every script's library in every script's venv.
- **`import tdd` is a top-level module**, the one exception to the `tabsdata_dev` namespace:
  the name a script author types, and it is never installed as a package -- put on
  PYTHONPATH here, copied into a one-off venv there. It is found with importlib.resources, so it
  works the same in an editable and a wheel install.
- A non-zero exit is one error event carrying `status`; the script's own output is untouched.
