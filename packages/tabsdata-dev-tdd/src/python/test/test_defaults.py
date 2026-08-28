#
# Copyright 2026 Tabsdata Inc.
#

import pathlib

from tabsdata_dev.tdd import defaults


def _dir(tmp_path: pathlib.Path, **files: str) -> pathlib.Path:
    d = tmp_path / defaults.DIR_NAME
    d.mkdir()
    for name, text in files.items():
        (d / f"{name}.txt").write_text(text)
    return tmp_path


def test_no_file_means_none(tmp_path):
    assert defaults.resolve(_dir(tmp_path), "venv", ["create"]) is None


def test_defaults_are_appended_and_typed_options_win(tmp_path):
    root = _dir(tmp_path, venv="--type uv\n--python=3.12\n# a comment\n\n--verbose\n")
    merged, used = defaults.resolve(
        root, "venv", ["create", "--name", "x", "--type=conda"]
    )
    assert merged == [
        "create",
        "--name",
        "x",
        "--type=conda",
        "--python=3.12",
        "--verbose",
    ]
    assert used == ["venv.txt"]


def test_action_file_beats_command_file(tmp_path):
    root = _dir(
        tmp_path, venv="--type uv\n--python 3.11\n", venv_create="--type conda\n"
    )
    merged, used = defaults.resolve(root, "venv", ["create", "--name", "x"])
    assert merged == ["create", "--name", "x", "--type", "conda", "--python", "3.11"]
    assert used == ["venv.txt", "venv_create.txt"]


def test_hyphenated_command_names_stay_unambiguous(tmp_path):
    root = _dir(tmp_path, **{"tdd-env_activate": "--toolset demo-env1\n"})
    merged, used = defaults.resolve(root, "tdd-env", ["activate"])
    assert merged == ["activate", "--toolset", "demo-env1"]
    assert used == ["tdd-env_activate.txt"]


def test_short_forms_count_as_typed(tmp_path):
    root = _dir(tmp_path, demo="--verbose\n--format json\n")
    merged, _ = defaults.resolve(root, "demo", ["-v"])
    assert merged == ["-v", "--format", "json"]


def test_a_hash_in_a_value_is_not_a_comment(tmp_path):
    root = _dir(tmp_path, t="--tag a#b  # but this is\n")
    merged, _ = defaults.resolve(root, "t", [])
    assert merged == ["--tag", "a#b"]


def test_a_line_that_is_not_an_option_is_an_error(tmp_path):
    root = _dir(tmp_path, t="uv\n")
    try:
        defaults.resolve(root, "t", [])
    except defaults.DefaultsError as exc:
        assert "t.txt:1" in str(exc)
        return
    raise AssertionError("expected DefaultsError")


def test_two_options_on_one_line_is_an_error(tmp_path):
    root = _dir(tmp_path, venv_create="--python 3.12.13 --type conda\n")
    try:
        defaults.resolve(root, "venv", ["create"])
    except defaults.DefaultsError as exc:
        assert "one option per line" in str(exc)
        return
    raise AssertionError("expected DefaultsError")
