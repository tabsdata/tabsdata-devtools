#
# Copyright 2026 Tabsdata Inc.
#

"""push --lane staging|prod: the mirror plan, its order, the gates, --full."""

from __future__ import annotations

import hashlib

import pytest
from conftest import FakeS3, make_cfg, release
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool.pypi import push as push_mod
from tabsdata_dev.tool.pypi.generate import generate
from tabsdata_dev.tool.pypi.plan import (
    DELETE,
    PUT,
    SKIP,
    Action,
    Local,
    Remote,
    execute,
    plan_mirror,
    remote_objects,
)
from tabsdata_dev.tool.pypi.tree import INDEX, load_index

LANE = make_cfg().lanes["staging"]


def run(tree, s3, monkeypatch, out, lane="staging", **kw):
    monkeypatch.setattr(push_mod.boto3, "client", lambda *a, **k: s3)
    monkeypatch.setattr(
        push_mod, "assert_committed_and_pushed", lambda *a, **k: "abc123def456"
    )
    kw.setdefault("dry_run", False)
    kw.setdefault("assume_yes", True)
    return push_mod.push(tree, make_cfg(), make_cfg().lanes[lane], out=out, **kw)


def verbs(actions):
    return {a.key: (a.verb, a.reason) for a in actions}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------ plan_mirror rules


def local_tree(tmp_path, files: dict[str, bytes]) -> dict[str, Local]:
    built = {}
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        built[rel] = Local(p, len(body), sha(body))
    return built


def test_unchanged_push_leaves_the_index_alone(tmp_path):
    local = local_tree(tmp_path, {"files/a.whl": b"A", INDEX: b"I"})
    remote = {
        "pypi/files/a.whl": Remote("e", 1, sha(b"A")),
        "pypi/index.json": Remote("e", 1, sha(b"I")),
    }
    actions = plan_mirror(local, remote, LANE, full=False)
    assert all(a.verb == SKIP for a in actions)
    # but a changed index alone is still delete-first, put-last
    remote["pypi/index.json"] = Remote("e", 1, sha(b"I-old"))
    actions = plan_mirror(local, remote, LANE, full=False)
    assert [(a.verb, a.key) for a in actions if a.verb != SKIP] == [
        (DELETE, "pypi/index.json"),
        (PUT, "pypi/index.json"),
    ]


def test_first_push_puts_everything_index_last(tmp_path):
    local = local_tree(
        tmp_path, {"files/a.whl": b"A", "simple/index.html": b"S", INDEX: b"I"}
    )
    actions = plan_mirror(local, {}, LANE, full=False)
    assert [(a.verb, a.key) for a in actions] == [
        (PUT, "pypi/files/a.whl"),
        (PUT, "pypi/simple/index.html"),
        (PUT, "pypi/index.json"),
    ]
    assert actions[-1].reason.startswith("index last")
    assert actions[0].sha256 == sha(b"A") and actions[0].immutable
    assert not actions[1].immutable


def test_same_sha_skips_changed_sha_puts_orphans_go_index_first(tmp_path):
    local = local_tree(
        tmp_path,
        {"files/a.whl": b"A", "files/b.whl": b"B2", "index.html": b"L", INDEX: b"I"},
    )
    remote = {
        "pypi/index.json": Remote("e", 1, sha(b"old")),
        "pypi/files/a.whl": Remote("e", 1, sha(b"A")),
        "pypi/files/b.whl": Remote("e", 2, sha(b"B1")),
        "pypi/files/gone.whl": Remote("e", 3, sha(b"G")),
        "pypi/index.html": Remote("e", 1, None),  # written before shas were stamped
    }
    actions = plan_mirror(local, remote, LANE, full=False)

    assert actions[0].key == "pypi/index.json" and actions[0].verb == DELETE
    assert actions[-1].key == "pypi/index.json" and actions[-1].verb == PUT
    v = verbs(actions)
    assert v["pypi/files/a.whl"] == (SKIP, "unchanged")
    assert v["pypi/files/b.whl"][0] == PUT and "changed" in v["pypi/files/b.whl"][1]
    assert v["pypi/files/gone.whl"] == (DELETE, "not in the tree")
    assert v["pypi/index.html"] == (PUT, "no sha256 recorded")
    # order: deletes before puts
    order = [a.verb for a in actions if a.verb != SKIP]
    assert order.index(DELETE) < order.index(PUT)
    assert order[: order.count(DELETE)] == [DELETE] * order.count(DELETE)


