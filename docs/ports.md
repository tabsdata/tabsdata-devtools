<!--
Copyright 2026 Tabsdata Inc.
-->

# Host ports

How tdd picks the host ports it binds -- for the containers `tdd system create` starts, and for
anything else that needs a local port -- and which ranges are reserved for what.

## Never an ephemeral port

A port taken with `bind(("", 0))` is an *ephemeral* one: macOS hands out 49152-65535, Linux
32768-60999 by default. That is the very pool every outgoing connection draws from, so a port
found free that way and released is routinely taken by a docker pull or a kubectl call in the
seconds before `docker run` binds it (`failed to bind host port 0.0.0.0:59718/tcp: address
already in use`). Everything tdd picks therefore lies **below 32768**, and a candidate is checked
with a plain `bind` -- no `SO_REUSEADDR`, because a port in TIME_WAIT is not free for docker
either. Ports are free, not reserved, when handed out; the ranges below are what keeps two
pickers from meeting.

## Ranges

| range | who | how |
|---|---|---|
| 20000-29999 | the systems, one slot of 100 per type | walked from the slot's start; a create takes the first free ports of its slot, skipping the ones it already handed out |
| 30000-32767 | everything else (`common.core.ports.PORT_RANGE`): an ssh tunnel's local end, ... | walked from a random start, so two tdd processes rarely meet |

A system's slot is `20000 + 100 * i` for the `i`-th type in the registry's declaration order
(`common.systems.systems._SLUGS`, `slot_order()`), so two creates -- in one `--type ALL` batch or
in separate runs -- never look at the same ports, and a system's ports are stable across
recreates. New system types are **appended** to the registry: inserting one would shift every
slot after it. A test checks this table against the registry; a new or moved system updates it.

`tdd system create --ports P,P,...` pins the ports instead; they are used in order, and the slot
is consulted once they run out. Backends that need no ports never ask.

| system | slot | |
|---|---|---|
| `mysql` | 20000-20099 | container |
| `postgres` | 20100-20199 | container |
| `mssqlserver` | 20200-20299 | container |
| `oracle` | 20300-20399 | container |
| `starrocks` | 20400-20499 | container |
| `db2` | 20500-20599 | container |
| `mysqlcdc` | 20600-20699 | container |
| `postgrescdc` | 20700-20799 | container |
| `awspostgres` | 20800-20899 | no ports |
| `fs` | 20900-20999 | no ports |
| `s3` | 21000-21099 | no ports |
| `gcs` | 21100-21199 | no ports |
| `azureblob` | 21200-21299 | no ports |
| `anthropic` | 21300-21399 | no ports |
| `openai` | 21400-21499 | no ports |
| `dev` | 21500-21599 | no ports |
| `snowflake` | 21600-21699 | no ports |
| `databricks` | 21700-21799 | no ports |
| `bigquery` | 21800-21899 | no ports |
| `mongodb` | 21900-21999 | container |
| `redpanda` | 22000-22099 | container |
| `druid` | 22100-22199 | container |
| `clickhouse` | 22200-22299 | container |
| `db2cdc` | 22300-22399 | container |
| `salesforce` | 22400-22499 | no ports |
| `gcppostgres` | 22500-22599 | no ports |
| `azpostgres` | 22600-22699 | no ports |
| `redpandasasl` | 22700-22799 | container |

## Where in the code

- `tabsdata_dev.common.core.ports` -- `find_free_ports(count, range, exclude, from_start)`,
  `find_free_port`, `is_free`, `PORT_RANGE`; the probes `port_open`, `http_ok`.
- `tabsdata_dev.common.systems.systems._common.ports` -- `system_port_range(slug)` and
  `PortRangeMixin.next_free_port()`, mixed into every container backend;
  `constants.PORT_BASE`, `PORTS_PER_SYSTEM`, `PORTS_CEILING`.
