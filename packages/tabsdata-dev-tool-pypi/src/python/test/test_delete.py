#
# Copyright 2026 Tabsdata Inc.
#

"""delete --lane staging [--at NAME]: one namespace, or the lane's own tree."""

from __future__ import annotations

import pytest
from conftest import FakeS3, make_cfg, release
from tabsdata_dev.common.core import cli
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool import pypi
from tabsdata_dev.tool.pypi import delete as delete_mod
from tabsdata_dev.tool.pypi.generate import generate
from test_push import run as push


def run(s3, monkeypatch, out, at="simple", **kw):
    monkeypatch.setattr(delete_mod.boto3, "client", lambda *a, **k: s3)
    kw.setdefault("assume_yes", True)
    lane = make_cfg().lanes["staging"].with_at(at)
    return delete_mod.delete(make_cfg(), lane, out=out, **kw)


@pytest.fixture
def bucket(raw, tree, staging, monkeypatch, out) -> FakeS3:
    """The lane's own tree and two namespaces beside it."""
    release(raw)
    generate(raw, staging, out)
    s3 = FakeS3()
    for at in ("simple", "tucu", "ana"):
        push(tree, s3, monkeypatch, out, lane_at=at)
    s3.deletes.clear()
    s3.invalidations.clear()
    return s3


def under(s3, prefix):
    return sorted(k for k in s3.objects if k.startswith(prefix))


def test_a_namespace_goes_index_first_and_nothing_else_with_it(
    bucket, monkeypatch, events, out
):
    lanes, ana = under(bucket, "pypi/simple/"), under(bucket, "pypi/ana/")
    tucu = under(bucket, "pypi/tucu/")
    run(bucket, monkeypatch, out, at="tucu")
    assert bucket.deletes[0] == "pypi/tucu/index.json"
    assert sorted(bucket.deletes) == tucu
    assert under(bucket, "pypi/tucu/") == []
    assert under(bucket, "pypi/simple/") == lanes and under(bucket, "pypi/ana/") == ana
    paths = bucket.invalidations[0]["InvalidationBatch"]["Paths"]["Items"]
    assert paths == ["/tucu/*"]
    assert "deleted 5 object(s) of namespace tucu" in events.text


def test_the_lanes_own_tree_goes_and_its_namespaces_stay(bucket, monkeypatch, out):
    tucu, ana = under(bucket, "pypi/tucu/"), under(bucket, "pypi/ana/")
    run(bucket, monkeypatch, out)
    assert bucket.deletes[0] == "pypi/index.json"
    assert sorted(bucket.objects) == sorted(tucu + ana)
    paths = bucket.invalidations[0]["InvalidationBatch"]["Paths"]["Items"]
    assert "/simple/*" in paths and "/files/*" in paths and "/tucu/*" not in paths


def test_dry_run_and_an_empty_target_delete_nothing(bucket, monkeypatch, events, out):
    before = dict(bucket.objects)
    run(bucket, monkeypatch, out, at="tucu", dry_run=True)
    assert bucket.objects == before and bucket.invalidations == []
    assert "delete  pypi/tucu/index.json" in events.text
    run(bucket, monkeypatch, out, at="nobody")
    assert bucket.objects == before and bucket.invalidations == []
    assert "nothing under s3://td-pypi-staging/pypi/nobody/ to delete" in events.text


def test_it_asks_unless_yes(bucket, monkeypatch, out):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ToolError, match="pass --yes"):
        run(bucket, monkeypatch, out, at="tucu", assume_yes=False)
    assert bucket.deletes == []


def test_staging_only():
    parse = pypi.build_parser().parse_args
    a = parse(["delete", "--lane", "staging", "--at", "tucu", "--dry-run"])
    assert (a.cmd, a.lane, a.at, a.dry_run, a.yes) == (
        "delete",
        "staging",
        "tucu",
        True,
        False,
    )
    assert parse(["delete", "--lane", "staging"]).at == "simple"
    for lane in ("prod", "raw"):
        with pytest.raises(cli.UsageError):
            parse(["delete", "--lane", lane])
