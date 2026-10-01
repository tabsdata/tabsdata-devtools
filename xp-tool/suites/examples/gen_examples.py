#
# Copyright 2026 Tabsdata Inc.
#
"""Generator for the REPETITIVE half of the ``examples`` suite set.

Most of what an example has to say about a connector is the same sentence with a
different class name in it: a file source works the same whether the bytes are on
a local disk or in a bucket, and a SQL source works the same whether the server is
PostgreSQL or Db2. The differences that DO matter — a dialect's row-limit syntax,
whether identifiers fold to uppercase, whether a destination can create its target
— are few, known, and listed per connector in the tables below.

So this file holds ONE description of each concern plus a per-connector delta, and
emits the concrete suites from it. That is the only way full coverage stays
truthful: when the shared explanation is wrong, it is wrong in one place, and when
a connector is genuinely different, the difference is a field in a table rather
than a paragraph someone forgot to update in eleven files.

WHAT IT EMITS, per suite
    ``<suite>.json``               the descriptor
    ``functions/<suite>/*.py``     ONE decorated function per file

    Files named ``supporting_*.py`` are scaffolding — the datagen publisher that
    makes input, the subscriber that stages a file to be read back. Everything
    else is the example itself.

    Decorators carry LITERAL values (paths, queries, table names, watermark
    seeds). No module constants, no shared helpers: a reader (human or agent)
    should be able to answer "what does this configuration do" from one screen,
    without following a name somewhere else.

WHAT IT DOES NOT EMIT
    The one-off suites, which are hand-written because they have nothing to be
    repetitive with: ``kafka_*``, ``salesforce_*``, ``grok_logs``,
    ``dataquality_checks``, ``tableframe_ops``. This generator never touches
    their files.

    Run it from anywhere; paths are resolved relative to this file.

        python suites/examples/gen_examples.py            # write everything
        python suites/examples/gen_examples.py --list     # just name the suites
"""
from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

SUITE_DIR = Path(__file__).resolve().parent
FN_DIR = SUITE_DIR / "functions"

COPYRIGHT = "#\n# Copyright 2026 Tabsdata Inc.\n#\n"

# Suites that are hand-written; the generator leaves them alone.
HANDWRITTEN = {
    "kafka_src",
    "kafka_registry",
    "salesforce_soql",
    "salesforce_report",
    "grok_logs",
    "dataquality_checks",
    "tableframe_ops",
    "triggers_scheduling",
    "source_metadata",
}


# --------------------------------------------------------------- connectors --
# A file connector: `Src`/`Dest` are field-identical across all four, so the only
# per-connector text is what the store IS and what its paths mean.
FILE_CONNECTORS = {
    "localfile": {
        "module": "tabsdatak.conn.localfile",
        "src": "LocalFileSrc",
        "dest": "LocalFileDest",
        "src_tpl": "local_file_in.yaml",
        "dest_tpl": "local_file_out.yaml",
        "src_type": "local_file_in",
        "dest_type": "local_file_out",
        "system": "fs",
        "label": "local-file",
        "conn_note": (
            "The connection (`connections/local_file_in.yaml` /\n"
            "    `local_file_out.yaml`) carries only a `base_path` — no credentials at\n"
            "    all, which is what makes the local-file connector the one to learn the\n"
            "    file-source shape on."
        ),
        "store_note": (
            "Directories are real here, so a path with a `/` in it creates one."
        ),
    },
    "s3": {
        "module": "tabsdatak.conn.s3",
        "src": "S3Src",
        "dest": "S3Dest",
        "src_tpl": "s3_file_in.yaml",
        "dest_tpl": "s3_file_out.yaml",
        "src_type": "s3_file_in",
        "dest_type": "s3_file_out",
        "system": "s3",
        "label": "S3",
        "conn_note": (
            "The connection (`connections/s3_file_in.yaml` / `s3_file_out.yaml`)\n"
            "    carries the bucket, the region, the AWS credentials and the `base_path`\n"
            "    prefix. None of that is in this file — which is what lets the same\n"
            "    function be pointed at another bucket, or at GCS, without a rewrite."
        ),
        "store_note": (
            "There are no directories: a path with a `/` in it is one flat key that\n"
            "    happens to contain a slash, so nothing is created and nothing is left\n"
            "    behind empty. Paths are always relative to `base_path` — never an\n"
            "    `s3://` URI."
        ),
    },
    "gcs": {
        "module": "tabsdatak.conn.gcs",
        "src": "GCSSrc",
        "dest": "GCSDest",
        "src_tpl": "gcs_file_in.yaml",
        "dest_tpl": "gcs_file_out.yaml",
        "src_type": "gcs_file_in",
        "dest_type": "gcs_file_out",
        "system": "gcs",
        "label": "GCS",
        "conn_note": (
            "The connection (`connections/gcs_file_in.yaml` / `gcs_file_out.yaml`)\n"
            "    carries the bucket, a service-account key and the `base_path` prefix."
        ),
        "store_note": (
            "There are no directories: a path with a `/` in it is one flat object name.\n"
            "    Paths are always relative to `base_path` — never a `gs://` URI."
        ),
    },
    "az": {
        "module": "tabsdatak.conn.azureblob",
        "src": "AzureBlobSrc",
        "dest": "AzureBlobDest",
        "src_tpl": "az_file_in.yaml",
        "dest_tpl": "az_file_out.yaml",
        "src_type": "az_file_in",
        "dest_type": "az_file_out",
        "system": "azureblob",
        "label": "Azure Blob",
        "conn_note": (
            "The connection (`connections/az_file_in.yaml` / `az_file_out.yaml`)\n"
            "    carries the container, the storage-account name and key, and the\n"
            "    `base_path` prefix."
        ),
        "store_note": (
            "There are no directories: a path with a `/` in it is one flat blob name.\n"
            "    Paths are always relative to `base_path` — never an `az://` URI."
        ),
    },
}

# A SQL source. `dialect` is the row-limit clause; `upper` says whether unquoted
# identifiers fold to uppercase (which decides what `max_for` must be given).
SQL_SOURCES = {
    "postgres": {
        "module": "tabsdatak.conn.postgres",
        "src": "PostgresSrc",
        "tpl": "postgres_sql_in.yaml",
        "type": "postgres_sql_in",
        "system": "postgres",
        "label": "PostgreSQL",
        "limit": "LIMIT 10",
        "limit5": "LIMIT 5",
        "upper": False,
        "note": "PostgreSQL is the reference dialect for these examples.",
    },
    "mysql": {
        "module": "tabsdatak.conn.mysql",
        "src": "MySQLSrc",
        "tpl": "mysql_sql_in.yaml",
        "type": "mysql_sql_in",
        "system": "mysql",
        "label": "MySQL",
        "limit": "LIMIT 10",
        "limit5": "LIMIT 5",
        "upper": False,
        "note": (
            "MySQL takes the same `LIMIT n` as PostgreSQL and preserves identifier\n"
            "    case, so these queries are byte-identical to the PostgreSQL ones."
        ),
    },
    "mssql": {
        "module": "tabsdatak.conn.mssql",
        "src": "MSSQLSrc",
        "tpl": "mssql_sql_in.yaml",
        "type": "mssql_sql_in",
        "system": "mssqlserver",
        "label": "SQL Server",
        "limit": "OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY",
        "limit5": "OFFSET 0 ROWS FETCH NEXT 5 ROWS ONLY",
        "upper": False,
        "note": (
            "SQL Server has no `LIMIT`: it wants either `SELECT TOP (n) ...` or the\n"
            "    ANSI `OFFSET n ROWS FETCH NEXT m ROWS ONLY` used here, which REQUIRES an\n"
            "    `ORDER BY` — no bad thing, since a paging read needs one anyway."
        ),
    },
    "oracle": {
        "module": "tabsdatak.conn.oracle",
        "src": "OracleSrc",
        "tpl": "oracle_sql_in.yaml",
        "type": "oracle_sql_in",
        "system": "oracle",
        "label": "Oracle",
        "limit": "FETCH FIRST 10 ROWS ONLY",
        "limit5": "FETCH FIRST 5 ROWS ONLY",
        "upper": True,
        "note": (
            "Oracle folds UNQUOTED identifiers to UPPERCASE, so `SELECT * FROM city`\n"
            "    comes back with columns `ID` / `NAME` / `COUNTRY_CODE`. Anything that\n"
            "    names a column by string has to match — and that fails at RUN time, not\n"
            "    at registration. Row limiting is `FETCH FIRST n ROWS ONLY`, not `LIMIT`."
        ),
    },
    "db2": {
        "module": "tabsdatak.conn.db2",
        "src": "Db2Src",
        "tpl": "db2_sql_in.yaml",
        "type": "db2_sql_in",
        "system": "db2",
        "label": "Db2",
        "limit": "FETCH FIRST 10 ROWS ONLY",
        "limit5": "FETCH FIRST 5 ROWS ONLY",
        "upper": True,
        "note": (
            "Db2 folds UNQUOTED identifiers to UPPERCASE, exactly as Oracle does, so\n"
            "    the frames come back with `ID` / `NAME` / `COUNTRY_CODE` and anything\n"
            "    naming a column by string has to match. Row limiting is\n"
            "    `FETCH FIRST n ROWS ONLY`."
        ),
    },
    "databricks": {
        "module": "tabsdatak.conn.databricks",
        "src": "DatabricksSrc",
        "tpl": "databricks_bulk_in.yaml",
        "type": "databricks_bulk_in",
        "system": "databricks",
        "label": "Databricks",
        "limit": "LIMIT 10",
        "limit5": "LIMIT 5",
        "upper": False,
        "note": (
            "Databricks is the one warehouse in this set that is also a SQL SOURCE.\n"
            "    The queries are Spark SQL (`LIMIT n`), and the connection needs the same\n"
            "    warehouse and staging volume the destination side uses."
        ),
    },
}

# A plain SQL destination: `tables` + `if_table_exists`, no schema evolution.
SQL_DESTS = {
    "postgres": {
        "module": "tabsdatak.conn.postgres",
        "dest": "PostgresDest",
        "tpl": "postgres_sql_out.yaml",
        "type": "postgres_sql_out",
        "system": "postgres",
        "label": "PostgreSQL",
        "note": (
            "PostgreSQL takes every source decimal faithfully, but stores a tz-aware\n"
            "    timestamp NAIVE — the offset is dropped on the way in."
        ),
    },
    "mysql": {
        "module": "tabsdatak.conn.mysql",
        "dest": "MySQLDest",
        "tpl": "mysql_sql_out.yaml",
        "type": "mysql_sql_out",
        "system": "mysql",
        "label": "MySQL",
        "note": "MySQL is the closest match to the PostgreSQL behaviour here.",
    },
    "mssql": {
        "module": "tabsdatak.conn.mssql",
        "dest": "MSSQLDest",
        "tpl": "mssql_sql_out.yaml",
        "type": "mssql_sql_out",
        "system": "mssqlserver",
        "label": "SQL Server",
        "note": "SQL Server names may be `schema.table`; a bare name uses `dbo`.",
    },
    "oracle": {
        "module": "tabsdatak.conn.oracle",
        "dest": "OracleDest",
        "tpl": "oracle_sql_out.yaml",
        "type": "oracle_sql_out",
        "system": "oracle",
        "label": "Oracle",
        "note": (
            "Oracle folds unquoted identifiers to UPPERCASE, so `customers_append`\n"
            "    below creates a table called `CUSTOMERS_APPEND`. Double-quote the name\n"
            "    in `tables` to keep it lowercase. Oracle NUMBER is a single numeric\n"
            "    type, so an integer column may come back as a float on a later read."
        ),
    },
    "db2": {
        "module": "tabsdatak.conn.db2",
        "dest": "Db2Dest",
        "tpl": "db2_sql_out.yaml",
        "type": "db2_sql_out",
        "system": "db2",
        "label": "Db2",
        "note": (
            "Db2 folds unquoted identifiers to UPPERCASE, so these targets are created\n"
            "    as `CUSTOMERS_APPEND` and friends."
        ),
    },
}


def para(text: str, indent: int = 4, width: int = 79) -> str:
    """Re-wrap a one-paragraph note to fit under `width`, indented by `indent`.

    The notes in the tables above are written as flowing prose; where one is
    interpolated INTO a sentence in a docstring, its first line inherits that
    sentence's length and can overflow. Wrapping at emit time keeps every
    generated file readable at 80 columns without hand-counting in the table.
    """
    blocks = [
        textwrap.fill(
            " ".join(block.split()),
            width=width,
            initial_indent=" " * indent,
            subsequent_indent=" " * indent,
        )
        for block in text.split("\n\n")
        if block.strip()
    ]
    # Paragraph breaks in the source note are deliberate; only the line breaks
    # WITHIN a paragraph are re-flowed.
    return "\n\n".join(blocks).lstrip()


def w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def suite_json(name: str, comment: str, domains, collections, functions, triggers) -> dict:
    return {
        "_copyright": "Copyright 2026 Tabsdata Inc.",
        "_comment": comment,
        "domains": domains,
        "collections": collections,
        "functions": functions,
        "triggers": triggers,
    }


def coll(name: str, type_: str, tpl: str | None, group: str, domains: dict | None = None) -> dict:
    c: dict = {"name": name, "type": type_, "group": group}
    if tpl:
        c["connection_template"] = f"connection-file:connections/{tpl}"
    if domains:
        c["domains"] = domains
    return c


def fn(collection: str, suite: str, module: str, symbol: str) -> dict:
    return {
        "collection": collection,
        "functionpath": f"functions/{suite}/{module}.py::{symbol}",
    }


def trig(collection: str, function: str, detached: bool = True) -> dict:
    return {"collection": collection, "function": function, "detached": detached}


