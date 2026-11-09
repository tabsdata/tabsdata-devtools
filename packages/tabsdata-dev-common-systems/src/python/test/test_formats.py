#
# Copyright 2026 Tabsdata Inc.
#

"""What a file domain stages: every model in csv, ndjson, parquet, avro and
xlsx, a log model as its lines, and what a format cannot hold left out -- read
back with the readers a consumer would use. The writers need the systems
toolset's packages, so a test skips where they are missing (the salesforce
toolset runs this package's tests too)."""

import random
from datetime import date, datetime
from decimal import Decimal

import pytest
from tabsdata_dev.common.systems import datagen, emit


def _initial(model: str) -> list[emit.Table]:
    return datagen.load_model(model).build_initial(
        random.Random(datagen.INITIAL_SEED), datagen.BASE_SIZE
    )


def _stage(tmp_path, model: str) -> dict[str, int]:
    from tabsdata_dev.common.systems.systems.fs.backend import Fs

    return Fs()._stage_and_upload(str(tmp_path / model), _initial(model), "S")


@pytest.fixture
def writers():
    for name in ("polars", "fastavro", "xlsxwriter"):
        pytest.importorskip(name)


def test_every_model_is_staged_in_every_format_it_can_be(tmp_path, writers, capsys):
    """Each table of each model, once per format -- but bronze's CDC table in
    Avro, whose ``@td.cdc.*`` names Avro refuses (and the run says so), and the
    log model, which is its lines alone."""
    for model in datagen.list_models():
        staged = _stage(tmp_path, model)
        tables = {t.name: len(t.rows) for t in _initial(model)}
        for name, rows in tables.items():
            for fmt in emit.formats_of(
                next(t for t in _initial(model) if t.name == name)
            ):
                rel = f"{fmt}/{name}_S.{fmt}"
                if model == "bronze" and name.endswith("cdc_stream") and fmt == "avro":
                    assert rel not in staged
                    continue
                assert staged.get(rel) == rows, (model, rel)
                assert (tmp_path / model / rel).is_file()
    assert "brz_cdc_stream: no avro file (not Avro names: @td.cdc.meta.op" in (
        capsys.readouterr().out
    )


def test_an_avro_file_holds_the_rows_with_their_types(tmp_path, writers):
    """Read back as written: decimals at their scale, nulls as nulls, a date a
    date and a timestamp a timestamp (arrow-avro's logical types)."""
    import fastavro

    _stage(tmp_path, "world")
    with (tmp_path / "world" / "avro" / "country_S.avro").open("rb") as f:
        reader = fastavro.reader(f)
        fields = {x["name"]: x["type"] for x in reader.writer_schema["fields"]}
        rows = list(reader)
    assert fields["surface_area"]["logicalType"] == "decimal"
    assert fields["indep_year"] == ["null", "int"]
    country = _initial("world")[0]
    assert len(rows) == len(country.rows)
    assert rows[0]["surface_area"] == Decimal(str(country.rows[0]["surface_area"]))
    assert any(r["indep_year"] is None for r in rows)

    _stage(tmp_path, "employees")
    with (tmp_path / "employees" / "avro" / "employees_S.avro").open("rb") as f:
        emp = next(iter(fastavro.reader(f)))
    assert isinstance(emp["birth_date"], date)

    _stage(tmp_path, "airportdb")  # time columns, which polars cannot write
    with (tmp_path / "airportdb" / "avro" / "flight_S.avro").open("rb") as f:
        flight = next(iter(fastavro.reader(f)))
    assert isinstance(flight["departure"], datetime)


def test_an_auto_column_left_to_the_database_is_null_in_avro(tmp_path, writers):
    import fastavro

    _stage(tmp_path, "sakila")
    with (tmp_path / "sakila" / "avro" / "payment_S.avro").open("rb") as f:
        assert next(iter(fastavro.reader(f)))["payment_id"] is None


def test_an_xlsx_file_is_one_sheet_with_a_header(tmp_path, writers):
    openpyxl = pytest.importorskip("openpyxl")
    _stage(tmp_path, "world")
    book = openpyxl.load_workbook(tmp_path / "world" / "xlsx" / "city_S.xlsx")
    sheet = book.worksheets[0]
    city = _initial("world")[1]
    assert len(book.worksheets) == 1
    assert [c.value for c in sheet[1]] == [c.name for c in city.columns]
    assert sheet.max_row == len(city.rows) + 1
    assert sheet.cell(2, 2).value == city.rows[0]["name"]


