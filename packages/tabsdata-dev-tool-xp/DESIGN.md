<!--
Copyright 2026 Tabsdata Inc.
-->

# xp

`tdd xp`: tabsdata-xp's `tdx-xp` ported -- run the example suites end to end against a tdkserver:
a suite is an ordered list of stages -- provision domains, create collections, register
functions, fire triggers, watch, run actions (change the data live, check what came out) --
that `run-suite` runs in order; `one-shot` creates a suite run, runs it and tears down, `bench`
times the phases, `--dry-run` prints the commands.

## Shape

- Toolset `xp`, its own; depends on `deps-xp` (pydantic, pyyaml, parquet-tools), `common-core`.
  Modules: `state`, `ids`, `reporter`, `models`, `suites`, `pointers`, `shell`, `conn`,
  `lanes`, `domains`, `project`, `actions`, `work`, `cycle`, and `scriptlib/tdd.py` -- the `tdd`
  module a python step imports, alone in its directory so that directory is all its PYTHONPATH
  gets. xp reaches `domain` and tdk through `tdd` and imports neither, so it shares no
  resolution with them.
- The tabsdata-xp `suites/` and `connections/` trees are **carried by** the package and are the
  default. They live at `<repo>/xp-tool/` (excluded from ruff), where they are read and edited,
  and a wheel build copies them in beside the module (`force-include`); an editable install
  copies nothing -- a link has no build step to hook -- so there `builtin_root()` finds them at
  the repo root instead, probing for `suites/` to tell the layouts apart. Same arrangement as
  the smoke scripts and the shell package's assets.
