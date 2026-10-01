<!--
Copyright 2026 Tabsdata Inc.
-->

# `examples` — how to USE the connectors

**One behaviour, one file.** Every `@publisher` / `@subscriber` / `@transformer`
/ `@stream_publisher` in this suite set lives in its own file, named after
itself, in a directory named after its suite. Open
`functions/postgres_src_incremental/read_always_empty.py` and you get one
decorated function and the paragraphs that explain it — no scrolling past four
other examples, no constants defined 200 lines up.

**Every connector, even where that is repetitive.** A file source works the same
on a local disk and in a bucket; a SQL source works the same on PostgreSQL and
Db2. Rather than document one and wave at the rest, each connector has its own
suites — so `--suite examples/oracle_src_incremental` is a thing you can run, and
its `FETCH FIRST` and its uppercase `max_for("ID")` are right there rather than
in a footnote.

**Literal values in the decorators.** Paths, queries, table names and watermark
seeds are written where they are used, not hoisted into module constants. The
one exception is a Kafka `schema`, which is a document rather than a setting.

**This is not `suites/connectors/`.** That suite set exercises every connector's
config surface to prove it *works* — a test matrix, optimised for coverage. These
are optimised for reading.

```bash
tdx-xp oneshot --suite examples/postgres_src_incremental --keep   # one concern
tdx-xp oneshot --suite examples                                   # all 56 lanes
python suites/examples/validate.py                                # offline check
python suites/examples/gen_examples.py                            # regenerate
```

## Layout

```
<suite>.json                     the descriptor
functions/<suite>/
    supporting_*.py              scaffolding — the datagen publisher that makes
                                 input, the subscriber that stages a file to be
                                 read back. NOT the example.
    <behaviour>.py               the example: one decorated function, named
                                 after the file
gen_examples.py                  generates the repetitive families (see below)
validate.py                      wiring + layout + import + table-name checks
```

`--dir-to-bundle` defaults to the function file's own directory, so a
per-suite directory is also what keeps a registration from bundling all 300
files.

## Generated vs hand-written

Forty-nine of the 56 suites are **generated** by `gen_examples.py` from a
per-connector table plus one description of each concern. That is what keeps
full coverage honest: when the shared explanation is wrong it is wrong in one
place, and when a connector genuinely differs — `FETCH FIRST` vs `LIMIT`,
uppercase identifiers, a warehouse that cannot create its target — the difference
is a field in a table rather than a paragraph someone forgot to update in eleven
files. Edit the generator, re-run it, and every affected suite moves together.

Seven are **hand-written**, because they have nothing to be repetitive with, and
the generator never touches them: `salesforce_soql`, `salesforce_report`,
`grok_logs`, `dataquality_checks`, `tableframe_ops`, `triggers_scheduling`,
`source_metadata`. The two Kafka examples, `kafka_src` (payload formats, the
buffer and trigger keys, dead-letter topics) and `kafka_registry` (a Confluent
schema registry and its wire format), live with the other Kafka suites in
`suites/kafka/`.

## The index

### Sources — files and object stores

`localfile`, `s3`, `gcs`, `az` each get all three. `S3Src` is field-identical to
`LocalFileSrc`; what changes is the connection.

| suite | what it teaches |
| --- | --- |
| `<c>_src_paths` | one fixed path, a wildcard, several paths folded one way or the other; array slots and `concat`; one source reads one FORMAT |
| `<c>_src_formats` | `format` (incl. the `.ndjson` case `AUTO` cannot infer) and CSV `format_cfg`, reader and writer sides mirrored |
| `<c>_src_lastmodified` | `initial_last_modified`: the advancing cutoff, the empty-match no-op, full reload as the contrast |

### Sources — SQL

`postgres`, `mysql`, `mssql`, `oracle`, `db2`, `databricks` each get both.

| suite | what it teaches |
| --- | --- |
| `<c>_src_queries` | one query, many queries in one session, `transactional`, `schema_overrides`, zero rows |
| `<c>_src_incremental` | `initial_values` + `:bind` + `ctx.set_attr` + `max_for()`, and the no-results rule that keeps a cursor from rewinding |

