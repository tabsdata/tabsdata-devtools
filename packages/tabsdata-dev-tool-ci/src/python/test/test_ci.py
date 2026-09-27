#
# Copyright 2026 Tabsdata Inc.
#

"""`tdd ci download` against a fake `gh` on PATH: a Python script that answers
the three calls the tool makes from a JSON file and logs every call."""

import json
import sys

import pytest

from tabsdata_dev.tool import ci

FAKE_GH = """#!{python}
import json, os, pathlib, sys
state = json.loads(pathlib.Path(os.environ["FAKE_GH_STATE"]).read_text())
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:2] == ["run", "list"]:
    runs = state["runs"]
    if "-w" in args:
        wf = args[args.index("-w") + 1]
        runs = [r for r in runs if r["workflowName"] == wf]
    print(json.dumps(runs))
elif args[0] == "api":
    for a in state["artifacts"]:
        print(json.dumps(a))
elif args[:2] == ["run", "download"]:
    name = args[args.index("-n") + 1]
    if name in state.get("broken", []):
        sys.exit("error downloading " + name)
    d = pathlib.Path(args[args.index("-D") + 1])
    d.mkdir(parents=True)
    if name.startswith("packed"):
        import io, tarfile
        with tarfile.open(d / (name + ".tar.gz"), "w:gz") as tf:
            data = name.encode()
            info = tarfile.TarInfo("inner/content.txt"); info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    else:
        (d / "content.txt").write_text(name)
else:
    sys.exit("unexpected: " + " ".join(args))
"""


