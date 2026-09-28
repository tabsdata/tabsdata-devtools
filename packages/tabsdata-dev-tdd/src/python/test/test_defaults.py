#
# Copyright 2026 Tabsdata Inc.
#

import pathlib

from tabsdata_dev.tdd import defaults


def _config(root: pathlib.Path, command: str, text: str) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{command}.toml"
    path.write_text(text)
    return path


def test_no_file_means_none(tmp_path):
    assert defaults.resolve(tmp_path, "venv", ["create"]) is None


def test_a_file_without_options_means_none(tmp_path):
    _config(tmp_path, "gsx", '[repos."o/n"]\nlabels = ["bug"]\n')
    assert defaults.resolve(tmp_path, "gsx", ["apply"]) is None


def test_defaults_are_appended_and_typed_options_win(tmp_path):
    _config(tmp_path, "venv", '[options]\ntype = "uv"\npython = "3.11"\n')
    merged, used = defaults.resolve(tmp_path, "venv", ["create", "--type", "conda"])
    assert merged == ["create", "--type", "conda", "--python", "3.11"]
    assert used == ["venv.toml [options]"]


def test_after_a_double_dash_nothing_is_an_option(tmp_path):
    _config(tmp_path, "mexe", '[options]\noutput = "on-completion"\n')
    argv = ["--dirs", "a", "--", "git", "log", "--output", "x"]
    merged, _ = defaults.resolve(tmp_path, "mexe", argv)
    assert merged == [
        "--dirs", "a", "--output", "on-completion", "--", "git", "log", "--output", "x",
    ]  # fmt: skip


def test_an_action_table_beats_the_command_table(tmp_path):
    _config(
        tmp_path,
        "venv",
        '[options]\ntype = "uv"\npython = "3.11"\n\n[options.create]\ntype = "conda"\n',
    )
    merged, used = defaults.resolve(tmp_path, "venv", ["create", "--name", "x"])
    assert merged == ["create", "--name", "x", "--type", "conda", "--python", "3.11"]
    assert used == ["venv.toml [options.create]", "venv.toml [options]"]
    # another action gets the command table only
    merged, _ = defaults.resolve(tmp_path, "venv", ["list"])
    assert merged == ["list", "--type", "uv", "--python", "3.11"]


def test_a_key_is_the_option_with_underscores_for_dashes(tmp_path):
    _config(tmp_path, "gsx", "[options.submit]\nno_defaults = true\ndry_run = false\n")
    merged, _ = defaults.resolve(tmp_path, "gsx", ["submit"])
    # true is the flag's presence; false contributes nothing, as on a command line
    assert merged == ["submit", "--no-defaults"]


def test_a_list_repeats_the_option(tmp_path):
    _config(tmp_path, "t", '[options]\nsuite = ["a", "b"]\n')
    merged, _ = defaults.resolve(tmp_path, "t", [])
    assert merged == ["--suite", "a", "--suite", "b"]


def test_short_forms_count_as_typed(tmp_path):
    _config(tmp_path, "demo", "[options]\nverbose = true\nforce = true\n")
    merged, _ = defaults.resolve(tmp_path, "demo", ["-v"])
    assert merged == ["-v", "--force"]
    # with both typed there is nothing left to add, and nothing is what comes
    # back -- the caller keeps the line as typed, with no `resolved:` noise
    assert defaults.resolve(tmp_path, "demo", ["-f", "-v"]) is None


def test_hyphenated_command_names_are_their_own_files(tmp_path):
    _config(tmp_path, "_tdd-env", '[options.activate]\ntoolset = "systems"\n')
    merged, used = defaults.resolve(tmp_path, "_tdd-env", ["activate"])
    assert merged == ["activate", "--toolset", "systems"]
    assert used == ["_tdd-env.toml [options.activate]"]


def test_a_file_that_is_not_toml_is_an_error(tmp_path):
    _config(tmp_path, "t", "options = [\n")
    try:
        defaults.resolve(tmp_path, "t", [])
    except defaults.DefaultsError as exc:
        assert "t.toml" in str(exc)
        return
    raise AssertionError("expected DefaultsError")


def test_options_must_be_a_table(tmp_path):
    _config(tmp_path, "t", "options = 3\n")
    try:
        defaults.resolve(tmp_path, "t", [])
    except defaults.DefaultsError as exc:
        assert "must be a table" in str(exc)
        return
    raise AssertionError("expected DefaultsError")


def test_the_argv_mapping_is_the_twin_of_the_common_core_one():
    # common-core is not importable here (this package has no dependencies), so
    # the twin is compared as source: the two bodies must stay identical.
    import inspect

    ours = inspect.getsource(defaults.to_argv)
    root = pathlib.Path(__file__).resolve().parents[5]
    theirs = (
        root
        / "packages/tabsdata-dev-common-core/src/python/main/tabsdata_dev"
        / "common/core/config.py"
    ).read_text()
    body = theirs.split("def to_argv(name: str, value: Any) -> list[str]:", 1)[1]
    body = body.split("\n\n\n", 1)[0]
    assert body.strip().splitlines()[-6:] == ours.strip().splitlines()[-6:]
