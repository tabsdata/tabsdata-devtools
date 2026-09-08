#
# Copyright 2026 Tabsdata Inc.
#

"""The `[n/N]` a run puts in front of every unit of its repetitive work.

`submit`, `apply` and `approve` do the same thing to one PR after another and
used to say nothing about how far along they were. A Counter numbers those
units: one event per unit AS IT FINISHES -- `info` when it went as it should,
`warn` when it did not -- with the counter in the message and `n`/`total` in
the fields, so `--format json` carries the same progress without the brackets.
This is `tdd xp`'s Reporter thinking, minus everything gsx has no use for: no
scratch dir, no timings, no report; a counter was all that was needed.

Two rules the counter keeps, so it can never lie:

- the total is the one that is known before the first unit runs (`apply` and
  `approve` know theirs; `submit` cannot know how many PRs it will have until
  it has pushed them, so it counts `[n]` and offers no denominator);
- every unit spends a number, including the ones that turn out to need no work
  and the ones that fail -- gsx attempts every PR and reports the failures
  together, so the count has to keep going or the last line would never reach
  the total.
"""

from __future__ import annotations

from typing import Any


class Counter:
    """The units of one run, numbered as each finishes.

    `total` is how many units there will be, or None when that cannot be known
    before the first one runs.
    """

    def __init__(self, out, total: int | None = None) -> None:
        self.out = out
        self.total = total
        self.done = 0

    def step(self, message: str, **fields: Any) -> None:
        """One unit that finished."""
        self._emit("info", message, fields)

    def failed(self, message: str, **fields: Any) -> None:
        """One unit that failed. The caller still collects it for the summary
        the run ends with; this is the line that says so while it goes on."""
        self._emit("warn", message, fields)

    def _emit(self, kind: str, message: str, fields: dict) -> None:
        self.done += 1
        if self.total is None:
            counts: dict[str, Any] = {"n": self.done}
            prefix = f"[{self.done}]"
        else:
            # A plan that turned out short must not print the impossible [6/5].
            self.total = max(self.total, self.done)
            counts = {"n": self.done, "total": self.total}
            # Right aligned, so [ 9/10] and [10/10] keep one column.
            prefix = f"[{self.done:>{len(str(self.total))}}/{self.total}]"
        getattr(self.out, kind)(f"{prefix} {message}", **{**counts, **fields})
