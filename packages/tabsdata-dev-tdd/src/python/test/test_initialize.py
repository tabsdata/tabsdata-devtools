#
# Copyright 2026 Tabsdata Inc.
#

"""`initialize` must build (or rebuild) the tool set without touching the user's
state in the tdd dir. `data/` (system and domain descriptors), `managed-venvs/`
(the user's `tdd venv` environments) and every `<command>.toml` are theirs, not the
installer's -- a re-init to pick up a dependency change must leave them intact.
The heavy uv steps are stubbed so this stays a fast unit test; what it pins is
which paths initialize is allowed to write."""

import pathlib

from tabsdata_dev.tdd import initialize, paths


PYTHON = "3.12.13"


def _fake_catalog():
    return {
        "toolsets": ["launchers"],
        "interpreter": PYTHON,
        "python": {"launchers": PYTHON},
        "tools": {"gsx": {"toolset": "launchers"}},
    }


def test_initialize_from_source_preserves_user_state(tmp_path, monkeypatch):
    dir_ = tmp_path / "tdd"
    # user state that must survive a re-init
    keep = {
        "data/system/dev": "sys",
        "data/domain/dev": "dom",
        "managed-venvs/scratch.json": '{"manager": "uv"}',
        "managed-venvs/uv/scratch/marker": "venv",
        # a command's own config file: its options and whatever it keeps
        "venv.toml": '[options.create]\ntype = "uv"\n',
        "gsx.toml": '[repos."o/n"]\nlabels = ["bug"]\n',
    }
    for rel, text in keep.items():
        p = dir_ / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    # Stub every step that would touch the network or build a real venv; record
    # which venvs would have been made so the good path is still asserted.
    made: list = []
    monkeypatch.setattr(
        initialize.generate_mod, "generate", lambda root, out: _fake_catalog()
    )
    monkeypatch.setattr(
        initialize,
        "_make_venv",
        lambda target, out, python: (
            target.mkdir(parents=True, exist_ok=True),
            made.append(target),
        ),
    )
    monkeypatch.setattr(initialize, "_uv", lambda *a, **k: None)
    monkeypatch.setattr(initialize, "_venv_install", lambda *a, **k: None)

    rc = initialize.initialize(dir_, _Out(), from_wheels=False)
    assert rc == 0

    for rel, text in keep.items():
        assert (dir_ / rel).read_text() == text, f"{rel} was disturbed by initialize"
    # no shared config file is written: a command that needs one owns <command>.toml
    assert not (dir_ / "config.toml").exists()
    # and it did do its job: the toolset, tdd-exe and shell venvs, and the catalog
    assert paths.venvs_dir(dir_) / "launchers" in made
    assert (dir_ / "catalog.json").is_file()


class _Out:
    """The Renderer surface initialize uses, quiet."""

    def debug(self, *a, **k): ...
    def info(self, *a, **k): ...
    def warn(self, *a, **k): ...
    def error(self, msg, **k):
        raise AssertionError(f"initialize errored: {msg}")

    def ok(self, *a, **k):
        return 0


def test_the_install_message_names_both_shells_and_how_each_loads():
    """A reader in PowerShell who copies the `source` line gets a silent
    no-op -- PowerShell treats a .sh as a document and hands it to the OS to
    open, so nothing loads and nothing is said. So the message names both
    loaders and the word each shell uses, `source` against `.`."""
    from tabsdata_dev.tdd import initialize

    assert initialize.SOURCE_NAME == "tdd-source.sh"
    assert initialize.SOURCE_NAME_PS == "tdd-source.ps1"
    assert initialize.SOURCE_HOW[initialize.SOURCE_NAME] == ("bash, zsh", "source")
    assert initialize.SOURCE_HOW[initialize.SOURCE_NAME_PS] == ("PowerShell", ".")


def test_initialize_writes_a_loader_per_family_and_reports_both(tmp_path, monkeypatch):
    """Both are written, always: which shell someone will open is not the
    installer's to guess."""
    dir_ = tmp_path / "tdd"
    (dir_ / "tdd-venvs" / "shells" / "bin").mkdir(parents=True)
    (dir_ / "tdd-venvs" / "shells" / "bin" / "python").write_text("")

    import json as json_mod
    import subprocess

    def fake_run(argv, **kwargs):
        payload = {
            "unix": ["tdd-source.sh", "SH __TDD_DIR__"],
            "powershell": ["tdd-source.ps1", "PS __TDD_DIR__"],
        }
        return subprocess.CompletedProcess(argv, 0, json_mod.dumps(payload), "")

    monkeypatch.setattr(initialize.subprocess, "run", fake_run)
    written = initialize._write_source(dir_, _Out())
    assert sorted(written) == ["tdd-source.ps1", "tdd-source.sh"]
    # each one has this dir baked in, so several tdd dirs each point at themselves
    assert (dir_ / "tdd-source.sh").read_text() == f"SH {dir_}"
    assert (dir_ / "tdd-source.ps1").read_text() == f"PS {dir_}"


