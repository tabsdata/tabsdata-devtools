#
# Copyright 2026 Tabsdata Inc.
#

"""promote, check, and yanked.yaml: the local half of the pipeline after generate."""

from __future__ import annotations

import json
import os

import pytest
from tabsdata_dev.common.core.errors import ToolError
from conftest import FakeS3, make_cfg, make_lane, release

from tabsdata_dev.tool.pypi import check as check_mod
from tabsdata_dev.tool.pypi import yanked
from tabsdata_dev.tool.pypi.check import check_local
from tabsdata_dev.tool.pypi.generate import generate
from tabsdata_dev.tool.pypi.promote import promote
from tabsdata_dev.tool.pypi.tree import (
    INDEX,
    YANKED,
    clear_tree,
    load_index,
    tree_files,
    wheel_path,
)

LINUX, MAC = "cp311-cp311-manylinux_2_28_x86_64", "cp311-cp311-macosx_11_0_arm64"


def yanks(tree):
    return {d.filename: d.yanked for d in load_index(tree) if d.yanked}


# -------------------------------------------------------------------- promote


def test_promote_copies_staging_to_prod_exactly(raw, staging, prod, out):
    release(raw, "0.9.6", [LINUX, MAC])
    generate(raw, staging, out)

    promote(staging, prod, out)

    assert tree_files(prod).keys() == tree_files(staging).keys()
    for rel, p in tree_files(staging).items():
        assert (prod / rel).read_bytes() == p.read_bytes()
    assert load_index(prod) == load_index(staging)
    d = load_index(prod)[0]  # wheels are hardlinked, not copied
    assert (
        os.stat(wheel_path(prod, d.filename)).st_ino
        == os.stat(wheel_path(staging, d.filename)).st_ino
    )


def test_promote_starts_from_scratch(raw, staging, prod, out):
    release(raw)
    generate(raw, staging, out)
    promote(staging, prod, out)
    stale = prod / "files" / "old-0.1-py3-none-any.whl"
    stale.write_bytes(b"old")

    promote(staging, prod, out)
    assert not stale.exists()


def test_promote_refuses_an_incomplete_staging(raw, staging, prod, out):
    release(raw)
    generate(raw, staging, out)
    (staging / INDEX).unlink()
    with pytest.raises(ToolError, match="not a complete tree"):
        promote(staging, prod, out)
    assert not (prod / INDEX).exists()


# ---------------------------------------------------------------------- check


def test_check_local_ok(raw, staging, events, out):
    release(raw, "0.9.6")
    generate(raw, staging, out)
    check_local(staging, out)
    assert "distribution(s), release(s)" in events.text


def test_check_local_fails_without_an_index(staging, out):
    with pytest.raises(ToolError, match="index.json is missing"):
        check_local(staging, out)


def test_check_local_fails_when_the_index_lists_a_missing_file(raw, staging, out):
    release(raw)
    generate(raw, staging, out)
    wheel_path(staging, load_index(staging)[0].filename).unlink()
    with pytest.raises(ToolError, match="not on disk"):
        check_local(staging, out)


def test_check_remote(monkeypatch, events, out):
    s3 = FakeS3()
    monkeypatch.setattr(check_mod.boto3, "client", lambda *a, **k: s3)
    lane = make_lane()

    with pytest.raises(ToolError, match="index.json is missing"):
        check_mod.check_remote(make_cfg(), lane, out)

    s3.put_object(
        Bucket=lane.bucket,
        Key="pypi/index.json",
        Body=b"{}",
        Metadata={"sha256": "ab" * 32},
    )
    check_mod.check_remote(make_cfg(), lane, out)
    said = events.text
    assert "s3://td-pypi-staging/pypi/index.json" in said
    assert "sha256 abababababab" in said


# ---------------------------------------------------------------- yanked.yaml


@pytest.mark.parametrize(
    "mask, expected",
    [
        ("tabsdata-0.9.6-*", ["0.9.6/" + LINUX, "0.9.6/" + MAC]),
        ("tabsdata_agent-*-*", []),  # other project, either spelling
        ("tabsdata-*-macosx_11_0_arm64", ["0.9.6/" + MAC, "0.9.7/" + MAC]),
        ("*-0.9.7-*", ["0.9.7/" + LINUX, "0.9.7/" + MAC]),
        ("*-*-manylinux_*", ["0.9.6/" + LINUX, "0.9.7/" + LINUX]),
        ("TabsData-0.9.6-manylinux_2_28_x86_64", ["0.9.6/" + LINUX]),  # name normalized
    ],
)
def test_mask_matching(raw, staging, mask, expected, out):
    release(raw, "0.9.6", [LINUX, MAC])
    release(raw, "0.9.7", [LINUX, MAC])
    generate(raw, staging, out)
    hits = [
        f"{d.version}/{d.filename.split('-', 2)[2][:-4]}"
        for d in load_index(staging)
        if yanked.matches(d, mask)
    ]
    assert sorted(hits) == sorted(expected)


