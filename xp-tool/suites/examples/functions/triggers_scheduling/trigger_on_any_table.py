#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — `trigger_by=AllTablesTrigger()`: fire when ANY input lands.

The blunt instrument, and often the right one. It watches every table the
function reads, so you cannot forget to add one to a list when the function grows
a new input — which is the failure mode `TablesTrigger` has and this does not.

    AllTablesTrigger()              wake on any of my inputs
    TablesTrigger(tables=[...])     wake on these, ignore the rest

Choose `AllTablesTrigger` when every input is equally a reason to recompute, and
`TablesTrigger` when one input is the driver and the others are lookups. On a
function with a single input they are the same thing, and this is the shorter
way to write it.

`TrashDest` is the dev sink: it discards every frame and is backed by no external
system, so a subscriber can be demonstrated — and a whole chain terminated —
without provisioning a destination. Use it in tests and examples; never as a
stand-in for a real destination you meant to configure.

A subscriber must return a frame for each output slot, so `TableFrame.empty()` is
what you hand back when there is nothing to pass on.
"""
from __future__ import annotations

from tabsdatak.api import AllTablesTrigger, TableFrameSpec, subscriber
from tabsdatak.conn.dev import TrashDest
from tabsdatak.tableframe import TableFrame


@subscriber(
    destination=TrashDest(),
    input_tables=["ops/batches_checked"],
    trigger_by=AllTablesTrigger(),
)
def trigger_on_any_table(checked: TableFrameSpec) -> TableFrameSpec:
    return TableFrame.empty() if checked is None else checked
