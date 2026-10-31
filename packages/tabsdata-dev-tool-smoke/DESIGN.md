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

- `scripts/` inside the package, once per shell family: `_common.sh` and
  `smoke-{km,eks,gke,aks}.sh` for a POSIX shell, `_common.ps1` and `smoke-km.ps1` (so far) for
  PowerShell 7 -- a family is the shell the user is in, read as every tool reads it
  (`proc.shell_family`). `list`, `run` and `export-scripts` see the caller's family only. The
  `_common` of a family is not a test but the stage engine every script of it sources, so it is
  always exported with them -- scripts without it do not run. `list` does not show it: it lists
  what a person can run, and the engine is not that.
- A `.ps1` script is its `.sh` twin: the same options and the same stages, in order (a test holds
  them to it). Where PowerShell differs is the engine's to absorb (see `_common.ps1`'s header):
  no `exec >>LOG`, a status that travels in `$LASTEXITCODE`, no stdin through the `tdd` function,
  and a bare `--` eaten by parameter binding. `smoke-km.ps1` takes the LLM key with `tdd domain
  info --format export --platform windows | Invoke-Expression`, the twin of the sh `eval`.
- The wheel does not carry a file mode, so the export sets 755: a smoke script that cannot be
  executed is the first thing a person would otherwise fix by hand.
- Overwriting is refused without `--force`. The reason to export is to edit, so silently replacing
  what is there is the one behaviour that loses work.

## `_smoke`, the engine's Python half

The stage engine is shell, once per family, because a stage runs its commands in the script's
own shell: `tdd venv` and `tdd env` change it. What the engine does beyond keeping stages is an
algorithm, and an algorithm written in two shells is two copies to drift -- so it is `tdd
_smoke`, a second entry point of this package, plumbing (the `_` keeps it out of `tdd help`):
the config edits (`set-uv-index`, `set-fn-resources`, `fill-placeholder`, `fill-pem`,
`fill-storage`, `placeholders-left`), reading a field of a command's JSON Lines
(`event-field`), masking a command line (`display`, ~30 calls a run), reading `tdkserver
status` (`instance-state`, `pods-ready`), a local instance's processes (`instance-pids`,
`instance-stop`, `instance-gone`) and the screen beyond the stage lines (`window`, `pointers`,
`paint-help`). A call costs ~100 ms, nothing beside a stage. So a script loads tdd first,
before its own checks and its banner; `--help`, read with the options, has `common_help` load
it from the tdd dir known so far, and is printed plain without one.

- The rolling window is `render.Renderer.live` -- the block every tool redraws in place on a
  terminal -- fed what the log gained since the command started, padded with blank rows to its
  full height (`WINDOW`, 10) so the screen holds still from the first redraw instead of
  growing under the command row by row, as it always has. The engine starts it in the
  background through the `tdd` function, so the job is a subshell a signal would not get
  through; it is ended by a stop file the engine writes, or by the engine's pid going away.
- `pointers` reads a path in either OS's form (`/...`, `C:\...`), so a failure on Windows
  names its logs too.

- A kminus instance's processes are found by `instances/NAME/` on their command line, through
  `psutil` (the standard library cannot read another process's command line on Windows), a
  backslash read as a slash. The caller and its ancestors are never among them: a shell may
  carry the folder in its own command line, and its helper must not end it. `instance-stop`
  asks a previous run's tdkserver to stop first (a managed venv's, else PATH's: optional in
  `bin-reqs.txt`), then terminates, waits up to 90s and kills -- the wait is what keeps a km
  winding down from killing the new cluster through reused pid files.

- The engine still runs `tdd tdkserver status` itself -- in the venv the run activated -- and
  pipes the listing in; the helper answers (`running`, `ready`, `not ready`) and the engine
  judges. A pods check is retried until the pods come up, so a no is an answer, never an error
  event leaving a failure log behind on every attempt.
- `display` takes the command after `--`, which the shared CLI layer reads as operands: a
  `--format json` of the command's own is a word to show, not the helper's format.

- The scripts call it as stage commands, `common_run tdd _smoke ...`, so the stage line shows
  what ran. `common_fill_placeholder`/`common_fill_pem` stay as wrappers: they put the value in
  `_TDD_SMOKE_VALUE`, because a value can be a password and never goes on a command line;
  `fill-storage` reads the `STORD__*`/`STORS__*` the scripts already export.
