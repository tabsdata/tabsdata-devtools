#
# Copyright 2026 Tabsdata Inc.
#

"""showcase · employees — HR views over the `employees` sample.

Three stages, one collection each:

  employees_src  (@publisher)    read departments / employees / dept_emp
                                 / salaries parquet from a local-file source
  employees_marts(@transformer)  a department roster and a high-earners view
  employees_out  (@subscriber)   write each view out to a local parquet file

Pure tabsdatak TableFrame API (join / filter / select / sort) — no polars. These are
ROW-PRESERVING transforms (carry the framework's system columns through).
"""
from __future__ import annotations

from tabsdatak.api import (
    TableFrameSpec,
    TableFramesSpec,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.tableframe.functions import concat
from tabsdatak.conn.bigquery import BigQueryDest
from tabsdatak.conn.localfile import LocalFileDest, LocalFileSrc
from tabsdatak.tableframe.functions import col


# --- ingest: local-file employees parquet -> employees_src -------------------
@publisher(
    source=LocalFileSrc(
        # The employees seed writes timestamped, possibly-duplicated shards per
        # table (`<table>_<YYYYMMDDThhmmss_mmm>.parquet`), so each entry globs.
        # `<table>_2*` (not `<table>*`) keeps the `dept_emp` slot from also
        # swallowing the `dept_manager` shards — the shard suffix always starts
        # with the year, so `_2` disambiguates against sibling table names.
        paths=[
            "parquet/departments_2*.parquet",
            "parquet/employees_2*.parquet",
            "parquet/dept_emp_2*.parquet",
            "parquet/salaries_2*.parquet",
        ],
    ),
    output_tables=["departments", "employees", "dept_emp", "salaries"],
)
def pub_employees(
    departments: TableFramesSpec,
    employees: TableFramesSpec,
    dept_emp: TableFramesSpec,
    salaries: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    # Each glob resolves to one file -> 1-element array slots -> slot[0].
    return (departments[0], employees[0], dept_emp[0], salaries[0])


# --- marts: enrichment joins + filter (employees_src -> employees_marts) -----
@transformer(
    input_tables=[
        "employees_src/dept_emp@NEW",
        "employees_src/departments@HEAD",
        "employees_src/employees@HEAD",
    ],
    output_tables=["dept_roster"],
)
def tfr_dept_roster(
    dept_emp_versions: TableFramesSpec, departments: TableFrameSpec, employees: TableFrameSpec
) -> TableFrameSpec:
    # Who works where: dept_emp -> departments (name) -> employees (name).
    dept_emp = concat(dept_emp_versions or [])
    roster = dept_emp.join(
        departments.select("dept_no", "dept_name"), on="dept_no", how="left"
    )
    roster = roster.join(
        employees.select("emp_no", "first_name", "last_name"), on="emp_no", how="left"
    )
    return roster.select("emp_no", "first_name", "last_name", "dept_name", "from_date")


@transformer(
    input_tables=["employees_src/salaries@NEW", "employees_src/employees@HEAD"],
    output_tables=["high_earners"],
)
def tfr_high_earners(
    salaries_versions: TableFramesSpec, employees: TableFrameSpec
) -> TableFrameSpec:
    # Salary records above a threshold, with the employee's name, highest first.
    salaries = concat(salaries_versions or [])
    return (
        salaries.filter(col("salary") > 70000)
        .join(employees.select("emp_no", "first_name", "last_name"), on="emp_no", how="left")
        .select("emp_no", "first_name", "last_name", "salary", "from_date")
        .sort("salary", descending=True)
    )


# --- serve: one view sink per table (employees_marts -> local parquet) -------
@subscriber(
    destination=LocalFileDest(paths=["dept_roster.parquet"]),
    input_tables=["employees_marts/dept_roster"],
)
def sink_dept_roster(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=LocalFileDest(paths=["high_earners.parquet"]),
    input_tables=["employees_marts/high_earners"],
)
def sink_high_earners(t: TableFrameSpec) -> TableFrameSpec:
    return t


# --- serve (warehouse): the same marts bulk-loaded into BigQuery -------------
# One mart sink per table. BigQuery target names must be backtick-quoted and
# resolve within the dataset of the `bq` domain's connection; staged via GCS.
@subscriber(
    destination=BigQueryDest(tables=["`dept_roster`"], if_table_exists="replace"),
    input_tables=["employees_marts/dept_roster"],
)
def bq_dept_roster(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=BigQueryDest(tables=["`high_earners`"], if_table_exists="replace"),
    input_tables=["employees_marts/high_earners"],
)
def bq_high_earners(t: TableFrameSpec) -> TableFrameSpec:
    return t
