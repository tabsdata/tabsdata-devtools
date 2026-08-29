#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Db2 source: SEVERAL BINDS, only one of them a watermark.

`initial_values` may seed any number of binds, and they do not all have to move.
`:min_pop` here is a CONSTANT this flow keeps in its own state: it is seeded once
and never written back, so every run falls back to the seed — which means it can
be re-tuned at run time with `ctx.set_attr` WITHOUT re-registering the function.

That is the useful half of the idea: a bind is a knob, not only a cursor.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TrxCtx, publisher
from tabsdatak.conn.db2 import Db2Src


@publisher(
    source=Db2Src(
        queries=[
            "SELECT * FROM city WHERE id > :wm AND population >= :min_pop "
            "ORDER BY id FETCH FIRST 5 ROWS ONLY"
        ],
        initial_values={"wm": 0, "min_pop": 1000000},
    ),
    output_tables=["big_city_page"],
)
def read_several_binds(city: TableFrameSpec, ctx: TrxCtx) -> TableFrameSpec:
    if city is None:
        return None
    top = city.max_for("ID")
    if top is not None and top["ID"] is not None:
        # Only `wm` is advanced; `min_pop` keeps falling back to its seed.
        ctx.set_attr("wm", int(top["ID"]))
    return city
