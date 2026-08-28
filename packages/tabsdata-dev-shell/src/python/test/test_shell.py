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


COMMON = "common.sh"


def _command_files():
    return [p for p in shell.scripts_dir().glob("*.sh") if p.name != COMMON]


def test_every_command_file_sources_common_sh():
    for path in _command_files():
        assert '. "${TDD_COMMON_SH' in path.read_text(), (
            f"{path.name} does not source common.sh"
        )


def test_every_command_file_registers_and_defines_a_matching_function():
    for path in _command_files():
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
    for path in _command_files():
        for line in path.read_text().splitlines():
            if line.startswith("tdd_fn_register "):
                assert "|" not in line, f"{path.name}: {line}"


def test_env_group_routes_activate_and_deactivate():
    text = (shell.scripts_dir() / "tdd-env.sh").read_text()
    assert "tdd_fn_register tdd-env " in text
    assert "activate)" in text and "deactivate)" in text
    assert "--toolset" in text


def test_every_command_uses_the_shared_helpers():
    # docs/command-cli-guidelines.md: --help, --verbose, --format, exit 0/1,
    # the event model and a failure log. common.sh is how a command gets all
    # of that at once; a command that prints on its own has almost certainly
    # dropped one.
    helpers = (
        "_tdd_cmd_reset",
        "_tdd_common_opt",
        "_tdd_cmd_check",
        "_tdd_error",
        "_tdd_ok",
    )
    for path in _command_files():
        text = path.read_text()
        for helper in helpers:
            assert helper in text, f"{path.name} does not call {helper}"
        assert "cat <<'HELP'" in text, f"{path.name} has no help text"
        assert "exit " not in text, (
            f"{path.name} calls exit; a sourced function must return"
        )
        # printf is fine inside $(...) helpers that return a value; echo at
        # statement level is a message that bypassed the renderer.
        assert "\n    echo " not in text, (
            f"{path.name} echoes instead of emitting an event"
        )


def test_every_command_returns_only_0_or_1():
    import re

    for path in _command_files():
        codes = set(re.findall(r"\breturn\s+(\d+)", path.read_text()))
        assert codes <= {"0", "1"}, f"{path.name} returns {sorted(codes)}"


def test_common_sh_defines_the_event_api_and_colours():
    text = (shell.scripts_dir() / COMMON).read_text()
    for fn in (
        "_tdd_ok",
        "_tdd_error",
        "_tdd_warn",
        "_tdd_info",
        "_tdd_debug",
        "_tdd_emit",
        "_tdd_color",
    ):
        assert f"{fn}()" in text, f"common.sh lacks {fn}"
    for kind, code in (("ok", "32"), ("error", "31"), ("warn", "33"), ("debug", "37")):
        assert f"{kind}) printf '\\033[{code}m'" in text, f"{kind} is not colour {code}"


def test_common_sh_declares_jq_for_every_command():
    # common.sh builds every JSON line with jq, so jq is a requirement of all
    # shell commands -- declared once, beside common.sh.
    assert "jq -cn" in (shell.scripts_dir() / COMMON).read_text()
    assert "jq" in _bin_reqs(shell.scripts_dir() / "common.bin-reqs.txt")
