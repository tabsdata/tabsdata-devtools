#
# Copyright 2026 Tabsdata Inc.
#

"""The guard: every subcommand runs at the root of a clone of `pypi-repo`.

The three refusals are the point -- `tdi-pypi` had none of them and found out at
the first missing file -- and so is the remote comparison, which must see two
spellings of one remote as one remote and two different remotes as two.
"""

from __future__ import annotations

import subprocess

import pytest
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool.pypi import repo

#: This module tests the guard, so conftest must not patch it away.
pytestmark = pytest.mark.real_repo_guard

REMOTE = "git@github.com:tabsdata/tabsdata-pypi.git"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def clone(path, remote: str | None = REMOTE):
    """A repository with one commit, and `remote` as origin."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    (path / "README").write_text("x")
    git(path, "add", "README")
    git(path, "commit", "-qm", "one")
    if remote:
        git(path, "remote", "add", "origin", remote)
    return path


@pytest.mark.parametrize(
    "spelling",
    [
        "git@github.com:tabsdata/tabsdata-pypi.git",
        "git@github.com:tabsdata/tabsdata-pypi",
        "https://github.com/tabsdata/tabsdata-pypi.git",
        "https://github.com/tabsdata/tabsdata-pypi",
        "https://github.com/tabsdata/tabsdata-pypi/",
        "ssh://git@github.com/tabsdata/tabsdata-pypi.git",
        "ssh://git@github.com:22/tabsdata/tabsdata-pypi.git",
        "GIT@GitHub.com:Tabsdata/Tabsdata-PyPI.git",
    ],
)
def test_every_spelling_of_one_remote_is_that_remote(spelling):
    assert repo.normalize(spelling) == "github.com/tabsdata/tabsdata-pypi"


@pytest.mark.parametrize(
    "other",
    [
        "git@github.com:tabsdata/tabsdata-infra.git",  # another repo
        "git@gitlab.com:tabsdata/tabsdata-pypi.git",  # another host
        "git@github.com:someone/tabsdata-pypi.git",  # another org
    ],
)
def test_a_different_remote_stays_different(other):
    """Normalizing must not be so eager that it collapses two repositories: the
    host and the whole path are what tells them apart."""
    assert repo.normalize(other) != "github.com/tabsdata/tabsdata-pypi"


def test_no_pypi_repo_says_how_to_set_one(tmp_path, monkeypatch):
    monkeypatch.chdir(clone(tmp_path / "c"))
    with pytest.raises(ToolError, match="no pypi-repo configured"):
        repo.require_root(None)


def test_outside_a_repository_is_refused(tmp_path, monkeypatch):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    monkeypatch.chdir(plain)
    with pytest.raises(ToolError, match="not inside a git repository"):
        repo.require_root(REMOTE)


def test_below_the_root_is_refused_and_says_where_the_root_is(tmp_path, monkeypatch):
    """The paths the tool uses are relative, so a subdirectory is not a smaller
    version of the root -- it is the wrong place entirely."""
    root = clone(tmp_path / "c")
    sub = root / "pypi-wheels"
    sub.mkdir()
    monkeypatch.chdir(sub)
    with pytest.raises(ToolError, match="runs at the root of the repository") as exc:
        repo.require_root(REMOTE)
    assert str(root) in str(exc.value)


def test_the_wrong_clone_is_refused_and_lists_what_it_found(tmp_path, monkeypatch):
    root = clone(tmp_path / "c", "git@github.com:tabsdata/tabsdata-infra.git")
    monkeypatch.chdir(root)
    with pytest.raises(ToolError, match="clone of a different repository") as exc:
        repo.require_root(REMOTE)
    assert "tabsdata-infra" in str(exc.value)  # what is here, not just what is wanted


def test_a_repository_with_no_remotes_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(clone(tmp_path / "c", remote=None))
    with pytest.raises(ToolError, match="no remotes"):
        repo.require_root(REMOTE)


def test_the_root_of_the_right_clone_passes(tmp_path, monkeypatch):
    root = clone(tmp_path / "c")
    monkeypatch.chdir(root)
    assert repo.require_root(REMOTE).resolve() == root.resolve()
    # ... whichever way either side spells the remote
    assert repo.require_root("https://github.com/tabsdata/tabsdata-pypi").resolve()


def test_any_remote_counts_not_only_origin(tmp_path, monkeypatch):
    """A fork has `origin` pointing at the fork and `upstream` at the real one;
    it is still a clone of the real one."""
    root = clone(tmp_path / "c", "git@github.com:someone/tabsdata-pypi.git")
    git(root, "remote", "add", "upstream", REMOTE)
    monkeypatch.chdir(root)
    assert repo.require_root(REMOTE).resolve() == root.resolve()