# ------------------------------------------------------------ file: sources --
def emit_file_src_paths(key: str, c: dict) -> tuple[str, dict]:
    """`<key>_src_paths` — WHICH files a publisher reads."""
    suite = f"{key}_src_paths"
    d = FN_DIR / suite
    src, mod = c["src"], c["module"]

    w(d / "supporting_generate_rows.py", COPYRIGHT + '''
"""SUPPORTING — not the example. Emits the three fixed frames this suite stages
as files, so the readers have something to read.

`DataGenSrc` carries its dataframes inline (base64 parquet on the wire) and is
backed by no external system, so a suite that needs input data costs one extra
no-op `dev` domain rather than a second real backend. It is SINGLE mode: one
frame per `Data`, so these parameters are plain frames, not lists.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            # Two same-shaped customer frames, so a wildcard has something to
            # union, and one differently-shaped orders frame, so a multi-path
            # read has two genuinely different tables.
            Data(pl.DataFrame({
                "id": [1, 2, 3],
                "name": ["Ada", "Grace", "Alan"],
                "country": ["GB", "US", "GB"],
            })),
            Data(pl.DataFrame({
                "id": [4, 5],
                "name": ["Edsger", "Barbara"],
                "country": ["NL", "US"],
            })),
            Data(pl.DataFrame({
                "order_id": [100, 101, 102],
                "customer_id": [1, 2, 4],
                "amount": [19.99, 250.00, 7.50],
            })),
        ]
    ),
    output_tables=["customers_2024", "customers_2025", "orders"],
)
def generate_rows(
    customers_2024: TableFrameSpec,
    customers_2025: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (customers_2024, customers_2025, orders)
''')

    w(d / "supporting_stage_csv_files.py", COPYRIGHT + f'''
"""SUPPORTING — not the example. Writes the two CSV files the readers in this
suite read back.

It runs REACTIVELY off the generator's publish — a subscriber needs no trigger of
its own — and the suite makes the generator's trigger a GATE (`"detached": false`),
so both files exist before any reader fires.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {c["dest"]}


@subscriber(
    destination={c["dest"]}(
        paths=["customers_2024.csv", "customers_2025.csv"],
        format=DestFileFormat.CSV,
    ),
    input_tables=["gen/customers_2024", "gen/customers_2025"],
)
def stage_csv_files(
    customers_2024: TableFrameSpec,
    customers_2025: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers_2024, customers_2025)
''')

    w(d / "supporting_stage_parquet_file.py", COPYRIGHT + f'''
"""SUPPORTING — not the example. Writes the one parquet file the multi-path
readers pair with the CSVs.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {c["dest"]}


@subscriber(
    destination={c["dest"]}(paths=["orders.parquet"], format=DestFileFormat.PARQUET),
    input_tables=["gen/orders"],
)
def stage_parquet_file(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
''')

    w(d / "read_fixed_path.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: ONE FIXED PATH.

`paths` declares one INPUT SLOT per entry, and every slot arrives as a LIST of
frames (`TableFramesSpec`) — one frame per file that entry matched. That holds
even for a path with no wildcard: this slot is a list of exactly one frame.

So a file publisher's parameter is ALWAYS a list, and the body always folds it.
`concat` of a one-element list is that element; writing it this way means the
body does not change if the path later grows a wildcard.

{c["conn_note"]}
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(paths=["customers_2024.csv"]),
    output_tables=["customers_2024"],
)
def read_fixed_path(customers: TableFramesSpec) -> TableFrameSpec:
    return concat(customers)
''')

    w(d / "read_wildcard.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: A WILDCARD PATH.

A `*` is allowed in the LAST path segment only (`a/b*.csv` is fine, `a*/b.csv`
is not). Both staged customer files match here, so the single slot carries two
frames and `concat` unions them into the one output table.

TWO THINGS TO GET RIGHT:

  * A WILDCARD IS A PREFIX MATCH. `customers_*` would also match
    `customers_archive_*` if such a file appeared. Pick a pattern nothing else
    can grow into, or accept whatever turns up.
  * `concat` defaults to `how="vertical"`, which REQUIRES identical schemas and
    fails loudly otherwise — the right default, because a file that does not fit
    the others is usually a mistake. Use `how="diagonal"` when the match set is
    genuinely heterogeneous: it takes the union of the columns and nulls the gaps.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(paths=["customers_*.csv"]),
    output_tables=["customers_all"],
)
def read_wildcard(customers: TableFramesSpec) -> TableFrameSpec:
    return concat(customers)
''')

    w(d / "read_multiple_paths.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: SEVERAL PATHS, folded into ONE table.

Two `paths` entries means TWO SLOTS — the same two files the wildcard example
matches by pattern, named explicitly instead. Each slot is its own list, so
folding across them means flattening both lists into one `concat`.

Choose explicit paths over a wildcard when the set is known and small: the read
then fails when a file is missing, instead of silently returning less data.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(paths=["customers_2024.csv", "customers_2025.csv"]),
    output_tables=["customers_union"],
)
def read_multiple_paths(
    year_2024: TableFramesSpec,
    year_2025: TableFramesSpec,
) -> TableFrameSpec:
    return concat([*year_2024, *year_2025])
''')

    w(d / "read_multiple_paths_split.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: SEVERAL PATHS, kept as SEPARATE tables.

The same two paths as `read_multiple_paths`, and the only difference is the
FOLD: one output table per slot instead of one table for both. That is the whole
choice a multi-path source gives you.

Output tables are POSITIONAL — `output_tables[i]` takes the i-th element of the
returned tuple, which is the i-th path. A file that is a different THING (a
different entity, a different schema) belongs in its own table; a file that is
more of the same belongs in the union.

ONE SOURCE READS ONE FORMAT. `format` — including the `AUTO` default — is
resolved for the SOURCE, not per path, so a `paths` list whose entries imply
different formats is rejected before it reads anything:

    Source format=AUTO could not be inferred from paths
    ['customers_2024.csv', 'orders.parquet']: mixed formats inferred

Which is why this reads the two CSVs and not the parquet staged beside them:
`orders.parquet` needs its OWN publisher. Worth knowing before designing a
landing zone that mixes formats in one directory.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(paths=["customers_2024.csv", "customers_2025.csv"]),
    output_tables=["customers_first", "customers_second"],
)
def read_multiple_paths_split(
    year_2024: TableFramesSpec,
    year_2025: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (concat(year_2024), concat(year_2025))
''')

    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} source / path selection — the four ways a file "
        f"publisher selects what it reads: one fixed path, one wildcard path, "
        f"several paths folded into ONE table, and the same several paths kept as "
        f"SEPARATE tables. Every file-source slot is an ARRAY (one frame per matched "
        f"file), so every reader folds with concat(). SELF-STAGING, one run, two "
        f"phases: the supporting_* functions generate three frames and write them as "
        f"customers_2024.csv / customers_2025.csv / orders.parquet, then the readers "
        f"read them back from the same domain. Ordering is the trigger list — "
        f"generate_rows is declared `detached: false`, which makes it a GATE whose "
        f"whole plan (publisher + both writers) completes before the readers fire. "
        f"One function per file under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite}`.",
        [
            {"name": "dev", "system": "dev"},
            {"name": f"{c['system']}_files", "system": c["system"]},
        ],
        [
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("stage", c["dest_type"], c["dest_tpl"], "destinations",
                 {"D0": f"{c['system']}_files"}),
            coll("files", c["src_type"], c["src_tpl"], "sources",
                 {"D0": f"{c['system']}_files"}),
        ],
        [
            fn("gen", suite, "supporting_generate_rows", "generate_rows"),
            fn("stage", suite, "supporting_stage_csv_files", "stage_csv_files"),
            fn("stage", suite, "supporting_stage_parquet_file", "stage_parquet_file"),
            fn("files", suite, "read_fixed_path", "read_fixed_path"),
            fn("files", suite, "read_wildcard", "read_wildcard"),
            fn("files", suite, "read_multiple_paths", "read_multiple_paths"),
            fn("files", suite, "read_multiple_paths_split", "read_multiple_paths_split"),
        ],
        [
            trig("gen", "generate_rows", detached=False),
            trig("files", "read_fixed_path"),
            trig("files", "read_wildcard"),
            trig("files", "read_multiple_paths"),
            trig("files", "read_multiple_paths_split"),
        ],
    )
    return suite, doc


def emit_file_src_formats(key: str, c: dict) -> tuple[str, dict]:
    """`<key>_src_formats` — the FILE FORMAT a publisher reads."""
    suite = f"{key}_src_formats"
    d = FN_DIR / suite
    src, mod, sysname = c["src"], c["module"], c["system"]

    shared = f'''A `{sysname}` domain seeded with the `world` model stages every entity in THREE
formats, one directory each — `csv/<entity>_<stamp>.csv`,
`ndjson/<entity>_<stamp>.ndjson`, `parquet/<entity>_<stamp>.parquet` — so the
three readers in this suite read the SAME rows three ways and differ in exactly
one field. The `<stamp>` is the staging time, which is why each path is a
wildcard.

A WILDCARD IS A PREFIX MATCH, and this model is a good reminder of what that
costs: `country_*` also matches `country_language_*`, so a slot you expected to
hold one file holds two — of 23 and 12 columns — and `concat` fails on the shape
rather than telling you the pattern was too wide. These readers use `city_*`,
which no other entity extends.'''

    w(d / "read_csv.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: reading CSV, with `format` named explicitly.

`format` chooses the reader: `AUTO` (the default) infers it from the file
extension, and `CSV` / `JSON` / `AVRO` / `PARQUET` / `LOG` name it outright. The
extension would have inferred CSV here too — it is spelled out so the three
readers in this suite differ in exactly one thing.

{shared}
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(paths=["csv/city_*.csv"], format=SrcFileFormat.CSV),
    output_tables=["city_from_csv"],
)
def read_csv(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
''')

    w(d / "read_ndjson.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: reading NDJSON, the case `AUTO` cannot infer.

`.ndjson` is newline-delimited JSON, which is exactly what the JSON reader
wants — but `AUTO` does not recognise that extension, so the format has to be
NAMED. This is the single most common file-source surprise, and the rule that
follows from it is: name `format` whenever the extension does not say (`.ndjson`,
`.txt`, `.dat`, no extension at all).

{shared}
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(paths=["ndjson/city_*.ndjson"], format=SrcFileFormat.JSON),
    output_tables=["city_from_json"],
)
def read_ndjson(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
''')

    w(d / "read_parquet.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: reading PARQUET, with nothing to configure.

No `format` at all: `AUTO` infers PARQUET from the extension. Parquet carries
its own schema and its own types, so there is no dialect to agree on and no
`format_cfg` to get wrong — which is why it is the format to prefer for anything
one Tabsdata function writes and another reads back.

{shared}
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(paths=["parquet/city_*.parquet"]),
    output_tables=["city_from_parquet"],
)
def read_parquet(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
''')

    w(d / "supporting_generate_products.py", COPYRIGHT + '''
"""SUPPORTING — not the example. A frame with a date and two nulls, so the CSV
dialect this suite writes and reads back has something to act on.
"""
from __future__ import annotations

from datetime import date

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "sku": ["A-1", "B-2", "C-3"],
                "released": [date(2024, 1, 15), date(2024, 6, 1), None],
                "price": [9.99, None, 42.0],
            }))
        ]
    ),
    output_tables=["products"],
)
def generate_products(products: TableFrameSpec) -> TableFrameSpec:
    return products
''')

    w(d / "supporting_stage_dialect_csv.py", COPYRIGHT + f'''
