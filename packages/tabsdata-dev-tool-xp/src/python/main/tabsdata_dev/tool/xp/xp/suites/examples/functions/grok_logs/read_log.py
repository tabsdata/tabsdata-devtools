#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — reading a file as a LOG, which is what makes grok necessary.

`SrcFileFormat.LOG` reads a file as TEXT: ONE ROW PER LINE, two columns — `file`
(the name it was read from) and `message` (the whole line, delimiters and all).
No parsing at all.

THAT IS THE POINT, and it is a deliberate pipeline choice rather than a
limitation: LAND THE RAW LINES FIRST, PARSE THEM DOWNSTREAM. A pattern that turns
out to be wrong is then fixed by re-running one transformer over a table you
already have, instead of re-ingesting the source. Logs are exactly the kind of
input whose format you discover you misunderstood on day three.

The transformers in the `ops` collection do the parsing, reacting to `@NEW`
versions of this table.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=LocalFileSrc(paths=["app.log"], format=SrcFileFormat.LOG),
    output_tables=["app_log"],
)
def read_log(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)
