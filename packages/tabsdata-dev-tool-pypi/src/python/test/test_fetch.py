#
# Copyright 2026 Tabsdata Inc.
#

"""fetch --lane raw|staging|prod: a bucket back onto disk, exactly; --force, --sync."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest
from conftest import FakeS3, make_cfg, make_lane
from tabsdata_dev.common.core import cli
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool import pypi
from tabsdata_dev.tool.pypi import fetch as fetch_mod


def on_disk(root: Path) -> list[str]:
    return sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
    )


# =========================================================================== raw

RELEASES = {
    "1.0.0": ["a-1.0.0-py3-none-any.whl", "b-1.0.0-py3-none-any.whl"],
    "1.0.1": [
        "a-1.0.1-py3-none-any.whl",
        "b-1.0.1-py3-none-any.whl",
        "c-1.0.1-py3-none-any.whl",
    ],
}


def body(name: str) -> bytes:
    return name.encode() * 100


def archive_bucket() -> FakeS3:
    s3 = FakeS3()
    for version, names in RELEASES.items():
        for n in names:
            s3.put_object(
                Bucket="td-raw-wheels", Key=f"wheels/{version}/{n}", Body=body(n)
            )
    s3.put_object(
        Bucket="td-raw-wheels", Key="wheels/README", Body=b"hi"
    )  # not a release
    s3.puts.clear()
    return s3


def run_raw(raw, s3, monkeypatch, out, **kw):
    monkeypatch.setattr(fetch_mod.boto3, "client", lambda *a, **k: s3)
    fetch_mod.fetch_raw(raw, make_cfg(), out=out, **kw)


def raw_on_disk(raw):
    return {
        d.name: sorted(p.name for p in d.glob("*.whl"))
        for d in sorted(raw.iterdir())
        if d.is_dir()
    }


def test_raw_fetches_every_version_and_rebuilds_manifests(
    raw, monkeypatch, events, out
):
    s3 = archive_bucket()
    run_raw(raw, s3, monkeypatch, out)
    assert raw_on_disk(raw) == {v: sorted(n) for v, n in RELEASES.items()}
    for v, names in RELEASES.items():
        assert (raw / v / "MANIFEST").read_text() == "\n".join(sorted(names)) + "\n"
        for n in names:
            assert (raw / v / n).read_bytes() == body(n)
    assert not (raw / "README").exists()
    said = events.text
    assert "5 fetched, 0 already present" in said
    assert "the archive is not served: no https://" in said


def test_raw_version_narrows(raw, monkeypatch, out):
    s3 = archive_bucket()
    run_raw(raw, s3, monkeypatch, out, version="1.0.1")
    assert raw_on_disk(raw) == {"1.0.1": sorted(RELEASES["1.0.1"])}
    with pytest.raises(ToolError, match="nothing archived"):
        run_raw(raw, s3, monkeypatch, out, version="9.9.9")


def test_raw_matching_files_are_skipped_unless_forced(raw, monkeypatch, events, out):
    s3 = archive_bucket()
    run_raw(raw, s3, monkeypatch, out)
    s3.gets.clear()
    run_raw(raw, s3, monkeypatch, out)
    assert s3.gets == []
    assert "0 fetched, 5 already present" in events.text
    run_raw(raw, s3, monkeypatch, out, force=True)
    assert len(s3.gets) == 5


def test_raw_corrupt_download_is_dropped_and_no_manifest_written(raw, monkeypatch, out):
    s3 = archive_bucket()
    name = RELEASES["1.0.0"][0]
    s3.objects[f"wheels/1.0.0/{name}"] = (
        hashlib.md5(b"other").hexdigest(),
        len(body(name)),
    )
    with pytest.raises(ToolError, match="1 download\\(s\\) failed"):
        run_raw(raw, s3, monkeypatch, out)
    assert not (raw / "1.0.0" / name).exists()
    assert not list(raw.rglob("*.part")) and not list(raw.rglob("MANIFEST"))


def test_raw_existing_manifest_is_kept_and_flagged_if_it_differs(
    raw, monkeypatch, events, out
):
    (raw / "1.0.1").mkdir()
    (raw / "1.0.1" / "MANIFEST").write_text("a-1.0.1-py3-none-any.whl\n")
    run_raw(raw, archive_bucket(), monkeypatch, out, version="1.0.1")
    assert (raw / "1.0.1" / "MANIFEST").read_text() == "a-1.0.1-py3-none-any.whl\n"
    assert "kept (differs)" in events.text


def test_raw_sync_prunes_what_the_archive_lacks(raw, monkeypatch, events, out):
    s3 = archive_bucket()
    run_raw(raw, s3, monkeypatch, out)
    (raw / "1.0.0" / "z.whl").write_bytes(b"never archived")
    (raw / "2.0.0").mkdir()
    (raw / "2.0.0" / "a-2.0.0-py3-none-any.whl").write_bytes(b"wip")
    (raw / "2.0.0" / "MANIFEST").write_text("a-2.0.0-py3-none-any.whl\n")
    (raw / ".empty").write_text("")

    run_raw(raw, s3, monkeypatch, out, sync=True, assume_yes=True)
    assert raw_on_disk(raw) == {v: sorted(n) for v, n in RELEASES.items()}
    assert not (raw / "2.0.0").exists() and (raw / ".empty").exists()
    assert (raw / "1.0.0" / "MANIFEST").exists()
    said = events.text
    assert "not in the archive, --sync removes them entirely: 2.0.0" in said
    assert "pruned 3 file(s)" in said


def test_sync_asks_first(raw, monkeypatch, out):
    s3 = archive_bucket()
    run_raw(raw, s3, monkeypatch, out)
    orphan = raw / "1.0.0" / "z.whl"
    orphan.write_bytes(b"x")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ToolError, match="not a terminal — pass --yes"):
        run_raw(raw, s3, monkeypatch, out, sync=True)
    assert orphan.exists()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "n")
    with pytest.raises(ToolError, match="aborted"):
        run_raw(raw, s3, monkeypatch, out, sync=True)
    monkeypatch.setattr("builtins.input", lambda: "y")
    run_raw(raw, s3, monkeypatch, out, sync=True)
    assert not orphan.exists()


def test_biggest_first_and_really_parallel(raw, monkeypatch, out):
    s3 = FakeS3()
    for n, size in {"m.whl": 300, "s.whl": 10, "l.whl": 9000, "xs.whl": 1}.items():
        s3.put_object(Bucket="td-raw-wheels", Key=f"wheels/1.0.0/{n}", Body=b"x" * size)
    run_raw(raw, s3, monkeypatch, out, parallel=1)
    assert [k.rsplit("/", 1)[1] for k in s3.gets] == [
        "l.whl",
        "m.whl",
        "s.whl",
        "xs.whl",
    ]

    s3 = archive_bucket()
    peak = in_flight = 0
    lock, started = threading.Lock(), threading.Event()
    real = s3.download_file

    def slow(Bucket, Key, Filename):
        nonlocal peak, in_flight
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
            if peak >= 3:
                started.set()
        started.wait(timeout=5)
        real(Bucket, Key, Filename)
        with lock:
            in_flight -= 1

    s3.download_file = slow
    run_raw(raw, s3, monkeypatch, out, force=True, parallel=3)
    assert peak == 3


# ==================================================================== lane

OBJECTS = {
    "index.html": b"<html>landing</html>",
    "simple/index.html": b"<html>root</html>",
    "simple/tabsdata/index.html": b"<html>tabsdata</html>",
    "files/tabsdata-1.0.0-py3-none-any.whl.metadata": b"Metadata-Version: 2.1\n",
    "files/tabsdata-1.0.0-py3-none-any.whl": b"PK" * 5000,
    "index.json": b'{"format": 1, "files": []}',
}


def lane_bucket(with_index=True) -> FakeS3:
    s3 = FakeS3()
    for rel, b in OBJECTS.items():
        if rel == "index.json" and not with_index:
            continue
        s3.put_object(Bucket="td-pypi-staging", Key=f"pypi/{rel}", Body=b)
    s3.puts.clear()
    return s3


def run_lane(tree, s3, monkeypatch, out, **kw):
    monkeypatch.setattr(fetch_mod.boto3, "client", lambda *a, **k: s3)
    fetch_mod.fetch_lane(tree, make_cfg(), make_lane(), out=out, **kw)


def test_lane_mirrors_everything_into_the_lane_tree_index_last(
    tree, staging, monkeypatch, events, out
):
    s3 = lane_bucket()
    run_lane(tree, s3, monkeypatch, out)
    assert on_disk(staging) == sorted(OBJECTS)
    for rel, b in OBJECTS.items():
        assert (staging / rel).read_bytes() == b
    assert s3.gets[-1] == "pypi/index.json"
    said = events.text
    assert "tree complete" in said
    assert "    s3://td-pypi-staging/pypi/\n" in said
    assert "    https://dxxxx.cloudfront.net/simple/\n" in said


def test_lane_without_a_remote_index_leaves_no_local_one(
    tree, staging, monkeypatch, events, out
):
    run_lane(tree, lane_bucket(), monkeypatch, out)
    assert (staging / "index.json").exists()
    run_lane(tree, lane_bucket(with_index=False), monkeypatch, out)
    assert not (staging / "index.json").exists()  # removed first, never re-fetched
    assert "did not finish" in events.text


def test_lane_sync_prunes_and_force_refetches(tree, staging, monkeypatch, out):
    s3 = lane_bucket()
    run_lane(tree, s3, monkeypatch, out)
    (staging / "simple" / "gone" / "index.html").parent.mkdir()
    (staging / "simple" / "gone" / "index.html").write_bytes(b"gone")
    run_lane(tree, s3, monkeypatch, out)
    assert (staging / "simple" / "gone" / "index.html").exists()  # no --sync
    s3.gets.clear()
    run_lane(tree, s3, monkeypatch, out, sync=True, assume_yes=True)
    assert not (staging / "simple" / "gone").exists()
    assert s3.gets == ["pypi/index.json"]  # everything else already matched
    run_lane(tree, s3, monkeypatch, out, force=True)
    assert len(s3.gets) > 1


def test_lane_leaves_the_namespaces_beside_it_alone(tree, staging, monkeypatch, out):
    """`push --at NAME` objects sit beside the lane's own; they are a developer's,
    never part of pypi-wheels/<lane>/."""
    s3 = lane_bucket()
    for rel in ("tucu/index.html", "tucu/files/x.whl", "tucu/index.json"):
        s3.put_object(Bucket="td-pypi-staging", Key=f"pypi/{rel}", Body=b"ns")
    run_lane(tree, s3, monkeypatch, out)
    assert on_disk(staging) == sorted(OBJECTS)
    assert not any("tucu" in k for k in s3.gets)


def test_lane_empty_bucket_is_an_error(tree, monkeypatch, out):
    with pytest.raises(ToolError, match="nothing under"):
        run_lane(tree, FakeS3(), monkeypatch, out)


# ========================================================================== cli


def parse(argv: str):
    return pypi.build_parser().parse_args(argv.split())


def test_cli_shapes():
    a = parse("fetch --lane raw --version 2.0.1 --force --sync --yes --parallel 4")
    assert (a.lane, a.version, a.force, a.sync, a.yes, a.parallel) == (
        "raw",
        "2.0.1",
        True,
        True,
        True,
        4,
    )
    assert parse("fetch --lane raw").parallel == 32
    assert parse("push --lane raw").parallel == 32
    assert parse("push --lane staging").at == "simple"
    assert parse("push --lane staging --at tucu").at == "tucu"
    a = parse("push --lane prod --full --dry-run --yes")
    assert (a.lane, a.full, a.dry_run, a.yes) == ("prod", True, True, True)
    a = parse("check --lane staging --local")
    assert (a.lane, a.local, a.remote) == ("staging", True, False)
    a = parse("cache-clean --lane prod --yes")
    assert (a.cmd, a.lane, a.yes) == ("cache-clean", "prod", True)
    assert parse("cache-clean --lane staging").yes is False
    assert parse("serve").lane == "staging"
    assert parse("generate").cmd == "generate" and parse("promote").cmd == "promote"


@pytest.mark.parametrize(
    "argv",
    [
        "check --lane staging",
        "check --lane raw --local",
        "check --lane staging --local --remote",
        "serve --lane raw",
        "cache-clean",
        "cache-clean --lane raw",
        "cache-clean --lane staging --dry-run",  # nothing to plan: it is one call
        "yank 1.0 --reason x",  # gone: edit yanked.yaml instead
        "unyank 1.0",
        "deploy --lane staging",
        "archive 2.0.1",
        "fetch-raw",
        "push --lane qa",
    ],
)
def test_cli_rejects_unknown_shapes(argv):
    with pytest.raises(cli.UsageError):
        parse(argv)


@pytest.mark.parametrize(
    "argv, message",
    [
        ("push --lane raw --full", "--full does not apply"),
        ("push --lane staging --version 1", "--version applies to --lane raw only"),
        ("push --lane staging --force", "--force applies to --lane raw only"),
        ("push --lane staging --sync", "--sync applies to --lane raw only"),
        ("push --lane raw --at tucu", "--at applies to the serving lanes only"),
        ("push --lane staging --at files", "--at 'files': a namespace is"),
        ("fetch --lane staging --version 1", "--version applies to --lane raw only"),
    ],
)
def test_cli_lane_specific_flag_rules(monkeypatch, capsys, argv, message):
    monkeypatch.setattr(pypi.config_mod, "load", lambda _p: make_cfg())
    assert pypi.main(argv.split()) == 1
    assert message in capsys.readouterr().err
