#
# Copyright 2026 Tabsdata Inc.
#

"""_merge_plan — the CDC batches a merge destination is driven through, and the
table each one must leave behind.

Standard library only: ``caps_merge_batches.py`` builds its frames from it,
``caps_<system>.py`` its subscribers' targets, and ``scripts/verify_merge.py``
holds the warehouse to it, so none of them can drift.

Every batch is one publisher (``caps_merge_<batch>`` -> ``caps_input/
cap_merge_<batch>``) and, per warehouse, one ``if_table_exists="merge"``
subscriber (``<system>_merge_<batch>``) onto the batch's target, keyed on
``cap_id`` with the marker in ``op``. The suite triggers the batches in the
order listed and checks the batch's target after each. A row is ``(op, cap_id,
name, qty)``; a load (``l``) or truncate (``t``) row carries no data -- every
other column null, the key too -- as a CDC source emits it.

The batches keep to what a CDC source emits: a load is the first row of its
batch -- an initial load writes its ``l`` header ahead of the table's rows --
while a truncate comes off the log and lands wherever it happened.
``_check_resets`` refuses a plan that puts a load anywhere else.

What each batch proves, beyond the plain insert / update / delete. On
``cap_merge``:

- ``b1`` creates the target: a merge brings a missing table into being.
- ``b2`` is an initial load onto a table holding stale rows: the target
  becomes exactly what follows the ``l`` -- keys it shares with the load take
  the load's values, the others are gone.
- ``b3`` coalesces several records per key: ``i -> u`` is an insert with the
  last payload, ``u -> u`` the last update, ``u -> d -> i`` of a live key an
  update with the insert's values, ``i -> d`` of a new key nothing at all.
- ``b4`` truncates a populated table, with changes ahead of the ``t`` voided.
- ``b5`` merges onto the truncated table, and passes over a record whose
  marker is no operation (``x``).
- ``b6`` resets twice -- a load, then a truncate mid-batch with changes after
  it -- and only the last counts: what the load brought is gone, the changes
  after the truncate apply to an empty table. The markers are upper case
  here, which a merge reads as lower.
- ``b7`` merges onto what ``b6`` left.
- ``b8`` is an initial load of an empty source table, a bare ``l``: it empties
  a populated target.

On targets of their own, since each needs a table nothing has created yet:

- ``load1`` is an initial load as the first write: the load creates
  ``cap_merge_from_load``, then ``load2`` merges changes onto it.
- ``trunc1`` is a bare ``t`` as the first write: the merge creates
  ``cap_merge_from_truncate`` empty, its columns typed from a batch whose
  every data value is null, then ``trunc2`` merges inserts onto it.

Each batch leaves its target different from the one before it -- or, for a
batch that creates its target empty, leaves a table where there was none: a
non-detached ``tdk fn trigger`` exits 0 even when a run failed, so a merge that
did not happen is caught by the check finding the previous state, or no table.
"""

from __future__ import annotations

from typing import NamedTuple

KEY = "cap_id"
MARKER = "op"
#: The data columns, as the frames name them; the marker comes last in a frame.
COLUMNS = ("cap_id", "name", "qty")

Row = tuple[str, int | None, str | None, int | None]
State = dict[int, tuple[str, int]]


class Batch(NamedTuple):
    name: str
    target: str
    what: str
    #: In arrival order.
    rows: list[Row]
    #: The target after the batch.
    expected: State


def _reset(op: str) -> Row:
    return (op, None, None, None)


