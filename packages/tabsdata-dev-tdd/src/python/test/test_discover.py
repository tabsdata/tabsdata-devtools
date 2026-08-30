#
# Copyright 2026 Tabsdata Inc.
#

from tabsdata_dev.tdd import discover, paths


def test_repo_root_is_found_when_editable():
    root = paths.repo_root()
    assert root is not None
    assert (root / "packages" / "tabsdata-dev-tdd").is_dir()


def test_bin_reqs_ignores_comments_and_blanks(tmp_path):
    f = tmp_path / "bin-reqs.txt"
    f.write_text("# a comment\n\ngit\nrg  # trailing\n")
    assert discover.parse_bin_reqs(f) == ["git", "rg"]


def test_bin_reqs_rejects_a_path(tmp_path):
    f = tmp_path / "bin-reqs.txt"
    f.write_text("/usr/bin/git\n")
    try:
        discover.parse_bin_reqs(f)
    except discover.LayoutError:
        return
    raise AssertionError("expected LayoutError")


def test_discover_real_repo():
    found = discover.discover(paths.repo_root())
    assert found["tools"]["demo-exe1"]["toolset"] == "demo-env1"
    assert found["tools"]["demo-exe2"]["toolset"] == "demo-env2"


def test_demo_marker_reaches_the_catalog_entry():
    found = discover.discover(paths.repo_root())
    assert found["tools"]["demo-exe1"]["demo"] is True


def test_tools_default_to_not_demo(tmp_path):
    pkg = tmp_path / "packages" / "tabsdata-dev-tool-real"
    pkg.mkdir(parents=True)
    (pkg / "pyproject.toml").write_text(
        '[project]\nname = "tabsdata-dev-tool-real"\n'
        'dependencies = ["tabsdata-dev-deps-x"]\n'
        '[project.scripts]\nreal = "m:main"\n'
    )
    (tmp_path / "packages" / "tabsdata-dev-deps-x").mkdir()
    found = discover.discover(tmp_path)
    assert found["tools"]["real"]["demo"] is False


def test_shell_commands_and_their_reqs_reach_the_catalog():
    found = discover.discover(paths.repo_root())
    shell = found["shell"]
    # common.sh needs jq and awk, so every shell command does; own reqs follow.
    assert shell["tdd-env"]["demo"] is False and shell["tdd-env"]["reqs"] == [
        "jq",
        "awk",
    ]
    assert shell["demo-fn1"]["demo"] is True
    assert shell["demo-fn1"]["reqs"] == ["jq", "awk", "whoami", "hostname"]
    assert shell["demo-fn2"]["reqs"] == ["jq", "awk", "uname", "date"]


def _shell_fixture(tmp_path, tool_name):
    scripts = tmp_path / "packages" / "tabsdata-dev-shell" / "scripts" / "unix"
    scripts.mkdir(parents=True)
    (scripts / "x.sh").write_text('tdd_fn_register x "an x"\ntddfn_x() { :; }\n')
    pkg = tmp_path / "packages" / f"tabsdata-dev-tool-{tool_name}"
    pkg.mkdir()
    (pkg / "pyproject.toml").write_text(
        f'[project]\nname = "tabsdata-dev-tool-{tool_name}"\n'
        'dependencies = ["tabsdata-dev-deps-d"]\n'
        f'[project.scripts]\n{tool_name} = "m:main"\n'
    )
    (tmp_path / "packages" / "tabsdata-dev-deps-d").mkdir()
    return scripts


def test_a_tool_cannot_take_a_shell_command_name(tmp_path):
    _shell_fixture(tmp_path, "x")
    try:
        discover.discover(tmp_path)
    except discover.LayoutError as exc:
        assert "already a shell command" in str(exc)
        return
    raise AssertionError("expected LayoutError")


def test_a_stray_bin_reqs_without_a_script_is_an_error(tmp_path):
    scripts = _shell_fixture(tmp_path, "y")
    (scripts / "ghost.bin-reqs.txt").write_text("git\n")
    try:
        discover.discover(tmp_path)
    except discover.LayoutError as exc:
        assert "ghost.sh" in str(exc)
        return
    raise AssertionError("expected LayoutError")


def test_every_tool_and_shell_command_has_a_design_doc():
    """Each Python tool package carries DESIGN.md beside its pyproject; each shell
    command a <name>.design.md beside its script; both with the house header and
    something to say (the how-to guides make writing one a step)."""
    root = paths.repo_root()
    assert root is not None
    docs = [p / "DESIGN.md" for p in (root / "packages").glob("tabsdata-dev-tool-*")]
    docs += [p / "DESIGN.md" for p in (root / "packages").glob("tabsdata-dev-common-*")]
    docs += [
        root / "packages/tabsdata-dev-tdd/DESIGN.md",
        root / "packages/tabsdata-dev-shell/DESIGN.md",
    ]
    scripts = root / "packages/tabsdata-dev-shell/scripts/unix"
    docs += [
        s.with_name(s.name[: -len(".sh")] + ".design.md")
        for s in scripts.glob("*.sh")
        if s.name != "common.sh"
    ]
    missing = [str(d.relative_to(root)) for d in docs if not d.is_file()]
    assert not missing, f"design docs missing: {missing}"
    for d in docs:
        text = d.read_text()
        assert text.startswith("<!--\nCopyright 2026 Tabsdata Inc.\n-->"), d
        assert len(text.splitlines()) >= 6, f"{d} says nothing"