### Sources — SaaS and streams

| suite | what it teaches |
| --- | --- |
| `salesforce_soql` | one SOQL per publisher, `include_deleted`, `$lastModified` as a static floor, and the two-layer incremental read that follows |
| `salesforce_report` | reports by id or name, several at once, server-side `filter` + `filter_logic`, `last_modified_column` |
| `postgrescdc_stream` | slots, `start_from`, `columns_format` × `flatten_columns`, buffer/trigger thresholds |
| `mysqlcdc_stream` | the same, on `server_id` instead of a slot, with a `head` that really replays |
| `db2cdc_stream` | the same, on ASN CD tables — `tables` names the shadow tables, not the source ones. **Needs no other db2cdc domain standing** (see below) |

### Destinations

| suite | what it teaches |
| --- | --- |
| `<c>_dest_formats` | the four writer formats and the CSV writer options; the returned-`None` skip. `localfile`, `s3`, `gcs`, `az` |
| `<c>_dest_tokens` | `${TRX_ID}` / `${EXEC_PLAN_ID}` / `${EXEC_PLAN_TS}`: one file per run instead of overwriting one |
| `<c>_dest_modes` | `append` vs `replace` (neither is an upsert), multi-table writes, `transactional`, when types are decided. `postgres`, `mysql`, `mssql`, `oracle`, `db2` |
| `<w>_dest_modes` | the same shape plus the staging hop a bulk loader adds. `snowflake`, `databricks`, `clickhouse`, `bigquery` |
| `starrocks_dest_modes` | the destination that CANNOT create its target, so its targets are seeded tables and its Primary Key model decides which mode goes where |
| `mongodb_dest_modes` | the destination that writes DOCUMENTS: `collections_with_ids`, `if_collection_exists`, and the only idempotent upsert sink in the set |
| `<w>_dest_evolution` | schema evolution — and that the values *and the defaults* differ per connector. `databricks`, `bigquery`, `clickhouse` |

### Features

| suite | what it teaches |
| --- | --- |
| `grok_logs` | `TableFrame.grok`: anchoring, `DATA` vs `GREEDYDATA`, the schema as a cast, null-on-no-match |
| `dataquality_checks` | `on_tables=[DataQuality(...)]`: classifiers, and `Enrich` / `Summary` / `Filter` / `Select` / `Fail` |
| `tableframe_ops` | joins, set differences via semi/anti joins, projections, aggregations, `@NEW` vs `@HEAD` |
| `triggers_scheduling` | **WHEN** a function runs: `trigger_by` with `CronTrigger` / `TablesTrigger` / `AllTablesTrigger`, and `Data(chunk_size=N)` for a source that advances per tick |
| `source_metadata` | the `@td.*` columns every source stamps (`@td.file.path`, `@td.sql.query`, ...) and the one `src_cfg` key that drops them |

## Conventions every example follows

* **A source's slot shape depends on the source.** A FILE source is ARRAY mode —
  one slot per `paths` entry, each a *list* of the frames that entry matched — so
  its parameters are always folded with `concat`. A SQL source is SINGLE mode:
  one frame per query. A CDC or Kafka stream is array mode again.
* **Returning `None` publishes nothing.** No new table version, so nothing
  downstream fires; on the destination side, no write at all — and no truncate,
  so a `replace` sink returning `None` leaves its target intact. Returning an
  *empty frame* is a different thing and does trigger downstream work.
* **`@NEW` vs `@HEAD`.** `coll/table@NEW` means "run when this table gets a new
  version"; `coll/table@HEAD` means "and read the current version of that one". A
  reference of either kind puts the function in the producer's execution plan.
* **A table name is unique per collection.** `fn register` rejects a second
  function claiming a name another owns. `validate.py` reproduces that check
  offline.
* **Ordering inside one run comes from the trigger list.** A trigger declared
  `"detached": false` is a GATE: `tdx-xp` waits for its whole plan (the publisher
  *and* whatever fires reactively off it) before firing the triggers after it.
  That is how a suite stages a file and then reads it back in a single run.