"""SUPPORTING — not the example, but half of the point: it writes the awkward
CSV that `read_csv_dialect` reads back, so the two `format_cfg` dicts can be
compared side by side.

`format_cfg` is SIDE-TYPED: these are WRITER keys, and passing one of them to a
source (or a reader key to a destination) fails validation at decoration time,
before anything runs.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {c["dest"]}


@subscriber(
    destination={c["dest"]}(
        paths=["products.csv"],
        format=DestFileFormat.CSV,
        format_cfg={{
            DestFileFormat.CSV: {{
                "separator": ";",
                "include_header": True,
                # The token this file uses for a missing value. Without it a null
                # is written as an empty field, which no reader can tell from an
                # empty string.
                "null_value": "NULL",
                "date_format": "%Y-%m-%d",
            }}
        }},
    ),
    input_tables=["gen/products"],
)
def stage_dialect_csv(products: TableFrameSpec) -> TableFrameSpec:
    return products
''')

    w(d / "read_csv_dialect.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: CONFIGURING THE CSV DIALECT with `format_cfg`.

`format_cfg` is keyed by the `SrcFileFormat` — `{{SrcFileFormat.CSV: {{...}}}}` —
and only CSV takes options; every other format maps to `{{}}` or is omitted.

The dict below is the mirror image of the one `supporting_stage_dialect_csv.py`
wrote with. GET ANY OF IT WRONG AND THE READ STILL SUCCEEDS: a wrong separator
gives one wide string column, a missing `null_values` gives the literal text
`"NULL"`, no `try_parse_dates` gives a string where a date belongs. A CSV dialect
mismatch is a silent-wrong-data bug, not an error — which is the reason to pin
the dialect on both sides rather than hope.

Reader keys, all optional: `separator`, `quote_char`, `eol_char`, `encoding`,
`null_values`, `missing_is_null`, `truncate_ragged_lines`, `comment_prefix`,
`try_parse_dates`, `decimal_comma`, `has_header`, `skip_rows`,
`skip_rows_after_header`, `raise_if_empty`, `ignore_errors`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(
        paths=["products.csv"],
        format=SrcFileFormat.CSV,
        format_cfg={{
            SrcFileFormat.CSV: {{
                "separator": ";",
                "has_header": True,
                "null_values": ["NULL"],
                "try_parse_dates": True,
                # Other reader keys worth knowing, left at their defaults here:
                #   "skip_rows": 2            skip N lines before the header
                #   "comment_prefix": "#"     drop lines starting with it
                #   "encoding": "utf8-lossy"  survive undecodable bytes
                #   "decimal_comma": True     European decimals (1,5 -> 1.5)
                #   "ignore_errors": True     null a bad field instead of failing
            }}
        }},
    ),
    output_tables=["products_roundtrip"],
)
def read_csv_dialect(products: TableFramesSpec) -> TableFrameSpec:
    # Round-trips to the frame the generator emitted: `released` is a date again
    # and the two missing values are nulls again, not the string "NULL".
    return concat(products)
''')

    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} source / formats — the `format` and `format_cfg` "
        f"fields. read_csv / read_ndjson / read_parquet read the SAME world-model rows "
        f"three ways and differ in exactly one field, including the case that matters: "
        f"`.ndjson` is newline-delimited JSON but AUTO cannot infer it, so the format "
        f"must be NAMED. read_csv_dialect then reads back an intentionally awkward CSV "
        f"(';' separator, 'NULL' null token, explicit date format) that a supporting "
        f"subscriber wrote with the mirror-image writer options — format_cfg is "
        f"side-typed, so a writer key on a source fails validation at decoration time, "
        f"and a dialect MISMATCH is a silent-wrong-data bug rather than an error. Note "
        f"the wildcard trap the world model exposes: `country_*` also matches "
        f"`country_language_*`, so these readers use `city_*`. One function per file "
        f"under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite}`.",
        [
            {"name": "dev", "system": "dev"},
            {"name": f"{c['system']}_world_xs", "system": c["system"],
             "model": "world", "data": "xs"},
            {"name": f"{c['system']}_files", "system": c["system"]},
        ],
        [
            coll("world", c["src_type"], c["src_tpl"], "sources",
                 {"D0": f"{c['system']}_world_xs"}),
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("stage", c["dest_type"], c["dest_tpl"], "destinations",
                 {"D0": f"{c['system']}_files"}),
            coll("custom", c["src_type"], c["src_tpl"], "sources",
                 {"D0": f"{c['system']}_files"}),
        ],
        [
            fn("world", suite, "read_csv", "read_csv"),
            fn("world", suite, "read_ndjson", "read_ndjson"),
            fn("world", suite, "read_parquet", "read_parquet"),
            fn("gen", suite, "supporting_generate_products", "generate_products"),
            fn("stage", suite, "supporting_stage_dialect_csv", "stage_dialect_csv"),
            fn("custom", suite, "read_csv_dialect", "read_csv_dialect"),
        ],
        [
            trig("gen", "generate_products", detached=False),
            trig("world", "read_csv"),
            trig("world", "read_ndjson"),
            trig("world", "read_parquet"),
            trig("custom", "read_csv_dialect"),
        ],
    )
    return suite, doc


def emit_file_src_lastmodified(key: str, c: dict) -> tuple[str, dict]:
    """`<key>_src_lastmodified` — incremental reads over file mtime."""
    suite = f"{key}_src_lastmodified"
    d = FN_DIR / suite
    src, mod = c["src"], c["module"]

    how = '''HOW THE CUTOFF WORKS
    `initial_last_modified` is compared against each candidate file's
    modification time:

      * FIRST run  — import every matched file modified at or after the cutoff.
      * LATER runs — the cutoff has ADVANCED to the newest file the previous run
        imported, so only strictly newer files come through.

    The framework persists the advanced cutoff on the function's transaction
    state, so the value in the decorator is only ever the SEED: editing it does
    NOT rewind a function that has already run.

    Pass a TIMEZONE-AWARE datetime. A naive one is ambiguous against file mtimes.

    This is the file-source analogue of the SQL `initial_values` watermark —
    same idea, except a file source advances the cutoff for you, where a SQL
    source hands you `ctx` to advance it yourself.'''

    drive = f'''DRIVING IT — run the project more than once
    1. `tdd xp one-shot --suite examples/{suite} --keep`
    2. Stage a NEW file into the domain (the data plane is insert-only: every
       `modify-data` writes a new, freshly stamped file next to the seed):
           tdd domain modify-data --domain <XP_ID>_{c["system"]}_world_xs \\\\
               --entity city --ops Insert --sets 5
    3. `tdd xp run-triggers --project <project> --monitor --time-out 30m`'''

    w(d / "read_since_cutoff.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: INCREMENTAL, `initial_last_modified` as a
moving cutoff.

{how}

The cutoff below is safely before anything this domain stages, so the first run
takes every matched file and each later run takes only what is newer.

{drive}
    This reader imports only the new file on the second run.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(
        paths=["parquet/city_*.parquet"],
        initial_last_modified=datetime(2000, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["city_new"],
)
def read_since_cutoff(city: TableFramesSpec) -> TableFrameSpec:
    # `concat` returns None for an empty list, so "no new files" publishes NO
    # version of the table at all — see read_future_cutoff.py.
    return concat(city)
''')

    w(d / "read_future_cutoff.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: WHEN NOTHING MATCHES, which is not an error.

A cutoff in the future matches nothing, on any run — the empty-slot path, pinned
here so it is deterministic and testable.

WHAT HAPPENS: the slot arrives as an EMPTY LIST, `concat` returns `None`, and a
publisher that returns `None` publishes NO new version of that table. Downstream
functions that depend on `@NEW` versions simply do not fire, which is exactly
what "nothing arrived this run" should mean.

DO NOT return an empty frame instead. That publishes a real, empty version and
DOES trigger downstream work — a different thing, and rarely the one you want.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(
        paths=["parquet/city_*.parquet"],
        initial_last_modified=datetime(2999, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["city_none"],
)
def read_future_cutoff(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
''')

    w(d / "read_every_run.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: NO CUTOFF, the full-reload contrast.

Without `initial_last_modified` every matched file is read on every run. That is
the right choice for a small reference dataset that is replaced wholesale, and
the wrong one for an append-only landing zone — where it means re-reading the
entire history to learn about one new file.

Run this suite twice and compare with `read_since_cutoff`: this table is rebuilt
from everything, that one grows by what arrived.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@publisher(
    source={src}(paths=["parquet/city_*.parquet"]),
    output_tables=["city_all"],
)
def read_every_run(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
''')

    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} source / incremental — `initial_last_modified`, the "
        f"file source's watermark: the first run imports every matched file at or "
        f"after the cutoff, then the cutoff ADVANCES so later runs import only what is "
        f"newer (persisted on the function's trx state, so the decorator value is only "
        f"the SEED and editing it does not rewind). Three publishers over the same "
        f"wildcard: read_since_cutoff (past cutoff -> incremental), read_future_cutoff "
        f"(future cutoff -> never matches, the empty-slot no-op where concat returns "
        f"None and NO version is published — versus returning an empty frame, which "
        f"publishes a real empty version and does trigger downstream), read_every_run "
        f"(no cutoff -> full reload). RUN IT TWICE to see the point: "
        f"`tdd domain modify-data --domain <XP_ID>_{c['system']}_world_xs --entity "
        f"city --ops Insert --sets 5` stages a new timestamped file, then run-triggers "
        f"again. One function per file under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite} --keep`.",
        [
            {"name": f"{c['system']}_world_xs", "system": c["system"],
             "model": "world", "data": "xs"},
        ],
        [
            coll("files", c["src_type"], c["src_tpl"], "sources",
                 {"D0": f"{c['system']}_world_xs"}),
        ],
        [
            fn("files", suite, "read_since_cutoff", "read_since_cutoff"),
            fn("files", suite, "read_future_cutoff", "read_future_cutoff"),
            fn("files", suite, "read_every_run", "read_every_run"),
        ],
        [
            trig("files", "read_since_cutoff"),
            trig("files", "read_future_cutoff"),
            trig("files", "read_every_run"),
        ],
    )
    return suite, doc


# ------------------------------------------------------- file: destinations --
def _supporting_customers(d: Path, note: str = "") -> None:
    """The datagen publisher every destination suite writes out."""
    w(d / "supporting_generate_customers.py", COPYRIGHT + f'''
"""SUPPORTING — not the example. The rows every sink in this suite writes.

