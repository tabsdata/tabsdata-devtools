<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-tool-pypi

`pypi.tabsdata.com` is a public, anonymous-read Python index serving only
Tabsdata's own wheels: static HTML on S3 behind CloudFront, no server, nothing
to patch. This tool builds that tree and publishes it. It is a port of
`tdi-pypi` from `tabsdata-infra/pypi`, which was a standalone package with a
venv of its own and two verifier scripts beside it.

## Shape

- Toolset `pypi` (`deps-pypi`: boto3, pyyaml, packaging). Its own rather than
  `systems`, which pins every SQL dialect in the shop: three small libraries
  should not share a resolution with `oracledb` and `polars`.
- Entry point `tabsdata_dev.tool.pypi:main`. State is the meta repository, not
  the tdd dir; the only thing under `<tdd_dir>` is `pypi.toml`.
- `bin-reqs`: `aws tofu uv git curl jq openssl dig` -- what `tools-verify.sh`
  checked. Only `git` is shelled out to (the prod gate); the rest are the
  workflow's, declared so a gap refuses the command rather than surfacing at
  step 6 of a 10-step publish.

## How it works

- **`pypi-repo` and the guard** (`repo.py`). The meta lives in a repository of
  its own whose root holds `config/`, `raw-wheels/` and `pypi-wheels/`. Its
  remote is `pypi-repo` in `<tdd_dir>/pypi.toml`, and every subcommand runs at
  the root of a clone of it. The check is three questions in the order a reader
  would ask them -- a repository? its root? a clone of the right one? -- each
  with its own message. It compares **remotes, not paths**: a path is one
  machine's, and remotes normalize to `host/org/repo`, so the ssh and https
  spellings of one remote agree. Every remote counts, not just `origin`, so a
  fork whose `upstream` is the real one still passes. `tdi-pypi` said "run from
  `pypi/`" in a docstring and found out at the first missing file.
- **The pipeline is one direction.** `raw-wheels/` is the source of truth;
  `generate` builds `pypi-wheels/staging/` from it, `promote` builds `prod/`
  from staging, and `push` makes a bucket *exactly* its local tree. Every tree
  ends with a root `index.json` written **last**, so its presence means complete
  -- `check` asks only that, and `serve`, `promote` and `push` refuse a tree
  without it.
- **Yanking is a file.** Each tree's `yanked.yaml` is read by `generate`
  (staging) and `promote` (prod) and never written by anything, so a yank
  survives a rebuild and is reviewable as a diff.
- **Prod has two gates**, both before anything is listed or written: every wheel
  it would serve is byte-identical in the archive, and HEAD is reachable from
  `release_ref`. Git is the release record; a push that is not in the remote
  history is un-revertable by anyone but whoever ran it.
- **`aws-check`** (`aws_check.py`) is `aws-verify.sh` over boto3 rather than the
  `aws` CLI -- the tool has one way of talking to AWS, so what the check proves
  and what a push does cannot drift. Live read probes first (a denial is a fact,
  not a prediction), then `iam:SimulatePrincipalPolicy` for the writes. When the
  simulator is itself denied, its sections are **skipped, never passed**, and
  the summary says so: a simulation reflects identity policies and SCPs only, so
  a resource policy, a permission boundary or a session policy can still deny at
  call time.
- **Safety is code, not config.** `config/lanes.yaml` answers only *where*
  things live; `POLICY` in `config.py` holds `require_archived`,
  `require_pushed` and `require_yes`, so weakening one takes a review. A lane in
  the YAML with no entry in `POLICY` is a hard error rather than a default, so a
  new lane cannot get prod-like reach with staging-like safety.
- **`--yes` is never inferred from a non-tty.** That would let a CI run satisfy
  the prod lane's `require_yes` without anyone typing it.

## Ported, with two house rules applied

Everything that printed now speaks events (`plan.py`'s plan is one `info` per
action, which in `--format json` is a line each -- a printed table never was),
and every `SystemExit` is a `ToolError`, so the failure log and exit 1 come from
the shared layer. The one exception is the interactive confirm in
`plan.confirm`: a question is not an event, and it is only ever asked of a
terminal.
