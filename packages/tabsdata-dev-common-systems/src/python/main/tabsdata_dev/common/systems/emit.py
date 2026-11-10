#
# Copyright 2026 Tabsdata Inc.
#

"""Row schema (``Column`` / ``Table``) and SQL rendering.

A model's ``datagenerator.py`` builds ``Table`` objects (typed columns + rows),
from which this module renders portable ``INSERT`` statements and typed SQL
literals, or (for file/object-store domains) writes one data file per table in
each of :data:`FILE_FORMATS` (:func:`write_frame`) -- or, for a log table (one
with a column marked :attr:`Column.log_line`), one ``.log`` file of its lines. The Avro schema and record a row is written as
(:func:`avro_schema`, :func:`avro_record`) are shared with the kafka data plane.

Column ``sql_type`` strings recognised: int/bigint/smallint/tinyint, boolean,
varchar(N)/char(N)/text, date/datetime/timestamp/time, decimal(P,S),
float/double. ``auto=True`` omits the column from ``INSERT`` (left to the
database IDENTITY).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# The data-file formats a file/object-store domain stages (one file per entity
# per format), each named ``<entity>_<file_stamp()>.<fmt>`` -- every format a
# tabsdata file source reads by extension, but a log.
FILE_FORMATS = ("csv", "ndjson", "parquet", "avro", "xlsx")
# The one format a log table is staged in: its lines, nothing else.
LOG_FORMAT = "log"

# One worksheet's data rows: Excel's 1,048,576 rows less the header.
XLSX_MAX_ROWS = 1_048_575


@dataclass
class Column:
    name: str
    sql_type: str
    nullable: bool = True
    auto: bool = False  # IDENTITY / SERIAL — skipped in INSERTs
    # The text a log file holds for the row; the table's other columns are
    # what the line says, which the --emit-ops trail carries and no file does.
    log_line: bool = False


@dataclass
class Table:
    name: str
    columns: list[Column]
    rows: list[dict]
    sql_post: list[str] = field(default_factory=list)


_DECIMAL_RE = re.compile(r"^decimal\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)$", re.IGNORECASE)
_VARCHAR_RE = re.compile(
    r"^(?:varchar|char|nvarchar|nchar)\s*\(\s*\d+\s*\)$", re.IGNORECASE
)


def _is_decimal(t: str):
    m = _DECIMAL_RE.match(t.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _is_string(t: str) -> bool:
    t = t.strip().lower()
    return t == "text" or _VARCHAR_RE.match(t) is not None


def _is_int(t: str) -> str | None:
    return {
        "tinyint": "int8",
        "smallint": "int16",
        "int": "int32",
        "integer": "int32",
        "bigint": "int64",
    }.get(t.strip().lower())


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t).lower()


_BARE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sql_quote_ident(
    name: str, quote: str, reserved: frozenset[str] = frozenset()
) -> str:
    """Wrap `name` in `quote` if it isn't a bare SQL identifier, doubling any
    embedded quote char so the name round-trips. `reserved` holds, in lower
    case, the words the dialect refuses as a bare column name: a bare name
    among them is quoted too."""
    if _BARE_IDENT_RE.match(name) and name.lower() not in reserved:
        return name
    return f"{quote}{name.replace(quote, quote * 2)}{quote}"


def _sql_escape(s: str) -> str:
    return s.replace("'", "''")


def _to_date(v):
    if v is None or (isinstance(v, date) and not isinstance(v, datetime)):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        return v
    raise TypeError(f"date column got {type(v).__name__}")


def _to_datetime(v):
    if v is None:
        return v
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, time(0, 0))
    if isinstance(v, str):
        return v
    raise TypeError(f"datetime column got {type(v).__name__}")


def _to_time(v):
    if v is None or isinstance(v, (time, str)):
        return v
    raise TypeError(f"time column got {type(v).__name__}")


def sql_literal(v: Any, sql_type: str) -> str:
    if v is None:
        return "NULL"
    # Oracle treats '' as NULL; emit NULL for empty strings everywhere for a
    # portable INSERT.
    if isinstance(v, str) and v == "":
        return "NULL"
    t = _norm(sql_type)
    if _is_int(t) is not None:
        return str(int(v))
    if t in ("boolean", "bool"):
        return "1" if v else "0"
    if t in ("float", "double", "real"):
        return str(float(v))
    if _is_decimal(t):
        return str(v)
    if t == "date":
        d = _to_date(v)
        return f"'{d.strftime('%Y-%m-%d') if isinstance(d, date) else d}'"
    if t in ("datetime", "timestamp"):
        d = _to_datetime(v)
        return f"'{d.strftime('%Y-%m-%d %H:%M:%S') if isinstance(d, datetime) else d}'"
    if t == "time":
        d = _to_time(v)
        return f"'{d.strftime('%H:%M:%S') if isinstance(d, time) else d}'"
    if _is_string(t):
        return f"'{_sql_escape(str(v))}'"
    return f"'{_sql_escape(str(v))}'"


def iter_insert_statements(
    table_name: str,
    columns: list[Column],
    rows: list[dict],
    *,
    batch: int = 1,
    quote: str = '"',
    reserved: frozenset[str] = frozenset(),
) -> Iterable[str]:
    """Yield ``INSERT INTO ... VALUES ...`` statements (no trailing ``;``).
    ``auto`` columns are skipped. With ``batch > 1`` each statement carries up to
    ``batch`` row tuples in one multi-row ``VALUES`` clause."""
    cols = [c for c in columns if not c.auto]
    col_names = ",".join(sql_quote_ident(c.name, quote, reserved) for c in cols)
    batch = max(batch, 1)
    for start in range(0, len(rows), batch):
        tuples = ",".join(
            "(" + ",".join(sql_literal(r.get(c.name), c.sql_type) for c in cols) + ")"
            for r in rows[start : start + batch]
        )
        yield f"INSERT INTO {table_name} ({col_names}) VALUES {tuples}"


# ---------------------------------------------------------------------------
# File output — one file per table, per format (for file/object-store domains)
# ---------------------------------------------------------------------------


def _frame(tbl: Table):
    """A polars DataFrame of `tbl` (ALL columns, incl. ``auto``), preserving
    column order even when there are no rows.

    Unlike SQL ``INSERT`` (where ``auto`` columns are skipped and the DB
    regenerates them), a file seed has no DB to regenerate anything — dropping
    ``auto`` columns would strip surrogate primary keys that other tables
    reference as foreign keys, leaving the file dataset internally unjoinable.
    datagen already populates these columns with real values, so keep them."""
    import polars as pl

    cols = list(tbl.columns)
    if tbl.rows:
        return pl.DataFrame(
            {c.name: [r.get(c.name) for r in tbl.rows] for c in cols}
        ).select([c.name for c in cols])
    return pl.DataFrame({c.name: [] for c in cols})


def log_column(tbl: Table) -> Column | None:
    """The column whose values are `tbl`'s log lines, or ``None`` when it is
    not a log table."""
    return next((c for c in tbl.columns if c.log_line), None)


def formats_of(tbl: Table) -> tuple[str, ...]:
    """The formats a file domain stages `tbl` in: a log table as its lines
    alone, every other one in each of :data:`FILE_FORMATS`."""
    return (LOG_FORMAT,) if log_column(tbl) is not None else FILE_FORMATS


def unwritable(tbl: Table, fmt: str) -> str | None:
    """Why `tbl` cannot be written as `fmt`, or ``None`` when it can: Avro
    names are ``[A-Za-z_][A-Za-z0-9_]*`` (bronze's ``@td.cdc.*`` columns are
    not), and a worksheet ends at :data:`XLSX_MAX_ROWS`."""
    if fmt == "avro":
        bad = [c.name for c in tbl.columns if not _BARE_IDENT_RE.match(c.name)]
        if bad or not _BARE_IDENT_RE.match(tbl.name):
            bad = bad or [tbl.name]
            more = f" and {len(bad) - 3} more" if len(bad) > 3 else ""
            return f"not Avro names: {', '.join(bad[:3])}{more}"
    if fmt == "xlsx" and len(tbl.rows) > XLSX_MAX_ROWS:
        return f"{len(tbl.rows)} rows, past a worksheet's {XLSX_MAX_ROWS}"
    return None


# ---------------------------------------------------------------------------
# Avro -- one schema per table, from its columns' SQL types
# ---------------------------------------------------------------------------


def _avro_type(sql_type: str):
    """The Avro type of a SQL column type, logical types where Avro has one --
    each of which arrow-avro (tabsdata's reader) maps to its Arrow type. A
    timestamp is ``local-timestamp-micros``: the models' times carry no zone."""
    t = _norm(sql_type)
    if t in ("tinyint", "smallint", "int", "integer"):
        return "int"
    if t == "bigint":
        return "long"
    if t in ("boolean", "bool"):
        return "boolean"
    if t in ("float", "double", "real"):
        return "double"
    dec = _is_decimal(t)
    if dec:
        return {
            "type": "bytes",
            "logicalType": "decimal",
            "precision": dec[0],
            "scale": dec[1],
        }
    if t == "date":
        return {"type": "int", "logicalType": "date"}
    if t in ("datetime", "timestamp"):
        return {"type": "long", "logicalType": "local-timestamp-micros"}
    if t == "time":
        return {"type": "long", "logicalType": "time-micros"}
    return "string"


def avro_schema(name: str, columns: list[Column], namespace: str = "tdd") -> dict:
    """The Avro record schema of rows of `columns`: a field per column, in
    order, a nullable column a ``["null", T]`` union defaulting to null. An
    ``auto`` column is nullable too: a model may leave it to the database that
    a file does not have (sakila's ``payment_id``)."""
    fields = []
    for c in columns:
        typ = _avro_type(c.sql_type)
        if c.nullable or c.auto:
            fields.append({"name": c.name, "type": ["null", typ], "default": None})
        else:
            fields.append({"name": c.name, "type": typ})
    return {
        "type": "record",
        "name": name,
        "namespace": namespace,
        "fields": fields,
    }


def _avro_value(v: Any, sql_type: str):
    """`v` as fastavro writes the column's Avro type: a Decimal at the
    column's scale, a date / datetime / time from the text a model may give."""
    if v is None:
        return None
    t = _norm(sql_type)
    dec = _is_decimal(t)
    if dec:
        return Decimal(str(v)).quantize(Decimal(1).scaleb(-dec[1]))
    if t == "date":
        d = _to_date(v)
        return date.fromisoformat(d) if isinstance(d, str) else d
    if t in ("datetime", "timestamp"):
        d = _to_datetime(v)
        return datetime.fromisoformat(d) if isinstance(d, str) else d
    if t == "time":
        d = _to_time(v)
        return time.fromisoformat(d) if isinstance(d, str) else d
    if t in ("float", "double", "real"):
        return float(v)
    if _is_int(t) is not None:
        return int(v)
    if t in ("boolean", "bool"):
        return bool(v)
    return str(v)


def avro_record(row: dict, columns: list[Column]) -> dict:
    """`row` as a record of :func:`avro_schema`'s schema for `columns`."""
    return {c.name: _avro_value(row.get(c.name), c.sql_type) for c in columns}


def _write_avro(tbl: Table, path: Path) -> None:
    import fastavro

    schema = fastavro.parse_schema(avro_schema(tbl.name, tbl.columns))
    records = (avro_record(r, tbl.columns) for r in tbl.rows)
    with path.open("wb") as f:
        fastavro.writer(f, schema, records)


def _write_log(tbl: Table, path: Path) -> None:
    """One line per row, LF-terminated, UTF-8: bytes, so Windows' text mode
    does not turn them into CRLF."""
    col = log_column(tbl)
    assert col is not None
    text = "".join(f"{r.get(col.name) or ''}\n" for r in tbl.rows)
    path.write_bytes(text.encode("utf-8"))


def file_stamp() -> str:
    """A filename timestamp ``YYYYMMDDThhmmss_mmm`` at the current local time —
    all files staged in one command invocation share the same stamp."""
    now = datetime.now()
    return now.strftime("%Y%m%dT%H%M%S_") + f"{now.microsecond // 1000:03d}"


def later_stamp(stamp: str, ms: int) -> str:
    """`stamp` (a :func:`file_stamp`) `ms` milliseconds later, in its format."""
    at = datetime.strptime(stamp[:-4], "%Y%m%dT%H%M%S").replace(
        microsecond=int(stamp[-3:]) * 1000
    ) + timedelta(milliseconds=ms)
    return at.strftime("%Y%m%dT%H%M%S_") + f"{at.microsecond // 1000:03d}"


def write_frame(tbl: Table, path: str | Path, fmt: str) -> None:
    """Write `tbl`'s columns and rows (incl. ``auto`` surrogate keys) to `path`
    as `fmt` (one of :data:`FILE_FORMATS`, or :data:`LOG_FORMAT` for a log
    table), creating parent directories. A table :func:`unwritable` as `fmt`
    is refused."""
    if fmt not in (*FILE_FORMATS, LOG_FORMAT):
        raise ValueError(
            f"unknown format {fmt!r}; expected one of {(*FILE_FORMATS, LOG_FORMAT)}"
        )
    why = unwritable(tbl, fmt)
    if why:
        raise ValueError(f"{tbl.name} cannot be written as {fmt}: {why}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt == LOG_FORMAT:
        if log_column(tbl) is None:
            raise ValueError(f"{tbl.name} is not a log table (no log_line column)")
        _write_log(tbl, p)
        return
    if fmt == "avro":
        # Not polars': it writes neither a time column nor an all-null one,
        # and its schema is the frame's, where this one is the columns'.
        _write_avro(tbl, p)
        return
    frame = _frame(tbl)
    if fmt == "csv":
        frame.write_csv(p)
    elif fmt == "ndjson":
        frame.write_ndjson(p)
    elif fmt == "xlsx":
        frame.write_excel(p)
    else:
        frame.write_parquet(p)