- tabsdata-xp's `connectors` dir is split here into `container-connectors` (docker/local
  systems) and `cloud-connectors` (lanes needing a cloud store or warehouse: az, bigquery,
  databricks, gcs, s3, snowflake). clickhouse and starrocks are container-connectors although
  they stage through s3/az/gcs: the aks/eks/gke smoke runs take `cloud-connectors`, and those
  two are not to run there. `cdc` holds the CDC stream sources' suites, the scenarios a source
  must survive, one suite each -- from an empty database, an initial load, an initial load
  under churn whose transactions run `--trx-mode serial|interleaved|nested|mix`, a tracked
  table left quiet for several rollovers, every key shape, the publisher disabled and enabled
  three times -- written by `cdc/gen_suites.py` for each of postgrescdc, mysqlcdc and db2cdc
  (a `Source` each: its publishers, its connections -- one MySQL server_id per collection that
  may run beside another -- what its log carries and how its head start is checked). Every one changes a table its
  stream does not track (`employeescdc`'s `audit`). `kafka` holds every Kafka stream
  source suite over a redpanda domain -- the connector's variants, the two examples
  (`kafka_src`, `kafka_registry`, hand-written, so the examples generator never knew them)
  and the topic, partition and schema-change suites -- with their functions and
  `verify_kafka.py`. `performance` holds the CDC ingestion suites (`gen_suites.py`
  writes them: per source an initial load and a changes run over a million rows loaded
  before the stream starts, so it reads a backlog). `scripts/cdc_throughput.py` measures two
  figures off the worker log, both before the trigger (whose time, and the commit's, is
  latency the thresholds choose): READ, the rows the source yielded over the seconds the
  stream pipeline waited on it (its `Polled` lines), and END TO END, the rows written to
  the files from the plugin's `run()` to the last file (the ledger's `Wrote` lines), with a
  steady rate over the files between the first and the last; both are the step's note,
  PARTIAL rather than failed when a stream is still short after the time-out. `kafka_json`
  is the Kafka source's, measured by the same script (the stream pipeline and ledger are
  every stream source's): ten million employees rows as
  JSON, forty passes of the domain's `modify-data --entity employees --size 2500` before the
  publisher is registered -- in passes, as one load builds every table of the model, ~12 rows
  for each employee sent. A type of their own so no connector run takes
  them, and meant to run one at a time. `mysql_airportdb` (hand-written, beside the
  generated ones) is a connector's capability surface at scale: mysql.json's, over an
  airportdb domain at size 1000, so one table crosses the SQL reader's 100K-row chunk; for
  it `performance/functions/` carries copies of the shared `caps_datagen.py` and
  `_srcmeta.py`. `dataquality/trends/mysqlcdc_airportdb` (hand-written, with its function
  and `scripts/verify_dq_trends.py`) is the DQ summary's trend table over a live run: a
  mysqlcdc airportdb (xs) stream with an initial load, triggered once a minute
  (`batch_min_secs=60`, `batch_max_secs=60` and no `batch_idle_secs`, so a batch is staged
  only when changes wait), a transformer classifying airport and passenger with six
  classifiers and `Summary(trends=Trends(...))`, and weather with five
  `ScaleCategorizer`s, one per scale, and a plain `Summary()` (a trend folds boolean
  classifiers only, and is off by default), 30 minutes of `modify-data` at ~1800 rows a
  minute -- whose inserts carry a defect per classifier at a share each run's seed sets,
  and readings around centres it sets with a share out of range (common-systems' design
  doc), so every pass rate and histogram moves every run -- and a check that every CDC
  version holds changes and they come about a minute apart, that at least five classifiers
  move from every run to the next and the trend's run, week, month and folded rows add up
  to the summaries, and that at least five categorizers' histograms add up, move from
  every version to the next and see both ends of their scale. `dataquality/trends/datagen_scale_samples` (with
  `functions/scale_plan.py`, `functions/dq_scale_samples.py` and
  `scripts/verify_dq_scale_samples.py`) shows every scale and boolean trends with no system
  at all: `scale_samples_spec.md`'s 22 columns, one relation family each, from `DataGenSrc`
  publishers -- ten of five tables, 9 with no data quality, 9 with boolean classifiers, 12
  with scale categorizers, 20 with both, one function's tables carrying all five scale types
  each -- triggered 100 times through a tick table, a pass every 30s or its plan's time if
  longer (two plans of one `DataGenSrc` publisher never overlap), 1000 rows a trigger
  (`chunk_size`). The data is made, not drawn: per column the defects each trigger holds
  are counts its profile sets -- smooth for a table, jumpy for some columns in every family
  -- changing every trigger, so the check knows every run's tallies exactly. The plan is
  standard library only, so the functions build from it and the check reads it. Both are in
  a directory of their own because a suite dir's lanes are its own files, not its subdirs':
  a bare `--suite dataquality` -- what the smoke runs take, on clusters with no mysqlcdc --
  stays the quick, self-contained lanes; the mysqlcdc suite's collection's `server_id` is
  1012. `blogs-material` holds suites written for blog posts: a function file is the code a
  post shows, and the suite proves it runs. `blogs-material/dataqualitytrends/salesforce-dq-trends`
  (with `functions/sf_leads_plan.py`, `functions/dq_salesforce_leads.py` and
  `scripts/verify_dq_salesforce.py`) is a publisher of a Salesforce Lead Lifetime report, a
  `DataGenSrc` standing in for `SalesforceReportSrc` -- 1000 leads named as the report API
  names its columns, 100 a trigger, ten triggers 30s apart, at most 30 rows of a run with an
  issue. The data quality is split the way a team would split it: ingest on the publisher's
  table -- ten boolean classifiers with named verdicts (`email_valid`, ...) whose failures
  improve, hold steady or go up and down, and the summary's trend -- and business on a
  transformer's, in a collection of its own (a source collection takes no transformer): two
  categorizers, open leads' days in status in 30-day buckets and the rating distribution,
  over columns the transformer adds, since a categorizer bins numbers. The function file
  spells every pattern, picklist, range and scale out literally, to read as an example; the
  plan holds the same values to make the data, and the check, holding every run's tallies and
  buckets to the plan's, catches a drift between them. `functions/dq_salesforce_leads_report.py`
  is the same publisher over `SalesforceReportSrc`, for the post, registered by no suite. The
  check imports `dataquality/trends/scripts/verify_dq_trends.py` across the tree rather than
  carrying a copy. `--suite <type>/<name>|<type>` selects under them or under `--suites-dir DIR`; `export-suites --dir DIR` copies them out.
- No `bin-reqs`: xp reaches tdk and tdkserver only through `tdd tdk`/`tdd tdkserver`,
  and those launchers declare the binaries themselves -- the requirement belongs to the
  command that runs the program. Pointers under `<tdd_dir>/data/xp`; a scratch dir per run
  under `/tmp/tdd-xp/`.
- Verbs: `list-suites`/`list-systems`/`export-suites`; `create-instance`; `run-suite` (the
  stages in order); the phase verbs `create-domains`, `create-project`, `run-triggers`,
  `monitor-project`, `run-actions`, each over every stage of its kind, and the matching
  `destroy-domains`/`destroy-project`/`destroy-instance`; `enable-function`/`disable-function`;
  `list-instances` and `list-projects` over the pointer store; `one-shot` and `bench` over the
  whole cycle. The phase verbs stay so a failed run can be finished or taken apart by hand;
  `run-suite` is safe to run again -- a domain or collection that exists is left alone, a
  function is registered with `--update`.

## How it works

