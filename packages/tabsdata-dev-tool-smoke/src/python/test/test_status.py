#
# Copyright 2026 Tabsdata Inc.
#

"""What a smoke run reads from `tdkserver status` (`tdd _smoke
instance-state`, `tdd _smoke pods-ready`)."""

import io

import pytest
from tabsdata_dev.tool.smoke import engine, status


@pytest.mark.parametrize(
    "fixture, found",
    [
        ("running.txt", status.RUNNING),
        # later builds draw the header heavy: `┡` rules it off, not `├`
        ("running-heavy-head.txt", status.RUNNING),
        # eks draws its tables even when stopped: empty, a completed job aside
        ("stopped-tables.txt", status.STOPPED),
        # later builds print an empty table as `No rows found.` instead
        ("stopped-no-rows.txt", status.STOPPED),
        ("not-running.txt", status.STOPPED),
        ("missing.txt", status.MISSING),
    ],
)
def test_the_state_is_read_from_the_listing(resource_folder, fixture, found):
    assert status.state((resource_folder / fixture).read_text()) == found


def test_colour_does_not_hide_a_table(resource_folder):
    painted = "\x1b[1mPods\x1b[0m\n" + (resource_folder / "running.txt").read_text()
    assert status.workload_rows(painted) == 4


def test_the_pods_table_ends_at_the_next_title(resource_folder):
    listed = status.pods((resource_folder / "running.txt").read_text())
    assert [p.name for p in listed] == [
        "srv-apiserver-58cc-pfkch",
        "srv-database-7d9f-x2k4q",
    ]


def test_a_heavy_header_is_not_read_as_a_pod(resource_folder):
    text = (resource_folder / "running-heavy-head.txt").read_text()
    assert status.workload_rows(text) == 8
    listed = status.pods(text)
    assert [p.name.rsplit("-", 2)[0] for p in listed] == [
        "srv-aiagent",
        "srv-aitdk",
        "srv-apiserver",
        "srv-embedder",
    ]
    assert status.unready(listed, ["srv-apiserver"]) == ([], [])


def test_a_pod_is_ready_only_running_with_every_container_ready(resource_folder):
    text = (resource_folder / "running.txt").read_text()
    listed = status.pods(text)
    assert status.unready(listed, ["srv-apiserver", "srv-database"]) == ([], [])
    assert status.unready(listed, ["srv-x"]) == (["srv-x"], [])

    half = status.pods(text.replace("x2k4q  │ Running │ 1/1", "x2k4q  │ Running │ 0/1"))
    missing, bad = status.unready(half, ["srv-apiserver", "srv-database"])
    assert missing == ["srv-database"]
    assert [str(p) for p in bad] == ["srv-database-7d9f-x2k4q (Running 0/1)"]


def _answer(monkeypatch, capsys, argv, text):
    monkeypatch.setattr("sys.argv", ["_smoke", *argv])
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    capsys.readouterr()
    code = engine.main()
    return code, capsys.readouterr().out.strip()


def test_the_helpers_answer_and_the_script_judges(resource_folder, monkeypatch, capsys):
    """A pods check is retried until the pods come up, so a no is an answer,
    exit 0 -- an error would leave a failure log behind on every attempt."""
    running = (resource_folder / "running.txt").read_text()
    stopped = (resource_folder / "not-running.txt").read_text()
    state = ["instance-state", "--instance", "sm_x"]
    assert _answer(monkeypatch, capsys, state, running) == (0, "running")
    assert _answer(monkeypatch, capsys, state, stopped) == (0, "stopped")

    ready = ["pods-ready", "--instance", "sm_x", "srv-apiserver", "srv-database"]
    assert _answer(monkeypatch, capsys, ready, running) == (0, engine.READY)
    assert _answer(monkeypatch, capsys, ready, stopped) == (0, engine.NOT_READY)
