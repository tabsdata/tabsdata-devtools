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
tests. So the scripts stay shell and are carried by this package.

They live at **`<repo>/smoke-tool/`**, where they are edited and run, and a wheel build copies them
in beside the module (`force-include`). An editable install copies nothing — a link has no build
step to hook — so there `scripts_dir()` finds them at the repo root instead; it tells the layouts
apart by probing for `_common.sh`. The shell package's assets work the same way.

The tool exports rather than runs them, and that is deliberate. They are made to be read and edited
while a failure is being chased — a stage commented out, an option tried —
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
`--name` and `--td-version`; the cluster three also require `--kube-config` and `--kube-context`.
There is no sane default for which cluster to reach, so those are required and `common_help` paints
a required option red on the page. `--kube-namespace` and `--uv-index` are not among them: the
run's own `--name` makes a namespace (`sm-<name>`, lowercased for RFC 1123), and no index means
whatever uv is already configured with.

`--db-domain`, `--storage-domain` and `--llm-domain` each name a **system**; the domain is always
created, named `sm_<NAME>__<system>`, and `--force` recreates it. The per-cloud defaults are the
storage and database beside the cluster (`awspostgres`/`s3`, `gcppostgres`/`gcs`,
`azpostgres`/`azureblob`); an LLM domain is created only when asked for. Each script's config
filling knows its own cloud's option keys, so naming another cloud's storage leaves placeholders
that `common_placeholders_left` then refuses — visibly, at `configure`.

A cluster run never writes to the kubeconfig it is given. It copies it into the run's work
directory, makes the copy current on the chosen context and namespace, and points tdkserver at the
copy: tdkserver resolves both from the *current* context, and its `venv update`, `config` and
`delete` take no `--context` to say otherwise. Nothing is borrowed, so cleanup returns nothing.
