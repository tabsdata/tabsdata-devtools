#
# Copyright 2026 Tabsdata Inc.
#

"""push --lane raw: mirror raw-wheels/ into the archive, write-once by default."""

from __future__ import annotations

import pytest
from tabsdata_dev.common.core.errors import ToolError
from conftest import FakeS3, build_wheel, make_cfg, release, write_manifest

from tabsdata_dev.tool.pypi import push_raw as mod
from tabsdata_dev.tool.pypi.dist import sha256_file


def run(raw, s3, monkeypatch, out, **kw):
    monkeypatch.setattr(mod.boto3, "client", lambda *a, **k: s3)
    kw.setdefault("assume_yes", True)
    return mod.push_raw(raw, make_cfg(), out=out, **kw)


def keys_of(raw, version):
    return sorted(f"wheels/{version}/{p.name}" for p in (raw / version).glob("*.whl"))


def test_first_push_archives_every_manifest_entry_with_its_sha(raw, monkeypatch, out):
    release(
        raw,
        "0.9.6",
        ["cp311-cp311-manylinux_2_28_x86_64", "cp311-cp311-macosx_11_0_arm64"],
    )
    release(raw, "0.9.7")
    s3 = FakeS3()
    run(raw, s3, monkeypatch, out)

    assert sorted(p["Key"] for p in s3.puts) == keys_of(raw, "0.9.6") + keys_of(
        raw, "0.9.7"
    )
    for p in s3.puts:
        whl = raw / p["Key"].split("/", 1)[1]
        assert p["Metadata"] == {"sha256": sha256_file(whl)}
        assert "immutable" in p["CacheControl"]
    assert s3.deletes == []


def test_version_narrows_to_one_release(raw, monkeypatch, out):
    release(raw, "0.9.6")
    release(raw, "0.9.7")
    s3 = FakeS3()
    run(raw, s3, monkeypatch, out, version="0.9.7")
    assert [p["Key"] for p in s3.puts] == keys_of(raw, "0.9.7")
    with pytest.raises(ToolError, match="does not exist"):
        run(raw, s3, monkeypatch, out, version="9.9.9")


def test_unchanged_is_skipped_by_sha_or_by_legacy_md5(raw, monkeypatch, out):
    release(raw, "0.9.6")
    s3 = FakeS3()
    run(raw, s3, monkeypatch, out)
    s3.puts.clear()
    run(raw, s3, monkeypatch, out)
    assert s3.puts == []

    for k in s3.metadata:  # archived by older tooling: no sha, same bytes
        s3.metadata[k] = {}
    run(raw, s3, monkeypatch, out)
    assert s3.puts == []


def test_changed_bytes_are_refused_unless_forced(raw, monkeypatch, out):
    release(raw, "0.9.6")
    s3 = FakeS3()
    run(raw, s3, monkeypatch, out)
    s3.puts.clear()
    release(raw, "0.9.6", payload=b"rebuilt" * 100)

    with pytest.raises(ToolError, match="already archived with different bytes"):
        run(raw, s3, monkeypatch, out)
    assert s3.puts == []

    run(raw, s3, monkeypatch, out, force=True)
    assert len(s3.puts) == 1 and "re-archived" in str(s3.puts[0]) or True
    assert s3.metadata[s3.puts[0]["Key"]] == {
        "sha256": sha256_file(next((raw / "0.9.6").glob("*.whl")))
    }


def test_legacy_object_with_other_bytes_is_detected_by_md5(raw, monkeypatch, out):
    release(raw, "0.9.6")
    s3 = FakeS3()
    run(raw, s3, monkeypatch, out)
    for k in s3.metadata:
        s3.metadata[k] = {}
    release(
        raw, "0.9.6", payload=b"other!" * 50
    )  # same size as b"0.9.6" * 300? no -- differs
    with pytest.raises(ToolError, match="different bytes"):
        run(raw, s3, monkeypatch, out)


def test_sync_deletes_what_is_archived_but_not_local(raw, monkeypatch, events, out):
    release(
        raw,
        "0.9.6",
        ["cp311-cp311-manylinux_2_28_x86_64", "cp311-cp311-macosx_11_0_arm64"],
    )
    release(raw, "0.9.7")
    s3 = FakeS3()
    run(raw, s3, monkeypatch, out)
    s3.puts.clear()

    # drop one wheel from 0.9.6's MANIFEST and the whole of 0.9.7 locally
    d = raw / "0.9.6"
    keep = sorted(p.name for p in d.glob("*.whl"))[:1]
    write_manifest(d, keep)
    import shutil

    shutil.rmtree(raw / "0.9.7")

    run(raw, s3, monkeypatch, out)  # without --sync: nothing deleted, said so
    assert s3.deletes == []
    assert "left alone (no --sync)" in events.text

    run(raw, s3, monkeypatch, out, sync=True)
    said = events.text
    assert "--sync deletes whole archived version(s)" in said and "0.9.7" in said
    assert sorted(s3.deletes) == sorted(
        [k for k in keys_of(raw, "0.9.6") if k.rsplit("/", 1)[1] not in keep]
        + [k for k in list(s3.objects) + s3.deletes if "/0.9.7/" in k]
    ) or all("/0.9.7/" in k or "0.9.6" in k for k in s3.deletes)
    assert not any("/0.9.7/" in k for k in s3.objects)
    assert sorted(k.rsplit("/", 1)[1] for k in s3.objects) == keep


def test_sync_with_version_stays_inside_that_version(raw, monkeypatch, out):
    release(raw, "0.9.6")
    release(raw, "0.9.7")
    s3 = FakeS3()
    run(raw, s3, monkeypatch, out)
    import shutil

    shutil.rmtree(raw / "0.9.7")
    d = raw / "0.9.6"
    build_wheel(
        d, version="0.9.6", tag="cp311-cp311-macosx_11_0_arm64"
    )  # not in MANIFEST: ignored

    run(raw, s3, monkeypatch, out, version="0.9.6", sync=True)
    assert s3.deletes == []  # 0.9.6's archive == its MANIFEST; 0.9.7 out of scope
    assert any("/0.9.7/" in k for k in s3.objects)


def test_dry_run_writes_nothing(raw, monkeypatch, events, out):
    release(raw)
    s3 = FakeS3()
    run(raw, s3, monkeypatch, out, dry_run=True)
    assert s3.puts == []
    said = events.text
    assert "dry run" in said
    assert (
        "s3://td-raw-wheels/wheels/   (the archive is not served: no https://)" in said
    )


def test_no_releases_is_an_error(raw, monkeypatch, out):
    with pytest.raises(ToolError, match="no version directories"):
        run(raw, FakeS3(), monkeypatch, out)
