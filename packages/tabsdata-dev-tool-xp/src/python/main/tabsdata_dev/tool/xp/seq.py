#
# Copyright 2026 Tabsdata Inc.
#

from __future__ import annotations

import contextlib
import os
import pathlib
from collections.abc import Iterator

from tabsdata_dev.common.core import filelock

from . import pointers, project, state
from .models import Instance
from .reporter import fs_token, rep


def groups(instances: dict[str, Instance]) -> dict[str, frozenset[str]]:
    exclusive = (
        project.exclusive_systems()
        if not state.run.dry_run and any(inst.domains for inst in instances.values())
        else set()
    )
    return {
        lane: frozenset(inst.seq)
        | {d.system for d in inst.domains if d.system in exclusive}
        for lane, inst in instances.items()
    }


def lock_file(group: str) -> pathlib.Path:
    return pointers.store() / "seq" / f"{fs_token(group)}.lock"


@contextlib.contextmanager
def held(inst: Instance) -> Iterator[None]:
    given = os.environ.pop(state.SEQ_ENV, None)
    names = (
        sorted(n for n in given.split(",") if n)
        if given is not None
        else sorted(groups({inst.name: inst})[inst.name])
    )
    if not names or state.run.dry_run:
        yield
        return
    with filelock.all_held(
        [lock_file(name) for name in names],
        waiting=lambda path: rep().note(
            f"seq '{path.stem}' is held by another run -- waiting for it"
        ),
    ):
        rep().note(f"seq {', '.join(names)}: held for this run")
        yield
