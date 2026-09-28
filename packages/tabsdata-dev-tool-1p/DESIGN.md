<!--
Copyright 2026 Tabsdata Inc.
-->

# _1p

What tdd fetches from and pushes to 1Password:

- `tdd _1p fetch [--crypto [1p:VAULT] [--item ITEM] [--field FIELD]] [--secrets [1p:VAULT]]
  [--format export|view|json]`: the descriptor crypto key and/or a shared vault's secrets, by
  default printed as `export` lines -- the outcome of the command -- for `tdd env set
  --crypto/--secrets` to apply. `view` names what was fetched without the values; `json`
  carries them (`values`).
- `tdd _1p push --vault 1p:VAULT --entry PATH|-`: file one item in a vault, replacing what is
  filed under its title -- the item `tdd system 1p-template` or `tdd system info --format 1p`
  writes, or a whole `op item get --format=json`.

## Shape

- Toolset `launchers`: it needs common-core only; depends on `deps-launchers`, `common-core`.
  Entry point `_1p = tabsdata_dev.tool.onepassword:main` (a module cannot start with a digit).
- `bin-reqs`: `op`, whose sign-in is the credential. The leading `_` makes it plumbing: out of
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
