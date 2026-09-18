<!--
Copyright 2026 Tabsdata Inc.
-->

# env

`tdd env set|unset|show`: the variables tdd manages in the calling shell -- the descriptor
crypto key, the 1Password secrets, tabsdata's `TD_*` settings and the Python index variables.

- `set --crypto` evals `tdd system crypto-key --format export` (1Password; skipped when
  `_TDD_CRYPTO_KEY` is already set unless `--force`), from `--vault`/`--item`/`--field`
  (`1p:Employee`, `DevSecrets`, `TD_BACKENDS_CRYPTO_KEY`) -- or `--value KEY` sets the variable
  verbatim, at least `crypto.MIN_SECRET_LEN` characters, no 1Password and no `--force` dance.
  `set --secrets [--vault 1p:V]` (default `1p:dev_xp`) evals `tdd system secrets --format export`,
  which also writes `_TDD_SYSTEMS`, the prefix list `unset --secrets` reads back. An item of that
  vault titled `_*` is ignored -- everything swept becomes a variable in this shell, and that is
  how an item says it is somebody's note rather than a system's config.
- `--vault` is one form for both, the provider ref `1p:NAME`, and both defaults are **literals**:
  no `ONE_PASSWORD_*` variable decides which vault a key comes from. `crypto-key` names the vault
  itself, so the ref sheds its `1p:` on the way (that verb takes either spelling).
- A secret on a command line is masked wherever tdd echoes one back: `_tdd_mask_argv` (common.sh)
  blanks the value of `--value`/`--password`/`--secret`/`--token`/`--key` in the failure log's
  `command:` line and in `tdd`'s `resolved:` line. `--py-idx URL` sets `UV_INDEX`/`PIP_EXTRA_INDEX_URL` plus
  `UV_INDEX_STRATEGY=unsafe-best-match`; `--py-default-idx URL` sets `UV_DEFAULT_INDEX`/`PIP_INDEX_URL`.
- `unset --td` clears every `TD_*` variable -- tabsdata's own; none of tdd's are `TD_`.
  `--vars PREFIX` clears by prefix but never `TDD_DIR`, which `tdd` itself needs.
- **Selections combine**: `set --crypto --secrets --py-idx URL` is one call, and `unset` the
  same, so a shell is furnished or cleared in one line. Nothing reaches disk -- both fetches are
  `--format export` output eval'd here.
- `unset --py-idx` also clears the legacy `UV_EXTRA_INDEX_URL`, and `--py-default-idx` the legacy
  `UV_INDEX_URL`, so a shell that predates the rename does not keep a stale index alive;
  `--vars PREFIX` is repeatable.
- `config` (`--show`/`--default`/`--create [--force]`) comes from the shared layer, over the
  per-action defaults `tdd_defaults_env` declares -- including the two vault literals, so the
  vault a key comes from is a line in `env.toml` and never an environment variable.
- `tdd-source` loads `$TDD_DIR/tdd-source.sh` again in this shell. It is the one shell file an
  editable install does not link to the checkout -- `tdd-install` generates it -- so a reinstall
  leaves the copy an open shell already loaded, and this is how that shell catches up without a
  new terminal. The greeting the file prints on a first source is suppressed on the way through
  (`_TDD_RESOURCING`): two announcements of one thing, and in `--format json` a line that is not
  JSON.
- `show --group all|td|pypi|secrets` prints one group instead of all three (default `all`, and
  a default like any other, so `[options.show] group` sets it).
- `show` lists three sorted groups -- TD (`^TD*` plus `_TDD_CRYPTO_KEY`, and `_TDD_SYSTEMS`
  while set), PyPi, Secrets -- `- NAME` when unset; values whose name says
  PASSWORD/SECRET/TOKEN/KEY/PASS/_PAT/_PEM/PEM_ are masked unless `--reveal`, in every group (the
  TD one holds `TD_BACKENDS_CRYPTO_KEY`). A PEM earns its place there twice over: a private key
  or a pinned certificate is a credential, and either way it is unreadable in a listing.

## The PowerShell twin

`scripts/powershell/env.ps1` is the same command; two things differ in kind.

- **`export NAME=VALUE` lines are parsed, not evaluated.** `tdd-exe system ... --format export`
  prints shell syntax, which PowerShell cannot `eval` -- and would not want to: handing vault
  text to a parser is how a value becomes code. The lines are matched against
  `^export ([A-Za-z_][A-Za-z0-9_]*)=(.*)$` and the value is unquoted by a POSIX quote scanner, so
  a multi-line certificate survives the way `eval` handles it for free here.
- **Listings sort with the ordinal comparer**, not the culture's, which ignores `_` and filed
  `_TDD_SYSTEMS` among the `TD_` names. Ordinal is `LC_ALL=C sort`, which is what this half
  gets from `sort` and what makes the two agree on any machine.

`Remove-Item Env:\NAME` is the only real removal: `[Environment]::SetEnvironmentVariable($name,
$null)` converts the `$null` to an empty string on the way to a `[string]` parameter and leaves
the variable set.