- A helper that answers with a value makes it the ok message, alone on stdout in the view
  format, so `$(tdd _smoke ...)` reads it in either family; the rest goes to stderr, the log.
- Every edit is literal on both sides (a placeholder holds `${{`, `?`, `:`; a value can hold
  `&`, `\1`, JSON), keeps the file's line endings, and writes a storage value as a YAML
  double-quoted scalar: bare, a value that is JSON reads back as a mapping and tdkserver
  refuses the config's shape. aws alone writes an empty credential as it is, as eks always
  did; gcp and azure leave it for `placeholders-left` to name.

## Running one

`run` owns one option, `--script`, and hands the script everything else on the line, in order — the
launchers' arrangement, for the same reason: the options are the script's, and its own help page is
the one that describes them. `main()` splits the line before the parser sees it (`split_run`), so
the shared parser never meets options it does not own. `--script` is taken from *anywhere* after
`run`, because `tdd` appends a config preset (`[options.run] script = "eks"`) at the end of the
line. `-h`/`--help` is the tool's until the script is named — `tdd smoke run --help` is this
action's page — and the script's after it: `tdd smoke run --script eks --help` is the script's own.
A `--` opening the script's part is dropped; the scripts' parsers would refuse it.

The script runs through its family's shell -- `bash`, or `pwsh -NoProfile -File` -- since the
wheel keeps no exec bit and Windows has none to keep, in the user's cwd, on the terminal it
was called from, so its screen, its rolling window and its colours are its own. `TDD_DIR` travels
on, so the script's `--tdd-dir` defaults to the dir the tool runs from; `_TDD_TOOL` is dropped,
since the sourced `tdd` function warns about a shell that carries one. Exit 0 stays 0 and anything
else is one error event with the status, as the launchers do; the script has already said what
failed and named its log. That shell is the tool's one required `bin-req`, per family
(`kubectl` and a previous run's `tdkserver` are optional ones `_smoke` runs). What a script needs of its own —
`kubectl`, `python3`, `uv`, a venv manager — is the script's to check, as it does in its first
stages; declaring them here would refuse an export on a machine that only wants the files.

## The scripts

`smoke-km.sh` runs against kminus, which brings its own cluster and its own database
(`srv-database`); the other three run against a cluster that already exists. All four take
`--name` and `--td-version`; the cluster three also require `--kube-config` and `--kube-context`.
There is no sane default for which cluster to reach, so those are required and `common_help` paints
`--uv-index` takes `@dev` (`https://d3mm0r95u5i3hf.cloudfront.net/simple/`), `@dev:NAME`
(`.../NAME/`, the namespace `tdd pypi push --lane staging --at NAME` publishes),
`@local[::PORT][:NAME]` (`http://localhost:PORT/NAME/`, `tdd pypi serve` on this machine, PORT
8000 and NAME `simple` when left out; `smoke-km` only -- the cluster scripts pass
`--no-local` and refuse it, their index going to pods, for which localhost is themselves) and
`@prod` (`https://pypi.tabsdata.com/simple/`) as
well as a URL; a NAME or PORT written empty (`@dev:`, `@local::`) is refused. Resolved once by
`common_resolve_uv_index` as soon as tdd is loaded, before the banner, so the banner, the `uv
pip install`, the `tabsdata.yaml` and tdkserver all see the URL and never the marker. The two
URLs live in `tdd _smoke uv-index` (`indexes.py`), because every script, in either family, has
to mean the same thing by `@dev`. An unknown
`@marker` is refused there and then: passed on, uv would read it as a URL and fail several
stages later, in a message about a failed install that says nothing about the option behind it.

a required option red on the page. `--kube-namespace` and `--uv-index` are not among them: the
run's own `--name` makes a namespace (`sm-<name>`, lowercased for RFC 1123), and no index means
whatever uv is already configured with.

`smoke-km` puts the index back into its own shell after unsetting it (`set-pypi`, only when
`--uv-index` was given). `tdkserver quickstart --uv-index URL` takes the URL and writes it into
the instance's `tabsdata.yaml` under `pods.global.envs`, and then the pods get nothing: the
pymanager pod reports `UV_INDEX = <unset>` and resolves against PyPI alone, so a version that
exists only on that index fails to install and quickstart dies in `ins-pymanager` with "no
version of tabsdata[all]==X". Seen on 2.0.0, 2.0.1 and 2.1.0; `UV_INDEX_STRATEGY` beside it does
arrive, so it is that one placeholder rather than the mechanism. kminus runs its pods as local
processes, so they inherit the script's environment and `tdd env set --py-idx` reaches them --
the same pair tdkserver meant to set. The cluster scripts do not do this and must not: their pods
run in a real cluster and inherit nothing from the machine the script was launched on, which is
why they write the value into `tabsdata.yaml` instead. Drop the stage when tdkserver hands its
own `--uv-index` to the pods.

`smoke-km` hands the `--llm-domain` key to quickstart as `--config <system>-key=env:LLM__API_KEY`:
`tdd domain info --format export` exports it into the script's shell and tdkserver reads it from
that variable, so the key is on no command line, in no log and in no `ps`. `--config` came after
2.2.0, deprecating `--anthropic-key`/`--openai-key`, so for 2.2.0 and older the script still
passes `--<system>-key KEY`, which `common_display` masks. The cluster scripts never took the
option: they fill the `${{secret:<system>-key?}}` placeholder in `aiagent.yaml`.

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
`common_kubeportforward_start` runs it under a supervisor that relaunches it whenever it exits
(`tdd _smoke forward-start`: a process of its own, its pid in a state file beside the log, its
output and kubectl's written straight into the log, ended by a stop file or by the script that
started it going away -- a run killed outright leaves no forward on the port), and
each xp stage opens with `common_kubeportforward_ensure`: the port answers, or the supervisor is
given up to 20s to bring it back, or the forward is started afresh from the arguments the last
start was given -- and if that fails, the stage fails in its own words and the suite is skipped.
A kubectl that had been up 10s (`PORTFORWARD_STEADY`) dropped a working tunnel and is relaunched
at once; one that died sooner is paused for 2s, so a forward that cannot start does not spin. A
drop now costs the requests in flight: xp sends a call that could not connect again for 30s, and
watches again after a monitor that failed, but a lane whose request was reset mid-flight fails.

`--td-fn-memory` and `--td-fn-disk` size the function pods: `pods.function.resources.memory` and
`.disk` in `tabsdata.yaml`, rewritten at `configure` beside the `UV_INDEX` line. The template asks
for 16Gi and 64Gi per function pod; the defaults are 8Gi and 32Gi, and each is an option so a run
can try the template's figures, or less, without editing the script. `tdd _smoke set-fn-resources`
finds the block by structure rather than by a regex over the file, because the file holds a
`resources:` block per service too, and it fails the stage unless it rewrote exactly one memory
and one disk line -- the shape check tdkserver runs at `create` would not notice a sizing that
silently missed. CPU is left as the template has it; nothing asked for it to move.

`--db-domain`, `--storage-domain` and `--llm-domain` each name a **system**; the domain is always
created, named `sm_<NAME>__<system>`, and `--force` recreates it. The per-cloud defaults are the
storage and database beside the cluster (`awspostgres`/`s3`, `gcppostgres`/`gcs`,
`azpostgres`/`azureblob`); an LLM domain is created only when asked for. Each script fills its
storage as its own cloud (`tdd _smoke fill-storage --cloud aws|gcp|azure`), whose map knows that
cloud's option keys, so naming another cloud's storage leaves placeholders that `tdd _smoke
placeholders-left` then refuses — visibly, at `configure`.

`--profile` names the tdk connection every `tdd tdk` call and every `tdd xp one-shot` uses
(`tdk COMMAND --profile NAME` -- tdk takes it per command, after the verb, never before it --
passed on as `xp --profile`). A tdk login is otherwise one per account, so
a smoke run would log out whatever another shell on the same account was doing, and a second run
would log out the first. It defaults to the run's `sm_NAME`, the way every other name the run
makes does; `tdd smoke run --script NAME --profile P` passes it through like any script option.

A cluster run never writes to the kubeconfig it is given. It copies it into the run's work
directory, makes the copy current on the chosen context and namespace, and points tdkserver at the
copy: tdkserver resolves both from the *current* context, and its `venv update`, `config` and
`delete` take no `--context` to say otherwise. Nothing is borrowed, so cleanup returns nothing.

A failure report names only what the run actually built. `left for you to look at` is read while a
failure is being chased, so an instance, a venv, a domain or a namespace that was never created --
each with a cleanup command for it -- costs the reader a detour. The instance and venv are on disk
and get asked, the namespace is asked once per report, and the domains are appended to
`SMOKE_DOMAINS` as each `tdd domain create` returns rather than declared up front.
