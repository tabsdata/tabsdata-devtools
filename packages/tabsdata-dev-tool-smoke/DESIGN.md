<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-tool-smoke

`tdd smoke` — the end-to-end smoke test scripts, carried as package data and exported on request.

## Why a tool that only copies files

A smoke run is a couple of dozen stages driving `tdd`, `tdkserver`, `kubectl` and `xp` against a
real cluster, with a screen model, a rolling log window and a failure report. That is a shell
program: it *is* the sequence of commands a person would type, which is the whole point of a smoke
test, and rewriting it in Python would put a translation layer between the test and the thing it
tests. So the scripts stay shell and ship inside this package the way xp's suites ship inside xp
(invariant 5: every resource ships in its package, found with `importlib.resources`).

The tool exports rather than runs them, and that is deliberate. They are made to be read and edited
while a failure is being chased — a stage commented out, `--stop-after` moved, an option tried —
and a copy the user owns is the honest way to allow it. It also lets a machine with a tdd install
and no checkout run one.

## Shape

```
tdd smoke export-scripts --dir DIR [--force]   copy them there, chmod 755
tdd smoke list-scripts                         what is carried, without writing
```

- `scripts/` inside the package: `_common.sh` and `smoke-{km,eks,gke,aks}.sh`. `_common.sh` is not
  a test but the shared stage engine every one of them sources, so it is always exported with
  them — four scripts without it do not run.
- The wheel does not carry a file mode, so the export sets 755: a smoke script that cannot be
  executed is the first thing a person would otherwise fix by hand.
- Overwriting is refused without `--force`. The reason to export is to edit, so silently replacing
  what is there is the one behaviour that loses work.

## The scripts

`smoke-km.sh` runs against kminus, which brings its own cluster and its own database
(`srv-database`); the other three run against a cluster that already exists. All four take
`--name`, `--td-version` and `--uv-index`; the cluster three add `--kube-config`, `--kube-context`
and `--kube-namespace`. Every one of those is **required** — a default would be a confusing
failure, or a quiet success against a cluster, namespace or index nobody meant to touch — and
`common_help` paints a required option red on the page.

A cluster run never writes to the kubeconfig it is given. It copies it into the run's work
directory, makes the copy current on the chosen context and namespace, and points tdkserver at the
copy: tdkserver resolves both from the *current* context, and its `venv update`, `config` and
`delete` take no `--context` to say otherwise. Nothing is borrowed, so cleanup returns nothing.