def test_a_table_past_a_worksheet_is_left_out_of_xlsx(monkeypatch, tmp_path, writers):
    monkeypatch.setattr(emit, "XLSX_MAX_ROWS", 2)
    table = emit.Table("t", [emit.Column("a", "int")], [{"a": i} for i in range(3)])
    assert emit.unwritable(table, "xlsx") == "3 rows, past a worksheet's 2"
    with pytest.raises(ValueError, match="cannot be written as xlsx"):
        emit.write_frame(table, tmp_path / "t.xlsx", "xlsx")
    assert emit.unwritable(table, "csv") is None


def test_a_log_file_is_the_lines_lf_terminated(tmp_path, writers):
    staged = _stage(tmp_path, "logs")
    assert set(staged) == {"log/app_S.log", "log/access_S.log"}
    for table in _initial("logs"):
        data = (tmp_path / "logs" / "log" / f"{table.name}_S.log").read_bytes()
        assert b"\r" not in data and data.endswith(b"\n")
        assert data.decode("utf-8").splitlines() == [r["line"] for r in table.rows]


def test_write_frame_refuses_a_log_of_a_table_without_lines(tmp_path):
    table = emit.Table("t", [emit.Column("a", "int")], [{"a": 1}])
    assert emit.formats_of(table) == emit.FILE_FORMATS
    with pytest.raises(ValueError, match="not a log table"):
        emit.write_frame(table, tmp_path / "t.log", "log")


def test_the_avro_schema_follows_the_sql_types():
    cols = [
        emit.Column("i", "smallint", nullable=False),
        emit.Column("b", "bigint", nullable=False),
        emit.Column("d", "decimal(8,3)", nullable=False),
        emit.Column("t", "time", nullable=False),
        emit.Column("ts", "datetime", nullable=False),
        emit.Column("s", "varchar(9)"),
        emit.Column("k", "int", nullable=False, auto=True),
    ]
    fields = emit.avro_schema("x", cols)["fields"]
    assert [f["type"] for f in fields] == [
        "int",
        "long",
        {"type": "bytes", "logicalType": "decimal", "precision": 8, "scale": 3},
        {"type": "long", "logicalType": "time-micros"},
        {"type": "long", "logicalType": "local-timestamp-micros"},
        ["null", "string"],
        ["null", "int"],
    ]
    row = {"i": 1, "b": 2, "d": 1.5, "t": "10:11:12", "ts": "2026-01-02 03:04:05"}
    record = emit.avro_record(row, cols)
    assert record["d"] == Decimal("1.500") and record["ts"] == datetime(
        2026, 1, 2, 3, 4, 5
    )


# ---- the logs model --------------------------------------------------------


def test_the_logs_model_is_deterministic_and_says_what_its_lines_do():
    first, again = _initial("logs"), _initial("logs")
    assert [t.rows for t in first] == [t.rows for t in again]
    app, access = first
    stamps = [r["ts"] for r in app.rows if r["ts"] is not None]
    assert stamps == sorted(stamps)
    for r in app.rows:
        if r["level"] is None:  # a stack-trace continuation: nothing to parse
            assert r["line"].startswith("    at ") and r["message"] is None
        else:
            assert f" {r['level']} [{r['service']}] req={r['request_id']} " in r["line"]
    assert any(r["level"] is None for r in app.rows)
    assert any(r["latency_ms"] is None for r in app.rows)
    for r in access.rows:
        assert r["line"].startswith(f"{r['client_ip']} - {r['user_name'] or '-'} [")
        assert f'" {r["status"]} ' in r["line"]


def test_the_access_log_spells_its_month_whatever_the_locale():
    from tabsdata_dev.common.systems.models.logs import datagenerator as logs

    row = logs.access_row(random.Random(1), 0, datetime(2026, 8, 9, 1, 2, 3))
    assert "[09/Aug/2026:01:02:03 +0000]" in row["line"]


def test_a_log_takes_inserts_only_after_its_seed():
    model = datagen.load_model("logs")
    assert {k for e in model.entities for k in e.supports} == {datagen.OpKind.INSERT}
    last = max(r["ts"] for t in _initial("logs") for r in t.rows if r["ts"])
    rng = random.Random(0)
    for entity in model.entities:
        row = entity.new_row(rng, 0)
        assert (row["ts"] or datetime.max) > last
        assert row["line"]


def test_shopevents_is_insert_only_with_keys_past_its_seed():
    model = datagen.load_model("shopevents")
    seeded = {
        t.name: max(r[t.columns[0].name] for r in t.rows)
        for t in _initial("shopevents")
    }
    for entity in model.entities:
        assert entity.supports == (datagen.OpKind.INSERT,)
        key = entity.new_row(random.Random(0), 0)[entity.columns[0].name]
        assert key > seeded[entity.table]