@pytest.mark.parametrize("bad", ["tabsdata-0.9.6", "tabsdata--*", "just-two"])
def test_malformed_masks_are_refused(raw, staging, bad, out):
    release(raw)
    staging.mkdir(parents=True)
    (staging / YANKED).write_text(f"- {bad}\n")
    with pytest.raises(ToolError, match="not a <PACKAGE>-<VERSION>-<OS> mask"):
        generate(raw, staging, out)


def test_not_a_list_is_refused(raw, staging, out):
    release(raw)
    staging.mkdir(parents=True)
    (staging / YANKED).write_text("yanked:\n  - tabsdata-*-*\n")
    with pytest.raises(ToolError, match="expected a list of masks"):
        generate(raw, staging, out)


def test_generate_creates_the_file_with_its_header_and_never_rewrites_it(
    raw, staging, out
):
    release(raw)
    generate(raw, staging, out)
    text = (staging / YANKED).read_text()
    assert text.startswith("# Yanked files for this tree (PEP 592).")
    assert "<PACKAGE>-<VERSION>-<OS>" in text
    assert yanks(staging) == {}

    (staging / YANKED).write_text(text + "- tabsdata-0.9.6-*\n")
    generate(raw, staging, out)
    assert (staging / YANKED).read_text() == text + "- tabsdata-0.9.6-*\n"  # untouched
    assert set(yanks(staging).values()) == {"tabsdata-0.9.6-*"}


def test_clear_tree_keeps_yanked_yaml_only(raw, staging, out):
    release(raw)
    generate(raw, staging, out)
    (staging / YANKED).write_text("- tabsdata-0.9.6-*\n")
    clear_tree(staging)
    assert sorted(p.name for p in staging.iterdir()) == [YANKED]
    assert (staging / YANKED).read_text() == "- tabsdata-0.9.6-*\n"


def test_generate_applies_staging_masks_to_pages_and_index(raw, staging, out):
    release(raw, "0.9.6")
    release(raw, "0.9.7")
    staging.mkdir(parents=True)
    (staging / YANKED).write_text("- tabsdata-0.9.6-*\n")

    generate(raw, staging, out)

    page = (staging / "simple" / "tabsdata" / "index.html").read_text()
    assert page.count('data-yanked="tabsdata-0.9.6-*"') == 1
    doc = json.loads((staging / INDEX).read_text())
    assert {f["version"]: f["yanked"] for f in doc["files"]} == {
        "0.9.6": "tabsdata-0.9.6-*",
        "0.9.7": None,
    }
    assert "yanked.yaml" not in tree_files(staging)  # never pushed

    # removing the mask un-yanks: the file is the whole truth
    (staging / YANKED).write_text("")
    generate(raw, staging, out)
    assert yanks(staging) == {}


def test_promote_applies_prods_own_masks_not_stagings(raw, staging, prod, out):
    release(raw, "0.9.6")
    release(raw, "0.9.7")
    staging.mkdir(parents=True)
    (staging / YANKED).write_text("- tabsdata-0.9.6-*\n")
    generate(raw, staging, out)
    prod.mkdir(parents=True)
    (prod / YANKED).write_text("- tabsdata-0.9.7-*\n")

    promote(staging, prod, out)

    assert set(yanks(staging).values()) == {"tabsdata-0.9.6-*"}
    assert set(yanks(prod).values()) == {"tabsdata-0.9.7-*"}
    assert (prod / YANKED).read_text() == "- tabsdata-0.9.7-*\n"  # untouched
    assert (
        'data-yanked="tabsdata-0.9.7-*"'
        in (prod / "simple" / "tabsdata" / "index.html").read_text()
    )
    assert (
        "tabsdata-0.9.6-*"
        not in (prod / "simple" / "tabsdata" / "index.html").read_text()
    )


def test_promote_without_a_prod_list_yanks_nothing_and_creates_the_file(
    raw, staging, prod, out
):
    release(raw, "0.9.6")
    staging.mkdir(parents=True)
    (staging / YANKED).write_text("- tabsdata-0.9.6-*\n")
    generate(raw, staging, out)

    promote(staging, prod, out)
    assert yanks(prod) == {}
    assert (prod / YANKED).read_text().startswith("# Yanked files")
