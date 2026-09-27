#
# Copyright 2026 Tabsdata Inc.
#

"""`tdd ci download` against a fake `gh` on PATH: a Python script that answers
the three calls the tool makes from a JSON file and logs every call."""

import io
import json
import sys
import zlib

import pytest

from tabsdata_dev.tool import ci

FAKE_GH = """#!{python}
import json, os, pathlib, sys
state = json.loads(pathlib.Path(os.environ["FAKE_GH_STATE"]).read_text())
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[0] == "api" and "/actions/runs?" in args[1]:
    # repos/O/R/actions/runs?per_page=P&page=N, newest first, as the jq wants
    query = dict(kv.split("=") for kv in args[1].split("?")[1].split("&"))
    size, page = int(query["per_page"]), int(query["page"])
    for r in state["runs"][(page - 1) * size : page * size]:
        print(json.dumps({{"id": r["databaseId"], "run_number": r["number"],
                          "name": r["workflowName"],
                          "path": ".github/workflows/" + r["workflowName"] + ".yml"}}))
elif args[0] == "api" and args[1].endswith("/zip"):
    # repos/O/R/actions/artifacts/<id>/zip: the artifact, zipped, on stdout
    import io, tarfile, zipfile
    art_id = int(args[1].split("/")[-2])
    name = next(a["name"] for a in state["artifacts"] if a["id"] == art_id)
    if name in state.get("broken", []):
        sys.exit("error downloading " + name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if name.startswith("packed"):
            # every packed artifact ships the same archive name, as each
            # assembly of a release run ships tabsdata-assembly-devpi.tar.gz;
            # the tar has no top-level dir
            tar = io.BytesIO()
            with tarfile.open(fileobj=tar, mode="w:gz") as tf:
                for member in (name + ".whl", "logs/" + name + ".log"):
                    data = name.encode()
                    info = tarfile.TarInfo(member); info.size = len(data)
                    tf.addfile(info, io.BytesIO(data))
            zf.writestr("bundle.tar.gz", tar.getvalue())
        elif name.startswith("clash"):
            zf.writestr("shared.txt", name)
        else:
            zf.writestr(name + ".txt", name)
    sys.stdout.buffer.write(buf.getvalue())
elif args[0] == "api":
    for a in state["artifacts"]:
        print(json.dumps(a))
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
    return {
        "id": zlib.crc32(name.encode()),
        "name": name,
        "size_in_bytes": size,
        "expired": expired,
    }


def test_extracts_every_live_artifact_straight_into_the_dir(
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
        assert (tmp_path / f"{name}.txt").read_text() == name
        assert not (tmp_path / name).exists()  # no folder per artifact
    assert not (tmp_path / "old.txt").exists()
    calls = gh.calls()
    assert calls[0][:2] == [
        "api",
        f"repos/{ci.DEFAULT_REPO}/actions/runs?per_page=100&page=1",
    ]
    assert calls[1][:2] == [
        "api",
        f"repos/{ci.DEFAULT_REPO}/actions/runs/111/artifacts",
    ]
    assert "--paginate" in calls[1]
    downloads = [c[1] for c in calls if c[0] == "api" and c[1].endswith("/zip")]
    assert sorted(downloads) == sorted(
        f"repos/{ci.DEFAULT_REPO}/actions/artifacts/{_art(n)['id']}/zip"
        for n in ("wheels", "logs")
    )
    done = [e for e in events if e["message"].startswith("wheels: downloaded")]
    assert done and done[0]["bytes"] > 0
    assert not list(tmp_path.glob(".*"))  # no zip, no staging dir left behind


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
    assert (tmp_path / "out" / "a.txt").exists()
    assert any("repos/o/r/" in " ".join(c) for c in gh.calls())


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
    assert (tmp_path / "a4.txt").exists()
    assert not (tmp_path / "a2.txt").exists()


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


def test_expand_expands_twice_into_the_dir(gh, tmp_path, monkeypatch, capsys):
    """The artifact is a zip holding a tar.gz: the zip is extracted, the tar
    expanded, and the dir is left with the tar's contents. Both artifacts ship
    an archive of the same name; each is expanded apart, so neither clobbers
    the other before it is opened."""
    gh(RUNS, [_art("packed-mac"), _art("packed-linux"), _art("plain")])
    code, events = _run(
        ["download", "--action", "7", "--dir", "out", "--expand", "--format", "json"],
        monkeypatch,
        capsys,
    )
    assert code == 0
    out = tmp_path / "out"
    for name in ("packed-mac", "packed-linux"):
        assert (out / f"{name}.whl").read_text() == name
        assert (out / "logs" / f"{name}.log").read_text() == name
    assert (out / "plain.txt").exists()
    assert not (out / "bundle.tar.gz").exists()
    assert sorted(p.name for p in out.iterdir()) == [
        "logs",
        "packed-linux.whl",
        "packed-mac.whl",
        "plain.txt",
    ]
    assert any(e.get("expanded") == "bundle.tar.gz" for e in events)
    # a phase in progress is a progress line, not an event of its own
    assert not any("expanding" in e["message"] for e in events)
    assert not any(": downloading" in e["message"] for e in events)


def test_without_expand_the_archive_is_left_as_the_zip_held_it(
    gh, tmp_path, monkeypatch, capsys
):
    gh(RUNS, [_art("packed-logs")])
    code, _ = _run(
        ["download", "--action", "7", "--format", "json"], monkeypatch, capsys
    )
    assert code == 0
    assert (tmp_path / "bundle.tar.gz").exists()


def test_two_artifacts_with_the_same_file_do_not_overwrite(
    gh, tmp_path, monkeypatch, capsys
):
    """Two artifacts holding the same file (as the assemblies of a release run
    each hold the same tar.gz, left unexpanded): the second is refused, naming
    the first, rather than silently winning."""
    gh(RUNS, [_art("clash-a"), _art("clash-b")])
    code, events = _run(
        ["download", "--action", "7", "--parallel", "1", "--format", "json"],
        monkeypatch,
        capsys,
    )
    assert code == 1
    err = events[-1]
    assert err["downloaded"] == ["clash-a"] and err["failed"] == ["clash-b"]
    warn = [e for e in events if e["event"] == "warn"][0]["message"]
    assert "shared.txt already came from artifact clash-a" in warn
    assert (tmp_path / "shared.txt").read_text() == "clash-a"
    assert not list(tmp_path.glob(".*"))


def test_expand_all_handles_zip_and_gz_and_refuses_escapes(tmp_path):
    import gzip
    import zipfile

    with zipfile.ZipFile(tmp_path / "r.zip", "w") as zf:
        zf.writestr("report/a.txt", "a")
    with gzip.open(tmp_path / "log.txt.gz", "wb") as f:
        f.write(b"log")
    (tmp_path / "keep.txt").write_text("k")
    assert ci.expand_all(tmp_path) == ["log.txt.gz", "r.zip"]
    assert (tmp_path / "report" / "a.txt").read_text() == "a"
    assert (tmp_path / "log.txt").read_text() == "log"
    assert (tmp_path / "keep.txt").exists()

    bad = tmp_path / "bad"
    bad.mkdir()
    with zipfile.ZipFile(bad / "evil.zip", "w") as zf:
        zf.writestr("../escaped.txt", "x")
    with pytest.raises(zipfile.BadZipFile, match="would land outside"):
        ci.expand_all(bad)
    assert not (tmp_path / "escaped.txt").exists()


def test_progress_says_how_far_each_piece_has_got():
    """What the ticker prints every TICK_SECS: one line per piece in flight."""
    from tabsdata_dev.common.core import render

    buf = io.StringIO()
    progress = ci.Progress(render.Renderer("ci", fmt="json", out=buf))
    key = progress.start("wheels", "downloading", 4 * 1024**2)
    progress.add(key, 1024**2)
    polled = progress.start("logs", "expanding logs.tar.gz", 1000, poll=lambda: 500)
    progress.report()
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    assert lines[0]["message"].startswith("wheels: downloading 25% (1.0 MiB of 4.0 MiB")
    assert (lines[0]["done"], lines[0]["total"]) == (1024**2, 4 * 1024**2)
    assert lines[1]["message"].startswith("logs: expanding logs.tar.gz 50%")
    progress.finish(key)
    progress.finish(polled)
    buf.truncate(0)
    buf.seek(0)
    progress.report()
    assert buf.getvalue() == ""  # nothing in flight, nothing said


def test_the_ticker_reports_while_a_download_runs(gh, tmp_path, monkeypatch):
    """A tick shorter than the download: progress lines arrive before it ends."""
    from tabsdata_dev.common.core import render

    gh(RUNS, [_art("wheels")])
    buf = io.StringIO()
    out = render.Renderer("ci", fmt="json", out=buf)
    slow = ci.fetch

    def fetch(repo, a, dest, progress, **kw):
        import time

        key = progress.start(a.name, "waiting", 10)
        time.sleep(0.3)
        progress.finish(key)
        slow(repo, a, dest, progress, **kw)

    monkeypatch.setattr(ci, "fetch", fetch)
    art = ci.Artifact(_art("wheels")["id"], "wheels", 2048, False)
    assert ci.download("o/r", [art], tmp_path, 1, out, tick=0.05) == []
    phases = [json.loads(x).get("phase") for x in buf.getvalue().splitlines()]
    assert "waiting" in phases


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_on_a_terminal_progress_is_redrawn_in_place(monkeypatch):
    """A terminal gets the status block, not a scrolling info line per tick."""
    from tabsdata_dev.common.core import render

    monkeypatch.setenv("NO_COLOR", "1")
    err = _Tty()
    out = render.Renderer("ci", out=_Tty(), err=err)
    with ci.Progress(out, tick=3600) as progress:
        assert progress.in_place
        key = progress.start("wheels", "downloading", 100)
        progress.add(key, 40)
        progress.report()
        first = err.getvalue().splitlines()[0]
        assert first.startswith(" 40%      40 B of 100 B") and first.endswith(
            "  downloading  wheels"
        )
        progress.say("info", "wheels: downloaded")
        progress.finish(key)
        progress.report()
    text = err.getvalue()
    assert "\033[1F\033[Jwheels: downloaded\n" in text
    assert text.endswith("\033[1F\033[J")  # the block is gone at the end


def test_the_run_search_pages_and_stops_at_the_first_page_that_has_it(
    gh, monkeypatch, capsys
):
    """Newest first, a page at a time, no further than the page with the run;
    `--workflow` matches a workflow's file name as well as its name."""
    runs = [
        {"number": 900 - i, "databaseId": 10_000 + i, "workflowName": "build"}
        for i in range(250)
    ]
    gh(runs, [_art("x")])
    code, events = _run(
        ["download", "--action", "760", "--format", "json"], monkeypatch, capsys
    )
    assert code == 0 and events[-1]["run_id"] == 10_140
    pages = [c[1] for c in gh.calls() if "/actions/runs?" in c[1]]
    assert pages == [
        f"repos/{ci.DEFAULT_REPO}/actions/runs?per_page=100&page=1",
        f"repos/{ci.DEFAULT_REPO}/actions/runs?per_page=100&page=2",
    ]
    assert ci.find_run("o/r", 899, "build.yml").id == 10_001
    seen = []
    with pytest.raises(ci.ToolError, match="latest 250 runs"):
        ci.find_run("o/r", 1, None, on_page=seen.append)
    assert seen == [100, 200, 250]
