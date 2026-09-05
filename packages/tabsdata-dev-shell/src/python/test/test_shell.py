#
# Copyright 2026 Tabsdata Inc.
#

from tabsdata_dev import shell


def test_scripts_dir_exists_and_holds_command_files():
    found = sorted(p.name for p in shell.scripts_dir().glob("*.sh"))
    assert found, "no shell command files were installed"
    assert "tdd-env.sh" in found


def _registered(text: str) -> list[str]:
    """Names passed to tdd_fn_register."""
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


def test_venv_delete_all_shares_the_removal_and_refuses_an_active_venv():
    text = (shell.scripts_dir() / "venv.sh").read_text()
    assert "_tdd_venv_remove() {" in text
    assert (
        text.count('_tdd_venv_remove "$_tdd_name"') == 3
    )  # delete, --all, create --force
    body = text.split("_tdd_venv_delete() {", 1)[1].split("\n}\n", 1)[0]
    assert "--all)" in body and '"--all and --name are exclusive"' in body
    assert '"$_TDD_VENV is active; run tdd venv deactivate first"' in body
    assert '"delete|--all|false"' in text


def test_venv_adopts_a_managed_venv_active_without_the_record():
    # The twin of common.core.managedvenv.adopted(): a venv under
    # managed-venvs/<type>/<name> whose marker agrees is ours however it was
    # entered; every subcommand adopts it before doing anything else.
    text = (shell.scripts_dir() / "venv.sh").read_text()
    assert "_tdd_venv_adopt() {" in text
    assert '[ "$_tdd_current" = "$_tdd_adir" ] || return 0' in text
    assert (
        '[ "$(cat "$(_tdd_venv_root)/$_tdd_aname.env" 2>/dev/null)" = "$_tdd_atype" ]'
        in text
    )
    for sub in ("create", "activate", "deactivate", "delete", "list"):
        body = text.split(f"_tdd_venv_{sub}() {{", 1)[1].split("\n}\n", 1)[0]
        assert "_tdd_venv_adopt" in body, sub


def test_venv_create_has_force_and_deactivate_handles_every_kind():
    text = (shell.scripts_dir() / "venv.sh").read_text()
    assert "--force | -f)" in text and '"create|--force|false"' in text
    assert '"deactivate|--force|false"' in text
    body = text.split("_tdd_venv_deactivate() {", 1)[1].split("\n}\n", 1)[0]
    assert "tdd venv deactivate --force drops it" in body  # stale record
    assert "tdd venv deactivate --force leaves it anyway" in body  # foreign venv
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
        "--py-idx | --py-idx=*)",
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


def test_sourcing_says_version_and_dir_in_interactive_shells_only():
    hello = shell.source_template().split(
        "# ---------------------------------------------------------------- hello", 1
    )[1]
    assert "case $- in" in hello and "*i*)" in hello  # interactive shells only
    assert '"$TDD_DIR/VERSION"' in hello
    assert "printf '\\ntdd %s installed at %s -- tdd -h for help\\n\\n'" in hello


def test_tdd_routes_the_short_version_flag_to_tdd_exe():
    text = shell.source_template()
    assert "-V | --version | --reqs)" in text


def test_env_set_takes_provider_refs_a_literal_default_and_a_crypto_value():
    text = (shell.scripts_dir() / "env.sh").read_text()
    # the vault of each selection is a literal, never read from the environment
    assert '_TDD_VAULT_CRYPTO="1p:Employee"' in text
    assert '_TDD_VAULT_SECRETS="1p:dev_xp"' in text
    assert "ONE_PASSWORD" not in text.replace(
        "# provider refs. Literals, not $ONE_PASSWORD_*: a vault is a choice made on the",
        "",
    )
    # --vault is one form for both: a provider ref
    assert "1p:?*) ;;" in text and "1p:NAME" in text
    assert (
        '_tdd_args=" --vault=${_tdd_v#1p:}"' in text
    )  # crypto-key wants the bare vault
    # --value: the key itself, at least MIN_SECRET_LEN characters, crypto only
    assert "_TDD_CRYPTO_MIN=12" in text
    assert '[ "${#_tdd_value}" -lt "$_TDD_CRYPTO_MIN" ]' in text
    assert "--value is the crypto key itself; pass --crypto to say so" in text
    # masking by name, in every group: the TD group carries TD_BACKENDS_CRYPTO_KEY
    assert (
        '"$_TDD_VARS_CRYPTO" | *PASSWORD* | *SECRET* | *TOKEN* | *KEY* | *PASS*' in text
    )
    assert '"set|--value|"' in text


def test_a_secret_option_value_is_masked_in_the_log_and_the_resolved_line():
    common = (shell.scripts_dir() / COMMON).read_text()
    assert "_tdd_mask_argv() {" in common
    assert "--(value|password|secret|token|key)" in common
    assert 'echo "command: tdd $(_tdd_mask_argv' in common
    assert '_tdd_info "resolved: tdd $(_tdd_mask_argv "$*")"' in shell.source_template()


def test_the_aliases_section_defines_gsx_over_the_command():
    text = shell.source_template()
    aliases = text.split("---- aliases", 1)[1]
    assert 'gsx() {\n    tdd gsx "$@"\n}' in aliases  # the command keeps every option
    # functions, not `alias`: a shell alias is not expanded non-interactively
    assert "alias gsx=" not in text


def test_every_shell_command_with_defaults_has_the_config_action():
    # the same action every Python tool gets from common.core.config
    common = (shell.scripts_dir() / COMMON).read_text()
    assert "_tdd_config_action() {" in common
    for piece in ("--show", "--default", "--create", "--force"):
        assert piece in common.split("_tdd_config_action() {", 1)[1]
    # write and replace, never half a config
    assert 'mv "$_tdd_cfg_tmp" "$_tdd_cfg_file"' in common
    # and the template is the command's own declarations, not a second list
    assert 'command -v "tdd_defaults_$1"' in common
    # --force rewrites the template but keeps what the file set and what it keeps
    assert '_tdd_config_template "$_tdd_cfg_cmd" $_tdd_cfg_keepcur' in common
    assert "keep = ($0 !~ /^\\[options[].]/)" in common
    for name in ("venv", "env", "pycache", "tdd-env"):
        text = (shell.scripts_dir() / f"{name}.sh").read_text()
        assert f"_tdd_config_action {name}" in text, name
        assert f"tdd_defaults_{name}()" in text, name


def test_the_defaults_command_is_gone_in_favour_of_config():
    assert not (shell.scripts_dir() / "defaults.sh").exists()
    text = shell.source_template()
    assert "config --create" in text and "default-opts" not in text


def test_the_shell_paints_help_the_way_the_python_half_does():
    common = (shell.scripts_dir() / COMMON).read_text()
    # the same two colours, and only for a terminal
    assert 'if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then' in common
    assert "function paintline(" in common and "function paint(" in common
    assert "bold l off" in common and "termcol substr(l" in common
    # every finished line goes out through it
    assert "print paint(" in common
    # and the listing tdd itself prints says it paints itself
    assert "_TDD_PRECOLORED=1" in shell.source_template()
