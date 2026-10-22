#
# Copyright 2026 Tabsdata Inc.
#

"""What the shell version could only be checked for by grepping its own source:
that the cache is read the way uv keys it, and that what is swept, reported and
left alone is what the design says."""

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest
from tabsdata_dev.tool import pycache

#: A cache holding one of everything the command has to tell apart.
TREE = (
    # an editable build: keyed by source hash, so a name-keyed clean skips it
    "sdists-v9/editable/aaaahash/tabsdata-dev-tool-xp-0.1.0/pyproject.toml",
    # an unpacked wheel, whose top level is the .dist-info
    "archive-v0/bbbbid/tabsdata_dev_tool_xp-0.1.0.dist-info/RECORD",
    # a whole cached environment: uv's to prune, ours only to report
    "archive-v0/ccccid/lib/python3.12/site-packages/tabsdata-9.9.9.dist-info/RECORD",
    # plain entries: a wheel and an index record
    "wheels-v6/pypi/tabsdata-1.2.3.whl",
    "simple-v16/pypi/tabsdata_dev-0.1.0.rkyv",
    # the import package inside a wheel: no version, so not a distribution
    "archive-v0/ddddid/tabsdata_dev/__init__.py",
    # someone else's package entirely
    "wheels-v6/pypi/polars-1.44.1.whl",
)


@pytest.fixture
def cache(tmp_path):
    root = tmp_path / "uvcache"
    for rel in TREE:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return root


def test_a_distribution_name_is_what_uv_would_key_it_by():
    assert pycache.distribution_name("tabsdata_dev_tool_xp-0.1.0.dist-info") == (
        "tabsdata-dev-tool-xp"
    )
    assert pycache.distribution_name("tabsdata-1.2.3.whl") == "tabsdata"
    assert pycache.distribution_name("tabsdata_dev-0.1.0.rkyv") == "tabsdata-dev"
    assert pycache.distribution_name("tabsdata-1.0.tar.gz") == "tabsdata"
    assert pycache.distribution_name("Tabsdata_Dev-0.1.0.http") == "tabsdata-dev"


def test_scan_takes_versioned_entries_only_and_ignores_case(cache):
    found = {str(p) for p in pycache.scan(cache, ["tabsdata"])}
    assert "wheels-v6/pypi/tabsdata-1.2.3.whl" in found
    assert "simple-v16/pypi/tabsdata_dev-0.1.0.rkyv" in found
    assert "sdists-v9/editable/aaaahash/tabsdata-dev-tool-xp-0.1.0" in found
    # the import package has no version: taking it would ask uv to clean a
    # distribution called tabsdata-dev, which does not exist
    assert "archive-v0/ddddid/tabsdata_dev" not in found
    # and another project's entries are not ours to touch
    assert not any("polars" in f for f in found)


def test_an_entry_inside_a_cached_environment_is_reported_not_addressed(cache):
    hits = pycache.scan(cache, ["tabsdata"])
    inside = [h for h in hits if pycache.inside_environment(h.parts)]
    assert [str(h) for h in inside] == [
        "archive-v0/ccccid/lib/python3.12/site-packages/tabsdata-9.9.9.dist-info"
    ]
    # it is still found, so the command can say it is there
    assert inside[0] in hits


def test_sweepable_is_the_source_shard_and_the_unpacked_wheel_only(cache):
    shards = {str(s) for s in pycache.sweepable(pycache.scan(cache, ["tabsdata"]))}
    assert shards == {"sdists-v9/editable/aaaahash", "archive-v0/bbbbid"}
    # never the environment archive, and never a bare top-level cache directory
    assert not any(s in ("archive-v0", "sdists-v9") for s in shards)


def test_the_search_for_pip_skips_this_tools_own_venv(monkeypatch):
    own = str(pathlib.Path(sys.executable).parent)
    monkeypatch.setenv("PATH", os.pathsep.join([own, "/somewhere/bin"]))
    assert pycache.search_path() == "/somewhere/bin"


