<!--
# Copyright 2026 Tabsdata Inc.
-->

# tdd system & domain Guide

As of 2026-10-14

## What they are

`tdd system` registers a data platform under a name. `tdd domain` carves an isolated slice out of a system and fills it
with a model and data. Every xp suite and every manual test against a database, object store, warehouse or Kafka broker
starts from these two.

- **System**: one platform with its connection details. 14 types run locally as docker containers (mysql, postgres,
  mssqlserver, oracle, db2, starrocks, clickhouse, the three `*cdc` variants, mongodb, redpanda, redpandasasl, druid).
  14 are remote: managed Postgres (aws, gcp, az), warehouses (snowflake, databricks, bigquery), object stores (s3, gcs,
  azureblob, plus a local `fs`) and credential-only services (anthropic, openai, salesforce, dev).
- **Domain**: an isolated container inside one system: a database, schema, folder, prefix, topic or dataset, whichever
  that system calls it. A domain has its own owner and credentials, one model and its data. Its name inside the system
  is `d_<user>_<build>_<domain>` unless you pass `--name-in-system`.
- **Store**: one encrypted descriptor file per name in `<tdd_dir>/data/system/` and `<tdd_dir>/data/domain/` (default
  `~/.tdd/data/`). Descriptors are AES-256-GCM under `$_TDD_CRYPTO_KEY`; every command that reads or writes the store
  needs that key. Reinstalling tdd never touches this directory.

## Setup (once)

Setup takes a running docker, a signed-in 1Password CLI (`op`) and four commands.

1. Install tdd: `./install.sh` from the tabsdata-dt checkout (or `cargo make install`), then source the loader so the
   `tdd` function exists.
2. Load the store key, and the cloud secrets if you are about to create cloud systems: `tdd env set --crypto --secrets`.
   `--crypto` fetches `_TDD_CRYPTO_KEY` from 1Password item `DevSecrets` and is needed in every shell. `--secrets` is
   needed only to create cloud systems: it exports their coordinates and credentials, every `<ITEM>__<FIELD>` in
   1Password vault `dev_xp` (for example `S3__BUCKET`, `SNOWFLAKE__PAT`). Once a system exists they live in its
   descriptor, so daily use needs `--crypto` alone.
3. Create the systems you need: `tdd system create --type postgres` makes one named `postgres`.
   `--type mysql,postgres,fs` makes several; `--type ALL` makes all 28, and the remote ones fail unless their secrets
   are loaded. `tdd system fetch-bin --type T` pre-pulls images.
4. Check: `tdd system list`, then `tdd system status --sys ALL`.

Container systems get fixed host ports (a 100-port slot per type from 20000; see `docs/ports.md`). Remote systems read
their `<TYPE>__<KEY>` variables once, at create, store them in the descriptor and probe the connection.
`tdd system 1p-template --type T` prints the 1Password item a remote type needs.

## Daily use

Every new shell starts with `tdd env set --crypto`; without it no `tdd system` or `tdd domain` command can read the
store, and each one fails. After that, a domain's life is create, model, data, change, destroy. Systems stay up between
sessions.

```
tdd env set --crypto                                    # every new shell: loads the store key
tdd domain create       --sys postgres --domain pg1
tdd domain models       --domain pg1                    # models this system takes
tdd domain create-model --domain pg1 --model employees
tdd domain create-data  --domain pg1 --size 2           # 2 x 100 rows per sizeable table
tdd domain modify-data  --domain pg1 --sets 5           # Mix of inserts, updates, deletes
eval "$(tdd domain info --domain pg1 --format export)"  # connection values into the shell
tdd domain destroy      --domain pg1
```

- **Size**: `--size N` (default 1) gives every sizeable table N x 100 rows; reference tables stay fixed. For an empty
  domain, stop after `create-model`.
- **Changes**: `modify-data` takes `--ops Insert|Update|Delete|Mix`, `--entity`, `--sets N`, `--seed N|AUTO` and, on SQL
  systems, `--trx-mode serial|interleaved|nested|mix`. It is deterministic for a given seed, so a check can predict the
  result. `--emit-ops FILE` records every row it wrote.
- **Many at once**: `tdd domain create --manifest m.json` runs create, create-model and create-data for every entry
  (`{name, sys, model, size}`). This is how xp builds a suite's domains.
- **Housekeeping**: `tdd domain list`, `tdd domain status --domain ALL`, `tdd system restart --sys ALL` after a docker
  or laptop restart, `tdd system clean-docker --yes` to sweep stray `tdd_*` containers. `tdd system destroy --sys X`
  refuses while the system has domains; `--force` destroys them first.
- **On failure**: every command prints one line and writes the full log to `<temp>/tdd-<tool>-<verb>-*.log`.

## Getting connection details

To connect to a domain (host, port, user, password, database), use `tdd domain info --domain NAME`. Usually it is the
domain you want, since it carries its own credentials; `tdd system info --sys NAME` does the same for a system.
`--format` sets the output:

| `--format` | What it prints                                                 | Typical use                                              |
|------------|----------------------------------------------------------------|----------------------------------------------------------|
| `json`     | The descriptor as JSON                                         | Reading it, scripts and agents                           |
| `export`   | One `export KEY='value'` line per connection key, shell-quoted | `eval "$(tdd domain info --domain pg1 --format export)"` |
| `unset`    | One `unset KEY` line per key                                   | Clearing what `export` set                               |

`--prefix P` names the keys `P__KEY` (`PG1__HOST`). `--domain ALL` or a comma list prints several, each prefixed with
its own name.

## Models and data

