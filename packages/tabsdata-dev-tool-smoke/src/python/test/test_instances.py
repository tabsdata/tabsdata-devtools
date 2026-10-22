#
# Copyright 2026 Tabsdata Inc.
#

"""A local instance's processes, found by the folder on their command line
(`tdd _smoke instance-pids|instance-stop|instance-gone`)."""

import os
import shutil
import subprocess
import sys

import pytest
from tabsdata_dev.tool.smoke import instances

#: Names no real run takes, so a developer's open instance never answers.
NAME = "sm_fixture_notarealrun"
OTHER = "sm_fixture_otherrun"


@pytest.fixture
def km(resource_folder):
    """Start stand-ins for km processes; every one is ended afterwards."""
    started = []

    def start(folder: str, *flags: str) -> subprocess.Popen:
        child = subprocess.Popen(
            [sys.executable, str(resource_folder / "sleeper.py"), folder, *flags],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert child.stdout.readline().strip() == "ready"
        started.append(child)
        return child

    yield start
    for child in started:
        child.kill()
        child.wait()


def test_a_process_is_found_by_its_instance_folder_in_either_separator(km):
    unix = km(f"/home/u/.tabsdata/instances/{NAME}/kube")
    windows = km(f"C:\\Users\\u\\.tabsdata\\instances\\{NAME}\\kube")
    km(f"/home/u/.tabsdata/instances/{OTHER}/kube")
    assert instances.pids(NAME) == sorted([unix.pid, windows.pid])


def test_the_caller_and_its_parents_are_never_the_instance(resource_folder, tmp_path):
    """A shell that runs the helper may carry the folder in its own command
    line (`bash -c '... instances/NAME/ ...'`): it is not the instance, and
    ending it would end the run."""
    answer = tmp_path / "answer"
    ask = resource_folder / "ask_pids.py"
    # a second command, so the shell stays alive above python instead of
    # exec-ing it
    shell = f'"$1" "$2" "$3" "$4"; : instances/{NAME}/'
    argv = ["sh", "-c", shell, "sh", sys.executable, str(ask), NAME, str(answer)]
    subprocess.run(argv, check=True)
    assert answer.read_text().strip() == "[]"


def test_a_name_that_only_begins_another_is_not_it(km):
    km(f"/home/u/.tabsdata/instances/{NAME}x/kube")
    assert instances.pids(NAME) == []


def test_stop_waits_the_processes_out_and_kills_what_ignores_a_term(
    km, tmp_path, monkeypatch
):
    monkeypatch.setattr(instances, "previous_tdkserver", lambda _: None)
    polite = km(f"/x/instances/{NAME}/a")
    stubborn = km(f"/x/instances/{NAME}/b", "--ignore-term")
    said = []
    assert instances.stop(NAME, tmp_path, [], said.append, wait=1, poll=0.2)
    polite.wait(timeout=5)
    stubborn.wait(timeout=5)
    assert any("killing" in line for line in said), said
    assert said[-1].startswith(f"instance {NAME} gone after")


def test_stop_says_so_when_nothing_runs(tmp_path):
    said = []
    assert instances.stop(NAME, tmp_path, [], said.append, wait=0, poll=0)
    assert said == [f"no km processes of instance {NAME} running"]


@pytest.mark.skipif(os.name == "nt", reason="the stand-in tdkserver is a sh script")
def test_the_previous_run_s_tdkserver_stops_it_first(
    km, tmp_path, resource_folder, monkeypatch
):
    """A tdkserver in a managed venv under the tdd dir is asked to stop the
    instance before anything is ended by hand."""
    venv_bin = tmp_path / "managed-venvs" / "uv" / NAME / "bin"
    venv_bin.mkdir(parents=True)
    fake = venv_bin / "tdkserver"
    shutil.copy(resource_folder / "tdkserver", fake)
    fake.chmod(0o755)
    record = tmp_path / "record"
    monkeypatch.setenv("RECORD", str(record))
    monkeypatch.setattr(instances.shutil, "which", lambda _: None)
    assert instances.previous_tdkserver(tmp_path) == fake

    km(f"/x/instances/{NAME}/a")
    assert instances.stop(NAME, tmp_path, ["-y"], [].append, wait=2, poll=0.2)
    assert record.read_text().split() == ["stop", "--instance", NAME, "-y"]


def test_gone_wants_no_process_and_no_folder(km, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    folder = instances.instance_folder(NAME)
    assert instances.gone(NAME, [].append)

    folder.mkdir(parents=True)
    said = []
    assert not instances.gone(NAME, said.append)
    assert said == [f"instance folder still exists: {folder}"]

    folder.rmdir()
    km(f"/x/instances/{NAME}/a")
    assert not instances.gone(NAME, [].append)
