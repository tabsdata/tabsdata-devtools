#
# Copyright 2026 Tabsdata Inc.
#

"""`initialize` must build (or rebuild) the tool set without touching the user's
state in the tdd dir. `data/` (system and domain descriptors), `managed-venvs/`
(the user's `tdd venv` environments) and every `<command>.toml` are theirs, not the
installer's -- a re-init to pick up a dependency change must leave them intact.
The heavy uv steps are stubbed so this stays a fast unit test; what it pins is
which paths initialize is allowed to write."""

from tabsdata_dev.tdd import initialize, paths


def _fake_catalog():
    return {
        "toolsets": ["launchers"],
        "python": {},
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
        lambda target, out, python=None: (
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