def test_full_ignores_the_bucket_and_resends_everything(tmp_path):
    local = local_tree(tmp_path, {"files/a.whl": b"A", INDEX: b"I"})
    remote = {
        "pypi/index.json": Remote("e", 1, None),
        "pypi/files/a.whl": Remote("e", 1, sha(b"A")),
        "pypi/files/gone.whl": Remote("e", 1, None),
    }
    actions = plan_mirror(local, remote, LANE, full=True)
    assert [(a.verb, a.key) for a in actions] == [
        (DELETE, "pypi/index.json"),
        (DELETE, "pypi/files/a.whl"),  # identical, deleted anyway, then re-put
        (DELETE, "pypi/files/gone.whl"),
        (PUT, "pypi/files/a.whl"),
        (PUT, "pypi/index.json"),
    ]
    assert verbs(actions)["pypi/files/a.whl"] == (PUT, "--full: everything")


def test_execute_runs_in_plan_order_and_stamps_sha(tmp_path, out):
    local = local_tree(tmp_path, {"files/a.whl": b"A", INDEX: b"I"})
    s3 = FakeS3()
    s3.put_object(Bucket="b", Key="pypi/index.json", Body=b"old")
    actions = plan_mirror(local, remote_objects(s3, "b", "pypi/"), LANE, full=False)
    execute(
        actions, "b", s3, dry_run=False, assume_yes=True, require_yes=False, out=out
    )

    assert s3.deletes == ["pypi/index.json"]
    assert [p["Key"] for p in s3.puts[1:]] == ["pypi/files/a.whl", "pypi/index.json"]
    assert s3.metadata["pypi/files/a.whl"] == {"sha256": sha(b"A")}
    assert s3.puts[1]["CacheControl"].startswith("public, max-age=31536000")
    assert s3.puts[2]["ContentType"] == "application/json"
    assert "IfNoneMatch" not in s3.puts[1]


def test_remote_objects_reads_sha_from_metadata_in_parallel(tmp_path):
    s3 = FakeS3()
    s3.put_object(Bucket="b", Key="pypi/x", Body=b"x", Metadata={"sha256": "ab"})
    s3.put_object(Bucket="b", Key="pypi/y", Body=b"yy")
    r = remote_objects(s3, "b", "pypi/", parallel=4)
    assert r["pypi/x"].sha256 == "ab" and r["pypi/x"].size == 1
    assert r["pypi/y"].sha256 is None
    assert sorted(s3.heads) == ["pypi/x", "pypi/y"]
    s3.heads.clear()
    remote_objects(s3, "b", "pypi/", with_sha=False)
    assert s3.heads == []


def test_batches_keep_index_alone_and_group_the_rest():
    from tabsdata_dev.tool.pypi.plan import _batches

    acts = [
        Action(DELETE, "i", "", alone=True),
        Action(DELETE, "a", ""),
        Action(SKIP, "s", ""),
        Action(DELETE, "b", ""),
        Action(PUT, "c", ""),
        Action(PUT, "d", ""),
        Action(PUT, "i", "", alone=True),
    ]
    assert [[a.key for a in b] for b in _batches(acts)] == [
        ["i"],
        ["a", "b"],
        ["c", "d"],
        ["i"],
    ]
    assert _batches([Action(SKIP, "s", "")]) == []