def test_the_toolset_sync_is_locked_to_pypi_whatever_the_shell_says(
    tmp_path, monkeypatch
):
    """A developer's shell pointing uv at a local mirror made every `uv sync`
    find the committed locks stale and re-lock them onto the mirror. The sync
    now drops the shell's index settings, names PyPI, and is --locked (a stale
    lock fails instead of being rewritten) -- except under --relock, which
    re-resolves, against PyPI too."""
    monkeypatch.setattr(
        initialize.generate_mod, "generate", lambda root, out: _fake_catalog()
    )
    monkeypatch.setattr(
        initialize,
        "_make_venv",
        lambda target, out, python: target.mkdir(parents=True, exist_ok=True),
    )
    monkeypatch.setattr(initialize, "_venv_install", lambda *a, **k: None)
    monkeypatch.setattr(initialize, "_install_pythons", lambda catalog, out: None)
    syncs: list = []
    monkeypatch.setattr(
        initialize,
        "_uv",
        lambda argv, out, failure, drop_env=(), **env: syncs.append((argv, drop_env)),
    )
    for relock, flag, not_flag in (
        (False, "--locked", "--upgrade"),
        (True, "--upgrade", "--locked"),
    ):
        syncs.clear()
        assert initialize.initialize(tmp_path / "tdd", _Out(), relock=relock) == 0
        [(argv, drop_env)] = [s for s in syncs if s[0][:2] == ["uv", "sync"]]
        assert argv[argv.index("--default-index") + 1] == "https://pypi.org/simple"
        assert flag in argv and not_flag not in argv
        assert set(drop_env) >= {"UV_INDEX", "UV_DEFAULT_INDEX"}
        assert argv[argv.index("--python") + 1] == PYTHON
        assert "--managed-python" in argv


def test_every_env_is_built_on_exactly_the_catalogs_interpreters(tmp_path, monkeypatch):
    """The interpreters are installed first, off PATH; a toolset env on the
    right version is synced in place, one on any other version rebuilt; the
    tdd and shells envs take the catalog's interpreter."""
    catalog = dict(_fake_catalog(), toolsets=["launchers", "xp"])
    catalog["python"] = {"launchers": PYTHON, "xp": "3.12.12"}
    made, steps = {}, []
    monkeypatch.setattr(initialize.generate_mod, "generate", lambda root, out: catalog)
    monkeypatch.setattr(initialize, "_venv_install", lambda *a, **k: None)
    # Every existing env stands on PYTHON: launchers is right, xp is not.
    monkeypatch.setattr(
        initialize,
        "_built_on",
        lambda target, python: python == PYTHON,
    )
    monkeypatch.setattr(
        initialize,
        "_make_venv",
        lambda target, out, python: made.update({target.name: python}),
    )
    monkeypatch.setattr(
        initialize,
        "_uv",
        lambda argv, out, failure, **env: steps.append(argv),
    )

    assert initialize.initialize(tmp_path / "tdd", _Out()) == 0
    installs = [argv for argv in steps if argv[:3] == ["uv", "python", "install"]]
    assert [argv[-1] for argv in installs] == ["3.12.12", PYTHON]
    for argv in installs:
        assert {"--managed-python", "--no-bin", "--no-registry"} <= set(argv)
    assert made == {"xp": "3.12.12", "tdd": PYTHON, "shells": PYTHON}


def test_only_an_env_on_uvs_exact_folder_counts_as_built_on_it(
    tmp_path,
    resource_folder,
):
    """uv's minor link runs the right version today and the next patch
    tomorrow; pyenv's interpreter of the same version is not uv's."""
    import shutil

    for env, built in (
        ("exact", True),
        ("minor-link", False),
        ("pyenv", False),
        ("empty", False),
    ):
        target = tmp_path / env
        shutil.copytree(resource_folder / env, target)
        assert initialize._built_on(target, PYTHON) is built, env
    assert initialize._built_on(tmp_path / "missing", PYTHON) is False


def test_a_venv_is_made_relocatable_on_the_exact_managed_interpreter(monkeypatch):
    steps = []
    monkeypatch.setattr(
        initialize,
        "_uv",
        lambda argv, out, failure, **env: steps.append(argv),
    )
    initialize._make_venv(pathlib.Path("/x/env"), _Out(), PYTHON)
    [argv] = steps
    assert argv[:2] == ["uv", "venv"] and argv[-1] == "/x/env"
    assert {"--relocatable", "--clear", "--managed-python"} <= set(argv)
    assert argv[argv.index("--python") + 1] == PYTHON


def test_uv_steps_run_without_the_dropped_variables(monkeypatch):
    import subprocess

    seen = {}

    def fake_run(argv, env, **kwargs):
        seen.update(env)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(initialize.subprocess, "run", fake_run)
    monkeypatch.setenv("UV_DEFAULT_INDEX", "http://localhost:3141/mirror/")
    monkeypatch.setenv("UV_INDEX", "https://private.example/simple/")
    monkeypatch.setenv("KEEP_ME", "1")
    initialize._uv(["uv", "sync"], _Out(), "failed", drop_env=initialize.INDEX_ENV)
    assert "UV_DEFAULT_INDEX" not in seen and "UV_INDEX" not in seen
    assert seen["KEEP_ME"] == "1" and seen["UV_LINK_MODE"] == "copy"
