#
# Copyright 2026 Tabsdata Inc.
#

import os
import subprocess
import sys
import threading
import time

import pytest
from tabsdata_dev.common.core import filelock


@pytest.fixture
def holder(resource_folder):
    """Start another process that holds a lock; return once it has it."""

    def start(path, seconds):
        p = subprocess.Popen(
            [sys.executable, resource_folder / "holder.py", path, str(seconds)],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert p.stdout.readline().strip() == "held"
        return p

    return start


def test_a_lock_waits_for_another_process_and_says_so_once(tmp_path, holder):
    path = tmp_path / "locks" / "salesforce.lock"
    other = holder(path, 0.6)
    told = []
    started = time.monotonic()
    with filelock.held(path, waiting=lambda: told.append(1)):
        waited = time.monotonic() - started
    other.wait(timeout=30)
    assert told == [1]
    assert waited >= 0.3


def test_a_free_lock_is_taken_without_waiting(tmp_path):
    told = []
    with filelock.held(tmp_path / "free.lock", waiting=lambda: told.append(1)):
        pass
    assert told == []


def test_a_released_lock_can_be_taken_again(tmp_path):
    path = tmp_path / "again.lock"
    for _ in range(3):
        with filelock.held(path):
            pass
    assert path.exists()


def test_two_holders_never_overlap(tmp_path):
    path = tmp_path / "shared.lock"
    inside, peak = [0], [0]
    guard = threading.Lock()

    def work():
        for _ in range(5):
            with filelock.held(path):
                with guard:
                    inside[0] += 1
                    peak[0] = max(peak[0], inside[0])
                time.sleep(0.01)
                with guard:
                    inside[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert peak[0] == 1


def test_all_held_takes_every_lock_in_one_order(tmp_path, holder):
    paths = [tmp_path / "b.lock", tmp_path / "a.lock", tmp_path / "b.lock"]
    other = holder(tmp_path / "a.lock", 0.4)
    told = []
    with filelock.all_held(paths, waiting=lambda p: told.append(p.name)):
        assert sorted(os.listdir(tmp_path)) == ["a.lock", "b.lock"]
    other.wait(timeout=30)
    assert told == ["a.lock"]