@pytest.fixture
def gh(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "gh"
    exe.write_text(FAKE_GH.format(python=sys.executable))
    exe.chmod(0o755)
    state = tmp_path / "state.json"
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_GH_STATE", str(state))
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    monkeypatch.chdir(tmp_path)

    def setup(runs, artifacts, broken=()):
        state.write_text(
            json.dumps({"runs": runs, "artifacts": artifacts, "broken": list(broken)})
        )

    def calls():
        return [json.loads(x) for x in log.read_text().splitlines()]

    setup.calls = calls
    return setup


def _run(argv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ci", *argv])
    code = ci.main()
    return code, [json.loads(x) for x in capsys.readouterr().out.splitlines()]


RUNS = [
    {"number": 7, "databaseId": 111, "workflowName": "build"},
    {"number": 8, "databaseId": 222, "workflowName": "build"},
    {"number": 8, "databaseId": 333, "workflowName": "nightly"},
]


def _art(name, expired=False, size=2048):
    return {"name": name, "size_in_bytes": size, "expired": expired}


def test_downloads_every_live_artifact_into_its_own_folder(
    gh, tmp_path, monkeypatch, capsys
):
    gh(RUNS, [_art("wheels"), _art("logs"), _art("old", expired=True)])
    code, events = _run(
        ["download", "--action", "7", "--format", "json"], monkeypatch, capsys
    )
    assert code == 0
    ok = events[-1]
    assert ok["event"] == "ok" and ok["run_id"] == 111
    assert sorted(ok["artifacts"]) == ["logs", "wheels"] and ok["expired"] == ["old"]
    for name in ("wheels", "logs"):
        assert (tmp_path / name / "content.txt").read_text() == name
    assert not (tmp_path / "old").exists()
    calls = gh.calls()
    assert calls[0][:4] == ["run", "list", "-R", ci.DEFAULT_REPO]
    assert calls[1][:2] == [
        "api",
        f"repos/{ci.DEFAULT_REPO}/actions/runs/111/artifacts",
    ]
    assert "--paginate" in calls[1]
    downloads = [c for c in calls if c[:2] == ["run", "download"]]
    assert {c[c.index("-n") + 1] for c in downloads} == {"wheels", "logs"}
    assert all(c[2] == "111" for c in downloads)


def test_an_ambiguous_number_needs_the_workflow(gh, tmp_path, monkeypatch, capsys):
    gh(RUNS, [_art("a")])
    code, events = _run(
        ["download", "--action", "8", "--format", "json"], monkeypatch, capsys
    )
    assert code == 1
    assert (
        "ambiguous" in events[-1]["message"] and "--workflow" in events[-1]["message"]
    )
    code, events = _run(
        [
            "download",
            "--action",
            "8",
            "--workflow",
            "nightly",
            "--repo",
            "o/r",
            "--dir",
            "out",
            "--format",
            "json",
        ],
        monkeypatch,
        capsys,
    )
    assert code == 0 and events[-1]["run_id"] == 333
    assert (tmp_path / "out" / "a" / "content.txt").exists()
    assert gh.calls()[-1][4] == "o/r"


def test_a_missing_run_is_an_error(gh, monkeypatch, capsys):
    gh(RUNS, [])
    code, events = _run(
        ["download", "--action", "99", "--format", "json"], monkeypatch, capsys
    )
    assert code == 1 and "run #99 not found" in events[-1]["message"]


def test_one_failure_does_not_stop_the_others(gh, tmp_path, monkeypatch, capsys):
    gh(RUNS, [_art(f"a{i}") for i in range(5)], broken=["a2"])
    code, events = _run(
        ["download", "--action", "7", "--parallel", "2", "--format", "json"],
        monkeypatch,
        capsys,
    )
    assert code == 1
    err = events[-1]
    assert err["failed"] == ["a2"] and sorted(err["downloaded"]) == [
        "a0",
        "a1",
        "a3",
        "a4",
    ]
    assert "1 of 5 artifact(s) failed: a2" in err["message"]
    assert (tmp_path / "a4" / "content.txt").exists()


def test_bad_options_are_refused_before_gh_runs(gh, monkeypatch, capsys):
    gh(RUNS, [])
    for argv in (["--parallel", "0"], ["--repo", "norepo"]):
        code, _ = _run(
            ["download", "--action", "7", *argv, "--format", "json"],
            monkeypatch,
            capsys,
        )
        assert code == 1
    code, _ = _run(["--format", "json"], monkeypatch, capsys)
    assert code == 1
    with pytest.raises(FileNotFoundError):
        gh.calls()  # nothing ran


def test_sizes_read_well():
    assert ci._size(10) == "10 B"
    assert ci._size(2048) == "2.0 KiB"
    assert ci._size(5 * 1024**3) == "5.0 GiB"


def test_unzip_unpacks_what_each_artifact_holds(gh, tmp_path, monkeypatch, capsys):
    gh(RUNS, [_art("packed-logs"), _art("plain")])
    code, events = _run(
        ["download", "--action", "7", "--dir", "out", "--unzip", "--format", "json"],
        monkeypatch,
        capsys,
    )
    assert code == 0
    folder = tmp_path / "out" / "packed-logs"
    assert (folder / "inner" / "content.txt").read_text() == "packed-logs"
    assert not (folder / "packed-logs.tar.gz").exists()
    assert (tmp_path / "out" / "plain" / "content.txt").exists()
    assert any(e.get("unpacked") == ["packed-logs.tar.gz"] for e in events)


def test_without_unzip_archives_stay_packed(gh, tmp_path, monkeypatch, capsys):
    gh(RUNS, [_art("packed-logs")])
    code, _ = _run(
        ["download", "--action", "7", "--format", "json"], monkeypatch, capsys
    )
    assert code == 0
    assert (tmp_path / "packed-logs" / "packed-logs.tar.gz").exists()


def test_unpack_all_handles_zip_and_gz_and_refuses_escapes(tmp_path):
    import gzip
    import zipfile

    with zipfile.ZipFile(tmp_path / "r.zip", "w") as zf:
        zf.writestr("report/a.txt", "a")
    with gzip.open(tmp_path / "log.txt.gz", "wb") as f:
        f.write(b"log")
    (tmp_path / "keep.txt").write_text("k")
    assert ci.unpack_all(tmp_path) == ["log.txt.gz", "r.zip"]
    assert (tmp_path / "report" / "a.txt").read_text() == "a"
    assert (tmp_path / "log.txt").read_text() == "log"
    assert (tmp_path / "keep.txt").exists()

    bad = tmp_path / "bad"
    bad.mkdir()
    with zipfile.ZipFile(bad / "evil.zip", "w") as zf:
        zf.writestr("../escaped.txt", "x")
    with pytest.raises(zipfile.BadZipFile, match="escapes"):
        ci.unpack_all(bad)
    assert not (tmp_path / "escaped.txt").exists()