13 models ship with tdd; 4 of them have tables that `modify-data` can change. Data is generated deterministically (seed
42), except sakila and world, which load the MySQL sample data sets, and salesforce, which loads a fixed snowfakery
recipe. Every model also carries an empty `xp_sentinel` table that suites write marker rows to.

| Model            | What it holds                                                                                                         | What modify-data changes                                                                                      |
|------------------|-----------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| airportdb        | Airports, airlines, planes, passengers, flights, bookings, weather                                                    | airport, passenger, weather (insert, update); booking (delete). Inserts carry deliberate data-quality defects |
| employees        | HR: departments, employees, titles, salaries                                                                          | employees (insert, update, delete); departments (update)                                                      |
| employeescdc     | CDC row-identity cases: a changing primary key, a composite key, a unique index without a key, no key, an audit table | all 5 tables (insert, update, delete)                                                                         |
| finance          | Subscription billing keyed to a snapshot of Salesforce accounts                                                       | customers (insert, update); subscription events (delete)                                                      |
| bronze           | Bronze-layer arrival patterns: snapshot, upsert with and without soft delete, CDC stream, append-only events          | nothing                                                                                                       |
| courierlogistics | Hubs, couriers, customers, shipments, tracking events                                                                 | nothing                                                                                                       |
| hospital         | Wards, staff, patients, admissions, appointments, diagnoses, prescriptions                                            | nothing                                                                                                       |
| restaurant       | Menu, recipes, orders, purchase orders                                                                                | nothing                                                                                                       |
| sakila           | The MySQL sakila sample; size scales rentals                                                                          | nothing                                                                                                       |
| schoolgrades     | Years, teachers, classes, students, enrollments, grades                                                               | nothing                                                                                                       |
| supermarket      | Suppliers, products, warehouses, stock, stock movements                                                               | nothing                                                                                                       |
| world            | The MySQL world sample; size scales cities                                                                            | nothing                                                                                                       |
| salesforce       | Accounts and opportunities in a Salesforce org; size 1 only                                                           | nothing                                                                                                       |

`tdd domain models --domain D` prints the same for a domain's system: `*` marks a table that grows with `--size`, and
I/U/D the changes it takes.

## Which system takes which model

**M** = supported, and modify-data changes it · **S** = supported (create-model + create-data) · **C** = create-model
only · **-** = not supported. Systems with identical support share a column.

| Model            | mysql<br>mysqlcdc<br>postgres<br>postgrescdc<br>db2<br>db2cdc<br>awspostgres<br>gcppostgres<br>azpostgres | mssqlserver<br>oracle<br>snowflake¹<br>databricks¹ | clickhouse<br>starrocks | fs<br>s3<br>gcs<br>azureblob² | redpanda<br>redpandasasl³ | druid⁴ | salesforce⁵ |
|------------------|:---------------------------------------------------------------------------------------------------------:|:--------------------------------------------------:|:-----------------------:|:-----------------------------:|:-------------------------:|:------:|:-----------:|
| airportdb        |                                                     M                                                     |                         M                          |            -            |               M               |             M             |   C    |      -      |
| employees        |                                                     M                                                     |                         M                          |            -            |               M               |             M             |   C    |      -      |
| employeescdc     |                                                     M                                                     |                         -                          |            -            |               M               |             M             |   C    |      -      |
| finance          |                                                     M                                                     |                         M                          |            -            |               M               |             M             |   C    |      -      |
| bronze           |                                                     S                                                     |                         S                          |            -            |               S               |             M             |   C    |      -      |
| courierlogistics |                                                     S                                                     |                         S                          |            -            |               S               |             M             |   C    |      -      |
| hospital         |                                                     S                                                     |                         S                          |            -            |               S               |             M             |   C    |      -      |
| restaurant       |                                                     S                                                     |                         S                          |            -            |               S               |             M             |   C    |      -      |
| sakila           |                                                     S                                                     |                         S                          |            -            |               S               |             M             |   C    |      -      |
| schoolgrades     |                                                     S                                                     |                         S                          |            -            |               S               |             M             |   C    |      -      |
| supermarket      |                                                     S                                                     |                         S                          |            -            |               S               |             M             |   C    |      -      |
| world            |                                                     S                                                     |                         S                          |            S            |               S               |             M             |   C    |      -      |
| salesforce       |                                                     -                                                     |                         -                          |            -            |               -               |             -             |   -    |      S      |

¹ modify-data in serial transactions only. ² modify-data appends only: pass `--ops Insert`. ³ Kafka has its own
commands: modify-data appends a fresh batch of the model's rows (no `--ops`), create-model takes `--up-to-partitions`,
create-data `--entity` and `--schema-changes`. ⁴ a datasource fills on ingestion, so there is no create-data. ⁵ size 1
only. Not listed: mongodb, bigquery, anthropic, openai and dev take no models.

SQL systems take a model when they have DDL for it, which is why clickhouse and starrocks stop at world and mssqlserver,
oracle, snowflake and databricks skip employeescdc. Object stores and Kafka take any generated model but only append.

## Gotchas

- **Type names change.** The SASL broker is now its own type, `redpandasasl`. A store still holding an old
  `redpanda_sasl` system fails the `kafka_sasl` suite with `no system named 'redpandasasl'`. Fix it with
  `tdd system create --type redpandasasl`.
- **Insert-only systems.** Object stores only append, so the default `--ops Mix` fails there; pass `--ops Insert`.
  Kafka (`redpanda`, `redpandasasl`) has its own modify-data, which appends a fresh batch for any model.
- **No key, no store.** A shell without `tdd env set --crypto` cannot read a single descriptor; an old
  `TD_BACKENDS_CRYPTO_KEY` gets a pointer to the new command.
