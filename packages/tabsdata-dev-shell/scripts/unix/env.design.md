<!--
Copyright 2026 Tabsdata Inc.
-->

# env

`tdd env set|unset|show`: the variables tdd manages in the calling shell -- the descriptor
crypto key, the 1Password secrets, tabsdata's `TD_*` settings and the Python index variables.

- `set --crypto` and `set --secrets` read 1Password through **one** `tdd _1p fetch` and eval its
  export lines here (in PowerShell, parse them). `--crypto` passes `--crypto=VAULT` and any
  `--item`/`--field` (defaults `1p:Employee`, and `_1p`'s own `DevSecrets`,
  `TD_BACKENDS_CRYPTO_KEY`); it is skipped when `_TDD_CRYPTO_KEY` is already set unless
  `--force` -- or `--value KEY` sets the variable verbatim, at least `CRYPTO_KEY_MIN_LEN`
  characters (common-core's `secrets`), no 1Password and no `--force` dance. `--secrets` passes
  `--secrets=VAULT` (default `1p:dev_xp`); the lines include `_TDD_SYSTEMS`, the prefix list
  `unset --secrets` reads back. An item of that vault titled `_*` is ignored -- everything swept
  becomes a variable in this shell, and that is how an item says it is somebody's note rather
  than a system's config. Until 2026-09-28 these were two `system` verbs (`crypto-key`,
  `secrets`), two child processes in the `systems` env; see the `_1p` design doc.
- `set --pypi-twine` is the third 1Password selection, in the same one fetch: `_1p fetch
  --pypi-twine=VAULT` (default the crypto key's vault, `1p:Employee`) reads the fields
  `PYPI_TWINE_USERNAME` and `PYPI_TWINE_PASSWORD` of `DevSecrets` and prints them as
  `TWINE_USERNAME`/`TWINE_PASSWORD`, the names `twine upload` reads -- the rename lives in `_1p`,
  so this half only applies lines. Unlike `--crypto` it is fetched every time: nothing else in
  tdd needs the variables, so there is no "already set" to save a trip for. `unset --pypi-twine`
  removes both; `show` lists them in the PyPi group, the password masked by name.
- `--vault` is one form for every selection, the provider ref `1p:NAME`, and the defaults are **literals**:
  no `ONE_PASSWORD_*` variable decides which vault a key comes from. `_1p fetch` takes the ref
  as it is, for both.
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

## Index markers

`--py-idx` and `--py-default-idx` take `@dev` (`https://d3mm0r95u5i3hf.cloudfront.net/simple/`),
`@dev:NAME` (`.../NAME/`, the namespace `tdd pypi push --lane staging --at NAME` publishes),
`@local[::PORT][:NAME]` (`http://localhost:PORT/NAME/`, `tdd pypi serve [--port PORT] [--at
NAME]` on this machine, PORT 8000 and NAME `simple` when left out) and `@prod`
(`https://pypi.tabsdata.com/simple/`) as well as a URL. A NAME push would refuse is refused here
too, and so is a NAME or PORT written empty (`@dev:`, `@local::`). Resolved by
`_tdd_resolve_index` in the shared layer so every option that takes an index URL takes them --
the smoke scripts' `--uv-index` does the same from their own engine, and a test holds the two
definitions in step. An unknown `@marker` is refused rather than exported: passed on, it would
reach uv or pip as a URL and fail in a message about a package, not about the option that set it.

The resolver sets `_TDD_INDEX_RESOLVED` rather than printing the value, because in
`--format json` an error event goes to stdout and a `$(...)` around a printing helper would
capture the event instead of the value.

**In PowerShell a marker must be quoted.** `--py-idx @dev` typed bare is splatting syntax: it
expands an undefined `$dev` and arrives as no argument at all, so the value is empty and nothing
warns. An empty value is therefore refused in both halves, and the PowerShell one says why and
shows `--py-idx '@dev'`.

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