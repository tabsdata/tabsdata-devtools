#
# Copyright 2026 Tabsdata Inc.
#
"""_srcmeta — the ``tabsdata.src_metadata.drop`` contract, shared by every connector
capability suite whose source reports metadata.

THE CONTRACT
    A source that reports metadata attaches it to the files it reads, and the server
    materialises it as extra columns on the published table, named with the reserved
    ``@td.`` prefix so they can never collide with the source's own columns:

        file sources (localfile / s3 / gcs / azureblob)   @td.file.path
        SQL sources  (mysql / postgres / oracle / db2 /   @td.sql.query
                      mssql / databricks)                 @td.sql.initial_values

    Every one of those sources accepts the ``src_cfg`` key
    ``tabsdata.src_metadata.drop``. Set it to ``True`` and the read reports no metadata
    at all, so the published table carries ONLY the source's own columns. It defaults
    to ``False``.

HOW EACH SUITE TESTS IT
    Two publishers reading THE SAME THING, differing only in that key, and one
    follow-up ``@transformer`` per publisher that asserts that side of the contract:

        <conn>_meta_keep        src_cfg omitted        -> metadata columns present
        <conn>_meta_drop        src_cfg {drop: True}   -> no @td. column at all
        <conn>_meta_keep_check  @transformer           -> :func:`check_keep`
        <conn>_meta_drop_check  @transformer           -> :func:`check_drop`

    A failed assertion raises, failing the transaction: that is the red/green signal.

ONE TRANSFORMER PER PUBLISHER, AND WHY
    The tempting shape is a single transformer reading both tables, so it can compare
    them directly. It does not work: ANY input reference puts a function in the plan of
    whatever produces that table — the ``@HEAD`` / ``@NEW`` marker does not change plan
    membership. A transformer naming both tables therefore runs in BOTH publishers'
    plans, and in each one the other publisher's table has no version for it, so the
    run fails on the missing input (``AssertionError: meta_keep: no table published``,
    once per lane, and the second transaction stalls behind the failed one).

    So each side gets its own transformer with a single ``@NEW`` input, and the reads
    stay in separate, independent plans — the same shape as every other publisher in
    these suites, with no trigger ordering to arrange.

    What that costs is the direct frame-to-frame comparison, so "the drop key changes
    NOTHING BUT the metadata" is asserted differently: each side pins its DATA columns
    to the same declared expectation (:data:`COUNTRY_COLUMNS` / :data:`QUERY_COLUMNS`).
    If the key changed anything else, one side fails.

BOTH SIDES ARE REAL ASSERTIONS (verified green 2026-08-07)
    The connectors report the metadata in the inputs manifest and the framework's
    stamp-inputs step turns it into columns, so a published table really does carry
    ``@td.file.path`` / ``@td.sql.*``::

        <conn>_meta_keep   @td.sql.query = 'SELECT code, name FROM country'
                           @td.sql.initial_values = '{}'
                           @td.file.path = 's3://…/parquet/country_2….parquet'
        <conn>_meta_drop   no ``@td.`` column at all

    :func:`check_keep` therefore proves the metadata is attached and complete, and
    :func:`check_drop` proves the key removes it — the latter only became a real
    assertion once the former passed, since with nothing ever attached it would have
    passed vacuously.

    This was red for a while (stamp-inputs read the manifest metadata into an unused
    local behind a ``TODO``); the assertions were left in unchanged throughout and went
    green when it landed.

WHY THE COLUMNS ARE VISIBLE AT ALL
    ``@td.`` columns are their own category (CONNECTOR), distinct from the framework's
    internal ``$td.`` ones: ``TableFrame.schema`` lists both, and ``_to_polars_lf()``
    (which drops the internals) KEEPS the connector columns. So :func:`columns_of` —
    the data columns plus the metadata — is what the assertions here work from.

    A connector column is also ordinary enough to ``select`` / ``filter`` / ``drop``,
    which is how the keep side's receipt table is built: the frame with its metadata
    dropped, i.e. exactly what the drop side produced in the first place.

NOT COVERED
    ``salesforce`` also accepts the key (``@td.salesforce.soql`` /
    ``@td.salesforce.reportId`` / ``@td.salesforce.last_modified``) but has no
    capability suite to extend — its sources need a live org. Sources that report no
    metadata do not accept the key at all (bigquery / snowflake / clickhouse /
    starrocks / mongodb / druid / kafka / dev), so there is nothing to test there.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from tabsdatak.conn.common.constants import (
    SRC_META_DROP_KEY,
    TD_CONNECTOR_COLUMN_PREFIX,
)
from tabsdatak.conn.common.file.constants import FILE_META_PATH
from tabsdatak.conn.common.sql.constants import (
    SQL_META_INITIAL_VALUES,
    SQL_META_QUERY,
)
from tabsdatak.tableframe import TableFrame

# The src_cfg a suite passes to the drop-side publisher. Taken from the connector's own
# constant, not spelled out, so a rename upstream breaks this suite instead of silently
# turning the drop-side read into a keep-side one (which would still pass a
# presence-only test).
DROP_METADATA: dict[str, bool] = {SRC_META_DROP_KEY: True}

# The metadata each source family reports, again from the connectors' own constants.
FILE_META: tuple[str, ...] = (FILE_META_PATH,)
SQL_META: tuple[str, ...] = (SQL_META_QUERY, SQL_META_INITIAL_VALUES)

# A query with no bind values serializes to this — the SQL sources always report both
# entries, so the shape of the metadata never changes from run to run.
NO_BINDS = "{}"

# The DATA columns each family's pair must publish, with or without the metadata — the
# stand-in for comparing the two frames directly (see the module docstring).
# The file pair reads the staged ``country`` parquet: the world model's country entity.
COUNTRY_COLUMNS: tuple[str, ...] = (
    "code", "name", "continent", "region", "surface_area", "indep_year", "population",
    "life_expectancy", "gnp", "gnp_old", "local_name", "government_form",
    "head_of_state", "capital", "code2",
)
# The SQL pair projects two of them. Case is not part of the expectation: Oracle and Db2
# fold an unquoted identifier to upper case, so the comparison is case-insensitive.
QUERY_COLUMNS: tuple[str, ...] = ("code", "name")


def columns_of(frame: TableFrame) -> list[str]:
    """The frame's data columns plus its ``@td.`` metadata columns (the framework's
    internal ``$td.`` ones dropped) — the view the contract is about."""
    return frame._to_polars_lf().collect_schema().names()


def meta_columns_of(frame: TableFrame) -> list[str]:
    """Just the connector metadata columns of `frame`."""
    return [c for c in columns_of(frame) if c.startswith(TD_CONNECTOR_COLUMN_PREFIX)]


def _assert_data_columns(frame: TableFrame, table: str, meta: Sequence[str],
                         data_columns: Sequence[str]) -> None:
    # Everything that is not metadata must be exactly the columns the read was asked
    # for. Case-insensitive: Oracle/Db2 upper-case an unquoted identifier.
    got = sorted(c.lower() for c in columns_of(frame) if c not in set(meta))
    want = sorted(c.lower() for c in data_columns)
    assert got == want, f"{table}: data columns {got} != {want}"


def _assert_rows(frame: TableFrame, table: str, why: str) -> None:
    assert frame._to_polars_lf().collect().height > 0, f"{table}: no rows, so {why}"


def check_keep(frame: TableFrame, meta: Sequence[str], data_columns: Sequence[str],
               exact: Mapping[str, str] | None = None,
               table: str = "meta_keep") -> TableFrame:
    """The keep side: `frame` carries EXACTLY the metadata columns `meta`, none of them
    null, each column named in `exact` holds that value on every row, and the remaining
    columns are exactly `data_columns`.

    ``exact`` is what makes this more than a presence check — a SQL source reports the
    query it actually ran, so the suite can pin it to the query it asked for.

    Returns the transformer's receipt: the frame with the metadata dropped, which is
    what the drop side should have produced."""
    assert frame is not None, f"{table}: no table published"
    got = meta_columns_of(frame)
    # Compared as a SET: the frame arranges its system columns canonically, so their
    # order is the framework's business, not the contract's.
    assert sorted(got) == sorted(meta), (
        f"{table}: metadata columns {sorted(got)} != {sorted(meta)}"
    )
    _assert_rows(frame, table, "the metadata was never asserted")
    df = frame._to_polars_lf().collect()
    for column in meta:
        nulls = df[column].null_count()
        assert nulls == 0, f"{table}: {column} null in {nulls} of {df.height} row(s)"
    for column, want in (exact or {}).items():
        seen = set(df[column].to_list())
        assert seen == {want}, f"{table}: {column} holds {sorted(seen)}, expected [{want!r}]"
    _assert_data_columns(frame, table, meta, data_columns)
    return frame.drop(*meta)


def check_drop(frame: TableFrame, data_columns: Sequence[str],
               table: str = "meta_drop") -> TableFrame:
    """The drop side: `frame` carries NO connector metadata column whatsoever, and its
    columns are exactly `data_columns` — the drop key removed the metadata and nothing
    else. Returns the frame unchanged as the transformer's receipt."""
    assert frame is not None, f"{table}: no table published"
    got = meta_columns_of(frame)
    assert not got, (
        f"{table}: {SRC_META_DROP_KEY} was set, but the table still carries {got}"
    )
    _assert_rows(frame, table, "the absence of metadata proves nothing")
    _assert_data_columns(frame, table, (), data_columns)
    return frame
