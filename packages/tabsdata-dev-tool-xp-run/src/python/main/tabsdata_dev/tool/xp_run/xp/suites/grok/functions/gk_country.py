#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.grok — messy real lines: ``%{GREEDYDATA}`` / ``%{DATA}``, values with
spaces, and an ``Expr`` instead of a column name.

``country`` is the entity a naive comma-counting pattern gets WRONG, which is why it is
here. polars quotes a field that contains the delimiter, so some lines carry more commas
than fields::

    AUS,Australia,Oceania,Australia and New Zealand,...,"Constitutional Monarchy, Federation",...
    COD,"Congo, The Democratic Republic of the",Africa,...

A pattern that counts commas would silently MIS-ALIGN those rows (a wrong parse, not a
null), so what a log parser can safely do here is take the fields up to the first quoted
one and keep the remainder verbatim — which is exactly what ``%{GREEDYDATA}`` is for.
The probes below therefore pin specific, known lines rather than asserting every row.

Three calls: the quoting-proof ``code`` + rest split; the leading fields where two of
them contain SPACES (``North America``, ``Australia and New Zealand``) that ``%{WORD}``
could not capture; and the same split with ``expr`` passed as a TableFrame ``Expr``
(``col("message")``) rather than the column's name.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.dev import TrashDest
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe import TableFrame, datatypes as td
from tabsdatak.tableframe.functions import col, concat
from tabsdatak.tableframe.grok import ColumnDefinition as CD

try:
    from ._harness import (
        MESSAGE, OPS, SRC, Grok, GrokCase, dtypes, filled, has_columns, row,
    )
except ImportError:
    from _harness import (
        MESSAGE, OPS, SRC, Grok, GrokCase, dtypes, filled, has_columns, row,
    )

# The whole remainder of the ABW line, verbatim — including the two EMPTY fields
# (`,,` for indep_year and capital), which GREEDYDATA keeps as-is.
_ABW_REST = ("Aruba,North America,Caribbean,193.0,,103000,78.4,828.0,793.0,Aruba,"
             "Nonmetropolitan Territory of The Netherlands,Beatrix,,AW")
# The AUS line's government_form is quoted BECAUSE it contains a comma; the quoting
# survives untouched inside a capture. Two remainders of the same line: after the code
# alone, and after the four leading fields (what the two patterns below each leave).
_AUS_TAIL = ("Australia,Oceania,Australia and New Zealand,"
             "7741220.0,1901,18886000,79.8,351182.0,392911.0,Australia,"
             '"Constitutional Monarchy, Federation",Elisabeth II,,AU')
_AUS_REST = ('7741220.0,1901,18886000,79.8,351182.0,392911.0,Australia,'
             '"Constitutional Monarchy, Federation",Elisabeth II,,AU')

# `%{WORD:code}` then everything else. Quoting-proof: the pattern makes no claim about
# what follows the first comma, so every line matches — including the header, whose
# first field is the word `code`.
_HEAD_REST = r"^%{WORD:code},%{GREEDYDATA:rest}$"

CASE = GrokCase(
    entity="country",
    table="country_lines",
    groks=[
        Grok(
            name="country_greedy",
            pattern=_HEAD_REST,
            schema={"code": CD("code", td.String), "rest": CD("rest", td.String)},
            expects=[
                has_columns(MESSAGE, "code", "rest"),
                dtypes(code=pl.String, rest=pl.String),
                # No line fails this pattern, not even the header — `%{WORD}` matches
                # the literal text `code` just as happily as `ABW`.
                filled("code", "rest"),
                row(pl.col("code") == "ABW", rest=_ABW_REST),
                row(pl.col("code") == "AUS", rest=_AUS_TAIL),
                row(pl.col("code") == "code",
                    rest=("name,continent,region,surface_area,indep_year,population,"
                          "life_expectancy,gnp,gnp_old,local_name,government_form,"
                          "head_of_state,capital,code2")),
            ],
        ),
        Grok(
            name="country_spaces",
            # Three `%{DATA}` captures (non-greedy: each stops at the next comma) then
            # the remainder. `continent` and `region` hold values WITH SPACES, which is
            # the difference between `%{DATA}` and `%{WORD}`/`%{NOTSPACE}`.
            pattern=(r"^%{WORD:code},%{DATA:name},%{DATA:continent},%{DATA:region},"
                     r"%{GREEDYDATA:rest}$"),
            schema={
                "code": CD("code", td.String),
                "name": CD("name", td.String),
                "continent": CD("continent", td.String),
                "region": CD("region", td.String),
                "rest": CD("rest", td.String),
            },
            expects=[
                row(pl.col("code") == "ABW", name="Aruba", continent="North America",
                    region="Caribbean"),
                row(pl.col("code") == "AFG", name="Afghanistan", continent="Asia",
                    region="Southern and Central Asia"),
                row(pl.col("code") == "AUS", name="Australia", continent="Oceania",
                    region="Australia and New Zealand", rest=_AUS_REST),
            ],
        ),
        Grok(
            name="country_expr",
            pattern=_HEAD_REST,
            # `expr` may be an EXPRESSION resolving to one string column, not only a
            # column name — anything the TableFrame API can build.
            expr=col(MESSAGE),
            schema={"code": CD("code", td.String), "rest": CD("rest", td.String)},
            expects=[
                has_columns("code", "rest"),
                filled("code", "rest"),
                row(pl.col("code") == "AND",
                    rest=("Andorra,Europe,Southern Europe,468.0,1278,78000,83.5,1630.0,,"
                          'Andorra,Parliamentary Coprincipality,"",55,AD')),
            ],
        ),
    ],
)


@publisher(
    source=LocalFileSrc(paths=CASE.paths, format=SrcFileFormat.LOG),
    output_tables=[CASE.table],
)
def country_pub(lines: TableFramesSpec) -> TableFrameSpec:
    # A globbed path is ARRAY mode: the slot is a LIST of frames, one per matched
    # file, so union them. The `world` model is reference-only (no modify-data
    # deltas), so today exactly one file matches — concat keeps that an assumption
    # about the data, not about the read.
    return concat(lines)


@transformer(input_tables=[f"{SRC}/{CASE.table}@NEW"], output_tables=CASE.output_names)
def country_tfr(log: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(log)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def country_sub(greedy: TableFrameSpec, spaces: TableFrameSpec,
                expr: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([greedy, spaces, expr])
    return TableFrame.empty()