Small and FIXED, which is what makes the write modes legible: re-run the project
and an `append` target grows by three rows while a `replace` target stays at
three. The frame carries a null, a date and a float so format and null handling
have something to act on.{note}
"""
from __future__ import annotations

from datetime import date

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({{
                "id": [1, 2, 3],
                "name": ["Ada", "Grace", "Alan"],
                "country": ["GB", "US", None],
                "signup_date": [date(2024, 1, 15), date(2024, 6, 1), date(2025, 2, 28)],
                "revenue": [1250.50, 98000.00, 42.75],
            }})),
            Data(pl.DataFrame({{
                "order_id": [100, 101, 102, 103],
                "customer_id": [1, 2, 1, 3],
                "amount": [19.99, 250.00, 7.50, 1300.00],
                "status": ["shipped", "shipped", "cancelled", "pending"],
            }})),
        ]
    ),
    output_tables=["customers", "orders"],
)
def generate_customers(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
''')


def emit_file_dest_formats(key: str, c: dict) -> tuple[str, dict]:
    suite = f"{key}_dest_formats"
    d = FN_DIR / suite
    dest, mod = c["dest"], c["module"]
    _supporting_customers(d)

    shape = f'''THE SHAPE OF A FILE DESTINATION
    `paths` declares one WRITE SLOT per entry, fed by `input_tables` in the SAME
    ORDER, and the function returns one frame per slot. A destination path names
    ONE file: no wildcards.

    {para(c["store_note"])}'''

    w(d / "write_parquet.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: PARQUET, with the format inferred.

No `format` at all: `AUTO` (the default) reads the `.parquet` extension. Parquet
carries its own schema and its own types, so the round trip is exact and there is
nothing to configure — the default choice for anything another Tabsdata function
will read back.

{shape}
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["customers.parquet"]),
    input_tables=["gen/customers"],
)
def write_parquet(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_avro.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: AVRO.

Like parquet, Avro carries its own schema and takes no `format_cfg`. Row-oriented
rather than columnar, so it suits a consumer that streams whole records; parquet
suits one that reads a few columns of many rows.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["customers.avro"], format=DestFileFormat.AVRO),
    input_tables=["gen/customers"],
)
def write_avro(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_json.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: JSON.

A TEXT format, so everything becomes a string on the way out and a reader has to
be told how to put it back. One thing to know: a tz-AWARE timestamp is written as
ISO-8601 in UTC (`2026-07-14T09:30:15Z`) whatever zone the column declared — the
instant is preserved, only the label is normalised — while a NAIVE timestamp is
written as-is with no offset. PARQUET and AVRO keep the column's own zone.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["customers.json"], format=DestFileFormat.JSON),
    input_tables=["gen/customers"],
)
def write_json(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_csv.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: CSV with the defaults.

Comma separated, header included, a null written as an EMPTY FIELD — which no
reader can tell from an empty string. That is the default worth knowing about,
and `write_csv_dialect.py` is how you fix it.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["customers.csv"], format=DestFileFormat.CSV),
    input_tables=["gen/customers"],
)
def write_csv(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_csv_dialect.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: CSV with `format_cfg`, for a consumer that
demands a particular dialect.

`format_cfg` is keyed by the `DestFileFormat` and only CSV takes options. It is
SIDE-TYPED: these are WRITER keys, and a READER key (`has_header`,
`try_parse_dates`, ...) here fails validation at decoration time — the two sides
are separate vocabularies.

Writer keys: `separator`, `quote_char`, `eol_char`, `include_header`,
`null_value`, `quote_style`, `date_format`, `time_format`, `datetime_format`,
`float_precision`, `float_scientific`, `maintain_order`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {dest}


@subscriber(
    destination={dest}(
        paths=["customers_dialect.csv"],
        format=DestFileFormat.CSV,
        format_cfg={{
            DestFileFormat.CSV: {{
                "separator": ";",
                "include_header": True,
                # An explicit null TOKEN, so "missing" stays distinguishable
                # from "empty string" — the most useful writer option there is.
                "null_value": "NULL",
                # Pin the rendering instead of taking the defaults.
                "date_format": "%d/%m/%Y",
                "float_precision": 2,
                # "necessary" (the default) quotes only what needs it; the
                # alternatives are "always", "non_numeric" and "never".
                "quote_style": "necessary",
            }}
        }},
    ),
    input_tables=["gen/customers"],
)
def write_csv_dialect(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_two_files.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: TWO FILES from one subscriber.

Two paths, two input tables, two returned frames — all POSITIONAL. Use one
subscriber when the files belong together (they are written in the same
transaction); use two when they do not, so one failing does not hold up the other.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {dest}


@subscriber(
    destination={dest}(
        paths=["customers_multi.csv", "orders_multi.csv"],
        format=DestFileFormat.CSV,
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_two_files(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
''')

    w(d / "write_nothing.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: RETURNING None, which writes NOTHING.

Not an empty file — no file. The write is not invoked at all, and any previous
file at that path is left exactly as it was.

That is the contract for "this run had nothing worth emitting", and it composes
with the source side: a publisher that returns `None` publishes no version, so
nothing downstream fires, so a sink like this one is never even reached.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["customers_skipped.csv"], format=DestFileFormat.CSV),
    input_tables=["gen/customers"],
)
def write_nothing(customers: TableFrameSpec) -> TableFrameSpec:
    return None
''')

    names = ["write_parquet", "write_avro", "write_json", "write_csv",
             "write_csv_dialect", "write_two_files", "write_nothing"]
    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} destination / formats — what a @subscriber writes. "
        f"`paths` declares one WRITE SLOT per entry, fed by input_tables in the same "
        f"order, one returned frame each; a destination path names ONE file (no "
        f"wildcards); a returned None writes NOTHING — no empty file, and the previous "
        f"file is left alone. Seven sinks over the same seeded table so only the format "
        f"differs: write_parquet (AUTO from the extension — exact types, nothing to "
        f"configure), write_avro, write_json (a text format; tz-aware timestamps are "
        f"normalised to UTC ISO-8601, where parquet/avro keep the column's zone), "
        f"write_csv (defaults — note a null becomes an EMPTY FIELD), write_csv_dialect "
        f"(writer format_cfg: separator, null_value, date_format, float_precision, "
        f"quote_style — side-typed, so a reader key here fails at decoration time), "
        f"write_two_files, write_nothing. One function per file under "
        f"functions/{suite}/. Run: `tdd xp one-shot --suite examples/{suite} --keep`.",
        [
            {"name": "dev", "system": "dev"},
            {"name": f"{c['system']}_out", "system": c["system"]},
        ],
        [
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("files", c["dest_type"], c["dest_tpl"], "destinations",
                 {"D0": f"{c['system']}_out"}),
        ],
        [fn("gen", suite, "supporting_generate_customers", "generate_customers")]
        + [fn("files", suite, n, n) for n in names],
        [trig("gen", "generate_customers")],
    )
    return suite, doc


def emit_file_dest_tokens(key: str, c: dict) -> tuple[str, dict]:
    suite = f"{key}_dest_tokens"
    d = FN_DIR / suite
    dest, mod = c["dest"], c["module"]
    _supporting_customers(d)

    tokens = f'''THE THREE TOKENS, substituted at WRITE time anywhere in a destination path

    ${{TRX_ID}}        the TRANSACTION id — the finest grain. One value per
                     committed transaction, so one file per write.
    ${{EXEC_PLAN_ID}}  the EXECUTION PLAN id — the whole plan a trigger started.
                     Several functions in one plan share it, so it GROUPS the
                     outputs of a single run.
    ${{EXEC_PLAN_TS}}  the plan's TIMESTAMP — sorts and reads chronologically,
                     which the opaque ids do not.

    They are the only tokens allowed; anything else in `${{...}}` is rejected when
    the descriptor is built, not at run time. And they are DESTINATION-only: a
    source path with a token in it is invalid, because a source globs rather than
    templates.

    {para(c["store_note"])}'''

    w(d / "write_per_transaction.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: ONE FILE PER TRANSACTION.

THE PROBLEM: a destination path is a fixed string, so a subscriber that writes
`customers.parquet` writes `customers.parquet` every run, each run replacing the
last. Fine for a "current state" export; useless for a landing zone, an audit
trail, or anything a downstream reader picks up incrementally.

{tokens}

`${{TRX_ID}}` in the FILENAME is the safe default for a landing zone: every write
is its own artefact, side by side in one directory — which is exactly the shape a
wildcard + `initial_last_modified` source consumes. These directories GROW;
nothing prunes them, and that is the trade for keeping history.

RUN THE PROJECT TWICE and watch files accumulate rather than be replaced.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["exports/customers_${{TRX_ID}}.parquet"]),
    input_tables=["gen/customers"],
)
def write_per_transaction(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_per_plan.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: ONE FOLDER PER RUN, with both files in it.

`${{EXEC_PLAN_ID}}` names the whole plan a trigger started, so every sink in the
same run resolves it to the same value. Putting it in the DIRECTORY position is
therefore how you group a run's outputs: this one subscriber writes two files
that land together, and any other sink in the same plan would land beside them.

Use `${{TRX_ID}}` when each write must be independently identifiable, and
`${{EXEC_PLAN_ID}}` when what matters is which run produced a set of files.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from {mod} import {dest}


@subscriber(
    destination={dest}(
        paths=[
            "runs/${{EXEC_PLAN_ID}}/customers.csv",
            "runs/${{EXEC_PLAN_ID}}/orders.csv",
        ],
        format=DestFileFormat.CSV,
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_per_plan(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
''')

    w(d / "write_per_timestamp.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: A CHRONOLOGICAL layout.

`${{EXEC_PLAN_TS}}` is the execution plan's timestamp, so it sorts correctly in a
plain listing — which the opaque ids do not. Reach for it whenever a human, a
`ls`, or a lexicographic key range has to find "the latest".
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["daily/${{EXEC_PLAN_TS}}/customers.parquet"]),
    input_tables=["gen/customers"],
)
def write_per_timestamp(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_archive.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: CHRONOLOGICAL **AND** UNIQUE.

Tokens compose, and more than one may appear in a path. `${{EXEC_PLAN_TS}}` as the
directory makes the archive browsable in time order; `${{TRX_ID}}` in the filename
guarantees two writes never collide inside one of those directories. This is the
belt-and-braces landing-zone layout.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["archive/${{EXEC_PLAN_TS}}/orders_${{TRX_ID}}.parquet"]),
    input_tables=["gen/orders"],
)
def write_archive(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
''')

    w(d / "write_latest.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: NO TOKEN, the deliberate contrast.

A fixed path is not a mistake — it is the right answer when what you want is one
file that always holds the current state, overwritten on every run. Point a
dashboard or a spreadsheet at this; point a pipeline at the token-written ones.

The two styles coexist happily in one suite, which is the point: pick per sink,
not per project.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(paths=["current/customers.parquet"]),
    input_tables=["gen/customers"],
)
def write_latest(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    names = ["write_per_transaction", "write_per_plan", "write_per_timestamp",
             "write_archive", "write_latest"]
    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} destination / path tokens — writing one file PER RUN "
        f"instead of overwriting the same one. A destination path is a fixed string, so "
        f"three substitution tokens are allowed anywhere in it and replaced at write "
        f"time: ${{TRX_ID}} (the transaction — finest grain, one file per write), "
        f"${{EXEC_PLAN_ID}} (the whole plan a trigger started — several sinks in one run "
        f"share it, so it GROUPS their outputs) and ${{EXEC_PLAN_TS}} (the plan "
        f"timestamp — sorts chronologically, which the opaque ids do not). Anything "
        f"else in ${{...}} is rejected when the descriptor is built; tokens are "
        f"DESTINATION-only. Five sinks: write_per_transaction (token in the filename), "
        f"write_per_plan (token as a directory, two files landing together), "
        f"write_per_timestamp, write_archive (both — chronological AND unique), "
        f"write_latest (no token: one always-current file, the deliberate contrast). "
        f"Token-written files are exactly what a wildcard + initial_last_modified "
        f"source consumes, and they GROW since nothing prunes them. RUN IT TWICE. One "
        f"function per file under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite} --keep`.",
        [
            {"name": "dev", "system": "dev"},
            {"name": f"{c['system']}_out", "system": c["system"]},
        ],
        [
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("files", c["dest_type"], c["dest_tpl"], "destinations",
                 {"D0": f"{c['system']}_out"}),
        ],
        [fn("gen", suite, "supporting_generate_customers", "generate_customers")]
        + [fn("files", suite, n, n) for n in names],
        [trig("gen", "generate_customers")],
    )
    return suite, doc


# -------------------------------------------------------------- sql: sources --
def emit_sql_src_queries(key: str, c: dict) -> tuple[str, dict]:
    suite = f"{key}_src_queries"
    d = FN_DIR / suite
    src, mod = c["src"], c["module"]

    rule = f'''THE ONE RULE FOR SQL SOURCES
    `queries` declares one INPUT SLOT per statement, and each slot arrives as a
    SINGLE frame (`TableFrameSpec`) — NOT a list. That is the opposite of a file
    source, where every slot is an array because one path may match many files.
    So a SQL publisher's parameters are plain frames with nothing to fold, and
    the i-th query feeds the i-th parameter and lands in the i-th
    `output_tables` entry.

    Queries must be SELECTs. The connector reads them; it does not run DDL/DML.

{c["label"].upper()} SPECIFICS
    {para(c["note"])}'''

    upper_note = (
        "\n\n    NOTE the frames come back with UPPERCASE column names (`CODE`, `NAME`,\n"
        "    ...), because the identifiers in these queries are unquoted. Alias them\n"
        "    (`SELECT code AS \"code\"`) if downstream code should stay dialect-neutral."
        if c["upper"] else ""
    )

    w(d / "read_one_query.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: ONE QUERY, one table.

{rule}{upper_note}

A NOTE ON OUTPUT-TABLE NAMES, since this suite has five publishers in one
collection: a table name is unique per COLLECTION, and `fn register` rejects a
function whose `output_tables` collide with a table another function already
owns. That is why this one is `country_only` rather than `country` — which
`read_many_queries` claims.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from {mod} import {src}


@publisher(
    source={src}(queries=["SELECT * FROM country"]),
    output_tables=["country_only"],
)
def read_one_query(country: TableFrameSpec) -> TableFrameSpec:
    return country
''')

    w(d / "read_many_queries.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: SEVERAL QUERIES, one table each.

Three queries, three slots, three tables — all positional. `transactional`
defaults to `True`, so all three run in ONE session and see ONE consistent
snapshot of the database: the three tables cannot disagree with each other, even
if the data changes mid-read.

That consistency is the reason to put related reads in ONE publisher rather than
three. Split them when they are genuinely independent, so one failing does not
hold up the others.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from {mod} import {src}


@publisher(
    source={src}(
        queries=[
            "SELECT * FROM country",
            "SELECT * FROM city",
            "SELECT * FROM country_language",
        ],
    ),
    output_tables=["country", "city", "country_language"],
)
def read_many_queries(
    country: TableFrameSpec,
    city: TableFrameSpec,
    language: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (country, city, language)
''')

    w(d / "read_without_transaction.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: `transactional=False`.

Each query gets its OWN connection and autocommits independently, instead of
sharing one transactional session. Cheaper and friendlier to a busy server —
and the queries can see different states of the database, which is precisely
what the default protects you from.

Use it when the reads have no consistency requirement between them, as here.
Keep the default when they do.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from {mod} import {src}


@publisher(
    source={src}(
        queries=[
            "SELECT code, name FROM country",
            "SELECT id, name FROM city",
        ],
        transactional=False,
    ),
    output_tables=["country_slim", "city_slim"],
)
def read_without_transaction(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (country, city)
''')

    w(d / "read_with_type_hints.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: `schema_overrides`, per-query dtype hints.

ONE ENTRY PER QUERY, in the same order, and the lengths must match — `None`
leaves that query's schema fully inferred, a dict overrides only the columns it
names.

Reach for it when the driver infers something you do not want: a zero-padded
code that should stay a string, a wide integer you would rather have as a float,
a numeric whose precision differs by database. It is a READ-side cast, so it
costs nothing downstream and keeps the table's schema stable across connectors.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.common.sql.types import DataType
from {mod} import {src}


@publisher(
    source={src}(
        queries=[
            "SELECT code, name, population FROM country",
            "SELECT id, name FROM city",
        ],
        schema_overrides=[
            {{"population": DataType.FLOAT}},
            None,
        ],
    ),
    output_tables=["country_typed", "city_untyped"],
)
def read_with_type_hints(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # `country.population` arrives as a float rather than the inferred integer.
    return (country, city)
''')

    w(d / "read_no_rows.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: WHEN THE QUERY MATCHES NOTHING.

Zero rows means the slot arrives as `None`, and returning `None` publishes NO new
version of the table. Downstream `@NEW` dependants do not fire — which is what
"nothing arrived this run" should mean.

Returning an EMPTY FRAME instead publishes a real, empty version and DOES trigger
downstream work. Both are legitimate; pick deliberately.

The body is written the long way to make the contract visible. In real code
`return city` does the same thing, because the slot is already `None`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from {mod} import {src}


@publisher(
    source={src}(queries=["SELECT * FROM city WHERE 1 = 0"]),
    output_tables=["city_empty"],
)
def read_no_rows(city: TableFrameSpec) -> TableFrameSpec:
    if city is None:
        return None
    return city
''')

    names = ["read_one_query", "read_many_queries", "read_without_transaction",
             "read_with_type_hints", "read_no_rows"]
    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} source / queries — what a SQL publisher runs. Unlike a "
        f"file source, a SQL source is SINGLE mode: one frame per query slot, never a "
        f"list, and query i feeds parameter i and lands in output_tables[i]. Five "
        f"publishers over a {c['system']} domain seeded with the world model: "
        f"read_one_query, read_many_queries (three queries in ONE session, so the three "
        f"tables cannot disagree — the reason to group related reads), "
        f"read_without_transaction (transactional=False: a connection and an autocommit "
        f"per query, no cross-query consistency), read_with_type_hints "
        f"(schema_overrides: one {{column: DataType}} entry per query, None to leave one "
        f"inferred), read_no_rows (the slot is None -> publish NO version, versus "
        f"publishing an empty one). Also note table names are unique per COLLECTION, "
        f"which is why read_one_query's output is `country_only`. One function per file "
        f"under functions/{suite}/. Run: `tdd xp one-shot --suite examples/{suite}`.",
        [
            {"name": f"{c['system']}_world_xs", "system": c["system"],
             "model": "world", "data": "xs"},
        ],
        [coll("db", c["type"], c["tpl"], "sources", {"D0": f"{c['system']}_world_xs"})],
        [fn("db", suite, n, n) for n in names],
        [trig("db", n) for n in names],
    )
    return suite, doc


def emit_sql_src_incremental(key: str, c: dict) -> tuple[str, dict]:
    suite = f"{key}_src_incremental"
    d = FN_DIR / suite
    src, mod = c["src"], c["module"]
    col_id = "ID" if c["upper"] else "id"
    col_pop = "POPULATION" if c["upper"] else "population"
    case_note = (
        f"\n    So `max_for` below must be given `\"{col_id}\"`, not `\"id\"` — and a\n"
        f"    watermark reader copy-pasted from a lowercase dialect fails at RUN time,\n"
        f"    with a column-not-found, rather than at registration."
        if c["upper"] else ""
    )

    pieces = f'''THE THREE PIECES
    1. BIND the watermark into the SQL as `:name` — a real, typed statement
       parameter, never string interpolation. No injection, no quoting, no
       dialect-specific literal formatting.
    2. SEED it with `initial_values`. This is the FIRST-RUN value ONLY: on every
       run the plugin reads `ctx.get_attr(name)` first and falls back to the seed
       when the store has no entry — so editing the seed later does NOT rewind a
       function that has already run.
    3. ADVANCE it from the batch you just read, with `ctx.set_attr`. The value
       persists on the flow's scratch state across transactions.

    A function that wants `ctx` just declares a parameter named `ctx`, after the
    table slots. (A `@stream_publisher` may NOT declare one.)

    `{c["limit"]}` is this dialect's row limit.

    {c["note"]}{case_note}'''

    w(d / "read_watermark_by_id.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: THE INCREMENTAL READ, one page per run.

{pieces}

GETTING THE NEW WATERMARK: `max_for()` returns the requested columns OF THE
TOP-RANKING ROW as a `{{column: value}}` dict, or `None` when the frame is empty.
Read it off THE DATA YOU ACTUALLY PUBLISHED, never off a separate
`SELECT max(...)`: a second query could see rows this batch did not, and those
rows would be skipped forever.

`ORDER BY` is not optional. Without it "the next 10 rows" is undefined and a
paging read silently loses data.

RUN THE PROJECT SEVERAL TIMES and watch the table grow by one page each time.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TrxCtx, publisher
from {mod} import {src}


@publisher(
    source={src}(
        queries=[
            "SELECT * FROM city WHERE id > :wm "
            "ORDER BY id {c["limit"]}"
        ],
        initial_values={{"wm": 0}},
    ),
    output_tables=["city_page"],
)
def read_watermark_by_id(city: TableFrameSpec, ctx: TrxCtx) -> TableFrameSpec:
    if city is None:
        return None
    top = city.max_for("{col_id}")
    if top is not None and top["{col_id}"] is not None:
        ctx.set_attr("wm", int(top["{col_id}"]))
    return city
''')

    w(d / "read_composite_watermark.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: A COMPOSITE CURSOR.

`max_for` takes SEVERAL columns and ranks by them in order — the first is
primary, each next one breaks ties on the previous — and returns them all from
the winning row. That is what a `(timestamp, id)` cursor needs: paging a table
whose timestamps are not unique requires both halves, and one call gets them.

A NOTE ON TIMESTAMP CURSORS: a seed, and anything `ctx.set_attr` stores, must be
a BASIC value (str / int / float / bool). So a datetime cursor travels as an
ISO-8601 STRING and the database casts it back:

    queries=["SELECT * FROM orders WHERE updated_at > CAST(:since AS timestamp) "
             "ORDER BY updated_at, id {c["limit"]}"],
    initial_values={{"since": "2024-01-01T00:00:00+00:00"}},
    ...
    top = orders.max_for("updated_at", "id")
    ctx.set_attr("since", top["updated_at"].isoformat())

The world sample has no timestamp column, so the live version below ranks by id
and reports population alongside it.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TrxCtx, publisher
from {mod} import {src}


@publisher(
    source={src}(
        queries=[
            "SELECT id, name, country_code, population FROM city "
            "WHERE id > :since ORDER BY id {c["limit"]}"
        ],
        initial_values={{"since": 0}},
    ),
    output_tables=["city_since"],
)
def read_composite_watermark(city: TableFrameSpec, ctx: TrxCtx) -> TableFrameSpec:
    if city is None:
        return None
    top = city.max_for("{col_id}", "{col_pop}")
    if top is not None and top["{col_id}"] is not None:
        ctx.set_attr("since", int(top["{col_id}"]))
    return city
''')

    w(d / "read_several_binds.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: SEVERAL BINDS, only one of them a watermark.

`initial_values` may seed any number of binds, and they do not all have to move.
`:min_pop` here is a CONSTANT this flow keeps in its own state: it is seeded once
and never written back, so every run falls back to the seed — which means it can
be re-tuned at run time with `ctx.set_attr` WITHOUT re-registering the function.

That is the useful half of the idea: a bind is a knob, not only a cursor.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TrxCtx, publisher
from {mod} import {src}


@publisher(
    source={src}(
        queries=[
            "SELECT * FROM city WHERE id > :wm AND population >= :min_pop "
            "ORDER BY id {c["limit5"]}"
        ],
        initial_values={{"wm": 0, "min_pop": 1000000}},
    ),
    output_tables=["big_city_page"],
)
def read_several_binds(city: TableFrameSpec, ctx: TrxCtx) -> TableFrameSpec:
    if city is None:
        return None
    top = city.max_for("{col_id}")
    if top is not None and top["{col_id}"] is not None:
        # Only `wm` is advanced; `min_pop` keeps falling back to its seed.
        ctx.set_attr("wm", int(top["{col_id}"]))
    return city
''')

    w(d / "read_always_empty.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} source: THE NO-RESULTS RULE, which is the one that bites.

This query can never return a row, so the empty path runs on EVERY run rather
than only once the table is drained.

WHEN THE BATCH IS EMPTY:

  * Do NOT call `ctx.set_attr`. Leave the watermark where it is. It STALLS at
    the last value, which is correct — the next run re-runs the same `WHERE` and
    picks up whatever arrived since.
  * Do NOT write a fallback like `ctx.set_attr("wm", 0)` in the empty branch.
    That REWINDS the cursor and re-ingests everything, forever, every time the
    source goes quiet. This is the single most common incremental bug, and it
    only shows up in production, where sources go quiet.
  * Return `None`, so no version of the table is published.

`max_for` returning `None`, and the column being `None` inside the returned dict,
are two different empties — the guard below checks both.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TrxCtx, publisher
from {mod} import {src}


@publisher(
    source={src}(
        queries=["SELECT * FROM city WHERE id > :wm AND 1 = 0"],
        initial_values={{"wm": 0}},
    ),
    output_tables=["city_never"],
)
def read_always_empty(city: TableFrameSpec, ctx: TrxCtx) -> TableFrameSpec:
    if city is None:
        return None
    top = city.max_for("{col_id}")
    if top is not None and top["{col_id}"] is not None:
        ctx.set_attr("wm", int(top["{col_id}"]))
    return city
''')

    names = ["read_watermark_by_id", "read_composite_watermark",
             "read_several_binds", "read_always_empty"]
    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} source / incremental — a parameterised query with a "
        f"persisted watermark. THE THREE PIECES: bind the cursor as `:name` (a typed "
        f"statement parameter, never string interpolation); seed it with initial_values "
        f"(FIRST RUN ONLY — every run reads ctx.get_attr first and falls back, so "
        f"editing the seed does not rewind); advance it with ctx.set_attr from the batch "
        f"you just published, reading the new value with max_for() (the top-ranking "
        f"row's columns as a dict; several columns = a composite cursor). THE "
        f"NO-RESULTS RULE is read_always_empty: when the slot is None leave the "
        f"watermark ALONE and return None — a `set_attr(wm, 0)` fallback in that branch "
        f"is the classic bug that re-ingests everything every time the source goes "
        f"quiet. Four publishers: read_watermark_by_id (one page per run — RUN IT "
        f"REPEATEDLY), read_composite_watermark, read_several_binds (a bind as a "
        f"re-tunable knob, not only a cursor), read_always_empty. Dialect: "
        f"`{c['limit']}`. One function per file under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite} --keep`, then run-triggers again.",
        [
            {"name": f"{c['system']}_world_xs", "system": c["system"],
             "model": "world", "data": "xs"},
        ],
        [coll("db", c["type"], c["tpl"], "sources", {"D0": f"{c['system']}_world_xs"})],
        [fn("db", suite, n, n) for n in names],
        [trig("db", n) for n in names],
    )
    return suite, doc


# --------------------------------------------------------- sql: destinations --
def emit_sql_dest_modes(key: str, c: dict) -> tuple[str, dict]:
    suite = f"{key}_dest_modes"
    d = FN_DIR / suite
    dest, mod = c["dest"], c["module"]
    _supporting_customers(d)

    shape = f'''THE SHAPE OF A SQL DESTINATION
    `tables` declares one WRITE SLOT per entry, fed by `input_tables` in the SAME
    ORDER, and the function returns one frame per slot. Names may be bare or
    qualified; a bare name resolves against the connection's default schema.

{c["label"].upper()} SPECIFICS
    {para(c["note"])}'''

    w(d / "write_append.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: `if_table_exists="append"`.

INSERT the rows. The table keeps growing across runs, and if it does not exist it
is CREATED on the first write.

APPEND IS NOT AN UPSERT. There is no key matching, no merge, and no delete of
rows this run did not produce — re-running this publishes the same three rows
again. An event log wants `append`; a table that mirrors a source of truth wants
`replace`; a real upsert is built downstream, not here.

{shape}

RE-RUN THE PROJECT and compare with `write_replace`: this target grows by three
rows each time, that one stays at three.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(tables=["customers_append"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_replace.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: `if_table_exists="replace"`.

TRUNCATE the table, then insert. The row count is whatever this run produced,
however often it runs — the mode for a table that mirrors a source of truth.

WHEN COLUMN TYPES ARE DECIDED: only when the target is CREATED — that is, under
`replace`, or under `append` into a table that does not exist yet. Writing into
an EXISTING table uses that table's columns and types, and a frame that does not
fit fails the write. So either create the table yourself with the DDL you want,
or let the first write create it and accept the connector's type mapping
(`TYPE_MAPPING.md` in `tabsdata-conn-common-sql` is the per-database matrix).

A separate target from the append example, so both can fire off the same publish.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(tables=["customers_replace"], if_table_exists="replace"),
    input_tables=["gen/customers"],
)
def write_replace(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_two_tables.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: TWO TABLES IN ONE WRITE, atomically.

Two names, two input tables, two returned frames — positional. `transactional`
defaults to `True` (spelled out here), which wraps EVERY table's write in one
transaction: either both targets are written or neither is.

That is the reason to put related targets in one subscriber. Two subscribers
would write independently, and a failure between them would leave the pair
inconsistent.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(
        tables=["customers_both", "orders_both"],
        if_table_exists="replace",
        transactional=True,
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_two_tables(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
''')

    w(d / "write_without_transaction.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: `transactional=False`, and `dest_cfg`.

Commits per table instead of wrapping the write in one transaction: faster, and
it holds fewer locks for less time — at the price of partial results when one
table fails.

`dest_cfg` tunes the write itself. `tabsdata.sql.chunk_size` is the knob that
matters for a big load: it sets how many rows go per round trip, trading memory
for fewer, larger statements.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(
        tables=["orders_fast"],
        if_table_exists="replace",
        transactional=False,
        dest_cfg={{"tabsdata.sql.chunk_size": 50000}},
    ),
    input_tables=["gen/orders"],
)
def write_without_transaction(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
''')

    w(d / "write_nothing.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: RETURNING None.

The write is NOT invoked for that slot: nothing is inserted — and, importantly,
nothing is TRUNCATED either. A `replace` sink that returns `None` leaves the
target's previous contents exactly as they were, rather than emptying it.

That asymmetry is the useful part: "no data this run" never destroys what is
already there.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(tables=["customers_append"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_nothing(customers: TableFrameSpec) -> TableFrameSpec:
    return None
''')

    names = ["write_append", "write_replace", "write_two_tables",
             "write_without_transaction", "write_nothing"]
    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} destination / write modes. `tables` declares one WRITE "
        f"SLOT per entry, fed by input_tables in the same order. if_table_exists is the "
        f"one decision: \"append\" (default) inserts and the table grows across runs, "
        f"\"replace\" truncates then inserts so the count stays put — and NEITHER is an "
        f"upsert (no key matching, no merge). Both CREATE the table when it is missing, "
        f"which is also the only moment column types are decided: writing into an "
        f"existing table uses that table's types. transactional=True (default) makes a "
        f"multi-table write all-or-nothing; False commits per table. A returned None "
        f"skips the write and does NOT truncate, so 'no data this run' never destroys "
        f"what is there. Five sinks: write_append, write_replace, write_two_tables, "
        f"write_without_transaction (+ dest_cfg chunk size), write_nothing. RE-RUN to "
        f"watch customers_append grow while customers_replace stays at three rows. One "
        f"function per file under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite} --keep`.",
        [
            {"name": "dev", "system": "dev"},
            {"name": f"{c['system']}_out", "system": c["system"]},
        ],
        [
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("db", c["type"], c["tpl"], "destinations", {"D0": f"{c['system']}_out"}),
        ],
        [fn("gen", suite, "supporting_generate_customers", "generate_customers")]
        + [fn("db", suite, n, n) for n in names],
        [trig("gen", "generate_customers")],
    )
    return suite, doc


# --------------------------------------------------- warehouse destinations --
WAREHOUSE_DESTS = {
    "snowflake": {
        "module": "tabsdatak.conn.snowflake",
        "dest": "SnowflakeDest",
        "tpl": "snowflake_bulk_out.yaml",
        "type": "snowflake_bulk_out",
        "system": "snowflake",
        "label": "Snowflake",
        "quote": lambda n: n,
        "staging": "Snowflake ingests through a STAGE: the frame is written there and   `PUT` + `COPY INTO` load it. The connection's `stage` is optional — when unset the plugin creates a session-scoped   TEMPORARY stage, so there is nothing to provision.",
        "note": (
            "Snowflake folds unquoted identifiers to UPPERCASE, so `customers_append`\n"
            "    below creates `CUSTOMERS_APPEND`. Double-quote the name in `tables` to\n"
            "    keep it lowercase. Snowflake has NO `schema_evolution` field: append and\n"
            "    replace are the whole vocabulary."
        ),
    },
    "databricks": {
        "module": "tabsdatak.conn.databricks",
        "dest": "DatabricksDest",
        "tpl": "databricks_bulk_out.yaml",
        "type": "databricks_bulk_out",
        "system": "databricks",
        "label": "Databricks",
        "quote": lambda n: n,
        "staging": "Databricks ingests through a VOLUME: the frame is written there and   `COPY INTO` loads it. The connection's `volume` MUST already exist — a missing volume is the single most   common first-run failure on this connector.",
        "note": (
            "Target names are completed from the connection's `catalog` / `schema`, so\n"
            "    `customers_append` is really `<catalog>.<schema>.customers_append`.\n"
            "    Databricks also has `schema_evolution` (default `\"update\"`) — see the\n"
            "    databricks_dest_evolution suite."
        ),
    },
    "clickhouse": {
        "module": "tabsdatak.conn.clickhouse",
        "dest": "ClickHouseDest",
        "tpl": "clickhouse_bulk_out_s3.yaml",
        "type": "clickhouse_bulk_out_s3",
        "system": "clickhouse",
        "label": "ClickHouse",
        "quote": lambda n: n,
        "staging_domain": "s3",
        # No multi-table sink: staging a second table in the same write leaves
        # ClickHouse reading a key that is not there (see the note below).
        "multi_table": False,
        "staging": 'ClickHouse ingests from an OBJECT STORE: the connection carries a `staging` block   (bucket + credentials + base path) and the server reads the staged parquet itself.   This suite stages through S3; `clickhouse_bulk_out_gcs.yaml` and `_az.yaml` are the   same connector with a different staging store.',
        "note": (
            "ClickHouse 24.8 has no time-of-day and no interval type, so a `Time`\n"
            "    column becomes a `DateTime64` on the sentinel date 1970-01-01 and a\n"
            "    `Duration` becomes an `Int64` in the source column's own unit.\n"
            "    `schema_evolution` defaults to `\"strict\"` here — see the\n"
            "    clickhouse_dest_evolution suite.\n\n"
            "    ONE TARGET PER SUBSCRIBER. This suite has no two-table sink, unlike\n"
            "    the other warehouses, because writing a SECOND table from the same\n"
            "    subscriber fails: `Code: 499 ... The specified key does not exist:\n"
            "    while reading key <prefix>/out_1.parquet`. The server is pointed at a\n"
            "    staged object that is not there. Give each target its own subscriber."
        ),
    },
    "bigquery": {
        "module": "tabsdatak.conn.bigquery",
        "dest": "BigQueryDest",
        "tpl": "bigquery_bulk_out.yaml",
        "type": "bigquery_bulk_out",
        "system": "bigquery",
        "label": "BigQuery",
        "quote": lambda n: f"`{n}`",
        "staging": 'BigQuery ingests from a GCS bucket named on the connection, which also   carries the service-account key, the project and the dataset.',
        "note": (
            "NOTE THE BACKTICKS. BigQuery wraps the WHOLE name in ONE backtick pair —\n"
            "    `my-project.dataset.table` — rather than quoting each part, which is what\n"
            "    lets a project id containing hyphens round-trip. Every other connector\n"
            "    here quotes per part, or not at all. Partial names are completed from the\n"
            "    connection's `project` / `dataset`."
        ),
    },
}


def emit_warehouse_dest_modes(key: str, c: dict) -> tuple[str, dict]:
    suite = f"{key}_dest_modes"
    d = FN_DIR / suite
    dest, mod, q = c["dest"], c["module"], c["quote"]
    _supporting_customers(d)

    preamble = f'''A BULK DESTINATION ADDS A STAGING HOP. These connectors do not INSERT row by
row: they write the frame to a staging area and have the warehouse ingest it,
which is why they load fast and why they have a prerequisite a plain database
does not.

    {para(c["staging"])}

{c["label"].upper()} SPECIFICS
    {para(c["note"])}'''

    w(d / "write_append.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: `if_table_exists="append"`.

INSERT the rows; the table grows across runs, and is CREATED if missing. Not an
upsert — no key matching, no merge. Re-running publishes the same rows again.

{preamble}
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(tables=["{q("customers_append")}"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_replace.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: `if_table_exists="replace"`.

Overwrite the table: the row count is whatever this run produced, however often
it runs. The mode for a mirror of a source of truth.

Column types are decided ONLY when the target is created — under `replace`, or
under `append` into a missing table. Writing into an existing table uses that
table's types, and a frame that does not fit fails the write.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(tables=["{q("customers_replace")}"], if_table_exists="replace"),
    input_tables=["gen/customers"],
)
def write_replace(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_two_tables.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: TWO TABLES from one subscriber.

Two names, two input tables, two returned frames — positional. Each is staged and
loaded in turn, so grouping them here mostly buys you one function to schedule and
one place to fail, rather than the atomicity a transactional SQL destination gives.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(
        tables=["{q("customers_both")}", "{q("orders_both")}"],
        if_table_exists="replace",
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_two_tables(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
''')

    w(d / "write_nothing.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} destination: RETURNING None.

Nothing is staged and nothing is loaded — and a `replace` target is NOT emptied.
"No data this run" leaves the warehouse exactly as it was, which also means no
staging cost for a run with nothing to say.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(tables=["{q("customers_append")}"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_nothing(customers: TableFrameSpec) -> TableFrameSpec:
    return None
''')

    names = ["write_append", "write_replace", "write_two_tables", "write_nothing"]
    if c.get("multi_table") is False:
        (d / "write_two_tables.py").unlink(missing_ok=True)
        names.remove("write_two_tables")
    domains = [
        {"name": "dev", "system": "dev"},
        {"name": f"{c['system']}_out", "system": c["system"]},
    ]
    dmap = {"D0": f"{c['system']}_out"}
    if c.get("staging_domain"):
        domains.append({"name": "stage_store", "system": c["staging_domain"]})
        dmap["D1"] = "stage_store"

    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} destination / write modes. The shape is the "
        f"SQL-destination one (one write slot per `tables` entry, append vs replace, a "
        f"returned None skipping the write without truncating, types decided only when "
        f"the table is created). What a BULK destination adds is a STAGING HOP — the "
        f"frame is written to a staging area and the warehouse ingests it, which is why "
        f"these load fast and why they have a prerequisite a plain database does not. "
        f"Four sinks: write_append, write_replace, write_two_tables, write_nothing. One "
        f"function per file under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite} --keep`.",
        domains,
        [
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("warehouse", c["type"], c["tpl"], "destinations", dmap),
        ],
        [fn("gen", suite, "supporting_generate_customers", "generate_customers")]
        + [fn("warehouse", suite, n, n) for n in names],
        [trig("gen", "generate_customers")],
    )
    return suite, doc


def emit_starrocks_dest_modes() -> tuple[str, dict]:
    """StarRocks is the destination that CANNOT create its target, so its write
    modes are a different example rather than a rename of the generic one."""
    suite = "starrocks_dest_modes"
    d = FN_DIR / suite

    w(d / "supporting_generate_world_rows.py", COPYRIGHT + '''
"""SUPPORTING — not the example, but the reason this suite looks different.