def test_execute_runs_a_batch_concurrently_and_the_index_alone_last(tmp_path, out):
    import threading

    files = {f"files/{i}.whl": bytes([i]) * 10 for i in range(6)}
    files[INDEX] = b"I"
    local = local_tree(tmp_path, files)
    s3 = FakeS3()
    for k in (
        "pypi/index.json",
        "pypi/files/old1.whl",
        "pypi/files/old2.whl",
        "pypi/files/old3.whl",
    ):
        s3.put_object(Bucket="b", Key=k, Body=b"x")
    s3.puts.clear()

    in_flight = peak = 0
    lock = threading.Lock()
    gate = threading.Event()
    real_put, real_del = s3.put_object, s3.delete_object

    def slow(fn):
        def wrapped(**kw):
            nonlocal in_flight, peak
            if kw["Key"].endswith("index.json"):
                return fn(**kw)  # runs alone by design; must not wait for company
            with lock:
                in_flight += 1
                peak = max(peak, in_flight)
                if peak >= 3:
                    gate.set()
            gate.wait(timeout=5)
            try:
                return fn(**kw)
            finally:
                with lock:
                    in_flight -= 1

        return wrapped

    s3.put_object, s3.delete_object = slow(real_put), slow(real_del)
    actions = plan_mirror(local, remote_objects(s3, "b", "pypi/"), LANE, full=False)
    execute(
        actions,
        "b",
        s3,
        dry_run=False,
        assume_yes=True,
        require_yes=False,
        parallel=4,
        out=out,
    )

    assert peak >= 3  # things really ran together
    assert s3.deletes[0] == "pypi/index.json"  # first, alone
    assert sorted(s3.deletes[1:]) == [
        "pypi/files/old1.whl",
        "pypi/files/old2.whl",
        "pypi/files/old3.whl",
    ]
    assert s3.puts[-1]["Key"] == "pypi/index.json"  # last, alone
    assert sorted(p["Key"] for p in s3.puts[:-1]) == sorted(
        f"pypi/{k}" for k in files if k != INDEX
    )


def test_each_batch_submits_biggest_first(tmp_path, out):
    local = local_tree(
        tmp_path,
        {
            "files/s.whl": b"s" * 10,
            "files/l.whl": b"l" * 9000,
            "files/m.whl": b"m" * 300,
            INDEX: b"I",
        },
    )
    s3 = FakeS3()
    actions = plan_mirror(local, {}, LANE, full=False)
    execute(
        actions,
        "b",
        s3,
        dry_run=False,
        assume_yes=True,
        require_yes=False,
        parallel=1,
        out=out,
    )
    assert [p["Key"].rsplit("/", 1)[1] for p in s3.puts] == [
        "l.whl",
        "m.whl",
        "s.whl",
        "index.json",
    ]


def test_a_failure_stops_before_the_index_is_written(tmp_path, events, out):
    local = local_tree(
        tmp_path, {"files/a.whl": b"A", "files/b.whl": b"B", INDEX: b"I"}
    )
    s3 = FakeS3()
    real = s3.put_object

    def flaky(**kw):
        if kw["Key"].endswith("b.whl"):
            raise RuntimeError("boom")
        return real(**kw)

    s3.put_object = flaky
    actions = plan_mirror(local, {}, LANE, full=False)
    with pytest.raises(ToolError, match="1 action\\(s\\) failed"):
        execute(
            actions, "b", s3, dry_run=False, assume_yes=True, require_yes=False, out=out
        )
    assert "pypi/files/a.whl" in s3.objects  # the batch finished
    assert "pypi/index.json" not in s3.objects  # but the index never went up
    assert "FAILED  put pypi/files/b.whl: boom" in events.text


# ----------------------------------------------------------------- push itself


def test_push_refuses_an_incomplete_tree(raw, tree, staging, monkeypatch, out):
    release(raw)
    generate(raw, staging, out)
    (staging / INDEX).unlink()
    with pytest.raises(ToolError, match="not a complete tree"):
        run(tree, FakeS3(), monkeypatch, out)