def test_pip_runs_with_that_path_and_not_the_one_we_inherited(monkeypatch):
    """Choosing the binary is not enough. A pyenv shim re-resolves `python3` by
    name from the PATH it is handed, and tdd puts its own toolset bin/ first,
    so a child given the inherited PATH execs tdd's interpreter -- which has no
    pip -- and a machine with pip is told it has none."""
    own = str(pathlib.Path(sys.executable).parent)
    monkeypatch.setenv("PATH", os.pathsep.join([own, "/somewhere/bin"]))
    seen = {}

    def fake(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    pycache._pip_run(["pip", "--version"])
    assert seen["env"]["PATH"] == "/somewhere/bin"
    assert own not in seen["env"]["PATH"]


# ------------------------------------------------------------------ end to end
class FakeUv:
    """`uv cache dir` answers with the tree; `uv cache clean NAMES` removes what
    uv really would, so what the command reports as left over is what is left."""

    def __init__(self, root):
        self.root = root
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        out = ""
        if argv[:3] == ["uv", "cache", "clean"]:
            named = set(argv[3:])
            for hit in pycache.scan(self.root, [""]):
                if pycache.inside_environment(hit.parts):
                    continue
                if not named or pycache.distribution_name(hit.name) in named:
                    target = self.root / hit
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    elif target.exists():
                        target.unlink()
            out = f"Removed {len(named)} packages"
        elif argv[:3] == ["uv", "cache", "dir"]:
            out = f"{self.root}\n"
        return subprocess.CompletedProcess(argv, 0, out, "")


def _events(capsys):
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def _run(monkeypatch, capsys, *argv, pip=None):
    monkeypatch.setattr(sys, "argv", ["pycache", *argv, "--format", "json"])
    calls = []

    def fake_pip(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(pycache, "pip_command", lambda: pip)
    monkeypatch.setattr(pycache, "_pip_run", fake_pip)
    code = pycache.main()
    return code, _events(capsys), calls


def test_clean_names_every_distribution_sweeps_the_shards_and_reports_the_rest(
    cache, monkeypatch, capsys
):
    uv = FakeUv(cache)
    monkeypatch.setattr(pycache.proc, "run", uv)
    code, events, pip_calls = _run(monkeypatch, capsys, "clean", pip=["pip"])
    assert code == 0, events

    cleaned = next(c for c in uv.calls if c[:3] == ["uv", "cache", "clean"])
    assert sorted(cleaned[3:]) == [
        "tabsdata",
        "tabsdata-dev",
        "tabsdata-dev-tool-xp",
    ]

    # the shards uv leaves behind are gone, and the environment archive is not
    assert not (cache / "sdists-v9/editable/aaaahash").exists()
    assert not (cache / "archive-v0/bbbbid").exists()
    assert (cache / "archive-v0/ccccid/lib/python3.12").exists()

    ok = events[-1]
    assert ok["event"] == "ok"
    assert ok["scope"] == "prefixes" and ok["prefixes"] == ["tabsdata"]
    assert ok["uv_packages"] == ["tabsdata", "tabsdata-dev", "tabsdata-dev-tool-xp"]
    assert ok["uv_entries"] == 4 and ok["uv_swept"] == 2
    assert ok["pip"] is True and "purged matching wheels" in ok["message"]

    # what survives is named rather than claimed purged
    warn = next(e for e in events if e["event"] == "warn")
    assert "still match" in warn["message"]
    assert warn["left"] == [
        "archive-v0/ccccid/lib/python3.12/site-packages/tabsdata-9.9.9.dist-info"
    ]

    # pip is done by prefix, in both spellings
    assert [c[-1] for c in pip_calls] == ["tabsdata*", "tabsdata*"]


def test_without_pip_the_clean_is_uv_only_and_says_so(cache, monkeypatch, capsys):
    monkeypatch.setattr(pycache.proc, "run", FakeUv(cache))
    code, events, pip_calls = _run(monkeypatch, capsys, "clean", pip=None)
    assert code == 0 and not pip_calls
    assert any(e["event"] == "warn" and "no pip found" in e["message"] for e in events)
    ok = events[-1]
    assert ok["pip"] is False and "pip: not found, skipped" in ok["message"]


def test_nothing_cached_under_the_prefix_is_an_ok_not_a_failure(
    cache, monkeypatch, capsys
):
    monkeypatch.setattr(pycache.proc, "run", FakeUv(cache))
    code, events, _ = _run(
        monkeypatch, capsys, "clean", "--package-prefixes", "nothing-here", pip=["pip"]
    )
    assert code == 0
    ok = events[-1]
    assert "nothing cached under nothing-here" in ok["message"]
    assert ok["uv_packages"] == [] and ok["uv_entries"] == 0 and ok["uv_swept"] == 0


def test_all_purges_both_caches_whole(cache, monkeypatch, capsys):
    uv = FakeUv(cache)
    monkeypatch.setattr(pycache.proc, "run", uv)
    code, events, pip_calls = _run(monkeypatch, capsys, "clean", "--all", pip=["pip"])
    assert code == 0
    assert ["uv", "cache", "clean"] in uv.calls  # no names: the whole cache
    assert pip_calls == [["pip", "cache", "purge"]]
    ok = events[-1]
    assert ok["scope"] == "all" and ok["uv"] is True and ok["pip"] is True
    assert ok["message"] == "purged the whole uv cache and the whole pip cache"


def test_a_subcommand_is_required(monkeypatch, capsys):
    monkeypatch.setattr(pycache, "pip_command", lambda: None)
    monkeypatch.setattr(sys, "argv", ["pycache", "--format", "json"])
    assert pycache.main() == 1
    error = _events(capsys)[-1]
    assert error["event"] == "error"
    assert "a subcommand is required: clean" in error["message"]


def test_a_uv_that_fails_is_one_error_with_its_output_in_the_log(
    cache, monkeypatch, capsys
):
    def failing(argv, **kwargs):
        if argv[:3] == ["uv", "cache", "dir"]:
            return subprocess.CompletedProcess(argv, 0, f"{cache}\n", "")
        return subprocess.CompletedProcess(argv, 1, "", "error: no such package")

    monkeypatch.setattr(pycache.proc, "run", failing)
    code, events, _ = _run(monkeypatch, capsys, "clean", pip=None)
    assert code == 1
    assert events[-1]["event"] == "error"
    assert events[-1]["message"] == "uv cache clean failed"
    assert "error: no such package" in pathlib.Path(events[-1]["log"]).read_text()