StarRocks does NOT create tables on write: the connector only issues `TRUNCATE`
(for replace) plus `INSERT INTO <t> (<cols>) SELECT * FROM FILES(...)`. So the
targets must ALREADY EXIST, and the frames must match their DDL.

This suite therefore writes into the tables the `world` model already seeded in
the backing domain, and the frames below are world-shaped. Only the NOT NULL
columns are emitted — the connector names the columns it loads from the staged
parquet, so the nullable ones are simply left NULL.

`city.id` is AUTO_INCREMENT and is deliberately omitted, so every append gets
FRESH keys and the row count GROWS. `country`'s primary key is `code`, so
appending the same codes would upsert in place instead — which is why the append
example targets `city` and the replace example targets `country`.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "code": ["USA", "ESP", "JPN"],
                "name": ["United States", "Spain", "Japan"],
                "continent": ["North America", "Europe", "Asia"],
                "region": ["North America", "Southern Europe", "Eastern Asia"],
                "surface_area": [9363520.0, 505992.0, 377829.0],
                "population": [331002651, 47351567, 125836021],
                "local_name": ["United States", "Espana", "Nippon"],
                "government_form": [
                    "Federal Republic",
                    "Constitutional Monarchy",
                    "Constitutional Monarchy",
                ],
                "code2": ["US", "ES", "JP"],
            })),
            Data(pl.DataFrame({
                "name": ["Washington", "Madrid", "Tokyo"],
                "country_code": ["USA", "ESP", "JPN"],
                "district": ["District of Columbia", "Madrid", "Tokyo-to"],
                "population": [689545, 3223334, 13929286],
            })),
        ]
    ),
    output_tables=["world_country", "world_city"],
)
def generate_world_rows(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (country, city)
''')

    w(d / "write_append.py", COPYRIGHT + '''
"""EXAMPLE — StarRocks destination: `if_table_exists="append"` into a table that
already exists.

The target is the `city` table the `world` model seeded, because StarRocks CANNOT
CREATE A TABLE ON WRITE (see supporting_generate_world_rows.py). That single fact
is what makes this connector's write modes worth their own example: `append` and
`replace` mean the same as everywhere else, but "the table does not exist yet" is
an error rather than a create.

`city.id` is AUTO_INCREMENT and the frame omits it, so each run inserts rows with
FRESH keys and the count GROWS — 100 seeded, +3 per run.

STAGING: StarRocks loads from an OBJECT STORE named on the connection. This suite
stages through S3; `starrocks_bulk_out_gcs.yaml` and `_az.yaml` are the same
connector with a different staging store.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.starrocks import StarRocksDest


@subscriber(
    destination=StarRocksDest(tables=["city"], if_table_exists="append"),
    input_tables=["gen/world_city"],
)
def write_append(city: TableFrameSpec) -> TableFrameSpec:
    return city
''')

    w(d / "write_replace.py", COPYRIGHT + '''
"""EXAMPLE — StarRocks destination: `if_table_exists="replace"`.

TRUNCATE + reload, so the count STAYS at three from the first run on — the 239
seeded countries are truncated away, which is worth knowing before pointing this
at anything you care about.

WHY THIS TARGET AND NOT `city`: `country`'s primary key is `code`, so an APPEND
of the same three codes would upsert in place and the count would never move —
a confusing demonstration. Append belongs on the AUTO_INCREMENT table, replace on
the keyed one. StarRocks' Primary Key model is what makes the choice matter.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.starrocks import StarRocksDest


@subscriber(
    destination=StarRocksDest(tables=["country"], if_table_exists="replace"),
    input_tables=["gen/world_country"],
)
def write_replace(country: TableFrameSpec) -> TableFrameSpec:
    return country
''')

    w(d / "write_nothing.py", COPYRIGHT + '''
"""EXAMPLE — StarRocks destination: RETURNING None.

Nothing is staged and nothing is loaded — and the `replace` target is NOT
truncated. On a connector whose replace mode throws away a seeded table, that
asymmetry is worth being sure of: a run with no data cannot empty the target.

NOT EXERCISED HERE: `schema_evolution="iceberg"`. StarRocks loads via
`INSERT ... SELECT * FROM FILES(...)` and does not pre-ALTER the target on that
path, so a widened frame fails with a column-count mismatch rather than adding
the column — unlike ClickHouse, whose iceberg path does add it. The field exists;
the load path cannot yet use it.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.starrocks import StarRocksDest


@subscriber(
    destination=StarRocksDest(tables=["city"], if_table_exists="append"),
    input_tables=["gen/world_city"],
)
def write_nothing(city: TableFrameSpec) -> TableFrameSpec:
    return None
''')

    names = ["write_append", "write_replace", "write_nothing"]
    doc = suite_json(
        suite,
        "EXAMPLE · StarRocks destination / write modes — the destination that CANNOT "
        "CREATE ITS TARGET. The connector only issues TRUNCATE (replace) plus "
        "INSERT INTO <t> (<cols>) SELECT * FROM FILES(...), so the targets must already "
        "exist and the frames must match their DDL: this suite writes world-shaped rows "
        "into the `city` and `country` tables the world model seeded in the backing "
        "domain. The Primary Key model then decides which mode goes where — city.id is "
        "AUTO_INCREMENT and the frame omits it, so append gets FRESH keys and the count "
        "GROWS; country's key is `code`, so appending the same codes would upsert in "
        "place, which is why replace targets that one (and truncates the 239 seeded "
        "countries away). write_nothing shows a returned None staging nothing and NOT "
        "truncating. schema_evolution=\"iceberg\" is deliberately NOT exercised: the "
        "INSERT ... SELECT FROM FILES path does not pre-ALTER the target, so a widened "
        "frame fails on column count rather than evolving. Staging is via S3 here; the "
        "_gcs and _az templates are the same connector with a different staging store. "
        "One function per file under functions/starrocks_dest_modes/. "
        "Run: `tdd xp one-shot --suite examples/starrocks_dest_modes --keep`.",
        [
            {"name": "dev", "system": "dev"},
            {"name": "starrocks_world_xs", "system": "starrocks",
             "model": "world", "data": "xs"},
            {"name": "stage_store", "system": "s3"},
        ],
        [
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("warehouse", "starrocks_bulk_out_s3", "starrocks_bulk_out_s3.yaml",
                 "destinations", {"D0": "starrocks_world_xs", "D1": "stage_store"}),
        ],
        [fn("gen", suite, "supporting_generate_world_rows", "generate_world_rows")]
        + [fn("warehouse", suite, n, n) for n in names],
        [trig("gen", "generate_world_rows")],
    )
    return suite, doc


def emit_mongodb_dest_modes() -> tuple[str, dict]:
    """MongoDB writes DOCUMENTS, so its field names are its own."""
    suite = "mongodb_dest_modes"
    d = FN_DIR / suite
    _supporting_customers(d)

    shape = '''MONGODB DOES NOT USE `tables` / `if_table_exists`. It writes documents, so:

    `collections_with_ids`   a list of `(collection, id_field)` PAIRS, one write
                             slot per entry. `collection` may be qualified
                             `<database>.<collection>`; a bare name uses the
                             database in the connection URI. `id_field` is the
                             document field used as the unique id — pass `None`
                             to let MongoDB generate `_id` itself.
    `if_collection_exists`   `"append"` (default) leaves existing documents in
                             place; `"replace"` DROPS the collection first.

    Everything else about the destination shape is the same: one slot per entry,
    fed positionally by `input_tables`, and a returned `None` writes nothing.

    BSON HAS NO TYPE for three of the values a table can carry, so the write
    converts them: a `Date` becomes a BSON datetime at midnight UTC, a `Time`
    becomes one on the sentinel date 1970-01-01 UTC, and a `Duration` becomes an
    integer count of nanoseconds. `Decimal` maps to `Decimal128` and round-trips
    exactly.'''

    w(d / "write_append.py", COPYRIGHT + f'''
"""EXAMPLE — MongoDB destination: APPEND with an explicit id field.

{shape}

`("customers_append", "id")` names `id` as the document id, so re-running this
tries to insert documents whose ids already exist — and with the default
`update_existing=False` that is an `InsertOne` collision, which aborts the batch.
`write_upsert.py` is the mode that wants to be re-run.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("customers_append", "id")],
        if_collection_exists="append",
    ),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_replace.py", COPYRIGHT + '''