- Talks to the server only through `tdd tdk` (`proc.tool_argv` -> `tdd-exe`), so xp needs neither
  tdk on its PATH nor tabsdata in its own toolset -- it needs a venv with tabsdata installed,
  the one the launcher picks and names (the last activated, managed by `tdd venv` or not). It
  provisions through `tdd domain create --manifest` (a domain-manifest stage) or the `tdd
  domain` calls a domains stage lists, and tears down with one `tdd domain destroy --manifest
  --format json`, parsing the batch events.
- `--profile NAME` is tdk's `--profile`: which connection the calls use, so two shells on one
  account each keep their own login. Absent, no option is passed and tdk uses its default
  connection. tdk attaches `--profile` to every command, not to the root group -- `tdk --profile
  P login` is refused, `tdk login --profile P` works -- so `shell.tdk_argv`, which builds every
  tdk argv, appends it last, past the verb; no call can miss it or misplace it; the verbs that reach tdk (`create-`/`destroy-`/`monitor-project`, `run-triggers`,
  `run-suite`, `enable-`/`disable-function`, `one-shot`, `bench`) take it and hand it to their fan-out children. The domain verbs never
  reach tdk and do not take it. **A step that calls tdk itself** (`tdd tdk fn disable`, a check
  script reading tables) writes `"--profile", "${td:profile}"` (or `--profile=${td:profile}`)
  in a tdd, exe or python step's options or params (a domain call refuses it, as it does any
  other `${td:...}`): the token is the run's profile name, and a run with none drops the
  option from the step's argv -- tdk refuses `--profile ""` (a name starts with a letter or
  digit) -- so the step reaches tdk's default connection, as xp's own calls do. Elsewhere in
  an argument the token is the empty string. `${td:...}`, not `${xp:...}`: it is tdk's
  setting, not the run's.
- **A domain-manifest stage is the batch**: `{"domain-manifest": {"emit_ops": FILE?, "domains":
  [{"name", "system", "model"?, "size"?, "emit"?}]}}` -- an object, not a list, for the setting
  beside its entries. xp writes the entries as a manifest (`domains-<n>.yaml`: `name`, `sys`,
  `name-in-system`, `model`, `size`, `emit-ops`) and runs ONE `tdd domain create --manifest`, the
  toolkit's batch: every domain in parallel, heaviest backend first, chaining create ->
  create-model -> create-data, one step per domain. `size` is `create-data --size` itself, a
  positive integer (~N x 100 rows; default 1, and only with a `model`). With `emit_ops`, each
  seeded domain whose `emit` is not false (default true) appends its seed's operations to a
  file of its own under the work dir -- two processes appending to one file with no lock can
  interleave, and on Windows an append is not atomic at all -- and once the batch is done xp appends those files to `emit_ops` in the
  order listed, so the trail does not depend on which domain finished first. A failed batch
  appends nothing. The built-in suites use it; the manifest's key is `emit-ops` because every
  manifest key mirrors a flag, the suite's `emit_ops` because every suite key is `_`.