def test_push_then_repush_is_a_no_op_that_does_not_invalidate(
    raw, tree, staging, monkeypatch, events, out
):
    release(
        raw,
        "0.9.6",
        ["cp311-cp311-manylinux_2_28_x86_64", "cp311-cp311-macosx_11_0_arm64"],
    )
    generate(raw, staging, out)
    s3 = FakeS3()

    run(tree, s3, monkeypatch, out)
    keys = sorted(s3.objects)
    assert keys[-1] == "pypi/simple/tabsdata/index.html" and "pypi/index.json" in keys
    assert [p["Key"] for p in s3.puts][-1] == "pypi/index.json"  # last on the wire too
    for d in load_index(staging):
        assert s3.metadata[f"pypi/files/{d.filename}"] == {"sha256": d.sha256}
    assert len(s3.invalidations) == 1
    paths = s3.invalidations[0]["InvalidationBatch"]["Paths"]["Items"]
    assert "/index.json" in paths and "/simple/*" in paths and "/files/*" not in paths

    s3.puts.clear()
    s3.deletes.clear()
    s3.invalidations.clear()
    run(tree, s3, monkeypatch, out)
    assert s3.puts == [] and s3.deletes == [] and s3.invalidations == []
    assert "nothing to do" in events.text


def test_repush_after_a_change_deletes_index_first_and_rewrites_it_last(
    raw, tree, staging, monkeypatch, out
):
    release(raw, "0.9.6")
    generate(raw, staging, out)
    s3 = FakeS3()
    run(tree, s3, monkeypatch, out)
    s3.puts.clear()
    s3.deletes.clear()
    s3.invalidations.clear()

    release(raw, "0.9.7")  # a new release: new wheel, new page, changed project page
    generate(raw, staging, out)
    run(tree, s3, monkeypatch, out)

    assert s3.deletes[0] == "pypi/index.json"
    assert s3.puts[-1]["Key"] == "pypi/index.json"
    put_keys = {p["Key"] for p in s3.puts}
    assert any("0.9.7" in k for k in put_keys)
    assert not any(
        "0.9.6" in k and k.endswith(".whl") for k in put_keys
    )  # unchanged wheel skipped
    paths = s3.invalidations[0]["InvalidationBatch"]["Paths"]["Items"]
    assert "/files/*" not in paths  # only new files/ objects: nothing cached changed


def test_removing_a_release_deletes_its_objects_and_invalidates_files(
    raw, tree, staging, monkeypatch, out
):
    release(raw, "0.9.6")
    release(raw, "0.9.7")
    generate(raw, staging, out)
    s3 = FakeS3()
    run(tree, s3, monkeypatch, out)
    s3.deletes.clear()
    s3.invalidations.clear()

    import shutil

    shutil.rmtree(raw / "0.9.7")
    generate(raw, staging, out)
    run(tree, s3, monkeypatch, out)

    gone = [k for k in s3.deletes if "0.9.7" in k]
    assert (
        len(gone) == 2
    )  # wheel and .metadata; the project page is rewritten, not deleted
    assert not any("0.9.7" in k for k in s3.objects)
    paths = s3.invalidations[0]["InvalidationBatch"]["Paths"]["Items"]
    assert "/files/*" in paths


def test_rebuilt_bytes_under_the_same_name_are_re_uploaded_and_files_invalidated(
    raw, tree, staging, monkeypatch, out
):
    release(raw, "0.9.6")
    generate(raw, staging, out)
    s3 = FakeS3()
    run(tree, s3, monkeypatch, out)
    s3.puts.clear()
    s3.invalidations.clear()

    release(raw, "0.9.6", payload=b"rebuilt" * 100)  # same filename, other bytes
    generate(raw, staging, out)
    run(tree, s3, monkeypatch, out)

    whl = [p for p in s3.puts if p["Key"].endswith(".whl")]
    assert (
        len(whl) == 1 and whl[0]["Metadata"]["sha256"] == load_index(staging)[0].sha256
    )
    paths = s3.invalidations[0]["InvalidationBatch"]["Paths"]["Items"]
    assert "/files/*" in paths


def test_objects_pushed_by_older_tooling_are_re_sent_once(
    raw, tree, staging, monkeypatch, out
):
    release(raw, "0.9.6")
    generate(raw, staging, out)
    s3 = FakeS3()
    run(tree, s3, monkeypatch, out)
    for k in list(s3.metadata):
        s3.metadata[k] = {}  # as if written before shas were stamped
    s3.puts.clear()

    run(tree, s3, monkeypatch, out)
    assert len(s3.puts) == len(s3.objects)  # everything, including the index
    s3.puts.clear()
    run(tree, s3, monkeypatch, out)
    assert s3.puts == []  # and now they carry shas, so never again


