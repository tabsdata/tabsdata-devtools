#
# Copyright 2026 Tabsdata Inc.
#

from tabsdata_dev import shell


def test_scripts_dir_exists_and_holds_command_files():
    found = sorted(p.name for p in shell.scripts_dir().glob("*.sh"))
    assert found, "no shell command files were installed"
    assert "tdd-env.sh" in found


def _registered(text: str) -> list[str]:
    """Names passed to tdd_fn_register, skipping its --demo flag."""
    names = []
    for line in text.splitlines():
        if not line.startswith("tdd_fn_register "):
            continue
        words = [w for w in line.split()[1:] if not w.startswith("--")]
        names.append(words[0])
    return names


def test_every_command_file_registers_and_defines_a_matching_function():
    for path in shell.scripts_dir().glob("*.sh"):
        text = path.read_text()
        registered = _registered(text)
        assert registered, f"{path.name} registers no command"
        for name in registered:
            assert f"tddfn_{name}()" in text, (
                f"{path.name} registers {name} but defines no tddfn_{name}"
            )


def test_template_carries_the_placeholder():
    assert "__TDD_DIR__" in shell.source_template()


def test_demo_commands_are_registered_as_demo():
    for n in (1, 2):
        text = (shell.scripts_dir() / f"demo-fn{n}.sh").read_text()
        assert f"tdd_fn_register --demo demo-fn{n} " in text


def _bin_reqs(path):
    return [
        line.split("#", 1)[0].strip()
        for line in path.read_text().splitlines()
        if line.split("#", 1)[0].strip()
    ]


def test_every_bin_reqs_file_sits_beside_its_script():
    for reqs in shell.scripts_dir().glob("*.bin-reqs.txt"):
        stem = reqs.name[: -len(".bin-reqs.txt")]
        assert (reqs.parent / f"{stem}.sh").is_file(), f"{reqs.name} has no {stem}.sh"


def test_demo_commands_declare_the_binaries_they_use():
    # The declaration is only worth having if it matches the script: every
    # declared binary is used, and the file exists for each demo command.
    for n in (1, 2):
        script = shell.scripts_dir() / f"demo-fn{n}.sh"
        declared = _bin_reqs(script.with_name(f"demo-fn{n}.bin-reqs.txt"))
        assert len(declared) >= 2
        for binary in declared:
            assert f"$({binary}" in script.read_text(), f"{binary} declared, not used"


def test_summaries_avoid_the_registry_delimiter():
    # tddsrc.sh keeps the registry as `name|summary|kind` lines; a `|` inside a
    # summary silently truncates it in every listing.
    for path in shell.scripts_dir().glob("*.sh"):
        for line in path.read_text().splitlines():
            if line.startswith("tdd_fn_register "):
                assert "|" not in line, f"{path.name}: {line}"


def test_env_group_routes_activate_and_deactivate():
    text = (shell.scripts_dir() / "tdd-env.sh").read_text()
    assert "tdd_fn_register tdd-env " in text
    assert "activate)" in text and "deactivate)" in text
    assert "--toolset" in text