"""EXAMPLE — MongoDB destination: REPLACE, which DROPS the collection first.

Not a truncate — a drop. Indexes and collection options defined on the target go
with it, which is the difference worth knowing about before pointing `replace` at
a collection someone tuned by hand.

`id_field=None` here lets MongoDB generate `_id`, so nothing can collide and the
collection holds exactly this run's documents.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("customers_replace", None)],
        if_collection_exists="replace",
    ),
    input_tables=["gen/customers"],
)
def write_replace(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_upsert.py", COPYRIGHT + '''
"""EXAMPLE — MongoDB destination: UPSERT, the closest thing to a merge in this set.

`update_existing=True` turns each write into an `UpdateOne(..., upsert=True)` on
the `id_field`, so a document whose id already exists is REPLACED rather than
rejected. That makes the sink idempotent: run it as often as you like and the
collection converges on the input.

No other destination in these examples can do this — the SQL and warehouse ones
offer append or replace and nothing in between. It works here because MongoDB
takes a per-document id.

The other knobs on this write: `docs_per_trx` bounds the batch (and, with
`use_trxs=True` on a replica set, wraps each batch in a MongoDB transaction),
`fail_on_duplicate_key` decides whether a collision raises or is logged, and
`maintain_order` trades speed for deterministic insert order.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("customers_upsert", "id")],
        if_collection_exists="append",
        update_existing=True,
        docs_per_trx=500,
        fail_on_duplicate_key=True,
    ),
    input_tables=["gen/customers"],
)
def write_upsert(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
''')

    w(d / "write_two_collections.py", COPYRIGHT + '''
"""EXAMPLE — MongoDB destination: TWO COLLECTIONS from one subscriber.

Two pairs, two input tables, two returned frames — positional, like every other
destination. Note the id fields differ per entry: `customers` is keyed by `id`
and `orders` by `order_id`, which is the reason the pair carries the id field
rather than the destination carrying one for all of them.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("customers_both", "id"), ("orders_both", "order_id")],
        if_collection_exists="replace",
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_two_collections(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
''')

    names = ["write_append", "write_replace", "write_upsert", "write_two_collections"]
    doc = suite_json(
        suite,
        "EXAMPLE · MongoDB destination / write modes — the destination that does not "
        "fit the `tables` + `if_table_exists` mould. It writes DOCUMENTS, so it takes "
        "collections_with_ids (a list of (collection, id_field) PAIRS, one write slot "
        "each; id_field=None lets MongoDB generate _id) and if_collection_exists "
        "(\"append\", or \"replace\" which DROPS the collection — indexes and all, not a "
        "truncate). Four sinks: write_append (explicit id, so a re-run collides under "
        "the default update_existing=False), write_replace (generated ids), "
        "write_upsert (update_existing=True turns each write into an upsert on the id "
        "field — the only idempotent, merge-like sink in these examples, which no SQL "
        "or warehouse destination here can do), write_two_collections (note the id "
        "fields differ per entry, which is why the pair carries it). BSON converts "
        "Date/Time/Duration on the way in; Decimal round-trips exactly. One function "
        "per file under functions/mongodb_dest_modes/. "
        "Run: `tdd xp one-shot --suite examples/mongodb_dest_modes --keep`.",
        [
            {"name": "dev", "system": "dev"},
            {"name": "mongodb_out", "system": "mongodb"},
        ],
        [
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("documents", "mongodb_out", "mongodb_out.yaml", "destinations",
                 {"D0": "mongodb_out"}),
        ],
        [fn("gen", suite, "supporting_generate_customers", "generate_customers")]
        + [fn("documents", suite, n, n) for n in names],
        [trig("gen", "generate_customers")],
    )
    return suite, doc


# ----------------------------------------------------- schema evolution ------
EVOLUTION = {
    "databricks": {
        "module": "tabsdatak.conn.databricks",
        "dest": "DatabricksDest",
        "tpl": "databricks_bulk_out.yaml",
        "type": "databricks_bulk_out",
        "system": "databricks",
        "label": "Databricks",
        "quote": lambda n: n,
        "permissive": "update",
        "default": "update",
        "mechanism": "forwards `mergeSchema=true` to `COPY INTO`",
    },
    "bigquery": {
        "module": "tabsdatak.conn.bigquery",
        "dest": "BigQueryDest",
        "tpl": "bigquery_bulk_out.yaml",
        "type": "bigquery_bulk_out",
        "system": "bigquery",
        "label": "BigQuery",
        "quote": lambda n: f"`{n}`",
        "permissive": "update",
        "default": "update",
        "mechanism": "sets the load job's schema-update options, adding the columns as NULLABLE",
    },
    "clickhouse": {
        "module": "tabsdatak.conn.clickhouse",
        "dest": "ClickHouseDest",
        "tpl": "clickhouse_bulk_out_s3.yaml",
        "type": "clickhouse_bulk_out_s3",
        "system": "clickhouse",
        "label": "ClickHouse",
        "quote": lambda n: n,
        "permissive": "iceberg",
        "default": "strict",
        "mechanism": "applies Iceberg-style schema deltas, ALTERing the target",
        "staging_domain": "s3",
    },
}


def emit_evolution(key: str, c: dict) -> tuple[str, dict]:
    suite = f"{key}_dest_evolution"
    d = FN_DIR / suite
    dest, mod, q = c["dest"], c["module"], c["quote"]
    perm, dflt = c["permissive"], c["default"]
    mech_wrapped = textwrap.fill(c["mechanism"], width=78)

    matrix = f'''THE VALUES AND THE DEFAULTS DIFFER PER CONNECTOR, which is the thing to carry
away — identical code is permissive on one warehouse and strict on another:

    Databricks   "update"  (DEFAULT) | "strict"
    BigQuery     "update"  (DEFAULT) | "strict"
    ClickHouse   "strict"  (DEFAULT) | "iceberg"
    StarRocks    "strict"  (DEFAULT) | "iceberg"   — but its INSERT ... SELECT
                 FROM FILES load path does not pre-ALTER the target, so a widened
                 frame fails on column count rather than evolving. The field
                 exists; the path cannot use it yet.
    Snowflake, PostgreSQL, MySQL, SQL Server, Oracle, Db2, MongoDB, Druid
                 no `schema_evolution` field at all — append and replace are the
                 whole vocabulary, and a mismatched frame fails.

    On {c["label"]} the permissive value is `"{perm}"` and the DEFAULT is
    `"{dflt}"`. Every subscriber in this suite spells the value out rather than
    relying on that default.

EVOLUTION IS ADDITIVE ONLY, everywhere. A REMOVED column, a RENAMED one or a
changed TYPE is not schema evolution — it is a migration, and no setting here
will do it for you.'''

    w(d / "supporting_generate_narrow.py", COPYRIGHT + '''
"""SUPPORTING — not the example. The NARROW frame (`sku`, `name`) that creates
the target.

It is a SEPARATE publisher from the wide one on purpose: the two writes must be
ORDERED, and two tables published by ONE function land in ONE plan, whose
subscribers run concurrently and in no particular order. Two publishers give the
suite two triggers to order, and its trigger list declares this one
`"detached": false` — a GATE that completes before the wide trigger fires.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[Data(pl.DataFrame({"sku": ["A-1", "B-2"], "name": ["Widget", "Gadget"]}))]
    ),
    output_tables=["products_v1"],
)
def generate_narrow(v1: TableFrameSpec) -> TableFrameSpec:
    return v1
