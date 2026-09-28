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
    assert found["tools"]["km"]["toolset"] == "launchers"
    assert found["tools"]["xp"]["toolset"] == "xp"  # its own: deps-xp
    # commented out with `[tool.tdd] disabled = true`: the package is in the
    # tree and the generator does not see it
    assert "gsx" not in found["tools"]
    assert "tabsdata-dev-tool-gsx" not in found["toolsets"]["launchers"]


def test_a_disabled_tool_is_skipped_whole(tmp_path):
    pkgs = tmp_path / "packages"
    for family in discover.SHELL_FAMILIES:
        (pkgs / "tabsdata-dev-shell" / "scripts" / family).mkdir(parents=True)
    (pkgs / "tabsdata-dev-deps-d").mkdir()
    for name, marker in (("a", ""), ("b", "[tool.tdd]\ndisabled = true\n")):
        pkg = pkgs / f"tabsdata-dev-tool-{name}"
        pkg.mkdir()
        (pkg / "pyproject.toml").write_text(
            f'[project]\nname = "tabsdata-dev-tool-{name}"\n'
            'dependencies = ["tabsdata-dev-deps-d"]\n'
            f'[project.scripts]\n{name} = "m:main"\n' + marker
        )
    found = discover.discover(tmp_path)
    assert sorted(found["tools"]) == ["a"]
    assert found["toolsets"] == {"d": ["tabsdata-dev-tool-a"]}


def test_shell_commands_and_their_reqs_reach_the_catalog():
    """Requirements are per family, because the shared layers differ: common.sh
    builds its JSON with jq and lays out its help with awk, and common.ps1 needs
    neither. What a command itself shells out to is the same in both."""
    found = discover.discover(paths.repo_root())
    shell = found["shell"]
    assert shell["_tdd-env"]["reqs"]["unix"] == ["jq", "awk"]
    assert shell["_tdd-env"]["reqs"]["powershell"] == []
    assert shell["venv"]["reqs"]["unix"] == ["jq", "awk", "pyenv", "uv", "conda"]
    assert shell["venv"]["reqs"]["powershell"] == ["pyenv", "uv", "conda"]
    assert shell["venv"]["files"] == {"unix": "venv.sh", "powershell": "venv.ps1"}


def test_the_families_must_register_the_same_commands(tmp_path):
    """One command, written twice: `tdd help` reads the same in either shell, so
    a command that exists in only one half is a build failure, not a surprise at
    run time."""
    scripts = _shell_fixture(tmp_path, "z")
    (scripts.parent / "powershell" / "x.ps1").unlink()
    try:
        discover.discover(tmp_path)
    except discover.LayoutError as exc:
        assert "do not match" in str(exc) and "missing x" in str(exc)
        return
    raise AssertionError("expected LayoutError")


def test_the_families_must_agree_on_a_summary(tmp_path):
    scripts = _shell_fixture(tmp_path, "w")
    (scripts.parent / "powershell" / "x.ps1").write_text(
        'tdd_fn_register x "a different x"\nfunction tddfn_x { }\n'
    )
    try:
        discover.discover(tmp_path)
    except discover.LayoutError as exc:
        assert "summary differs" in str(exc)
        return
    raise AssertionError("expected LayoutError")


def _shell_fixture(tmp_path, tool_name):
    root = tmp_path / "packages" / "tabsdata-dev-shell" / "scripts"
    scripts = root / "unix"
    scripts.mkdir(parents=True)
    (scripts / "x.sh").write_text('tdd_fn_register x "an x"\ntddfn_x() { :; }\n')
    # the same command in the other family: the registration line is spelled
    # identically in both, which is what one regex can hold them to
    (root / "powershell").mkdir()
    (root / "powershell" / "x.ps1").write_text(
        'tdd_fn_register x "an x"\nfunction tddfn_x { }\n'
    )
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
    command a <name>.DESIGN.md beside its script; both with the house header and
    something to say (the how-to guides make writing one a step)."""
    root = paths.repo_root()
    assert root is not None
    docs = [p / "DESIGN.md" for p in (root / "packages").glob("tabsdata-dev-tool-*")]
    docs += [p / "DESIGN.md" for p in (root / "packages").glob("tabsdata-dev-common-*")]
    docs += [
        root / "packages/tabsdata-dev-tdd/DESIGN.md",
        root / "packages/tabsdata-dev-shell/DESIGN.md",
    ]
    # One design doc per command, not per family: it describes the command, and
    # it lives beside the POSIX file, which the generator treats as canonical.
    scripts = root / "packages/tabsdata-dev-shell/scripts/unix"
    docs += [
        # `<name>.design.md`, exactly: this passes on a case-insensitive
        # filesystem whatever case is written here, and fails on Linux.
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


def test_every_toolset_lock_resolves_against_pypi_alone():
    """A lock records its registry's URLs; one resolved through a developer's
    local mirror (a devpi on localhost:3141, once all four of them) installs
    only where that mirror runs. `cargo make lock` and tdd-install's sync both
    pin PyPI; this is what catches a lock made any other way."""
    import tomllib

    from tabsdata_dev.tdd import initialize

    root = paths.repo_root()
    assert root is not None
    locks = sorted((root / "packages").glob("tabsdata-dev-toolset-*/uv.lock"))
    assert locks, "no toolset locks found"
    wrong = {}
    for lock in locks:
        data = tomllib.loads(lock.read_text())
        registries = {
            p["source"]["registry"]
            for p in data.get("package", [])
            if "registry" in p.get("source", {})
        }
        if registries - {initialize.LOCK_INDEX}:
            wrong[lock.parent.name] = sorted(registries - {initialize.LOCK_INDEX})
    assert not wrong, (
        f"locks name a registry other than {initialize.LOCK_INDEX}: {wrong} -- re-lock "
        "with `cargo make lock` (it unsets the shell's uv index settings)"
    )


def test_the_lock_task_drops_the_same_index_settings_the_sync_does():
    """Makefile.toml's `lock` and initialize.py's sync must agree on the index
    and on which of the shell's settings to drop, or one of them re-locks onto
    a mirror the other never sees."""
    from tabsdata_dev.tdd import initialize

    root = paths.repo_root()
    assert root is not None
    task = (
        (root / "Makefile.toml")
        .read_text()
        .split("[tasks.lock]", 1)[1]
        .split("\n[tasks.", 1)[0]
    )
    assert f"unset {' '.join(initialize.INDEX_ENV)}\n" in task
    assert f"--default-index {initialize.LOCK_INDEX}" in task
