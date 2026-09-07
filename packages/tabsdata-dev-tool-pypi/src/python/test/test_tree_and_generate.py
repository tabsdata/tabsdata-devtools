#
# Copyright 2026 Tabsdata Inc.
#

"""MANIFEST semantics, and generate: from scratch, index.json last."""

from __future__ import annotations

import json
import os

import pytest
from tabsdata_dev.common.core.errors import ToolError
from conftest import build_wheel, release, write_manifest

from tabsdata_dev.tool.pypi.generate import generate
from tabsdata_dev.tool.pypi.tree import (
    INDEX,
    load_index,
    read_index,
    read_manifest,
    tree_files,
    wheel_path,
)

# ------------------------------------------------------------------- MANIFEST


def test_manifest_is_required(raw):
    d = raw / "0.9.6"
    build_wheel(d)
    with pytest.raises(ToolError, match="MANIFEST is missing"):
        read_manifest(d)


def test_manifest_lists_what_is_processed_and_comments_are_ignored(raw):
    d = raw / "0.9.6"
    a = build_wheel(d, tag="cp311-cp311-manylinux_2_28_x86_64")
    build_wheel(d, tag="cp311-cp311-macosx_11_0_arm64")  # present, not listed
    (d / "MANIFEST").write_text(f"# only linux\n{a.name}   # trailing\n\n")
    assert read_manifest(d) == [a.name]


def test_manifest_naming_an_absent_file_is_fatal(raw):
    d = raw / "0.9.6"
    build_wheel(d)
    write_manifest(d, ["ghost-0.9.6-py3-none-any.whl"])
    with pytest.raises(ToolError, match="not present"):
        read_manifest(d)


def test_manifest_duplicates_and_empty_are_fatal(raw):
    d = raw / "0.9.6"
    w = build_wheel(d)
    write_manifest(d, [w.name, w.name])
    with pytest.raises(ToolError, match="duplicates"):
        read_manifest(d)
    (d / "MANIFEST").write_text("# nothing\n")
    with pytest.raises(ToolError, match="lists no files"):
        read_manifest(d)


# ------------------------------------------------------------------- generate


def test_generate_builds_the_whole_tree_and_writes_the_index_last(
    raw, staging, events, out
):
    release(
        raw,
        "0.9.6",
        ["cp311-cp311-manylinux_2_28_x86_64", "cp311-cp311-macosx_11_0_arm64"],
    )
    release(raw, "0.9.7")

    generate(raw, staging, out)

    dists = load_index(staging)
    assert [d.release for d in dists] == ["0.9.6", "0.9.6", "0.9.7"]
    for d in dists:
        assert wheel_path(staging, d.filename).exists()
        assert (staging / "files" / f"{d.filename}.metadata").exists()
    files = tree_files(staging)
    assert "index.html" in files and "simple/index.html" in files
    assert "simple/tabsdata/index.html" in files
    assert INDEX not in files  # tree_files leaves the index to its callers

    doc = json.loads((staging / INDEX).read_text())
    assert doc["format"] == 1 and doc["releases"] == ["0.9.6", "0.9.7"]
    assert [f["filename"] for f in doc["files"]] == sorted(
        f["filename"] for f in doc["files"]
    )
    # the index is the newest file in the tree
    newest = max(p.stat().st_mtime_ns for p in files.values())
    assert (staging / INDEX).stat().st_mtime_ns >= newest
    assert "tree complete" in events.text


def test_generate_hardlinks_wheels(raw, staging, out):
    d = release(raw)
    generate(raw, staging, out)
    whl = next(d.glob("*.whl"))
    assert os.stat(whl).st_ino == os.stat(wheel_path(staging, whl.name)).st_ino


def test_generate_starts_from_scratch(raw, staging, out):
    release(raw, "0.9.6")
    generate(raw, staging, out)
    stale = staging / "files" / "stale-0.1-py3-none-any.whl"
    stale.write_bytes(b"left over")
    (staging / "simple" / "stale" / "index.html").parent.mkdir()
    (staging / "simple" / "stale" / "index.html").write_text("stale")
    old_index = (staging / INDEX).read_text()

    generate(raw, staging, out)
    assert not stale.exists()
    assert not (staging / "simple" / "stale").exists()
    assert (
        json.loads((staging / INDEX).read_text())["files"]
        == json.loads(old_index)["files"]
    )


def test_generate_refuses_before_deleting_when_a_manifest_is_bad(raw, staging, out):
    release(raw, "0.9.6")
    generate(raw, staging, out)
    d = raw / "0.9.7"
    build_wheel(d, version="0.9.7")
    write_manifest(d, ["ghost-0.9.7-py3-none-any.whl"])

    with pytest.raises(ToolError, match="not present"):
        generate(raw, staging, out)
    assert read_index(staging) is not None  # the good tree was left alone


def test_generate_refuses_a_filename_claimed_by_two_releases(raw, staging, out):
    release(raw, "0.9.6")
    # the same wheel filename staged again under another release directory
    src = next((raw / "0.9.6").glob("*.whl"))
    other = raw / "0.9.6-rebuilt"
    other.mkdir()
    (other / src.name).write_bytes(src.read_bytes())
    write_manifest(other)

    with pytest.raises(ToolError, match="one release only"):
        generate(raw, staging, out)
    assert read_index(staging) is None  # nothing was written


def test_generate_with_no_releases_is_an_error(raw, staging, out):
    with pytest.raises(ToolError, match="no version directories"):
        generate(raw, staging, out)


def test_load_index_says_what_a_missing_index_means(staging):
    with pytest.raises(ToolError, match="not a complete tree"):
        load_index(staging)