''')

    w(d / "supporting_generate_wide.py", COPYRIGHT + '''
"""SUPPORTING — not the example. The WIDER frame (`sku`, `name`, `price`,
`category`) appended to the table the narrow one created.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "sku": ["C-3", "D-4"],
                "name": ["Doohickey", "Thingamajig"],
                "price": [9.99, 42.00],
                "category": ["tools", "toys"],
            }))
        ]
    ),
    output_tables=["products_v2"],
)
def generate_wide(v2: TableFrameSpec) -> TableFrameSpec:
    return v2
''')

    w(d / "write_narrow_first.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]}: CREATE the target from the narrow frame.

`replace` rather than `append`, so the example is REPEATABLE: it recreates the
two-column table from scratch, and a second run of the project starts from the
same place instead of appending to an already-evolved table.

The evolution happens in `write_wider_evolving.py`, which must be `append` —
a `replace` there would recreate the table wide and there would be nothing to
observe.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(tables=["{q("products_evolve")}"], if_table_exists="replace"),
    input_tables=["gen/products_v1"],
)
def write_narrow_first(v1: TableFrameSpec) -> TableFrameSpec:
    return v1
''')

    w(d / "write_wider_evolving.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]}: APPEND a WIDER frame, with evolution ALLOWED.

`schema_evolution="{perm}"`
{mech_wrapped}
so `price` and `category` are ADDED to the table, and the two rows written before
them read back NULL there.

{matrix}
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(
        tables=["{q("products_evolve")}"],
        if_table_exists="append",
        schema_evolution="{perm}",
    ),
    input_tables=["gen/products_v2"],
)
def write_wider_evolving(v2: TableFrameSpec) -> TableFrameSpec:
    return v2
''')

    w(d / "write_narrow_locked.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]}: create a SECOND target, this one under a contract.

Same narrow frame, a different table — so one run can show both outcomes side by
side: `products_evolve` ends up four columns wide, `products_locked` stays two.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(tables=["{q("products_locked")}"], if_table_exists="replace"),
    input_tables=["gen/products_v1"],
)
def write_narrow_locked(v1: TableFrameSpec) -> TableFrameSpec:
    return v1
''')

    w(d / "write_wider_conformed.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]}: `schema_evolution="strict"`, and what you do about it.

Handing this target the wider frame AS-IS would FAIL the write. That is the whole
value of `strict`: a target with a contract tells you upstream changed shape,
instead of silently growing columns nobody planned.

So the function CONFORMS the frame to the target — `select` the columns the table
has — which is the real answer at a strict boundary: decide explicitly what the
extra columns mean rather than letting them widen a table by accident. It also
keeps this suite green instead of demonstrating by crashing.

TO SEE THE REFUSAL: delete the `.select(...)` below and re-run. The write fails
with a schema mismatch.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {mod} import {dest}


@subscriber(
    destination={dest}(
        tables=["{q("products_locked")}"],
        if_table_exists="append",
        schema_evolution="strict",
    ),
    input_tables=["gen/products_v2"],
)
def write_wider_conformed(v2: TableFrameSpec) -> TableFrameSpec:
    return v2.select("sku", "name")
''')

    names = ["write_narrow_first", "write_wider_evolving",
             "write_narrow_locked", "write_wider_conformed"]
    domains = [
        {"name": "dev", "system": "dev"},
        {"name": f"{c['system']}_out", "system": c["system"]},
    ]
    dmap = {"D0": f"{c['system']}_out"}
    if c.get("staging_domain"):
        domains.append({"name": "stage_store", "system": c["staging_domain"]})
        dmap["D1"] = "stage_store"

    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} destination / SCHEMA EVOLUTION — what happens when the "
        f"frame no longer matches the table. A target is created from a NARROW frame "
        f"(sku, name) and then appended to with a WIDER one (sku, name, price, "
        f"category), twice: with evolution ALLOWED (schema_evolution=\"{perm}\", which "
        f"{c['mechanism']}) the new columns are added and the earlier rows read back "
        f"NULL there; with it REFUSED (\"strict\") the write would fail, so "
        f"write_wider_conformed CONFORMS the frame with a .select() — the real answer "
        f"at a strict boundary, and what keeps this suite green (delete the select and "
        f"re-run to see the refusal). THE VALUES AND DEFAULTS DIFFER PER CONNECTOR "
        f"(Databricks/BigQuery \"update\" by default, ClickHouse/StarRocks \"strict\"; "
        f"Snowflake and the plain databases have no such field), and on {c['label']} the "
        f"default is \"{dflt}\" — so every sink here spells the value out. Evolution is "
        f"ADDITIVE ONLY: a dropped, renamed or retyped column is a migration, not "
        f"evolution. v1 uses `replace` so the example is repeatable and v2 uses "
        f"`append` so there is something to evolve; ordering comes from TWO supporting "
        f"publishers with the narrow trigger declared `detached: false` as a GATE. One "
        f"function per file under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite} --keep`.",
        domains,
        [
            coll("gen", "datagen_in", "datagen_in.yaml", "sources", {"D0": "dev"}),
            coll("warehouse", c["type"], c["tpl"], "destinations", dmap),
        ],
        [
            fn("gen", suite, "supporting_generate_narrow", "generate_narrow"),
            fn("gen", suite, "supporting_generate_wide", "generate_wide"),
        ] + [fn("warehouse", suite, n, n) for n in names],
        [
            trig("gen", "generate_narrow", detached=False),
            trig("gen", "generate_wide"),
        ],
    )
    return suite, doc


# ------------------------------------------------------------------- cdc -----
CDC = {
    "postgres": {
        "module": "tabsdatak.conn.postgres",
        "src": "PostgresCdcStreamSrc",
        "tpl": lambda i: "postgres_cdc.yaml",
        "type": "postgres_cdc",
        "system": "postgrescdc",
        "label": "PostgreSQL",
        "tables": '["employees", "departments"]',
        "tables_note": (
            "Unqualified names resolve against the connection's `current_schema`\n"
            "    (`public` for these domains), so the same function works whatever\n"
            "    database the domain was given."
        ),
        "cursor": "replication slot",
        "cursor_note": (
            "Postgres logical decoding needs a SLOT: a persistent WAL cursor the server\n"
            "    will not garbage-collect until the consumer confirms it.\n"
            "    `replication_slot_behavior=\"reuse\"` (the default) requires the slot to\n"
            "    exist; `\"create\"` creates it and no-ops if it does.\n\n"
            "    A slot admits ONE active consumer, so every concurrent stream needs its\n"
            "    OWN slot name — and its own collection, since these four run at once.\n\n"
            "    OPERATIONAL WARNING: an abandoned slot PINS WAL FOREVER and will fill the\n"
            "    server's disk. If you stop consuming, drop it:\n"
            "        SELECT pg_drop_replication_slot('ex_cdc_tabular');"
        ),
        "head_note": (
            "the oldest WAL the slot still retains. NOTE logical decoding cannot reach\n"
            "    back past SLOT CREATION, so on Postgres this does NOT replay a\n"
            "    pre-existing table — unlike MySQL and Db2. It differs from `\"tail\"` only\n"
            "    for changes made while the consumer was away."
        ),
        "position_note": (
            "`LsnPosition(lsn=N)` resumes at an exact WAL LSN — the shape the runner\n"
            "    itself persists (`{\"lsn\": N}`), so it is how you rewind a stream to a\n"
            "    known point by hand."
        ),
        "before_note": (
            "The `postgrescdc` system sets `REPLICA IDENTITY FULL` on every model table,\n"
            "    so UPDATE and DELETE rows carry complete before-images. WITHOUT it\n"
            "    Postgres sends only the key columns and the old side is mostly null."
        ),
        "extra_src": (
            '\n        replication_slot="ex_cdc_{v}",\n'
            '        replication_slot_behavior="create",'
        ),
        "cfg_extra": '"postgres.cdc.blocking_timeout_seconds": 5,',
        "per_variant_tpl": False,
    },
    "mysql": {
        "module": "tabsdatak.conn.mysql",
        "src": "MySQLCdcStreamSrc",
        "tpl": lambda i: ["mysql_cdc_612.yaml", "mysql_cdc_613.yaml",
                          "mysql_cdc_614.yaml", "mysql_cdc_615.yaml"][i],
        "type": "mysql_cdc",
        "system": "mysqlcdc",
        "label": "MySQL",
        "tables": '["employees", "departments"]',
        "tables_note": (
            "Unqualified names resolve against the connection's default database."
        ),
        "cursor": "server_id",
        "cursor_note": (
            "MySQL has NO slot to create or drop. Every consumer registers as a REPLICA,\n"
            "    and MySQL admits a single replica per `server_id`: a second stream\n"
            "    attaching with the same id disconnects the first with\n"
            "    `(1236, \"A replica with the same server_uuid/server_id ...\")`.\n\n"
            "    `server_id` lives on the CONNECTION, not on the source — so each variant\n"
            "    here gets its own connection template (`connections/mysql_cdc_612.yaml`\n"
            "    through `_615.yaml`, a block kept clear of the 51x ids the connectors\n"
            "    capability suite uses) and therefore its own collection.\n\n"
            "    The upside of having no slot: nothing pins the binlog when you walk away.\n"
            "    A stopped MySQL stream leaks nothing; a stopped Postgres one holds WAL."
        ),
        "head_note": (
            "the oldest retained binlog event — and the binlog is retained server-wide\n"
            "    (3 days on this container), so `\"head\"` GENUINELY REPLAYS history,\n"
            "    including the `create-data` seed load, which arrives as a wave of\n"
            "    INSERTs. That is a full backfill and an ongoing stream from ONE function.\n"
            "    It also scans other databases' traffic on the same server and filters it\n"
            "    out, so expect a slow first pass."
        ),
        "position_note": (
            "`BinlogPosition(file=..., pos=4)` resumes at an exact file + byte offset\n"
            "    (`pos=4` skips the binlog magic bytes, i.e. that file from its\n"
            "    beginning); `GtidPosition(gtid=\"uuid:N\")` resumes after a Global\n"
            "    Transaction ID; `TimestampPosition(ts=...)` at the first event at or\n"
            "    after a wall clock. `SHOW BINARY LOGS` / `SHOW MASTER STATUS` tell you\n"
            "    what to put there. All of them are SEEDS, used only until the stream\n"
            "    persists its own offset."
        ),
        "before_note": (
            "MySQL's row-based binlog carries the full before-image on UPDATE and DELETE\n"
            "    with no extra configuration — there is no `REPLICA IDENTITY` to set."
        ),
        "extra_src": "",
        "cfg_extra": '"mysql.cdc.blocking_timeout_seconds": 5,',
        "per_variant_tpl": True,
    },
    "db2": {
        "module": "tabsdatak.conn.db2",
        "src": "Db2CdcStreamSrc",
        "tpl": lambda i: "db2_cdc.yaml",
        "type": "db2_cdc",
        "system": "db2cdc",
        "label": "Db2",
        "tables": '["${D0__CD_TABLE_PREFIX}EMPLOYEES", "${D0__CD_TABLE_PREFIX}DEPARTMENTS"]',
        "tables_note": (
            "`tables` NAMES THE CD TABLES, NOT THE SOURCE TABLES. Db2 SQL Replication\n"
            "    captures changes into shadow change-data tables that the ASN capture\n"
            "    program (`asncap`) populates in the background, so what the stream reads\n"
            "    is the CD table of `EMPLOYEES`, not `EMPLOYEES`; the ingester resolves\n"
            "    the source back through `ASN.IBMSNAP_REGISTER`. The CD tables are the\n"
            "    domain's own -- `ASN.TD_<tag of its schema>__<TABLE>` -- and it records\n"
            "    the prefix as `CD_TABLE_PREFIX`, which xp puts in for\n"
            "    `${D0__CD_TABLE_PREFIX}` when it registers the function. Db2 also folds\n"
            "    unquoted identifiers to uppercase, which is why the names are written\n"
            "    that way."
        ),
        "cursor": "capture-table watermark",
        "cursor_note": (
            "There is no slot and no replica id — each tracked CD table has its own\n"
            "    watermark, and the stream drains them. What Db2 has instead is a\n"
            "    REGISTRATION per captured table, and that is where the operational\n"
            "    weight of this connector sits.\n\n"
            "    EACH DOMAIN HAS ITS OWN CD TABLES, named after its schema, so any number\n"
            "    of db2cdc domains carrying the same model share a system -- this suite\n"
            "    and `container-connectors/db2cdc` can be up together.\n\n"
            "    A DESTROY CLEANS UP -- `Db2Cdc.destroy_domain` deregisters every\n"
            "    table it finds in `ASN.IBMSNAP_REGISTER` under the domain's schema before\n"
            "    dropping that schema (CAPSTOP, delete the REGISTER and PRUNCNTL rows,\n"
            "    drop the `LM_TD_<tag>__<T>` trigger, drop the CD table, clear DATA\n"
            "    CAPTURE). That is why a destroy takes minutes rather than a second. A\n"
            "    domain torn down some other way leaves its registrations behind, holding\n"
            "    names only a domain of the same schema would want."
        ),
        "head_note": (
            "replays each tracked CD table from its origin — so, like MySQL and unlike\n"
            "    Postgres, it can replay a load that happened before the stream started,\n"
            "    for as long as the CD table still holds it."
        ),
        "position_note": (
            "`CommitSeqPosition(...)` resumes at a global commit sequence,\n"
            "    `TableCommitSeqPosition(...)` at a per-table one, and\n"
            "    `TimestampPosition(ts=...)` at a wall clock."
        ),
        "before_note": (
            "The CD tables carry the before-image when the registration was created with\n"
            "    full-row capture, which the `db2cdc` system does."
        ),
        "extra_src": "",
        "cfg_extra": '"db2.cdc.blocking_timeout_seconds": 5,',
        "per_variant_tpl": False,
    },
}

CDC_VARIANTS = [
    ("stream_tabular", "cdc_tabular", "columns", True, "tail",
     "ORDINARY TABULAR CHANGE ROWS.\n\nThe default pair of settings, and what you want for anything that lands in a\ntable and then gets queried."),
    ("stream_struct", "cdc_struct", "struct", False, "tail",
     "NESTED STRUCTS on both sides.\n\nNothing is inlined, so the frame's columns do NOT depend on the tracked table's\ncolumns — which is the point: a mid-stream schema change moves the payload, not\nthe schema. `TableFrame.unnest` expands a struct column later, if and when you\nwant the flat shape."),
    ("stream_map", "cdc_map", "map", True, "tail",
     "MAPS for the old values, new values still inlined.\n\n`flatten_columns` stays True, so `columns_format` only shapes the OLD side. The\nusual middle ground: query the current values normally, keep the before-image\nopaque."),
    ("stream_replay", "cdc_replay", "columns", True, "head",
     "REPLAY from the earliest position the source retains."),
]


def emit_cdc(key: str, c: dict) -> tuple[str, dict]:
    suite = f"{key}cdc_stream"
    d = FN_DIR / suite
    src, mod = c["src"], c["module"]

    shape = f'''A CDC SOURCE IS NOT A PUBLISHER. `@stream_publisher`, and the differences are
all operational:

  * NO TRIGGER. Registering a stream publisher STARTS it. The worker comes up
    seconds after `create-project` and runs until the function is disabled or
    deleted — which is why this suite's `triggers` list is empty. `tdk worker
    list` shows them; they carry no execution plan.
  * ONE SLOT PER TRACKED TABLE (`cardinality = len(tables)`), and each slot is an
    ARRAY of the frames that flush carried — like a file source, not like a SQL
    source. Fold with `concat`.
  * NO `ctx` PARAMETER. A stream publisher runs in the runtime's stream loop, not
    per transaction; declaring `ctx` is an error.

  Changes are buffered and written to parquet files per the `tabsdata.cdc.buffer.*`
  keys; the files are staged as one batch when a `tabsdata.cdc.trigger.*` threshold
  fires (`src_cfg`) or when `flush_interval_mins` is reached, and never sooner than
  60 seconds after the previous batch.

WHAT `tables` MEANS HERE
    {para(c["tables_note"])}

THE CURSOR: {c["cursor"].upper()}
    {c["cursor_note"]}

WHAT EVERY EMITTED ROW CARRIES
    Change METADATA under `@td.cdc.meta.*`:
        op  'i' | 'u' | 'd'        tx   transaction id     ts  commit time
        sq  sequence in the tx     ord  global ordering    sch source schema
        fmt / flat / seg           (the config the row was produced under)

    and the VALUES, laid out by `columns_format` and `flatten_columns` TOGETHER:

        flatten_columns=True (default)   the NEW values are inlined as ordinary
                                         top-level columns, so the row reads like
                                         a normal table row and `columns_format`
                                         then only shapes the OLD values.
        columns_format="columns"         one column per field per side:
                                         `@td.cdc.data.col.new.<field>` /
                                         `@td.cdc.data.col.old.<field>`
        columns_format="struct"          one nested struct per side:
                                         `@td.cdc.data.row.new` / `.row.old`
        columns_format="map"             one map per side:
                                         `@td.cdc.data.map.new` / `.map.old`

    RULE OF THUMB: `columns` + flattened for anything that lands in a table and
    gets queried; `struct` / `map` when the tracked table's schema may CHANGE
    mid-stream and you would rather carry the payload opaquely than have the
    frame's columns shift underneath you.

    BEFORE-IMAGES:
    {para(c["before_note"])}

WHEN A BATCH CLOSES: `src_cfg`
    `tabsdata.cdc.buffer.max_rows` / `.max_bytes` / `.max_secs` bound the
    in-memory buffer; `tabsdata.cdc.trigger.max_rows` / `.max_bytes` /
    `.max_secs` decide when a batch is emitted; `tabsdata.cdc.poll_interval_
    seconds` is how often the loop looks. The small values below make a demo
    responsive; production wants larger batches and fewer, bigger files.

DRIVING IT
    tdd xp one-shot --suite examples/{suite} --keep      # the streams start
    tdd domain modify-data --domain <XP_ID>_{c["system"]}_employees_xs \\\\
        --entity employees --ops Mix --sets 5

    `--ops` takes ONE of `Insert` / `Update` / `Delete` / `Mix` — not a list.
    `Mix` is what gives the stream all three operations in one go, which is the
    point when what you are looking at is `@td.cdc.meta.op`.'''

    for i, (name, collection, fmt, flat, start, headline) in enumerate(CDC_VARIANTS):
        variant = collection.replace("cdc_", "")
        start_doc = (
            "`start_from=\"head\"` —\n    "
            + para(c["head_note"])
            + "\n\n    "
            + c["position_note"]
            if start == "head"
            else "`start_from=\"tail\"` — only changes made after the stream attaches,\n"
                 "    which is the safe default."
        )
        extra = c["extra_src"].format(v=variant) if c["extra_src"] else ""
        w(d / f"{name}.py", COPYRIGHT + f'''
"""EXAMPLE — {c["label"]} CDC: {headline}

    {start_doc}