- **A domains stage is `tdd domain` calls** -- `{"name", "command", "options"}`, run as
  `tdd domain <command> --domain <name> <options...>`: a domain's `create` (`--sys SYSTEM`), then
  what fills it (`create-model --model
  M`, `create-data --size N [--emit-ops FILE]`, any data verb). Each domain's calls run in the
  order written, the domains side by side (bounded by `$TDD_PARALLELISM`), one step per call; the
  first failure stops the rest at their next call. xp adds `--name-in-system` to a create itself
  (the domain's name in its system, see *Run identity and names*), so a suite may not;
  a domain's first call is its create, and a domain is created once. A domain whose create finds
  it already in the store is left alone, its other calls with it. It says what a manifest
  cannot -- any option, any data verb after the seed -- at the cost of the batch: each call is a
  child of its own, not heaviest first. Teardown, for both kinds, is one `destroy --manifest`
  over every created domain.
- **The project phase is fanned out except where order is meaning**: project -> groups ->
  collections in parallel -> functions **serial**, because registration order is what the
  dependency graph is built from -> triggers fired in batches gated by `detached` -> the
  transaction monitor. A monitor that exits non-zero is started again every 5s: it only reads,
  and on a cluster the usual cause is the port-forward dropping for seconds, which used to fail
  every lane watching at that moment while their transactions ran on. The run fails once the
  monitor has kept failing for 120s; a watch that lasted 30s reached the server and restarts
  that clock. tdk's own monitor rides out a short outage too (tabsdata-os `live_monitor`); this
  covers the tdk versions that do not. Every other tdk call (`shell.run_tdk`) is sent again every
  2s, for up to 30s, while tdk fails without having connected (urllib3's "Failed to establish a
  new connection"): the request never left, so even a create is safe to repeat. A reset
  mid-request is not retried -- a create may have landed. **The whole watch ends at the monitor's `time_out`**, which
  a monitor stage must give (`{"monitor": {"time_out": "30m"}}`; `monitor-project` and
  `run-triggers --monitor` take `--time-out`): transactions still running then fail the run.
  `{"monitor": true}` -- a watch with no end, which is what a hung run looks like -- is refused;
  a suite with no monitor stage does not monitor. `run-triggers` (it was `run-project`) fires the
  triggers and nothing else.
- `--secret-env` names the variable holding the domain crypto key (default `_TDD_CRYPTO_KEY`)
  and maps it into that name for the `tdd domain` children. In a connection template
  `$secret:D<n>__KEY` resolves from the backing domain's descriptor (the environment as a
  fallback) into an inline `secret:VALUE`, and the document is piped to `tdk collection create
  --conn-file -` -- a credential is never written to disk. `${D<n>__KEY}`, in a template or in a
  function's source, interpolates plain, for a value that is a name rather than a secret (the D0
  domain's in-system name, say).

## Run identity and names

- **A suite run has an `XP_ID`**, `xp_<USER>_<BUILD>_s<SS>_<YYYYMMDD>T<hhmmss>`: tabsdata-os's
  build identity (`$TD_BUILD_USER`, else the OS login; `$TD_BUILD_NUMBER`, else `0`), the
  process's slot and the second, UTC, the run began. Its **`XP_SHORT_ID`** is the same in 14
  characters, `<UUU><BB><SS>_<TTTTTT>` -- the user's first 3 characters, the build's last 2
  digits, the slot, the seconds since 2026-01-01Z in base 36, 6 wide (until 2094; fixed width,
  so names sort as the runs did) -- for the names a run leaves inside systems, whose
  identifiers are short (Postgres: 63 bytes). Lower case only: Postgres folds an unquoted name
  to lower case and DB2/Oracle/Snowflake to upper, so a mixed-case alphabet makes two seconds
  one name. Rejected: one base-62 character per field (`a` and `A` fold together),
  `(YYYY-2026)MMDDhhmmss` as one number in base 36 (7 characters from 2027). Runs one process
  starts are a second apart (`ids.new`), so a suite dir's lanes, each a run of its own, never
  share an ID. Processes started together keep apart by their **slot**, two base-36
  characters (1296 slots, `00` unless given): a one-shot over many suites starts each suite's
  child with `--id-slot <k>`, so children that draw the same second still differ. A name built
  from these IDs is taken by `tdd domain create --name-in-system` as given, never cut: one
  longer than the system takes fails before anything is written. run.log says both IDs at the
  run's start and end.
- **A suite is resolved for its run as it is read**: `${xp:name(x)}` is `<XP_ID>_x`, the domain
  in the tdd store, and `${xp:id}` / `${xp:short_id}` the IDs -- in every string of the suite,
  which is then plain values (a collection's `D0` must equal a domain's name, a string compare).
  The resolved suite is left as `suite.resolved.json` in the run's scratch dir. The domain's
  container in its system is the same name with `XP_SHORT_ID` for `XP_ID`
  (`tuc00_0e2aec_pgcdc`); a name written without `${xp:name(...)}` is **fixed** and used as
  written in both, for whoever wants that name. `tdd domain create` refuses a
  `--name-in-system` already in the system, so two runs drawing one name do not mix.
  `${xp:dir}` / `${xp:project}` are left for the run to fill in as it goes. Every built-in
  suite and every generator uses `${xp:name(...)}`.
- **A suite run is `--suite-run R`** (it was `--instance`): a pointer holding the run's IDs, by
  default named by its XP_ID, so it is always a file holding its XP_ID. An existing R is reused,
  its IDs with it -- how a failed run is finished a phase at a time; one of another suite is
  refused. **The project is `<XP_ID>_<suite>`** unless `--project P` names one; XP_ID is in no
  entity name inside it, which the project scopes. A project on the server that the run does not
  hold is refused unless `--force`, which deletes it and creates it again.

## Suite stages

A suite is an ordered **list of stages**, each an object holding one of `domain-manifest`,
`domains`, `collections`, `functions`, `triggers`, `monitor`, `actions` or `sentinel`, plus
`_`-prefixed annotations (`_comment`, `_copyright`; an object holding only those is a
comment). Kinds repeat, in any order the dependencies allow:

```
[
  {"domain-manifest": {"domains": [{"name": "${xp:name(pg)}", "system": "postgrescdc"}]}},
  {"actions": [{"background": {"name": "churn", "tags": ["live"], "actions": [...]}}]},
  {"collections": [...]},
  {"functions": [{"collection": "c", "functionpath": "...", "enabled": false}]},
  {"triggers": [...]},
  {"monitor": {"time_out": "30m"}},
  {"actions": [{"wait": {"name": "settle", "for": ["churn"]}}]},
  {"sentinel": [{"collection": "c", "table": "xp_sentinel_changes",
                 "wait_for_key": "done", "time_out": "10m"}]}
]
```

- **`run-suite` runs them in order**, one-shot through it: a domain-manifest stage is one batch,
  a domains stage runs its calls, the
  project is created before the first
  stage that talks to it, collections in parallel, functions serial, triggers in their gated
  batches, a monitor stage watches until the transactions finish. An actions stage's background
  blocks keep running through the stages after it -- the point of ordering: data changing
  while a collection is created or a stream publisher takes its initial snapshot -- and a later
  actions stage may wait for them; the suite's end waits for whatever still runs, and a stage
  that fails stops them. `live` and `execute`, the kinds `actions` replaced, are refused naming
  it.
- **Checked when the suite is read**, besides each kind's own checks: exactly one kind per
  stage, and nothing named from a *later* stage -- a collection's domains, a function's
  collection. A name defined nowhere is left to the stage that uses it.
  Stage numbers in messages count every entry of the list, comments included: the number a
  reader counts to in the file.
- **The older single object is refused**, naming the list it ran as
  (`[{"domains"}, {"collections"}, {"functions"}, {"triggers"}, {"monitor": {...}}]`). It is
  still *recognised* -- by `list-suites`, which marks it, and by a suite dir -- so an old file is a
  loud error rather than a lane silently missing. The built-in suites were converted to exactly
  the stages they ran (empty kinds dropped); `examples/gen_examples.py` writes its 49 in the
  list form. Rejected: keeping both forms -- two ways to write a suite, and the old one cannot
  express order.
- **The phase verbs take every stage of their kind** (`create-domains` all domains stages,
  `run-actions` all actions stages as one script); `bench` runs the phases in lockstep across its
  lanes and ignores the order. A suite dir under `run-suite` or one-shot is one lane per
  definition, each running its own stages -- lanes no longer move in lockstep.
- **A sentinel stage is a latch**: each entry holds until `wait_for_key` is in some version of
  `table` in `collection`, and fails the run once `time_out` has passed. The key is one
  `tdd domain sentinel-data --key` wrote at the source, which the functions carry through to a
  table of the project; the stage reads its `sentinel_key` column. Every committed version is
  read (`tdk table versions --max-result 0`, then `tdk table data --version V --sql ...` for the
  key), each once -- a stream publisher writes each flush as a version of its own, holding only
  that flush's rows, so the latest alone would miss a key flushed earlier. It polls every 5s;
  the entries run in turn, but a key that arrived while an earlier one was awaited is found on
  the first look. It is how a stage waits for data to have *arrived* rather than for a guessed
  pause. **The column is read as the table spells it**: DB2 upper-cases unquoted names, so its
  stream carries `SENTINEL_KEY`, and tdk's SQL (Polars) matches a column's case -- so the name
  comes from `tdk table schema` of the first readable version, matched case-insensitively, and
  is quoted in the query. Found on a real run, where every read of a DB2 table failed with
  "unable to find column" and the stage timed out saying "0 version(s) read": a version that
  cannot be read is retried, and the time-out now counts those and gives the last error. A
  table with no such column at all fails at once. It runs under `run-suite` (so one-shot); no phase verb takes it and `bench` ignores it.
- **Durations** -- a sentinel's or monitor's `time_out`, a `sleep`'s or `timeout`'s `time` -- are
  `"<VALUE><UNIT>"` with unit `s`, `m` or `h` (`"90s"`, `"2m"`, `"1.5h"`), and nothing else: a
  bare number is refused when the suite is read, since nothing in it says what it counts.
- **A run has a working dir**, `<scratch>/work`, made on first use and kept with the scratch dir.
  A suite names it `${xp:dir}` -- in a domain call's options and an action's options or
  params -- and the run's project `${xp:project}`; they are
  replaced when the value is used (the dir is a run's; a suite is read before any run), and any
  other `${xp:...}` is refused when the suite is read, and so is an older spelling (`${XP_WORK_DIR}`, `${xp_name(x)}`, ...), naming the one it is now. `--emit-ops ${xp:dir}/ops.jsonl` on
  every data call, the seed's create-data included, is one trail of every operation a run
  applied, for a script to check against what came out the other end.
- **The CDC check**, `cdc/scripts/verify_cdc_ops.py`, a python step tagged
  `check`: the CDC stream's output against the trail, the snapshot as the state the operations
  before it leave, and the changes after it one by one in the same source transactions
  (cascades replayed before the snapshot; transactions paired by content, so one lost or extra is
  reported alone; what the database logs besides the trail -- the rows a cascade takes, an update
  that changed nothing -- is the suite's to say, `--cascades`/`--noops logged|unlogged`, with no
  default: a check that accepts either lets a stream drop what it should carry). Column names are
  compared without case -- db2 reports them upper-cased, the trail has the model's -- and the stream is
  read in commit order -- its `seg`, the commit position every source stamps (postgres' commit
  LSN, mysql's GTID sequence, db2's commit sequence), padded and compared as a string since
  db2's passes what jq's numbers hold -- and the trail is written in commit order too (`tdd
  domain modify-data` writes a `--trx-mode` run's transactions as they committed). Ordering by
  transaction id was right until transactions overlapped: a postgres xid is the order they
  began, and a nested run commits backwards. `--untracked ENTITY...` leaves out of the trail
  the tables the domain changes and the stream does not track, so a stream that carried one
  shows it as an operation nothing expected. Every change is checked by its whole row images -- the before-image all columns
  of the row as the trail left it, an update's row all columns after it -- since a table without
  a key is known to a stream by nothing less; an update that sets a key column moves the row to
  its new key. `--start initial-load|head|tail` says what precedes the changes: a snapshot, the
  seed replayed from the log's head (checked as a snapshot is), or nothing. The CDC suites all
  run over `employeescdc`, a model made for them: a primary key every update changes, a
  composite one, a table with only a unique index and one with no key at all -- and `audit`,
  a plain-keyed table every data command changes and no suite's stream tracks.
- **The Kafka suites and their check**, `kafka/kafka_*.json` over
  `kafka/functions/caps_kafka_topics.py`, checked by `kafka/scripts/verify_kafka.py` (a python step tagged
  `check`). A `KafkaStreamSrc` reads one topic string, which librdkafka subscribes to as a regex
  when it starts with `^`: that is how one publisher reads several topics. Its frames share one
  slot and say the pattern, not the topic, so the function routes each frame to its topic's table
  by its columns, the rest to a `kafka_unrouted` the check expects empty. The suites build their
  domain with a domains stage, for redpanda's `--up-to-partitions`/`--entity`/
  `--schema-changes`, and produce in a background loop while the publishers start. The check
  takes each table's messages from the trail, polls until every one has arrived exactly once --
  in its table or as a dead letter -- and fails at `--time-out`: separate publishers carry no
  ordering a sentinel could stand on. `T1+T2=E` is two publishers in one consumer group, where a
  rebalance may hand a partition over before its offsets were committed; `--allow-duplicates`
  counts those instead of failing on them. `--dead-entities` names the topics whose messages may
  be refused, so a message a publisher failed to decode is not counted as arrived. Every Kafka
  suite is checked: the connector's variants, the payload formats (`kafka_src`), the schema
  registry (`kafka_registry`), what stages a batch (`kafka_triggers`: bytes and rows within
  minutes, against a 10-minute clock a control publisher must not have run out), a publisher
  disabled and enabled (`kafka_pause_resume`, duplicates not allowed) and SASL credentials
  (`kafka_sasl`, on a `redpandasasl` system). The domain's data plane writes JSON only;
  `scripts/produce_events.py` writes the rest -- Avro without a header, Protobuf, Avro in the
  Confluent wire format through the registry -- and appends to the same trail.
- **`"enabled": false`** on a function registers it with `tdk fn register --disabled`: a stream
  publisher does not start until `enable-function --project P --collection C --function F`
  (tdk's `fn enable`); `disable-function` stops one. A group project is refused -- its lanes'
  functions are each their own.

## Actions

An `actions` stage is a script: every actions stage of a suite is one, with one scope. An entry is
a one-key object, one of five steps or four blocks; each has a `name` (a letter, then letters,
digits, `_`, `-`; unique across the suite) and may have `tags`:

```
{"tdd":    {"name", "tool", "command", "options": [...], "continue_on_fail": false}}
{"exe":    {"name", "program", "params": [...], "continue_on_fail": false}}
{"python": {"name", "script", "params": [...], "reqs": ["polars==1.9.0"], "continue_on_fail": false}}
{"sleep":  {"name", "time": "<VALUE><UNIT>"}}
{"wait":   {"name", "for": [NAMES]}}
{"background": {"name", "actions": [...]}}
{"parallel":   {"name", "lanes": 0, "actions": [...]}}
{"loop":       {"name", "repeat": N, "actions": [...]}}
{"timeout":    {"name", "time": "<VALUE><UNIT>", "stop_on_timeout": true, "actions": [...]}}
```

- **`tdd` runs `tdd-exe TOOL COMMAND OPTIONS...`**, any of tdd's Python tools, the words as
  typed -- the developer's to get right. A shell tool (`venv`, `env`, `_tdd-env`) is refused when
  the suite is read: `tdd-exe` cannot reach a shell function. **`exe` runs any program on the
  PATH**; having it is the suite's business, nothing is declared. **`python` runs `uv run
  --no-project --with REQ... SCRIPT PARAMS...`** from the suite dir (the script a `.py` in it,
  checked when the suite is read), with `scriptlib/`'s `tdd` module on its PYTHONPATH -- `from
  tdd import tdd`, every tool one call away -- whatever the reqs make, since it is the standard
  library only. It replaced `tdd _xp-execute` and its one-off venvs: uv caches the environment a
  set of reqs makes, and PEP 723 inline metadata works too. A step gets `XP_WORK_DIR`,
  `XP_PROJECT`, `XP_ID`, `XP_SHORT_ID`, `XP_SUITE_RUN`, `XP_SUITE_DIR` and `tdd-exe` first on its
  PATH; a python step's stdout line `xp-note: <text>` (`tdd.note()`; the last wins) is in its
  step's note, deciding nothing. Rejected: a script that passes by printing, or a result file --
  an exit code is what every tool already speaks.
- **`background` starts its actions and the script goes on**; **`parallel`** runs them side by
  side, `lanes` at a time (0: all), and joins them at its end; **`loop`** runs them `repeat`
  times, each pass complete when everything it started has finished, so nothing outlives the
  loop that started it; **`timeout`** runs them for at most `time`, then fails the run
  (`stop_on_timeout`, the default) or goes on and leaves them running.
- **A wait reaches back, not in**: it names entries *before* it in its own list or an enclosing
  one -- an earlier actions stage's top level included, so a background block in one stage is
  waited for in a later one. A name inside another entry's block may not have started yet, or
  may start again; a block holding the wait would wait for itself; a sleep or wait holds nothing
  to wait for. Each pass of a loop has its own scope, so a name means that pass's run. **A
  bounded parallel holds no wait**: lanes waiting could starve the lanes they wait for. Rejected:
  waits reaching anywhere, which needs a rule for "which run of a block nested in a loop" and
  can deadlock.
- **Failures**: the first failure anywhere -- a step without `continue_on_fail` -- stops the
  script: what runs finishes its step (a change set is not killed half way), nothing new starts,
  and that failure is the run's. `continue_on_fail` reports it and goes on; the run fails at its
  end -- a check that fails is never a green run. **What still runs when the run ends** -- a
  timed-out block left running -- **is killed**: each step runs in a process group of its own
  (`start_new_session`; a new process group on Windows), SIGTERM then, after 5s, SIGKILL; a step
  so ended is said as ended, not failed.
- **Tags pick what runs**: an entry's tags are its own and every enclosing block's. `--tags A,B`
  runs the steps with A or B, `--skip-tags C,D` those with neither, both together those passing
  both; a block runs when a step inside it does, and only those; a wait on what does not run is
  met at once; `--no-actions` runs no actions stage (and takes no tags). `run-suite`, `one-shot`
  and `run-actions` take them; `--no-live` is gone. The built-in suites' former live stages are
  tagged `live` -- `--skip-tags live` is what `--no-live` was -- and their checks `check`.
- **Every step that runs something is one step of the run**, labelled with the blocks and passes
  it is under (`churn > churn-pass 7/20 > change`); its output goes to run.log as it comes, each
  line prefixed with that label, so steps side by side stay readable. A background block runs on
  a thread, not in a bounded pool: entries wait for one another, and a pool full of waiters
  would never run what they wait for.
- **`--dry-run` prints the script in order**: the commands, the pauses as `sleep N`, and where a
  block goes to the background, ends, runs side by side, is bounded or waited for as `#`
  comments. A shell rendering with subshells was the first version of the live script and was
  dropped with nested waits: a subshell cannot `wait` on a pid its parent started.
- **Where it runs is the suite's stage order.** A monitor stage sees what has started when it
  begins: a stream that buffers its changes needs a sentinel stage waiting for a key written
  after the last change. `run-actions --suite-run R` runs every actions stage as one script and
  nothing else, over a group's lanes too; `bench` does not run actions -- its phases are timings,
  and a script's pauses would be what they measured.

## Suites, lanes and pointers

A selector is `<type>/<name>` for one definition or `<type>` for a **directory**, which fans out
to one suite run and project per definition file in it -- a "swim lane". A selector that resolves
to nothing names the suite it probably meant (`--suite s3` -> `cloud-connectors/s3`) rather than
only pointing at `list-suites`: the name alone is what a reader remembers, and it is exactly the
shape that stopped working when the connectors were split in two. Offered, never accepted -- a
bare name is unique today and need not stay so. Each lane is a normal
single-lane `xp` child run with `--format json`, so the parent aggregates their event streams
live under a running total (`TDD_PARALLELISM` bounds them). Their lines share one console, so
the parent sizes the columns for every lane before the first line: the suite column as the
longest lane's label (from each lane's suite run pointer), the lanes' own `[n/m]` as the widest,
and -- where a lane's steps and notes are known up front (`run-suite`, one-shot's: a
`LanePlan` per lane from `suite_steps`/`suite_notes`) -- `[N/M]` as the run's whole total from
its first line and the note column as the longest note. A phase with no plan (the teardowns)
counts a lane once it reports, its `[N/M]` width estimated as the lanes times the largest seen,
so it holds when lanes run one after another. Found when `TDD_PARALLELISM=1` over a suite dir
climbed the total lane by lane and every column shifted at 10. `--fail-fast` lets the first failure
kill the rest; without it every lane is attempted, and a multi-phase run records the lanes that
died against their phase, drops them from later phases and reports them once at the end. Children
nest their scratch under the parent's through `_TDD_XP_SCRATCH`, honoured only with the parent's
pid in `_TDD_XP_PARENT`, so a stale export is reported and ignored.

**Sequence groups** keep lanes that share something single-tenant apart, as pytest's `_seq`
groups do. A lane's groups are the names its suite lists in a `{"seq": ...}` element and every
system its domains are on whose type is **exclusive** (`tdd system list` reports it; Salesforce
is, since every domain of a system is the one org and a data load wipes the whole org). The
dispatcher never runs two lanes of one group at once, handing a free slot to the next lane whose
groups are idle, so the rest of the suite keeps running beside them; a held-back lane says which
group it waits for. Each lane child also holds a lock file per group under the xp store
(`seq/<group>.lock`) for its whole run, so two separate runs on one machine take turns as well.
The parent hands a child its groups in `_TDD_XP_SEQ`, so the child does not read the system store
again. Found when `examples/salesforce_report` and `examples/salesforce_soql` ran together and
one's wipe deleted the Accounts the other's Opportunities were being loaded against. A run on
another machine against the same org is not covered.

`one-shot --suite` also takes a comma list of selectors or `ALL` -- every suite dir holding a
definition -- the same selector shape as `tdd system` / `tdd domain` (`batch.py`). Each selector is
a whole `one-shot` child of its own through the generic batch (`common.core.batch`), not a lane:
its own suite run, scratch dir and report, nothing nested under a parent's, so any one can be
re-run alone. They run **one at a time** unless `TDD_PARALLELISM` is set, unlike the batch's
default of 10: every child provisions domains on the same systems and the same instance, and a
pile-up there fails runs for no fault of their own. Each child's lines stream as `[SEL] line`;
`--fail-fast` (passed on, and starting no further selector), `--report` (the batch's JSON) and
Ctrl-C mean what they mean for the other batch verbs. `--suite-run` / `--project` name one run,
so a list refuses them, and every selector is resolved before the first child starts.

The pointer store is `<tdd_dir>/data/xp/`: `i-<R>` for a suite run (a definition file is
recorded as its path, re-read live for the run, with the run's `xp_id` and `xp_short_id`; a
directory records one member pointer per lane, each a run of its own, plus a group pointer with
an ID of its own), `p-<P>` for a project naming its suite run or group -- so every later verb
needs only `--project`. The verbs keep their instance names (`create-instance`,
`list-instances`) until a pass that makes xp's commands consistent. `connections/` templates are found by walking up from the suite dir to the first
ancestor holding one, else the built-in ones.

## Progress, logs and the report

One **step** is one unit of a suite's work: a domain, the project, a collection group, a
collection, a function registration, a trigger, the monitor wait. A command declares how many it
is about to run and wraps each one, which times it and reports it *as it finishes* as an event
whose message is the progress line and whose fields carry the structured step -- which is exactly
what the lane dispatcher reads back. The detail (every command and its output) goes to
`<scratch>/run.log` and never to the console; failures alone also go to `<scratch>/errors.log`,
created on the first one, so its existence answers "did this run go wrong"; `report.json` is
written at the end and becomes the fields of the run's final `ok`/`error`. A monitor that finds
failed transactions saves each one's worker logs to `<scratch>/trx-logs/<trx>/<worker>.log`
before it fails, and names them in errors.log: a one-shot or smoke run destroys the instance
next, and the workers with it. It fetches per worker (`worker list --trx`, `worker logs
--worker`) because `trx logs` prompts for a pick when several ran. Every run gets one
scratch directory under `/tmp/tdd-xp/`, announced at startup and **never deleted** -- the
manifests it authored, the logs, the report, and one subdir per lane.

`list-systems --suite S` is the pre-flight: every system the suite's domains name, with its type
from `tdd system list`, `ok` or `MISSING`. One missing system fails it, so a run does not spend
minutes on a suite run whose lanes cannot provision.
