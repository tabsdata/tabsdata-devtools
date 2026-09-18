<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-tool-smoke

`tdd smoke` — the end-to-end smoke test scripts, carried as package data: run one, or export them to
read and edit.

## Why the scripts stay shell

A smoke run is a couple of dozen stages driving `tdd`, `tdkserver`, `kubectl` and `xp` against a
real cluster, with a screen model, a rolling log window and a failure report. That is a shell
program: it *is* the sequence of commands a person would type, which is the whole point of a smoke
test, and rewriting it in Python would put a translation layer between the test and the thing it
tests. So the scripts stay shell and are carried by this package.

They live at **`<repo>/smoke-tool/`**, where they are edited and run, and a wheel build copies them
in beside the module (`force-include`). An editable install copies nothing — a link has no build
step to hook — so there `scripts_dir()` finds them at the repo root instead; it tells the layouts
apart by probing for `_common.sh`. The shell package's assets work the same way.

`run` executes the carried copy and `export-scripts` hands out a copy; both are the same scripts.
The export came first and stays: a run being chased is read and edited — a stage commented out, an
option tried — and a copy the user owns is the honest way to allow that, on a machine with a tdd
install and no checkout too. `run` is for the other day, when the script is right and a smoke is
one `tdd` command like everything else here.

## Shape

```
tdd smoke run --script NAME [SCRIPT-OPTION...]  run the carried smoke-NAME.sh; every other argument is its
tdd smoke export-scripts --dir DIR [--force]    copy them there, chmod 755
tdd smoke list                                  the four scripts, what each is, how to run it
```

- `scripts/` inside the package: `_common.sh` and `smoke-{km,eks,gke,aks}.sh`. `_common.sh` is not
  a test but the shared stage engine every one of them sources, so it is always exported with
  them — four scripts without it do not run. `list` does not show it: it lists what a person can
  run, and the engine is not that.
- The wheel does not carry a file mode, so the export sets 755: a smoke script that cannot be
  executed is the first thing a person would otherwise fix by hand.
- Overwriting is refused without `--force`. The reason to export is to edit, so silently replacing
  what is there is the one behaviour that loses work.

## Running one

`run` owns one option, `--script`, and hands the script everything else on the line, in order — the
launchers' arrangement, for the same reason: the options are the script's, and its own help page is
the one that describes them. `main()` splits the line before the parser sees it (`split_run`), so
the shared parser never meets options it does not own. `--script` is taken from *anywhere* after
`run`, because `tdd` appends a config preset (`[options.run] script = "eks"`) at the end of the
line. `-h`/`--help` is the tool's until the script is named — `tdd smoke run --help` is this
action's page — and the script's after it: `tdd smoke run --script eks --help` is the script's own.
A `--` opening the script's part is dropped; the scripts' parsers would refuse it.

The script runs through `bash` — the wheel keeps no exec bit — in the user's cwd, on the terminal it
was called from, so its screen, its rolling window and its colours are its own. `TDD_DIR` travels
on, so the script's `--tdd-dir` defaults to the dir the tool runs from; `_TDD_TOOL` is dropped,
since the sourced `tdd` function warns about a shell that carries one. Exit 0 stays 0 and anything
else is one error event with the status, as the launchers do; the script has already said what
failed and named its log. `bash` is the tool's one `bin-req`. What a script needs of its own —
`kubectl`, `python3`, `uv`, a venv manager — is the script's to check, as it does in its first
stages; declaring them here would refuse an export on a machine that only wants the files.

## The scripts

`smoke-km.sh` runs against kminus, which brings its own cluster and its own database
(`srv-database`); the other three run against a cluster that already exists. All four take
`--name` and `--td-version`; the cluster three also require `--kube-config` and `--kube-context`.
There is no sane default for which cluster to reach, so those are required and `common_help` paints
`--uv-index` takes `@dev` (`https://d3mm0r95u5i3hf.cloudfront.net/simple/`) and `@prod`
(`https://pypi.tabsdata.com/simple/`) as well as a URL, resolved once by
`common_resolve_uv_index` right after parsing so the banner, the `uv pip install`, the
`tabsdata.yaml` and tdkserver all see the URL and never the marker. The two URLs live in
`_common.sh`, because the four scripts have to mean the same thing by `@dev`. An unknown
`@marker` is refused there and then: passed on, uv would read it as a URL and fail several
stages later, in a message about a failed install that says nothing about the option behind it.

a required option red on the page. `--kube-namespace` and `--uv-index` are not among them: the
run's own `--name` makes a namespace (`sm-<name>`, lowercased for RFC 1123), and no index means
whatever uv is already configured with.

`--kube-port-forward` is the local port `kubectl port-forward` listens on -- the one `tdk` logs in
to -- and it moves that end only. Each script has its own default, so two runs on one machine
never fight over it: km's instance starts at 10000 (`--port`), eks forwards from 11000, aks from
12000, gke from 13000. The apiserver's own port in the cluster stays 2457 in all of them. The local port is the one thing another run, a forward a `--keep` run left or
a local tdkserver can already hold; the apiserver's port in its own namespace clashes with
nothing, and moving it along (`tdkserver create --port`) would smoke a port nobody deploys with.
So `common_kubeportforward_start` takes LOCAL and REMOTE, the scripts keep `PORT` for the cluster
end and `FORWARD_PORT` for the local one, and a local port already taken is refused by name before
kubectl is launched -- kubectl would fail to bind while the readiness probe answered, and the run
would log in to whatever was there.

The forward is **supervised, and checked before every suite**. It is one long-lived stream through
the cluster's tunnel, and the tunnel drops on its own: on AKS the node autoprovisioner replacing
the node that carries the konnectivity agents ended a run's forward mid-suite (`error: lost
connection to pod`) on two consecutive days, and every stage after it failed in a second as "not
logged in" -- which is what a dead forward looks like from `tdk`. kubectl does not reconnect, so
`common_kubeportforward_launch` runs it under a subshell that relaunches it whenever it exits, and
each xp stage opens with `common_kubeportforward_ensure`: the port answers, or the supervisor is
given up to 20s to bring it back, or the forward is started afresh from the arguments the last
start was given -- and if that fails, the stage fails in its own words and the suite is skipped.
A drop now costs the requests in flight and nothing after them; the lanes those requests belonged
to still fail, since xp does not retry a reset.

`--td-fn-memory` and `--td-fn-disk` size the function pods: `pods.function.resources.memory` and
`.disk` in `tabsdata.yaml`, rewritten at `configure` beside the `UV_INDEX` line. The template asks
for 16Gi and 64Gi per function pod; the defaults are 8Gi and 32Gi, and each is an option so a run
can try the template's figures, or less, without editing the script. `common_set_fn_resources`
finds the block by structure rather than by a regex over the file, because the file holds a
`resources:` block per service too, and it fails the stage unless it rewrote exactly one memory
and one disk line -- the shape check tdkserver runs at `create` would not notice a sizing that
silently missed. CPU is left as the template has it; nothing asked for it to move.

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

A failure report names only what the run actually built. `left for you to look at` is read while a
failure is being chased, so an instance, a venv, a domain or a namespace that was never created --
each with a cleanup command for it -- costs the reader a detour. The instance and venv are on disk
and get asked, the namespace is asked once per report, and the domains are appended to
`SMOKE_DOMAINS` as each `tdd domain create` returns rather than declared up front.