{shape}
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from {mod} import {src}
from tabsdatak.tableframe.functions import concat


@stream_publisher(
    source={src}(
        tables={c["tables"]},{extra}
        start_from="{start}",
        columns_format="{fmt}",
        flatten_columns={flat},
        src_cfg={{
            "tabsdata.cdc.buffer.max_rows": 100,
            "tabsdata.cdc.buffer.max_secs": 5,
            "tabsdata.cdc.trigger.max_rows": 10,
            "tabsdata.cdc.trigger.max_secs": 60,
            "tabsdata.cdc.poll_interval_seconds": 1,
            {c["cfg_extra"]}
        }},
    ),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def {name}(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # One slot per tracked table, each an ARRAY of the frames this flush carried.
    # `concat` drops Nones and returns None for an empty list, so it doubles as
    # the "this flush carried nothing for this slot" guard. Vertical (the strict
    # default) on purpose: a mid-stream schema change should surface here rather
    # than be absorbed silently.
    return (concat(employees), concat(departments))
''')

    extra_comment = (
        "The CD tables are the domain's own (named after its schema; the functions take "
        "the prefix as ${D0__CD_TABLE_PREFIX}), so db2cdc domains of one model share a "
        "system. "
        if key == "db2" else ""
    )
    doc = suite_json(
        suite,
        f"EXAMPLE · {c['label']} CDC (@stream_publisher) — the configuration choices "
        f"that decide what a change stream hands you. Registering a stream publisher "
        f"STARTS it, so there are NO TRIGGERS and none are needed; there is no ctx; and "
        f"there is one ARRAY slot per tracked table, folded with concat. THE CURSOR is "
        f"this connector's {c['cursor']}. THE ROW SHAPE comes from columns_format and "
        f"flatten_columns together — metadata always under @td.cdc.meta.* (op i/u/d, "
        f"tx, sq, ts, ord, sch) and the values as inlined columns, "
        f"@td.cdc.data.col.new/old.<field>, @td.cdc.data.row.* structs or "
        f"@td.cdc.data.map.* maps; use columns+flattened for tables you query, "
        f"struct/map when the tracked schema may change mid-stream. start_from picks "
        f"where to begin (tail / head / an exact position). src_cfg buffer/trigger/poll "
        f"thresholds decide WHEN a batch closes. Four stream publishers, one collection "
        f"each, over a {c['system']} domain seeded with the employees model. Drive it "
        f"with `tdd domain modify-data --entity employees --ops Mix --sets 5` (--ops "
        f"takes ONE of Insert/Update/Delete/Mix, not a list). {extra_comment}One function per file under functions/{suite}/. "
        f"Run: `tdd xp one-shot --suite examples/{suite} --keep`.",
        [
            {"name": f"{c['system']}_employees_xs", "system": c["system"],
             "model": "employees", "data": "xs"},
        ],
        [
            coll(collection, c["type"], c["tpl"](i), "sources",
                 {"D0": f"{c['system']}_employees_xs"})
            for i, (_, collection, _, _, _, _) in enumerate(CDC_VARIANTS)
        ],
        [
            fn(collection, suite, name, name)
            for name, collection, _, _, _, _ in CDC_VARIANTS
        ],
        [],
    )
    return suite, doc


# ------------------------------------------------------------------ main -----
def build() -> dict[str, dict]:
    """Every generated suite: name -> descriptor. Writes the function files as a
    side effect."""
    suites: dict[str, dict] = {}

    for key, c in FILE_CONNECTORS.items():
        for emit in (emit_file_src_paths, emit_file_src_formats,
                     emit_file_src_lastmodified, emit_file_dest_formats,
                     emit_file_dest_tokens):
            name, doc = emit(key, c)
            suites[name] = doc

    for key, c in SQL_SOURCES.items():
        for emit in (emit_sql_src_queries, emit_sql_src_incremental):
            name, doc = emit(key, c)
            suites[name] = doc

    for key, c in SQL_DESTS.items():
        name, doc = emit_sql_dest_modes(key, c)
        suites[name] = doc

    for key, c in WAREHOUSE_DESTS.items():
        name, doc = emit_warehouse_dest_modes(key, c)
        suites[name] = doc

    name, doc = emit_starrocks_dest_modes()
    suites[name] = doc
    name, doc = emit_mongodb_dest_modes()
    suites[name] = doc

    for key, c in EVOLUTION.items():
        name, doc = emit_evolution(key, c)
        suites[name] = doc

    for key, c in CDC.items():
        name, doc = emit_cdc(key, c)
        suites[name] = doc

    return suites


def build_names() -> list[str]:
    """The suites `build()` will emit — derived from the specs, so it can be asked
    without writing anything."""
    names = []
    for key in FILE_CONNECTORS:
        names += [f"{key}_src_paths", f"{key}_src_formats",
                  f"{key}_src_lastmodified", f"{key}_dest_formats",
                  f"{key}_dest_tokens"]
    for key in SQL_SOURCES:
        names += [f"{key}_src_queries", f"{key}_src_incremental"]
    names += [f"{k}_dest_modes" for k in SQL_DESTS]
    names += [f"{k}_dest_modes" for k in WAREHOUSE_DESTS]
    names += ["starrocks_dest_modes", "mongodb_dest_modes"]
    names += [f"{k}_dest_evolution" for k in EVOLUTION]
    names += [f"{k}cdc_stream" for k in CDC]
    return sorted(names)


def as_stages(doc: dict) -> list:
    """The suite as xp reads it: an ordered list of stages -- the ``_``
    annotations, then the domains (a domain-manifest, created in one parallel
    batch), collections, functions and triggers (each only when it has entries)
    and a monitor. Built as one object because that is how the sections are
    gathered; the order is what the stages are."""
    notes = {k: v for k, v in doc.items() if k.startswith("_")}
    stages = [notes] if notes else []
    # A suite's domains are its run's own: ${xp:name(x)} is <XP_ID>_x once read.
    own = "${xp:name(%s)}".__mod__
    if doc.get("domains"):
        domains = [{**d, "name": own(d["name"])} for d in doc["domains"]]
        stages.append({"domain-manifest": {"domains": domains}})
    for kind in ("collections", "functions", "triggers"):
        if not doc.get(kind):
            continue
        entries = doc[kind]
        if kind == "collections":
            entries = [
                {**c, "domains": {k: own(v) for k, v in c["domains"].items()}}
                if c.get("domains")
                else c
                for c in entries
            ]
        stages.append({kind: entries})
    stages.append({"monitor": {"time_out": "30m"}})
    return stages


def main() -> int:
    if "--list" in sys.argv[1:]:
        names = build_names()
        for n in names:
            print(n)
        print(f"\n{len(names)} generated + {len(HANDWRITTEN)} hand-written "
              f"= {len(names) + len(HANDWRITTEN)} suites")
        return 0

    # Each generated suite's functions/ dir is REMOVED first, so a renamed or
    # deleted function cannot leave a stale file behind that the descriptor no
    # longer references. Hand-written suites are never touched.
    for name in build_names():
        shutil.rmtree(FN_DIR / name, ignore_errors=True)
    suites = build()
    for name, doc in sorted(suites.items()):
        (SUITE_DIR / f"{name}.json").write_text(
            json.dumps(as_stages(doc), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(f"wrote {len(suites)} suite(s) + their functions/ dirs under {SUITE_DIR}")
    print(f"hand-written and untouched: {', '.join(sorted(HANDWRITTEN))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
