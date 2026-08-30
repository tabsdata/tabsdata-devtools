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
        assert '. "${_TDD_COMMON_SH' in path.read_text(), (
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
        assert "_tdd_help_text <<'HELP'" in text, f"{path.name} has no help text"
        assert "cat <<" not in text, f"{path.name} prints help on its own"
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


def test_no_two_command_files_define_the_same_function():
    # Every command file is sourced into one shell, so a helper name defined
    # twice is silently the last one loaded -- `tdd env --help` once printed
    # tdd-env's help this way, and a `_tdd_help` in common.sh once replaced the
    # loader's own.
    import re

    sources = {p.name: p.read_text() for p in _command_files()}
    sources[COMMON] = (shell.scripts_dir() / COMMON).read_text()
    sources["tddsrc.sh"] = (
        shell.source_template()
    )  # the loader shares the namespace too
    owners: dict[str, str] = {}
    for name, text in sorted(sources.items()):
        for fn in re.findall(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*\(\)", text, re.M):
            assert fn not in owners, (
                f"{fn}() is defined in both {owners[fn]} and {name}"
            )
            owners[fn] = name


def _render_help(declaration: str) -> list[str]:
    import os
    import subprocess

    done = subprocess.run(
        ["bash", "-c", f'. "{shell.scripts_dir() / COMMON}"; _tdd_help_text'],
        input=declaration,
        capture_output=True,
        text=True,
        env={**os.environ, "COLUMNS": "80"},
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def test_help_renders_in_the_argparse_layout():
    # The shell helps must read like the Python ones: usage, description,
    # tables with the help at column 24 and wrapped, common options first.
    long_help = " ".join(["word"] * 30)
    lines = _render_help(
        "usage: tdd x sub [--name NAME]\n"
        "\n"
        "Does a thing.\n"
        "\n"
        "commands:\n"
        "  sub   the one subcommand\n"
        "\n"
        "options:\n"
        f"  --name NAME   who; {long_help}\n"
        "  --a-very-long-option-name VALUE   goes on its own line\n"
        "\n"
        "example: tdd x sub\n"
    )
    assert lines[0] == "usage: tdd x sub [--name NAME]"
    assert lines[1:3] == ["", "Does a thing."]
    o = lines.index("options:")
    assert lines.index("commands:") < o
    assert lines[o + 1] == "  -h, --help            show this help message and exit"
    assert lines[o + 2] == "  -v, --verbose         show debug events too"
    assert lines[o + 3] == (
        "  --format {json,view}  json is JSON Lines, one event per line (default: view)"
    )
    assert lines[o + 4].startswith("  --name NAME           who; word")
    assert lines[o + 5].startswith(" " * 24 + "word")
    i = lines.index("  --a-very-long-option-name VALUE")
    assert lines[i + 1] == " " * 24 + "goes on its own line"
    assert lines[-1] == "example: tdd x sub"
    assert max(len(line) for line in lines) <= 78


def test_help_adds_the_options_section_when_the_declaration_has_none():
    lines = _render_help("usage: tdd y [-h]\n\nDoes.\n")
    assert lines == [
        "usage: tdd y [-h]",
        "",
        "Does.",
        "",
        "options:",
        "  -h, --help            show this help message and exit",
        "  -v, --verbose         show debug events too",
        "  --format {json,view}  json is JSON Lines, one event per line (default: view)",
    ]


def test_common_sh_declares_awk_for_the_help_layout():
    assert "awk" in _bin_reqs(shell.scripts_dir() / "common.bin-reqs.txt")


def test_venv_exports_tdd_venv_for_the_launchers():
    # tdk/tdkserver (common.core.managedvenv) read the active venv from
    # _TDD_VENV; the shell side must publish exactly that name.
    text = (shell.scripts_dir() / "venv.sh").read_text()
    assert '_TDD_VENV="$_tdd_name"' in text and "export _TDD_VENV" in text
    assert "unset _TDD_VENV _TDD_VENV_PS1" in text


def test_venv_create_has_force_and_deactivate_handles_every_kind():
    text = (shell.scripts_dir() / "venv.sh").read_text()
    assert "--force | -f)" in text and '"create|--force|false"' in text
    for means in (
        "conda deactivate",
        "pyenv deactivate",
        "deactivate 2>/dev/null",
        "unset VIRTUAL_ENV",
    ):
        assert means in text, f"deactivate lacks {means}"


def test_pycache_clean_sweeps_what_uv_cache_clean_skips():
    # `uv cache clean <name>` leaves editable builds and their archives (keyed
    # by source path); the count must come from versioned distribution entries
    # only, and leftovers must be reported rather than claimed purged.
    text = (shell.scripts_dir() / "pycache.sh").read_text()
    assert '-iname "$_tdd_p*-[0-9]*"' in text
    assert (
        "sdists-v*" in text
        and "archive-v*" in text
        and 'rm -rf "$_tdd_cache/$_tdd_shard"' in text
    )
    assert "still match" in text


def test_env_routes_set_unset_show_and_owns_every_managed_variable():
    text = (shell.scripts_dir() / "env.sh").read_text()
    assert "set | unset | show)" in text
    for opt in (
        "--crypto)",
        "--secrets)",
        "--td)",
        # the tdd dir itself survives any prefix
        "TDD_DIR kept (tdd needs it; never unset)",
        "--vars | --vars=*)",
        "--py-idxx | --py-idxx=*)",
        "--py-default-idx | --py-default-idx=*)",
        "--reveal)",
    ):
        assert opt in text, f"env.sh lacks {opt}"
    # show names _TDD_SYSTEMS only while it is set
    assert '${_TDD_SYSTEMS+"$_TDD_VARS_SYSTEMS"}' in text
    # unset --secrets works off _TDD_SYSTEMS, never off 1Password
    assert "for _tdd_p in $(printf '%s' \"$_TDD_SYSTEMS\")" in text
    assert not (shell.scripts_dir() / "vars.sh").exists(), "vars was folded into env"
    # the extra index only counts with the matching uv strategy; show has 3 groups
    assert "UV_INDEX_STRATEGY" in text and "unsafe-best-match" in text
    for group in (
        "_tdd_vars_show_group TD td",
        "_tdd_vars_show_group PyPi pypi",
        "_tdd_vars_show_group Secrets secrets",
    ):
        assert group in text


def test_the_loader_checks_that_a_pyenv_shim_is_wired():
    text = shell.source_template()
    assert 'pyenv which "$_tdd_b"' in text and "*/shims/*)" in text
    # help is never blocked by a missing requirement
    assert "--help | -h) unset _tdd_a; return 0" in text
    assert '_tdd_fn_check_reqs "$_tdd_cmd" "$@"' in text


def test_prompt_marks_tdd_in_red_and_the_venv_in_green():
    assert "_tdd_ps1_wrap()" in (shell.scripts_dir() / COMMON).read_text()
    template = shell.source_template()
    assert "_tdd_star=\"$(_tdd_ps1_wrap red '*') \"" in template
    assert 'PS1="$_tdd_star${PS1-}"' in template
    # re-sourced (a reinstall): the previous marker is removed, never stacked
    assert 'PS1="${PS1/"$_TDD_PROMPT_MARK"/}"' in template
    assert '_TDD_PROMPT_MARK="$_tdd_star"' in template
    venv = (shell.scripts_dir() / "venv.sh").read_text()
    # (<type>/<python>/<name>) in green, written AFTER the star so it stays first
    assert '_tdd_ps1_wrap green "($_tdd_type/${_tdd_py:-?}/$_tdd_name)"' in venv
    assert '"$_tdd_star"*) PS1="$_tdd_star$_tdd_mark${_tdd_ps1#"$_tdd_star"}"' in venv
