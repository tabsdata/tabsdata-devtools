#
# Copyright 2026 Tabsdata Inc.
#
"""_harness — reusable scaffolding for the ``grok`` suite.

PURPOSE
    The ``grok`` suite exercises ``TableFrame.grok`` — the ``tabsdatak.tableframe.grok``
    feature that turns one unstructured text column into structured, typed columns —
    end to end, on REAL unstructured input rather than a hand-built frame.

    The input is the ``world`` model's own CSV, read as a LOG. A file domain stages
    every model entity as ``csv/<entity>_<stamp>.csv`` (plus ndjson/parquet), and
    ``SrcFileFormat.LOG`` reads a file as TEXT: one row per LINE, two columns —
    ``file`` (the file's name) and ``message`` (the whole line, delimiters and all).
    So the publisher deliberately throws the CSV's structure away, and grok is what
    puts it back:

        csv/city_<stamp>.csv          LocalFileSrc(format=LOG)      .grok(...)
        1,Kabul,AFG,Kabol,1780000  ->  message: "1,Kabul,AFG,…"  ->  city_id  1
                                                                    city_name Kabul
                                                                    country_code AFG
                                                                    district Kabol
                                                                    population 1780000

    Each test file is a three-function chain over the suite's three collections,
    modelled on the ``tableframe_api`` and ``dataquality`` suites:

        pub  (@publisher , collection ``gk_src`` , LocalFileSrc + SrcFileFormat.LOG)
            reads one entity's staged CSV as lines and publishes the raw
            ``file``/``message`` table. No parsing here — that is the point.
        tfr  (@transformer, collection ``gk_ops`` , connection-less)
            applies the GROK CALLS UNDER TEST to ``message``, emitting one result
            table per call. ``grok`` appends one column per named capture and keeps
            the source column, so it is ROW-PRESERVING — which is what a transformer
            output must be for the sink to accept it.
        sub  (@subscriber , collection ``gk_sink``, TrashDest)
            reads the result tables and ASSERTS the parse: which columns exist, their
            dtypes, the values on a probe row, and which rows came back null. A failed
            assertion raises, failing the transaction — that is the red/green signal.

THE ORACLE
    polars has no grok, so (unlike ``tableframe_api``) there is no reference
    implementation to re-run: the expectations ARE the oracle. They are authored
    against data of KNOWN content — the canonical MySQL ``world`` sample data, whose
    first rows never change — so a probe like "the row whose ``city_id`` is 1 is
    Kabul, AFG, Kabol, 1780000" is a real assertion about grok's output, not a
    tautology. Every expectation must hold BOTH on the live file and on the embedded
    :data:`SAMPLE` lines, so :meth:`GrokCase.selfcheck` can run the whole comparison
    offline (no server, no domain) — hence: no expectation about total row counts,
    and every probe row is one of the sample lines.

WHAT THE CSV-AS-LOG GIVES YOU FOR FREE
    * A HEADER LINE that no typed pattern matches (``%{INT:id}`` vs ``"id"``), which
      is the natural test of grok's documented "non-matching rows come back null"
      contract — a real non-match, not a synthetic one.
    * QUOTED FIELDS: ``country`` has names and government forms containing commas
      (``"Constitutional Monarchy, Federation"``) and empty ``""`` values, because
      polars quotes them on write. A comma-counting pattern cannot parse those lines,
      so ``gk_country`` parses what a log parser really can: the fields before the
      first quoted one, plus ``%{GREEDYDATA}`` for the rest.
    * Values with SPACES inside a comma-delimited line (``North America``), which is
      what separates ``%{DATA}`` / ``%{GREEDYDATA}`` from ``%{WORD}`` / ``%{NOTSPACE}``.

ADDING A TEST
    Copy an existing file. Pick the entity, write one :class:`Grok` per call under
    test (a result-table name, a pattern, a capture -> ``ColumnDefinition`` schema and
    its expectations), assemble one module-level ``CASE = GrokCase(...)``, and wire
    the pub/tfr/sub triple (thin stubs that delegate to the case). The transformer's
    ``output_tables`` and the subscriber's ``input_tables`` come from
    ``CASE.output_names``; only the signatures must be spelled out with the right
    arity (one param per Grok). Then:
      * ``python ../validate.py gk_<name>`` — imports the file (runs the decorator
        signature checks) and runs ``CASE.selfcheck()`` over the sample lines. Fast,
        no server.
      * add the stem to the right category in ``../gen_suites.py`` and run
        ``python ../gen_suites.py`` — regenerates every ``<category>.json`` from the
        files (no hand-editing of JSON).
    Then ``tdx-xp oneshot --suite grok/<category>`` runs one category, or
    ``tdx-xp oneshot --suite grok`` runs the whole suite (a bare ``--suite <dir>`` fans
    out over every ``*.json`` in the dir, one instance per file).

EXAMPLES vs TESTS
    This harness is for the TESTS (``gk_<name>.py``): declarative cases whose subscriber
    asserts what each grok call produced. The suite also carries EXAMPLES
    (``gk_ex_<name>.py``, category ``examples``) that use NONE of this — they call
    ``TableFrame.grok`` inline in a plain @transformer body and land the result as
    parquet, so they read the way user code reads. Assertions belong here; a new way of
    USING grok belongs there.

    Name each file ``gk_<name>.py``: the worker imports a function's file by its bare
    stem with the bundle dir on ``sys.path``, so the ``gk_`` prefix keeps every stem
    clear of stdlib module names. Table names must be unique per COLLECTION, and every
    file shares ``gk_src``/``gk_ops``, so prefix them per file.

Import this module from a test file with the relative-then-absolute fallback::

    try:
        from ._harness import Grok, GrokCase, OPS, SRC, dtypes, row
    except ImportError:
        from _harness import Grok, GrokCase, OPS, SRC, dtypes, row

At registration the CLI loads the function file as a submodule of a synthetic package
(the RELATIVE import resolves); on the worker the file is imported top-level with the
bundle directory on ``sys.path`` (the ABSOLUTE import resolves). The try/except makes
one file work in both.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import polars as pl

from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.grok import ColumnDefinition

# Collection names, shared so every test file's cross-collection table refs
# (transformer input ``<SRC>/<table>@NEW``, subscriber input ``<OPS>/<table>``) stay in
# lockstep with the collections declared in the suite JSON.
SRC = "gk_src"      # sources        — LocalFileSrc publishers reading CSV as LOG
OPS = "gk_ops"      # transform      — the grok calls under test
SINK = "gk_sink"    # destinations   — TrashDest subscribers (assert + discard)

# The two columns SrcFileFormat.LOG produces (transporter ``text`` format): the file's
# name, and one row per line holding the WHOLE line.
FILE = "file"
MESSAGE = "message"

# The staged-file glob for an entity of a file domain, relative to the domain root: the
# data plane writes ``csv/<entity>_<YYYYMMDD>T<hhmmss_mmm>.csv``, so the stamp is globbed
# away — from its leading ``2`` (the year), NOT from the underscore, because
# ``country_*`` would also match ``country_language_*``. The source's matcher takes only
# ``*`` / ``?`` (no character classes), so this is the same trick the connectors suite
# uses (``parquet/country_2*.parquet``). A glob makes the source ARRAY mode: one slot
# holding every match, oldest file first.
def log_glob(entity: str) -> str:
    return f"csv/{entity}_2*.csv"


# The first lines of each entity's staged CSV, verbatim — the offline stand-in for the
# file the publisher reads live (:meth:`GrokCase.selfcheck`). Real ``world`` reference
# data: countries/cities/languages from the canonical MySQL sample DB, whose leading
# rows are fixed, so an expectation written against them holds on the live file too.
# The header line is included on purpose: it is the suite's non-matching row.
SAMPLE: Mapping[str, tuple[str, ...]] = {
    "city": (
        "id,name,country_code,district,population",
        "1,Kabul,AFG,Kabol,1780000",
        "2,Qandahar,AFG,Qandahar,237500",
        "3,Herat,AFG,Herat,186800",
        "4,Mazar-e-Sharif,AFG,Balkh,127800",
        "5,Amsterdam,NLD,Noord-Holland,731200",
        "6,Rotterdam,NLD,Zuid-Holland,593321",
    ),
    "country_language": (
        "country_code,language,is_official,percentage",
        "ABW,Dutch,T,5.3",
        "ABW,English,F,9.5",
        "ABW,Papiamento,F,76.7",
        "ABW,Spanish,F,7.4",
        "AFG,Balochi,F,0.9",
        "AFG,Dari,T,32.1",
    ),
    "country": (
        "code,name,continent,region,surface_area,indep_year,population,life_expectancy,"
        "gnp,gnp_old,local_name,government_form,head_of_state,capital,code2",
        "ABW,Aruba,North America,Caribbean,193.0,,103000,78.4,828.0,793.0,Aruba,"
        "Nonmetropolitan Territory of The Netherlands,Beatrix,,AW",
        "AFG,Afghanistan,Asia,Southern and Central Asia,652090.0,1919,22720000,45.9,"
        "5976.0,,Afganistan/Afqanestan,Islamic Emirate,Mohammad Omar,1,AF",
        # Quoted EMPTY head_of_state — polars quotes an empty string on write.
        "AND,Andorra,Europe,Southern Europe,468.0,1278,78000,83.5,1630.0,,Andorra,"
        'Parliamentary Coprincipality,"",55,AD',
        # Quoted government_form CONTAINING A COMMA: the line has more commas than
        # fields, which is what makes comma-counting patterns wrong on real CSV.
        "AUS,Australia,Oceania,Australia and New Zealand,7741220.0,1901,18886000,79.8,"
        '351182.0,392911.0,Australia,"Constitutional Monarchy, Federation",'
        "Elisabeth II,,AU",
    ),
}


# --- expectations ------------------------------------------------------------
# An expectation is a named assertion over one grok result, materialised as an eager
# polars DataFrame (system columns dropped). polars is the assertion language, not an
# oracle: it states what grok is specified to have produced. Raise AssertionError to
# fail — that fails the subscriber, the transaction and the run.
@dataclass(frozen=True)
class Expect:
    """One assertion over a grok result frame: ``what`` names it in the failure
    message, ``check`` raises AssertionError if it does not hold."""

    what: str
    check: Callable[[pl.DataFrame], None]


def has_columns(*names: str) -> Expect:
    """Every named column is present (one per capture, plus whatever was kept)."""

    def check(df: pl.DataFrame) -> None:
        missing = [n for n in names if n not in df.columns]
        assert not missing, f"missing column(s) {missing}; have {df.columns}"

    return Expect(f"has columns {list(names)}", check)


def no_columns(*names: str) -> Expect:
    """No named column is present — for the CAPTURE names a ``ColumnDefinition``
    renamed away, which must not leak into the output."""

    def check(df: pl.DataFrame) -> None:
        present = [n for n in names if n in df.columns]
        assert not present, f"unexpected column(s) {present}"

    return Expect(f"no columns {list(names)}", check)


def order(*names: str) -> Expect:
    """The named columns appear in this RELATIVE order. grok's output order follows
    the schema dict, not the order the captures occur in the pattern."""

    def check(df: pl.DataFrame) -> None:
        got = [c for c in df.columns if c in set(names)]
        assert got == list(names), f"column order {got} != {list(names)}"

    return Expect(f"order {list(names)}", check)


def dtypes(**by_column: object) -> Expect:
    """Each column's dtype is exactly the one its ``ColumnDefinition`` asked for —
    the cast grok applies after the capture (every capture is text before it)."""

    def check(df: pl.DataFrame) -> None:
        for name, want in by_column.items():
            assert name in df.columns, f"missing column {name!r}; have {df.columns}"
            got = df.schema[name]
            assert got == want, f"{name}: dtype {got} != {want}"

    return Expect(f"dtypes {sorted(by_column)}", check)


def row(where: pl.Expr, **values: object) -> Expect:
    """EXACTLY ONE row matches ``where``, and it holds ``values``. The probe row must
    be one of the :data:`SAMPLE` lines so the expectation also holds offline."""

    def check(df: pl.DataFrame) -> None:
        hit = df.filter(where)
        assert hit.height == 1, f"{hit.height} row(s) match the probe, expected 1"
        for name, want in values.items():
            got = hit[name][0]
            assert got == want, f"{name}: {got!r} != {want!r}"

    return Expect(f"row {sorted(values)}", check)


def nulls(where: pl.Expr, *columns: str) -> Expect:
    """Every row matching ``where`` is NULL in each named column — grok's contract for
    a line the pattern does not match (the CSV header line, a partial match)."""

    def check(df: pl.DataFrame) -> None:
        hit = df.filter(where)
        assert hit.height > 0, "no row matches the predicate, so nothing was asserted"
        for name in columns:
            bad = hit.filter(pl.col(name).is_not_null())
            assert bad.height == 0, (
                f"{name}: {bad.height} of {hit.height} matching row(s) not null "
                f"(first: {bad[name][0]!r})"
            )

    return Expect(f"nulls in {list(columns)}", check)


def filled(*columns: str, where: pl.Expr | None = None) -> Expect:
    """No NULL in the named columns (optionally only over the rows matching ``where``)
    — the positive half of the null contract: a matching line loses nothing."""

    def check(df: pl.DataFrame) -> None:
        hit = df if where is None else df.filter(where)
        assert hit.height > 0, "no row to assert on"
        for name in columns:
            n = hit.filter(pl.col(name).is_null()).height
            assert n == 0, f"{name}: {n} of {hit.height} row(s) null"

    return Expect(f"filled {list(columns)}", check)


def count(where: pl.Expr, n: int) -> Expect:
    """Exactly ``n`` rows match ``where`` — for a pattern that is expected to match
    only some lines (use a predicate the sample lines determine, not the whole file)."""

    def check(df: pl.DataFrame) -> None:
        got = df.filter(where).height
        assert got == n, f"{got} row(s) match, expected {n}"

    return Expect(f"count == {n}", check)


# --- the case ---------------------------------------------------------------
# A row-preserving follow-up applied to a grok result inside the transformer (a
# filter/select/sort — never group_by, whose output does not sink).
Then = Callable[[TableFrame], TableFrame]


@dataclass(frozen=True)
class Grok:
    """One ``TableFrame.grok`` call under test, plus what its result must look like.

    ``name``    : the result table this call emits (unique within its collection —
                  every file shares ``gk_ops``, so prefix it per file).
    ``pattern`` : the grok pattern, with a named capture per column to extract
                  (``%{INT:id}``); the standard grok pattern library is available, and
                  raw regex may be mixed in (``(?:%{WORD:x})?``, anchors).
    ``schema``  : capture name -> ``ColumnDefinition(name, dtype)``. The definition's
                  ``name`` renames the output column and its ``dtype`` casts it; the
                  DICT ORDER fixes the output column order.
    ``expects`` : the assertions the subscriber runs over the result.
    ``expr``    : what to parse — a column name (default :data:`MESSAGE`) or a
                  tabsdatak ``Expr`` resolving to one string column.
    ``then``    : optional row-preserving follow-up on the grok result.
    """

    name: str
    pattern: str
    schema: dict[str, ColumnDefinition]
    expects: Sequence[Expect] = ()
    expr: object = MESSAGE
    then: Then | None = field(default=None)

    def apply(self, log: TableFrame) -> TableFrame:
        out = log.grok(self.expr, self.pattern, self.schema)
        return self.then(out) if self.then is not None else out


class GrokCase:
    """One grok test case: the entity whose CSV is read as a log, and the grok calls
    over its lines.

    A test file builds a single ``GrokCase`` and threads it through the pub/tfr/sub
    triple — the publisher reads :attr:`paths`, the transformer calls
    :meth:`transform`, the subscriber calls :meth:`verify`. :meth:`selfcheck` runs the
    whole thing offline against :data:`SAMPLE` (no server, no domain).
    """

    def __init__(self, entity: str, table: str, groks: Sequence[Grok]) -> None:
        # ``entity`` : a ``world`` model entity (city / country_language / country) —
        #              picks both the live file glob and the offline sample lines.
        # ``table``  : the published lines table (unique within ``gk_src``).
        # ``groks``  : the calls under test, one result table each.
        assert entity in SAMPLE, f"unknown entity {entity!r}; have {sorted(SAMPLE)}"
        assert groks, "a GrokCase needs at least one Grok"
        self.entity = entity
        self.table = table
        self.groks = tuple(groks)

    @property
    def paths(self) -> list[str]:
        """The ``LocalFileSrc(paths=...)`` value: the entity's staged CSV."""
        return [log_glob(self.entity)]

    @property
    def output_names(self) -> list[str]:
        """The result table names, in call order — the transformer's ``output_tables``
        and (bare) the subscriber's ``input_tables``."""
        return [g.name for g in self.groks]

    def lines(self) -> TableFrame:
        """The sample lines shaped exactly as ``SrcFileFormat.LOG`` delivers them:
        ``file`` + ``message``, one row per line. Offline only."""
        rows = SAMPLE[self.entity]
        return TableFrame.from_polars(pl.DataFrame({
            FILE: [f"{self.entity}_20260101T000000_000.csv"] * len(rows),
            MESSAGE: list(rows),
        }))

    def transform(self, log: TableFrame) -> tuple:
        """Apply every grok call to the published lines table. Returns one TableFrame
        per call, in order — the transformer's output tables."""
        return tuple(g.apply(log) for g in self.groks)

    def verify(self, received) -> None:
        """Run each call's expectations over the received result tables (materialised
        to eager polars, system columns dropped). Raises AssertionError naming the
        result table and the expectation that failed."""
        actual = tuple(received) if isinstance(received, (tuple, list)) else (received,)
        assert len(actual) == len(self.groks), (
            f"output-arity mismatch: {len(self.groks)} grok call(s) but "
            f"{len(actual)} table(s) received"
        )
        for got, grok in zip(actual, self.groks):
            assert got is not None, f"{grok.name}: no table received"
            df = got._to_polars_lf().collect()
            _run(grok, df)

    def selfcheck(self) -> None:
        """Run every call and its expectations OFFLINE over :data:`SAMPLE` (no server;
        does NOT test the LOG read or the storage round-trip — that is what
        ``tdx-xp oneshot --suite grok/<category>`` covers).

        Each call is checked independently, so one failure does not hide the others;
        raises a single AssertionError listing every failing call."""
        log = self.lines()
        failures: list[str] = []
        for grok in self.groks:
            try:
                _run(grok, grok.apply(log)._to_polars_lf().collect())
            except Exception as e:  # noqa: BLE001 -- record & continue to the next call
                first = str(e).splitlines()[0] if str(e) else ""
                failures.append(f"{grok.name}: {type(e).__name__}: {first[:160]}")
        if failures:
            raise AssertionError("; ".join(failures))


def _run(grok: Grok, df: pl.DataFrame) -> None:
    # Every expectation of one grok call, each failure labelled with the result table
    # and the expectation's own description.
    for e in grok.expects:
        try:
            e.check(df)
        except AssertionError as exc:
            raise AssertionError(f"{grok.name} [{e.what}]: {exc}") from None
