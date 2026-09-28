<!--
Copyright 2026 Tabsdata Inc.
-->

# _1p

`tdd _1p fetch [--crypto 1p:VAULT [--item ITEM] [--field FIELD]] [--secrets 1p:VAULT]`: read
the descriptor crypto key and/or a shared vault's secrets from 1Password and print them as
`export` lines -- the outcome of the command -- for `tdd env set --crypto/--secrets` to apply.

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
- **Provider refs everywhere.** `--crypto` takes `1p:VAULT` like `--secrets` (the old verb took
  a bare vault and stripped a `1p:` it was handed); `--item`/`--field` say where in the vault
  the key is and default to `DevSecrets`/`TD_BACKENDS_CRYPTO_KEY`. The vaults have no default
  here: `tdd env` keeps them (`1p:Employee`, `1p:dev_xp`) as literals in `env.toml`, and a
  direct caller names one.
- **The key is checked here.** One shorter than `secrets.CRYPTO_KEY_MIN_LEN` is refused with
  where it came from, not left to fail at the first descriptor it cannot open; the value is
  never in the message. `common.systems.crypto` and both `env` scripts use the same number.
- **The values are the output.** The ok event's message is the export lines, in JSON too --
  that is what the command is for, and only `env` runs it, into `$(...)`, never a log.
