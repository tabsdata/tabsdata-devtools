#
# Copyright 2026 Tabsdata Inc.
#

"""Config loading (including the policy guard) and the git release check."""

from __future__ import annotations

import subprocess

import pytest
from tabsdata_dev.common.core.errors import ToolError

from tabsdata_dev.tool.pypi import config as config_mod
from tabsdata_dev.tool.pypi.git import assert_committed_and_pushed


@pytest.fixture
def good(resource_folder) -> str:
    """A lanes.yaml with both lanes the policy knows, staging and prod."""
    return (resource_folder / "lanes.yaml").read_text()


def write(tmp_path, text):
    p = tmp_path / "lanes.yaml"
    p.write_text(text)
    return p


# --------------------------------------------------------------------- config


def test_loads_lanes_and_keys(tmp_path, good):
    cfg = config_mod.load(write(tmp_path, good))
    assert cfg.region == "us-east-1"
    assert cfg.release_ref == "origin/main"
    assert cfg.lane("prod").key("simple/index.html") == "pypi/simple/index.html"
    assert cfg.archive.key("0.9.6", "x.whl") == "wheels/0.9.6/x.whl"


def test_policy_is_attached_from_code_not_yaml(tmp_path, good):
    cfg = config_mod.load(write(tmp_path, good))
    assert cfg.lane("prod").policy.require_archived is True
    assert cfg.lane("prod").policy.require_pushed is True
    assert cfg.lane("prod").policy.require_yes is True
    assert cfg.lane("staging").policy.require_archived is False
    assert cfg.lane("staging").policy.require_pushed is False


def test_a_lane_without_a_policy_is_rejected(tmp_path, good, resource_folder):
    text = good + (resource_folder / "wild-lane.yaml").read_text()
    with pytest.raises(ToolError, match="no policy in POLICY"):
        config_mod.load(write(tmp_path, text))


def test_a_missing_lane_is_rejected(tmp_path, good):
    text = good.split("  prod:")[0]
    with pytest.raises(ToolError, match="missing lane"):
        config_mod.load(write(tmp_path, text))


def test_unknown_lane_lookup_lists_what_exists(tmp_path, good):
    cfg = config_mod.load(write(tmp_path, good))
    with pytest.raises(ToolError, match="unknown lane"):
        cfg.lane("nope")


def test_missing_config_file_says_where_to_run_from(tmp_path):
    with pytest.raises(ToolError, match="pypi/ directory"):
        config_mod.load(tmp_path / "absent.yaml")


# ------------------------------------------------------------------------ git


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A local clone with a real 'origin', so the ancestry check is meaningful."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True)

    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(origin), str(work)], check=True)
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "Test")

    (work / "pypi-wheels").mkdir()
    (work / "config").mkdir()
    (work / "pypi-wheels" / "keep").write_text("x")
    git(work, "add", "-A")
    git(work, "commit", "-m", "initial")
    git(work, "push", "origin", "main:main")

    monkeypatch.chdir(work)
    return work


PATHS = ["pypi-wheels", "config"]


def test_clean_and_pushed_passes(repo):
    head = assert_committed_and_pushed(PATHS, "origin/main")
    assert len(head) == 40


def test_uncommitted_change_is_rejected(repo):
    (repo / "pypi-wheels" / "keep").write_text("modified")
    with pytest.raises(ToolError, match="uncommitted changes"):
        assert_committed_and_pushed(PATHS, "origin/main")


def test_untracked_sidecar_is_rejected(repo):
    (repo / "pypi-wheels" / "new.json").write_text("{}")
    with pytest.raises(ToolError, match="uncommitted changes"):
        assert_committed_and_pushed(PATHS, "origin/main")


def test_config_changes_are_guarded_too(repo):
    (repo / "config" / "lanes.yaml").write_text("account: 'x'\n")
    with pytest.raises(ToolError, match="uncommitted changes"):
        assert_committed_and_pushed(PATHS, "origin/main")


def test_committed_but_unpushed_is_rejected(repo):
    (repo / "pypi-wheels" / "keep").write_text("modified")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "local only")
    with pytest.raises(ToolError, match="not reachable from origin/main"):
        assert_committed_and_pushed(PATHS, "origin/main")


def test_pushing_makes_it_pass(repo):
    (repo / "pypi-wheels" / "keep").write_text("modified")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "release")
    git(repo, "push", "origin", "main:main")
    assert_committed_and_pushed(PATHS, "origin/main")


def test_ancestry_not_equality__ref_may_have_moved_on(repo, tmp_path):
    """A release commit stays valid after someone else pushes on top of it."""
    (repo / "pypi-wheels" / "keep").write_text("release")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "release")
    git(repo, "push", "origin", "main:main")
    released = git(repo, "rev-parse", "HEAD").stdout.strip()

    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(tmp_path / "origin.git"), str(other)], check=True
    )
    git(other, "config", "user.email", "o@example.com")
    git(other, "config", "user.name", "Other")
    (other / "unrelated.txt").write_text("later work")
    git(other, "add", "-A")
    git(other, "commit", "-m", "later")
    git(other, "push", "origin", "main:main")

    # our HEAD is behind origin/main now, but still an ancestor of it
    assert assert_committed_and_pushed(PATHS, "origin/main") == released


def test_missing_release_ref_is_rejected(repo):
    with pytest.raises(ToolError, match="does not exist"):
        assert_committed_and_pushed(PATHS, "origin/nonexistent")
