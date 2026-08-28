#
# Copyright 2026 Tabsdata Inc.
#

import re

from tabsdata_dev.tdd import paths, version


def test_shipped_matches_the_repo_root_file():
    root = paths.repo_root()
    assert version.shipped() == (root / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version.shipped())


def test_current_prefers_the_stamp_in_the_tdd_dir(tmp_path):
    assert version.installed(tmp_path) is None
    assert version.current(tmp_path) == version.shipped()
    (tmp_path / "VERSION").write_text("9.9.9\n")
    assert version.installed(tmp_path) == "9.9.9"
    assert version.current(tmp_path) == "9.9.9"


def test_stamp_writes_the_shipped_version(tmp_path):
    version.stamp(tmp_path)
    assert version.installed(tmp_path) == version.shipped()
