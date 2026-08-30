<!--
Copyright 2026 Tabsdata Inc.
-->

# env

`tdd env set|unset|show`: the variables tdd manages in the calling shell -- the descriptor
crypto key, the 1Password secrets, tabsdata's `TD_*` settings and the Python index variables.

- `set --crypto` evals `tdd system crypto-key --as export` (1Password; skipped when
  `_TDD_CRYPTO_KEY` is already set unless `--force`); `set --secrets [--vault 1p:V]` evals
  `tdd system secrets --as export`, which also writes `_TDD_SYSTEMS`, the prefix list `unset
  --secrets` reads back. `--py-idxx URL` sets `UV_INDEX`/`PIP_EXTRA_INDEX_URL` plus
  `UV_INDEX_STRATEGY=unsafe-best-match`; `--py-default-idx URL` sets `UV_DEFAULT_INDEX`/`PIP_INDEX_URL`.
- `unset --td` clears every `TD_*` variable -- tabsdata's own; none of tdd's are `TD_`.
  `--vars PREFIX` clears by prefix but never `TDD_DIR`, which `tdd` itself needs.
- `show` lists three sorted groups -- TD (`^TD*` plus `_TDD_CRYPTO_KEY`, and `_TDD_SYSTEMS`
  while set), PyPi, Secrets -- `- NAME` when unset; values whose name says
  PASSWORD/SECRET/TOKEN/KEY/PASS/_PAT are masked unless `--reveal`.