def test_full_wipes_and_resends(raw, tree, staging, monkeypatch, events, out):
    release(raw, "0.9.6")
    generate(raw, staging, out)
    s3 = FakeS3()
    s3.put_object(Bucket="td-pypi-staging", Key="pypi/files/junk.whl", Body=b"junk")
    run(tree, s3, monkeypatch, out)
    s3.puts.clear()
    s3.deletes.clear()
    s3.heads.clear()

    before = sorted(s3.objects)
    run(tree, s3, monkeypatch, out, full=True)
    assert s3.heads == []  # no per-object comparison
    assert sorted(s3.deletes) == before  # everything that was there went first
    assert s3.deletes[0] == "pypi/index.json"
    assert "pypi/files/junk.whl" not in s3.objects
    assert len(s3.puts) == len(s3.objects)
    assert s3.puts[-1]["Key"] == "pypi/index.json"
    assert "--full" in events.text


def test_dry_run_writes_nothing(raw, tree, staging, monkeypatch, events, out):
    release(raw)
    generate(raw, staging, out)
    s3 = FakeS3()
    run(tree, s3, monkeypatch, out, dry_run=True)
    assert s3.puts == [] and s3.invalidations == []
    said = events.text
    assert "dry run" in said and "put     pypi/index.json" in said


def test_push_prints_where_the_lane_is_read_from(
    raw, tree, staging, monkeypatch, events, out
):
    release(raw)
    generate(raw, staging, out)
    run(tree, FakeS3(), monkeypatch, out)
    said = events.text
    assert "    s3://td-pypi-staging/pypi/\n" in said
    assert "    https://dxxxx.cloudfront.net/simple/\n" in said
    assert "    https://pypi-staging.tabsdata.com/simple/\n" in said
    assert "live in about a minute at https://dxxxx.cloudfront.net/simple/ and" in said


def test_lane_urls_skip_a_dash_domain():
    from dataclasses import replace

    from conftest import make_lane

    assert replace(make_lane(), domain="-").urls == [
        "https://dxxxx.cloudfront.net/simple/"
    ]
    assert replace(make_lane(), domain="").urls == [
        "https://dxxxx.cloudfront.net/simple/"
    ]
    assert make_lane("prod").urls == [
        "https://dxxxx.cloudfront.net/simple/",
        "https://pypi-prod.tabsdata.com/simple/",
    ]


# ----------------------------------------------------------------- prod gates


def test_prod_requires_yes(raw, tree, staging, prod, monkeypatch, out):
    release(raw)
    generate(raw, staging, out)
    from tabsdata_dev.tool.pypi.promote import promote

    promote(staging, prod, out)
    s3 = FakeS3()
    for d in load_index(prod):
        s3.put_object(
            Bucket="td-raw-wheels",
            Key=f"wheels/{d.release}/{d.filename}",
            Body=b"x" * d.size,
            Metadata={"sha256": d.sha256},
        )
    with pytest.raises(ToolError, match="requires an explicit --yes"):
        run(tree, s3, monkeypatch, out, lane="prod", assume_yes=False)


def test_prod_refuses_a_wheel_missing_from_or_different_in_the_archive(
    raw, tree, staging, prod, monkeypatch, out
):
    release(raw)
    generate(raw, staging, out)
    from tabsdata_dev.tool.pypi.promote import promote

    promote(staging, prod, out)
    d = load_index(prod)[0]
    s3 = FakeS3()
    with pytest.raises(ToolError, match="NOT ARCHIVED"):
        run(tree, s3, monkeypatch, out, lane="prod")
    assert s3.puts == []

    key = f"wheels/{d.release}/{d.filename}"
    s3.put_object(
        Bucket="td-raw-wheels",
        Key=key,
        Body=b"x" * d.size,
        Metadata={"sha256": "00" * 32},
    )
    with pytest.raises(ToolError, match="sha256 000000000000 !="):
        run(tree, s3, monkeypatch, out, lane="prod")

    # a legacy archive object with no sha is judged by size
    s3.put_object(Bucket="td-raw-wheels", Key=key, Body=b"x" * (d.size + 1))
    with pytest.raises(ToolError, match="size"):
        run(tree, s3, monkeypatch, out, lane="prod")

    s3.put_object(
        Bucket="td-raw-wheels",
        Key=key,
        Body=b"x" * d.size,
        Metadata={"sha256": d.sha256},
    )
    run(tree, s3, monkeypatch, out, lane="prod")  # passes
    assert "pypi/index.json" in s3.objects


