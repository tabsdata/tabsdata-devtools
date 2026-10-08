#
# Copyright 2026 Tabsdata Inc.
#

from __future__ import annotations

import contextlib
import os
import pathlib
import time
from collections.abc import Callable, Iterator

POLL_SECONDS = 0.2


@contextlib.contextmanager
def held(
    path: pathlib.Path, waiting: Callable[[], None] | None = None
) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if not try_lock(fd):
            if waiting is not None:
                waiting()
            while not try_lock(fd):
                time.sleep(POLL_SECONDS)
        try:
            yield
        finally:
            release(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def all_held(
    paths: list[pathlib.Path], waiting: Callable[[pathlib.Path], None] | None = None
) -> Iterator[None]:
    with contextlib.ExitStack() as stack:
        for path in sorted(set(paths)):
            stack.enter_context(
                held(path, None if waiting is None else lambda p=path: waiting(p))
            )
        yield


if os.name == "nt":
    import msvcrt

    def try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