BATCHES: list[Batch] = [
    Batch(
        "b1",
        "cap_merge",
        "changes onto no table",
        [
            ("i", 1, "alpha", 10),
            ("i", 2, "bravo", 20),
            ("i", 3, "charlie", 30),
        ],
        {1: ("alpha", 10), 2: ("bravo", 20), 3: ("charlie", 30)},
    ),
    Batch(
        "b2",
        "cap_merge",
        "initial load over stale rows",
        [
            _reset("l"),
            ("i", 1, "alpha-load", 11),
            ("i", 4, "delta", 40),
            ("i", 5, "echo", 50),
        ],
        {1: ("alpha-load", 11), 4: ("delta", 40), 5: ("echo", 50)},
    ),
    Batch(
        "b3",
        "cap_merge",
        "several changes per key",
        [
            ("u", 4, "delta-2", 41),
            ("d", 4, None, None),
            ("i", 4, "delta-3", 42),
            ("d", 5, None, None),
            ("i", 6, "foxtrot", 60),
            ("i", 7, "golf", 70),
            ("u", 7, "golf-2", 71),
            ("i", 8, "hotel", 80),
            ("d", 8, None, None),
            ("u", 1, "alpha-2", 12),
            ("u", 1, "alpha-3", 13),
        ],
        {
            1: ("alpha-3", 13),
            4: ("delta-3", 42),
            6: ("foxtrot", 60),
            7: ("golf-2", 71),
        },
    ),
    Batch(
        "b4",
        "cap_merge",
        "truncate",
        [
            ("u", 1, "alpha-void", 14),
            ("d", 6, "foxtrot", 60),
            ("i", 9, "india-void", 90),
            _reset("t"),
        ],
        {},
    ),
    Batch(
        "b5",
        "cap_merge",
        "changes onto the truncated table",
        [
            ("i", 10, "juliet", 100),
            ("i", 11, "kilo", 110),
            ("x", 12, "lima-void", 120),
            ("u", 10, "juliet-2", 101),
        ],
        {10: ("juliet-2", 101), 11: ("kilo", 110)},
    ),
    Batch(
        "b6",
        "cap_merge",
        "a load, then a truncate: the last reset wins",
        [
            _reset("L"),
            ("I", 11, "kilo-void", 111),
            ("I", 12, "lima-void", 120),
            ("U", 12, "lima-void-2", 121),
            _reset("T"),
            ("I", 13, "mike", 130),
            ("U", 13, "mike-2", 131),
            ("I", 14, "november", 140),
            ("D", 14, None, None),
        ],
        {13: ("mike-2", 131)},
    ),
    Batch(
        "b7",
        "cap_merge",
        "changes onto what the truncate left",
        [
            ("d", 13, "mike-2", 131),
            ("i", 15, "oscar", 150),
            ("i", 16, "papa", 160),
            ("u", 15, "oscar-2", 151),
        ],
        {15: ("oscar-2", 151), 16: ("papa", 160)},
    ),
    Batch(
        "b8",
        "cap_merge",
        "initial load of an empty table",
        [_reset("l")],
        {},
    ),
    Batch(
        "load1",
        "cap_merge_from_load",
        "initial load as the first write",
        [
            _reset("l"),
            ("i", 1, "quebec", 10),
            ("i", 2, "romeo", 20),
            ("i", 3, "sierra", 30),
        ],
        {1: ("quebec", 10), 2: ("romeo", 20), 3: ("sierra", 30)},
    ),
    Batch(
        "load2",
        "cap_merge_from_load",
        "changes onto the table a load created",
        [
            ("u", 1, "quebec-2", 11),
            ("d", 2, None, None),
            ("i", 4, "tango", 40),
        ],
        {1: ("quebec-2", 11), 3: ("sierra", 30), 4: ("tango", 40)},
    ),
    Batch(
        "trunc1",
        "cap_merge_from_truncate",
        "truncate as the first write",
        [_reset("t")],
        {},
    ),
    Batch(
        "trunc2",
        "cap_merge_from_truncate",
        "changes onto the table a truncate created",
        [
            ("i", 1, "uniform", 10),
            ("i", 2, "victor", 20),
        ],
        {1: ("uniform", 10), 2: ("victor", 20)},
    ),
]

NAMES = [b.name for b in BATCHES]
#: Every target, in the order the batches first write it.
TARGETS = list(dict.fromkeys(b.target for b in BATCHES))


def batch(name: str) -> Batch:
    for entry in BATCHES:
        if entry.name == name:
            return entry
    raise KeyError(f"no merge batch {name!r}; the plan has {', '.join(NAMES)}")


def _check_resets() -> None:
    """A load only as its batch's first row, the one place a source puts it."""
    for b in BATCHES:
        late = [i for i, row in enumerate(b.rows) if row[0].lower() == "l" and i > 0]
        if late:
            raise ValueError(f"batch {b.name}: a load is row {late[0]}; it can only be the first")


_check_resets()