def test_prod_git_gate_is_consulted(raw, tree, staging, prod, monkeypatch, out):
    release(raw)
    generate(raw, staging, out)
    from tabsdata_dev.tool.pypi.promote import promote

    promote(staging, prod, out)
    monkeypatch.setattr(push_mod.boto3, "client", lambda *a, **k: FakeS3())

    def refuse(*a, **k):
        raise ToolError("refusing to push — uncommitted changes")

    monkeypatch.setattr(push_mod, "assert_committed_and_pushed", refuse)
    with pytest.raises(ToolError, match="uncommitted"):
        push_mod.push(
            tree, make_cfg(), make_cfg().lanes["prod"], assume_yes=True, out=out
        )


# ---------------------------------------------------------------- cache-clean


def test_cache_clean_invalidates_everything(monkeypatch, events, out):
    from tabsdata_dev.tool.pypi import cache as cache_mod

    s3 = FakeS3()
    monkeypatch.setattr(cache_mod.boto3, "client", lambda *a, **k: s3)
    cache_mod.cache_clean(LANE, out, assume_yes=True)

    assert len(s3.invalidations) == 1
    inv = s3.invalidations[0]
    assert inv["DistributionId"] == LANE.distribution
    assert inv["InvalidationBatch"]["Paths"] == {"Quantity": 1, "Items": ["/*"]}
    assert inv["InvalidationBatch"]["CallerReference"].startswith(
        "cache-clean-td-pypi-staging-"
    )
    said = events.text
    assert "invalidation I000 created on EXXXX: /*" in said
    assert "https://dxxxx.cloudfront.net/simple/" in said


def test_cache_clean_prod_requires_yes(monkeypatch, out):
    from tabsdata_dev.tool.pypi import cache as cache_mod

    s3 = FakeS3()
    monkeypatch.setattr(cache_mod.boto3, "client", lambda *a, **k: s3)
    with pytest.raises(ToolError, match="requires an explicit --yes"):
        cache_mod.cache_clean(make_cfg().lanes["prod"], out, assume_yes=False)
    assert s3.invalidations == []


def test_cache_clean_staging_asks_and_refuses_off_a_tty(monkeypatch, out):
    from tabsdata_dev.tool.pypi import cache as cache_mod
    from tabsdata_dev.tool.pypi import plan as plan_mod

    s3 = FakeS3()
    monkeypatch.setattr(cache_mod.boto3, "client", lambda *a, **k: s3)
    monkeypatch.setattr(plan_mod.sys.stdin, "isatty", lambda: False)
    with pytest.raises(ToolError, match="not a terminal"):
        cache_mod.cache_clean(LANE, out, assume_yes=False)
    assert s3.invalidations == []


def test_cache_clean_from_the_cli(monkeypatch):
    from tabsdata_dev.tool import pypi
    from tabsdata_dev.tool.pypi import cache as cache_mod

    s3 = FakeS3()
    monkeypatch.setattr(cache_mod.boto3, "client", lambda *a, **k: s3)
    monkeypatch.setattr(pypi.config_mod, "load", lambda _p: make_cfg())
    assert pypi.main(["cache-clean", "--lane", "prod", "--yes"]) == 0
    assert [i["DistributionId"] for i in s3.invalidations] == ["EXXXX"]
    assert s3.invalidations[0]["InvalidationBatch"]["Paths"]["Items"] == ["/*"]


def test_push_invalidation_is_labelled_push(raw, tree, staging, monkeypatch, out):
    release(raw, "0.9.6")
    generate(raw, staging, out)
    s3 = FakeS3()
    run(tree, s3, monkeypatch, out)
    ref = s3.invalidations[0]["InvalidationBatch"]["CallerReference"]
    assert ref.startswith("push-td-pypi-staging-")
