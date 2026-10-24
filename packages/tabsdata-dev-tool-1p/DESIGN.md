<!--
Copyright 2026 Tabsdata Inc.
-->

# _1p

What tdd fetches from and pushes to 1Password:

- `tdd _1p fetch [--crypto [1p:VAULT] [--item ITEM] [--field FIELD]] [--secrets [1p:VAULT]]
  [--pypi-twine [1p:VAULT]] [--platform macos|linux|windows] [--format export|github|view|json]
  [--device console|file]`: the descriptor crypto key, a shared vault's secrets and/or the PyPI
  upload credentials, by default printed as an export -- the outcome of the command -- written
  for `--platform`: `export` lines on macos (the default) and linux, for
  `tdd env set --crypto/--secrets/--pypi-twine` to apply; on windows a PowerShell file of `$env:`
  lines. `github` prints them as a GitHub Actions step appends them to `$GITHUB_ENV`, every value
  masked out of the job log first. `view` names what was fetched without the values; `json`
  carries them (`values`). `--device file` writes the outcome to a new file in the system temp
  folder and prints its path instead.
- **Windows has no 1Password.** An operator exports there from a Mac --
  `tdd _1p fetch --crypto --secrets 1p:VAULT --platform windows > secrets.ps1` -- carries the
  file over, loads it into the PowerShell 7 session (`. .\secrets.ps1`) and deletes it: it holds
  the values in clear. The values are PowerShell single-quoted strings, so nothing in them expands
  and a PEM keeps its lines; `op` is optional everywhere, and a read without it says this.
- `tdd _1p push --vault 1p:VAULT --entry PATH|-`: file one item in a vault, replacing what is
  filed under its title -- the item `tdd system 1p-template` or `tdd system info --format 1p`
  writes, or a whole `op item get --format=json`.

## Shape

- Toolset `launchers`: it needs common-core only; depends on `deps-launchers`, `common-core`.
  Entry point `_1p = tabsdata_dev.tool.onepassword:main` (a module cannot start with a digit).
- `bin-reqs`: `op`, optional like everywhere -- each read checks it and says what to do without
  it -- whose sign-in is the credential. The leading `_` makes it plumbing: out of
  `tdd help`, listed by `tdd -x`.

## Decisions

- **Its own tool, not two `system` verbs.** It was `tdd system crypto-key` and `tdd system
  secrets` until 2026-09-28, and neither had anything to do with a system: the key opens every
  descriptor and the secrets are what `system create` later reads, but fetching them touches no
  store and no backend. Being `system` verbs put them in the `systems` toolset -- every SQL
  driver in the shop -- for two `op` calls, and made `tdd env` depend on the heaviest env there
  is. The providers were already in common-core (`secrets`, `secrets_1p`); this tool is a thin
  command over them in the lightest toolset.
- **One call for both.** `env set --crypto --secrets` was two child processes; `fetch` takes
  both and prints one set of lines, the key first.
- **Provider refs everywhere.** `--crypto`, `--secrets` and `push --vault` take `1p:VAULT` (the
  old verbs took a bare vault; `push` refuses any provider but `1p`, the only one that files).
  Given alone, `--crypto` reads `1p:Employee` -- the vault every user has -- and `--secrets`
  `1p:dev_xp`, the team's; literals, never a variable of the environment. They are the same two
  `tdd env` keeps in `env.toml`, which a test holds in step. `--item`/`--field` say where in the
  vault the key is and default to `DevSecrets`/`TD_BACKENDS_CRYPTO_KEY`.
- **`--pypi-twine` renames on the way out.** The upload credentials sit in the crypto key's item,
  `DevSecrets`, as `PYPI_TWINE_USERNAME`/`PYPI_TWINE_PASSWORD`; `fetch` exports them as
  `TWINE_USERNAME`/`TWINE_PASSWORD`, the names twine reads, so the mapping is in one place
  (`TWINE_FIELDS`) and `env` in both shells only applies lines. Given alone it reads
  `1p:Employee`, the crypto key's vault; the item is fixed -- `--item`/`--field` say where the
  crypto key is, and stay that.
- **`export` is a `--format`, and `fetch`'s default.** The lines to eval are what the command
  is for, so they are the outcome with no flag; `common.core.cli.run(formats=...)` lets a
  command add a format it renders itself beside `json`/`view`. `view` is for a person at a
  terminal and never shows a value; `json` is asked for by a program and carries them. `push`
  has nothing to export: it reads the default as `view` and does not offer `export`.
- **The key is checked here.** One shorter than `secrets.CRYPTO_KEY_MIN_LEN` is refused with
  where it came from, not left to fail at the first descriptor it cannot open; the value is
  never in the message. `common.systems.crypto` and both `env` scripts use the same number.
- **The values are the output.** The ok event's message is the export lines, in JSON too --
  that is what the command is for, and only `env` runs it, into `$(...)`, never a log.
- **`github` is the CI loader (2026-10-24).** GitHub Actions caps the secrets a workflow can
  carry, so a run fetches its own from 1Password with a service account token
  (`OP_SERVICE_ACCOUNT_TOKEN`, which `op` reads on its own: this tool reads no `OP_*` variable
  and never signs in). The step is one redirect, `tdd _1p fetch --crypto 1p:dev_xp --item Tabsdata --secrets
  --format github >> "$GITHUB_ENV"`: stdout is the `$GITHUB_ENV` lines alone, every variable in
  the delimiter form (`NAME<<ghadelimiter_<uuid>`, the value, the delimiter), the one syntax
  that carries a PEM as well as a word with no quoting rules and no delimiter a value can
  contain. The masks (`::add-mask::`, one per non-empty line of every value, since GitHub masks
  only the exact string it is given) and the names summary are info events, which `view`
  renders on stderr -- the runner reads workflow commands on stderr exactly as on stdout
  (`actions/runner`, `OutputManager.OnDataReceived`, one handler for both streams), and they go
  out before the values so nothing can show them. `_TDD_SYSTEMS` stays unmasked: it is no
  secret, and masking `PG S3` would hide those words everywhere in the log. `--platform` means
  nothing here; the file syntax is the runner's.
- **`--device` says where the outcome goes (2026-10-24).** `console`, the default of every
  format, prints it as it always has; `file` writes the same content to a new file in the
  system temp folder (`tdd-1p-*.sh|.ps1|.env|.json|.txt` by format, mkstemp's 0600, never a
  name to guess or reuse) and prints that path as the outcome (`path` in JSON). It holds the
  values in clear, so the caller deletes it once applied; the values never reach the console.
  Rendering is a switch on the format and, inside each, on the device: one return per leaf.
- **`push` is `system 1p-set`, moved (2026-09-28).** Filing an item touches no system; the
  item's shape does (`common.systems.onepassword` builds it from a backend), so `1p-template`
  stays in `system` and pipes into `_1p push`. Named for what it does against `fetch`. Always a delete then a create (`secrets_1p.set_item`): `op
  item create` files a *second* item under a title that already exists, and a vault with two
  `S3` items reads back a coin toss; what it replaces stays in Recently Deleted for 30 days. The
  item is piped to `op` (`item create -`), so it reaches it through neither argv nor a file, and
  is refused before the delete if it is not an item (no `title`/`category`/`fields`). What is
  uploaded is those three keys and no field `reference` (`secrets_1p.for_upload`), so a whole
  `op item get --format=json` can be handed straight back -- the rest describes the item it was
  read from.
