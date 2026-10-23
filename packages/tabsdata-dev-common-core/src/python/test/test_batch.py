#
# Copyright 2026 Tabsdata Inc.
#

"""batch.execute: the spawn path system/domain rely on, unchanged, and the
streamed path mexe runs on -- lines as they come, order kept, a failure that
stops what is running, pipelines included."""

import io
import json
import os
import subprocess
import sys
import time

import pytest
from tabsdata_dev.common.core import batch, render

posix = pytest.mark.skipif(os.name == "nt", reason="drives sh")


def _renderer():
    out, err = io.StringIO(), io.StringIO()
    return render.Renderer("t", fmt="json", out=out, err=err), out


def _events(out):
    return [json.loads(line) for line in out.getvalue().splitlines()]


def _fake_spawn(results):
    def spawn(argv):
        rc, text = results[argv[0]]
        return subprocess.CompletedProcess(argv, rc, stdout=text, stderr="")

    return spawn


class Recorder(batch.Reporter):
    def __init__(self, out):
        super().__init__(out, "t", "x")
        self.seen = []

    def start(self, task):
        self.seen.append(("start", task.name))

    def line(self, task, line):
        self.seen.append(("line", task.name, line))

    def end(self, task, done, total):
        self.seen.append(("end", task.name, task.status))


def test_spawn_runs_heaviest_first_and_summarizes():
    out, stream = _renderer()
    tasks = [batch.Task("light", 1, [["a"]]), batch.Task("heavy", 9, [["b"]])]
    rc = batch.execute("run", tasks, _fake_spawn({"a": (0, "A\n"), "b": (0, "B")}), out)
    assert rc == 0
    assert [t.name for t in tasks] == ["heavy", "light"]
    events = _events(stream)
    assert events[0]["message"] == "run: 2 target(s), parallel x10, heaviest first"
    assert events[-1]["event"] == "ok" and events[-1]["ok"] == 2
    assert tasks[1].output == "A"  # stripped, as it always was


def test_spawn_fail_fast_skips_what_has_not_started():
    out, stream = _renderer()
    tasks = [batch.Task(n, 0, [[n]]) for n in ("a", "b", "c")]
    rc = batch.execute(
        "run",
        tasks,
        _fake_spawn({"a": (3, "boom"), "b": (0, ""), "c": (0, "")}),
        out,
        fail_fast=True,
        workers=1,
        heaviest_first=False,
    )
    assert rc == 1
    assert [t.status for t in tasks] == ["fail", "skipped", "skipped"]
    assert _events(stream)[-1]["event"] == "error"


def test_brief_says_one_line_per_task_and_keeps_a_failures_output():
    stream = io.StringIO()
    out = render.Renderer("t", fmt="json", verbose=True, out=stream, err=io.StringIO())
    tasks = [batch.Task("good", 0, [["a"]]), batch.Task("bad", 0, [["b"]])]
    rc = batch.execute(
        "run",
        tasks,
        _fake_spawn({"a": (0, "made it\n"), "b": (3, "why it broke")}),
        out,
        workers=1,
        heaviest_first=False,
        brief=True,
    )
    assert rc == 1
    shown = [e for e in _events(stream) if e["event"] in ("info", "warn")]
    assert [e["message"].splitlines()[0] for e in shown] == [
        "run: 2 target(s), parallel x1",
        "[1/2] good OK (0.0s)",
        "[2/2] bad FAIL (0.0s)",
    ]
    assert shown[1]["message"] == "[1/2] good OK (0.0s)"
    assert shown[1]["output"] == "made it"
    assert "why it broke" in shown[2]["message"]
    # --verbose brings a success's output back, as a debug event.
    debug = [e["message"] for e in _events(stream) if e["event"] == "debug"]
    assert any("made it" in m for m in debug)


@posix
def test_streamed_lines_arrive_in_order_in_each_cwd(tmp_path):
    for name in ("b", "a"):
        (tmp_path / name).mkdir()
    out, _ = _renderer()
    say = Recorder(out)
    tasks = [
        batch.Task(
            n, 0, [["sh", "-c", "basename $PWD; echo two >&2"]], cwd=tmp_path / n
        )
        for n in ("b", "a")
    ]
    rc = batch.execute(
        "run", tasks, None, out, workers=1, heaviest_first=False, reporter=say
    )
    assert rc == 0
    assert say.seen == [
        ("start", "b"),
        ("line", "b", "b"),
        ("line", "b", "two"),
        ("end", "b", "ok"),
        ("start", "a"),
        ("line", "a", "a"),
        ("line", "a", "two"),
        ("end", "a", "ok"),
    ]
    assert tasks[0].output == "b\ntwo"


@posix
def test_kill_on_fail_stops_a_running_pipeline():
    # `sleep | cat` outlives a killed shell and holds the pipe open unless the
    # whole tree goes.
    out, _ = _renderer()
    tasks = [
        batch.Task("slow", 0, [["sh", "-c", "sleep 30 | cat"]]),
        batch.Task("bad", 0, [["sh", "-c", "sleep 0.3; exit 4"]]),
        batch.Task("later", 0, [["sh", "-c", "echo never"]]),
    ]
    started = time.monotonic()
    rc = batch.execute(
        "run",
        tasks,
        None,
        out,
        workers=2,
        heaviest_first=False,
        kill_on_fail=True,
        final=False,
    )
    assert rc == 1
    assert time.monotonic() - started < 10
    assert {t.name: t.status for t in tasks} == {
        "slow": "aborted",
        "bad": "fail",
        "later": "skipped",
    }
    assert tasks[1].returncode == 4


def test_the_streamed_env_reaches_the_child(tmp_path):
    out, _ = _renderer()
    task = batch.Task(
        "env",
        0,
        [[sys.executable, "-c", "import os; print(os.environ['BATCH_PROBE'])"]],
        cwd=tmp_path,
    )
    env = {**os.environ, "BATCH_PROBE": "here"}
    assert batch.execute("run", [task], None, out, env=env, final=False) == 0
    assert task.output == "here"