* **Nothing is pinned to a run.** A backend name a function needs — a Kafka
  topic, say — is written `${D0__DB}` and interpolated at registration, so two
  instances of a suite never collide.
* **Credentials are never in the code.** Every connection lives in
  `connections/<type>.yaml` and is registered on the collection; the function
  names only the `Src` / `Dest`.

## Which connector has which knob

The shapes generalise, the vocabularies do not. Check this before copying an
example onto another connector.

| capability | who has it |
| --- | --- |
| `initial_last_modified` (auto-advancing) | the file connectors: `localfile`, `s3`, `gcs`, `azureblob` |
| `initial_values` + `:bind` watermark | every SQL source |
| `format` / `format_cfg` | the file connectors only — and `format` is per SOURCE, not per path, so one source reads one format |
| destination path tokens | the file connectors only |
| `@td.*` source metadata + `tabsdata.src_metadata.drop` | every source; the columns differ per kind (see `source_metadata`) |
| `trigger_by=CronTrigger(...)` | `@publisher` only — nothing upstream to react to |
| `trigger_by=TablesTrigger/AllTablesTrigger` | `@transformer` and `@subscriber` |
| `tables` + `if_table_exists` | every SQL and warehouse destination — except `mongodb`, which takes `collections_with_ids` + `if_collection_exists` |
| an upsert | `mongodb` alone (`update_existing=True`) |
| `schema_evolution` = `update` \| `strict` | `databricks` (default `update`), `bigquery` (default `update`) |
| `schema_evolution` = `strict` \| `iceberg` | `clickhouse` (default `strict`), `starrocks` (default `strict`, but its load path cannot yet use it) |
| no `schema_evolution` at all | `snowflake`, `postgres`, `mysql`, `mssql`, `oracle`, `db2`, `mongodb`, `druid` |
| create-on-write | everything except `starrocks` |
| a staging area on the connection | `snowflake` (stage), `databricks` (volume), `clickhouse` / `starrocks` / `bigquery` (object store) |
| CDC via a replication slot | `postgrescdc` |
| CDC via a `server_id` replica | `mysqlcdc` |
| CDC via ASN CD tables | `db2cdc` |
| source only, no destination | `kafka`, `salesforce`, every CDC connector |
| destination only, no source | `snowflake`, `clickhouse`, `starrocks`, `bigquery`, `mongodb`, `druid` — there is no `SnowflakeSrc` to pair with `SnowflakeDest` |

`druid` has no example: there is no connection template for it in `connections/`.
It is shape-identical to `<c>_dest_modes`.

### db2cdc: each domain its own CD tables

A Db2 registration's change-data table lives in the one shared `ASN` schema, so the
db2cdc system names it after the domain: `ASN.TD_<tag of the schema>__<TABLE>`. The
domain records the prefix as `CD_TABLE_PREFIX`, and `db2cdc_stream`'s functions name
their tables `${D0__CD_TABLE_PREFIX}EMPLOYEES`, which xp fills in when it registers
them. Any number of db2cdc domains of one model share a system -- this suite and
the `cdc/db2cdc_*` suites can be up together.

`Db2Cdc.destroy_domain` deregisters every table under the domain's schema before
dropping it, which is why a db2cdc teardown takes minutes rather than a second.

## Adding an example

**To a generated family** — edit `gen_examples.py` and re-run it. A new connector
is a new entry in `FILE_CONNECTORS` / `SQL_SOURCES` / `SQL_DESTS` /
`WAREHOUSE_DESTS` / `EVOLUTION` / `CDC`; a new *concern* is a new emitter plus a
line in `build()`. Every generated `functions/<suite>/` directory is deleted and
rewritten, so a renamed function leaves nothing stale behind — do not hand-edit
files in one.

**A hand-written suite** — add `functions/<suite>/<behaviour>.py` with ONE
decorated function named after the file, and wire it into `<suite>.json`.

Then, either way:

```bash
python suites/examples/validate.py <suite>     # wiring, layout, imports, names
tdx-xp oneshot --suite examples/<suite>        # the real thing
```

Keep each suite to ONE concern. If it needs two paragraphs to say what it is
about, it is two suites.
