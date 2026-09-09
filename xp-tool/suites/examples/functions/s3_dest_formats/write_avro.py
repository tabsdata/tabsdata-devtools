#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 destination: AVRO.

Like parquet, Avro carries its own schema and takes no `format_cfg`. Row-oriented
rather than columnar, so it suits a consumer that streams whole records; parquet
suits one that reads a few columns of many rows.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.s3 import S3Dest


@subscriber(
    destination=S3Dest(paths=["customers.avro"], format=DestFileFormat.AVRO),
    input_tables=["gen/customers"],
)
def write_avro(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
