#
# Copyright 2026 Tabsdata Inc.
#

"""Materializing a tdd dir: one venv per toolset, plus the shell env.

Standard library only. Everything it says goes through the renderer it is
given -- docs/command-cli-guidelines.md -- so `tdd-install --format json` is a
stream of events and a failure is one error with uv's output in the log.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

from . import catalog as catalog_mod
from . import generate as generate_mod
from . import paths
from . import render
from . import version as version_mod

LOCK_SUFFIX = ".lock"
SHELL_DIST = "tabsdata-dev-shell"
SHELL_ENV = "shells"
TDD_DIST = "tabsdata-dev-tdd"
_TDD_VENV = "tdd"
SOURCE_NAME = "tdd-source.sh"
SOURCE_NAME_PS = "tdd-source.ps1"
#: Identifies a tdd folder to `cargo make uninstall`, which deletes only a
#: folder carrying it; the Makefile.toml uninstall task holds the same values.
MARKER_NAME = ".tdd-i-am"
MARKER = "tabsdata-dev tdd folder"

#: How each loader is loaded, in the shell it is for. PowerShell has no
#: `source`, and dot-sourcing there is `.` followed by a space -- which is
#: exactly the mistake the message exists to prevent.
SOURCE_HOW = {
    SOURCE_NAME: ("bash, zsh", "source"),
    SOURCE_NAME_PS: ("PowerShell", "."),
}
SOURCE_TEMPLATE = "tddsrc.sh"

# Every env tdd creates is relocatable: uv rewrites the console-script shebangs
# to resolve the interpreter relatively, so the whole tdd dir can be moved,
# copied or zipped without reinstalling. See docs/DESIGN.md for what this does
# and does not buy you.
RELOCATABLE_ENV = {"UV_VENV_RELOCATABLE": "1", "UV_LINK_MODE": "copy"}

#: The one index every committed toolset uv.lock resolves against. A lock
#: records its registry's URLs, so one resolved through a developer's local
#: mirror is usable only where that mirror runs.
LOCK_INDEX = "https://pypi.org/simple"

#: uv's index settings a developer's shell may carry -- a devpi mirror, a
#: private index. `uv sync` honours them, finds every lock "stale" against
#: them and silently re-locks it onto that index; so the toolset sync runs
#: without them. Makefile.toml's `lock` task unsets the same list.
INDEX_ENV = ("UV_INDEX", "UV_DEFAULT_INDEX", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL")


class StepFailed(Exception):
    """A uv step failed; carries its captured output for the error log."""

    def __init__(self, message: str, output: str):
        super().__init__(message)
        self.output = output


def initialize(
    dir_: pathlib.Path,
    out: render.Renderer,
    relock: bool = False,
    from_wheels: bool = False,
) -> int:
    """Materialize one venv per toolset, the shell env, and tdd-source.sh.

    Two modes. The default builds from the source checkout with editable
    installs -- the development loop, where a source edit is live everywhere at
    once. `from_wheels` installs prebuilt wheels and their exported locks out of
    <dir>/wheels instead, needs no checkout at all, and is how a pinned tool set
    travels to a teammate or a CI runner.
    """
    paths.require_uv()
    try:
        catalog = (
            _from_wheels(dir_, out) if from_wheels else _from_source(dir_, out, relock)
        )
    except StepFailed as exc:
        return out.error(str(exc), details=exc.output)
    if catalog is None:
        return 1
    return _finish(dir_, catalog, out)


# --------------------------------------------------------------- source mode


def _from_source(dir_: pathlib.Path, out: render.Renderer, relock: bool) -> dict | None:
    root = paths.repo_root()
    if root is None:
        out.error(
            "no source repo found; a wheel-installed tdd cannot build envs from "
            "source. Use `tdd-install --from-wheels`."
        )
        return None

    out.debug(f"checkout: {root}")
    catalog = generate_mod.generate(root, out)
    envs = paths.venvs_dir(dir_)
    envs.mkdir(parents=True, exist_ok=True)

    _install_pythons(catalog, out)
    for toolset in catalog["toolsets"]:
        project = root / "packages" / (generate_mod.TOOLSET_PREFIX + toolset)
        target = envs / toolset
        python = catalog["python"][toolset]
        out.info(
            f"syncing toolset {toolset} -> {target} (python {python})",
            step="sync",
            toolset=toolset,
            python=python,
        )
        # uv sync would create the env itself, but not relocatably; make it
        # first so sync populates a relocatable venv instead. An env on another
        # interpreter -- built before the pin, or by hand -- is rebuilt.
        if not _built_on(target, python):
            _make_venv(target, out, python)
        # Against the lock's own index, and --locked: an install never
        # rewrites a committed lock -- a stale one is an error naming `cargo
        # make lock`, not a quiet re-resolve. --relock is the one exception,
        # and it re-resolves against the same index.
        argv = [
            "uv",
            "sync",
            "--quiet",
            "--project",
            str(project),
            "--default-index",
            LOCK_INDEX,
            *_python_args(python),
        ]
        argv.append("--upgrade" if relock else "--locked")
        _uv(
            argv,
            out,
            f"failed to sync toolset {toolset}"
            + ("" if relock else " (a stale uv.lock? re-lock with `cargo make lock`)"),
            drop_env=INDEX_ENV,
            UV_PROJECT_ENVIRONMENT=str(target),
        )

    # tdd-exe and the shell commands get their own envs inside the tdd dir, so
    # nothing has to be installed globally and no venv has to be active for
    # `tdd` to work.
    for env_name, dist, label in (
        (_TDD_VENV, TDD_DIST, "tdd-exe"),
        (SHELL_ENV, SHELL_DIST, "shell commands"),
    ):
        target = envs / env_name
        out.info(f"installing {label} -> {target}", step="install", env=env_name)
        # Neither is a uv project, so unlike the toolsets they must be created
        # before anything can be installed into them.
        _make_venv(target, out, catalog["interpreter"])
        _venv_install(
            target,
            ["--editable", str(root / "packages" / dist)],
            out,
            f"failed to install {label}",
        )
    return catalog


# --------------------------------------------------------------- wheels mode


def _from_wheels(dir_: pathlib.Path, out: render.Renderer) -> dict | None:
    """Install each toolset from wheels plus exported locks in <dir>/wheels."""
    wheels = dir_ / "wheels"
    if not wheels.is_dir() or not any(wheels.glob("*.whl")):
        out.error(
            f"no wheels in {wheels}; run `cargo make install` "
            f"(or `cargo make install -- --dir {dir_}`) first"
        )
        return None

    # The shipped catalog is the source of truth here -- there is no repo to
    # discover from, which is the whole point of this mode.
    catalog = catalog_mod.shipped()
    envs = paths.venvs_dir(dir_)
    envs.mkdir(parents=True, exist_ok=True)

    _install_pythons(catalog, out)
    for toolset in catalog["toolsets"]:
        _install_locked(
            envs / toolset,
            wheels,
            wheels / f"{toolset}{LOCK_SUFFIX}",
            catalog["members"][toolset],
            f"toolset {toolset}",
            out,
            catalog["python"][toolset],
        )
    for env_name, dist, label in (
        (_TDD_VENV, TDD_DIST, "tdd-exe"),
        (SHELL_ENV, SHELL_DIST, "shell commands"),
    ):
        _install_locked(
            envs / env_name,
            wheels,
            wheels / f"{env_name}{LOCK_SUFFIX}",
            [dist],
            label,
            out,
            catalog["interpreter"],
        )
    return catalog


def _install_locked(
    target: pathlib.Path,
    wheels: pathlib.Path,
    lock: pathlib.Path,
    dists: list[str],
    label: str,
    out: render.Renderer,
    python: str,
) -> None:
    """Install `dists` into `target` against an exported lock.

    Third-party dependencies come from the lock -- pinned and hashed, straight
    off the toolset's committed uv.lock. The first-party wheels then go in with
    --no-deps, so the resolver never reopens a decision the lock already made.
    That is what makes wheels mode reproducible rather than a fresh resolution.
    """
    if not lock.is_file():
        raise StepFailed(
            f"missing {lock.name} beside the wheels; rebuild with `cargo make wheels`",
            "",
        )

    out.info(f"installing {label} -> {target}", step="install", env=target.name)
    _make_venv(target, out, python)
    if not _lock_is_empty(lock):
        _venv_install(
            target,
            ["--require-hashes", "-r", str(lock)],
            out,
            f"failed to install {lock.name}",
        )
    # --refresh because uv caches wheels by filename, and a rebuilt first-party
    # wheel keeps its name (same VERSION) while its contents change. Without it
    # the env silently gets the previous build. Third-party wheels above are
    # immutable per version, so they keep using the cache.
    _venv_install(
        target,
        ["--refresh", "--no-deps", "--find-links", str(wheels), *dists],
        out,
        f"failed to install {label}",
    )


def _lock_is_empty(lock: pathlib.Path) -> bool:
    """An export with no third-party dependencies is comments only."""
    return not any(
        line.strip() and not line.lstrip().startswith("#")
        for line in lock.read_text().splitlines()
    )


# --------------------------------------------------------------- uv steps


def _uv(
    argv: list[str],
    out: render.Renderer,
    failure: str,
    drop_env: tuple[str, ...] = (),
    **extra_env: str,
) -> None:
    """Run one uv step with its output captured, without the variables named
    in `drop_env`.

    In json mode nothing but events may reach the terminal, and in view mode
    uv's chatter is noise on success -- so the output goes to debug when the
    step works and into the error log when it does not.
    """
    out.debug(" ".join(argv))
    env = {k: v for k, v in os.environ.items() if k not in drop_env}
    result = subprocess.run(
        argv,
        env=dict(env, **RELOCATABLE_ENV, **extra_env),
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise StepFailed(failure, f"$ {' '.join(argv)}\n{output}")
    if output:
        out.debug(output)


def _venv_install(
    target: pathlib.Path, args: list[str], out: render.Renderer, failure: str
) -> None:
    _uv(
        ["uv", "pip", "install", "--quiet", "--python", str(target), *args],
        out,
        failure,
    )


def _python_args(python: str) -> list[str]:
    """Exactly `python`, and only one uv installed: never a pyenv, homebrew or
    system interpreter, nor the venv that happens to be active. The exact
    version also keeps the env off uv's minor link (cpython-3.12-...), which
    uv re-points whenever it installs a newer patch."""
    return [
        "--managed-python",
        "--python",
        python,
    ]


def _install_pythons(catalog: dict, out: render.Renderer) -> None:
    """Install every interpreter the envs are built on, before any is needed.
    --no-bin and --no-registry: nothing lands on PATH (uv would link
    python3.X into ~/.local/bin) or in the Windows registry (where the `py`
    launcher looks), so the machine's own `python` stays what it was."""
    for python in sorted({catalog["interpreter"], *catalog["python"].values()}):
        _uv(
            [
                "uv",
                "python",
                "install",
                "--quiet",
                "--managed-python",
                "--no-bin",
                "--no-registry",
                python,
            ],
            out,
            f"failed to install python {python}",
        )


def _built_on(target: pathlib.Path, python: str) -> bool:
    """Whether the env at `target` stands on uv's own folder for exactly
    `python` (cpython-3.12.13-<platform>). Its version alone is not enough: an
    env on uv's minor link (cpython-3.12-<platform>) runs 3.12.13 today and
    whatever patch uv installs next tomorrow, and pyenv's 3.12.13 is not uv's."""
    cfg = target / "pyvenv.cfg"
    if not cfg.is_file():
        return False
    for line in cfg.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            return f"cpython-{python}-" in value
    return False


def _make_venv(target: pathlib.Path, out: render.Renderer, python: str) -> None:
    """Create a relocatable venv on exactly `python`. Copies rather than
    hardlinks from the cache, so the result survives being archived or moved
    to another filesystem.

    --clear because re-running init over an existing tdd dir is the documented
    way to pick up a dependency change, and uv refuses to overwrite a venv
    without it. A rebuilt env starts empty, which is what "re-init" should mean.
    """
    _uv(
        [
            "uv",
            "venv",
            "--quiet",
            "--clear",
            "--relocatable",
            *_python_args(python),
            str(target),
        ],
        out,
        f"failed to create the venv {target}",
    )


# --------------------------------------------------------------- shared tail


def _finish(dir_: pathlib.Path, catalog: dict, out: render.Renderer) -> int:
    catalog_mod.write(dir_ / catalog_mod.CATALOG_NAME, catalog)
    # Stamp what was built here, so `tdd --version` describes this dir rather
    # than whatever checkout tdd-exe happens to be linked to.
    version_mod.stamp(dir_)
    (dir_ / MARKER_NAME).write_text(MARKER + "\n")

    written = _write_source(dir_, out)
    summary = f"initialized {dir_} ({len(catalog['tools'])} tools, {len(catalog['toolsets'])} toolsets)"
    if written:
        # Both shells, named: a reader in PowerShell who copies the `source`
        # line gets a silent no-op -- PowerShell treats a .sh as a document and
        # hands it to the OS to open, so nothing loads and nothing is said.
        lines = "\n".join(
            f"    {shell:<11} {how} {path}"
            for path, (shell, how) in (
                (written[name], SOURCE_HOW[name])
                for name in (SOURCE_NAME, SOURCE_NAME_PS)
                if name in written
            )
        )
        summary += (
            "\n\n  load it to get the `tdd` function, and every tool with it:"
            f"\n\n{lines}\n"
        )
    posix = written.get(SOURCE_NAME) if written else None
    return out.ok(
        summary,
        tdd_dir=str(dir_),
        tools=len(catalog["tools"]),
        toolsets=catalog["toolsets"],
        source=str(posix) if posix else None,
        sources={name: str(path) for name, path in (written or {}).items()},
        version=version_mod.shipped(),
    )


def _write_source(dir_: pathlib.Path, out: render.Renderer) -> dict[str, pathlib.Path]:
    """Install one loader per shell family, with this tdd dir baked in.

    The templates ship inside the shell package, so they are versioned with the
    commands they load. Baking the dir is what lets several tdd dirs each have
    a loader that points at itself.

    Both families are written, always: which shell someone will open is not the
    installer's to guess, a loader is a few kilobytes, and the alternative --
    write one, tell the other to reinstall -- fails exactly when a teammate
    opens the other shell. Both come back, keyed by file name, because the
    install message names both.
    """
    python = paths.venv_exe(paths.venvs_dir(dir_) / SHELL_ENV, "python")
    if not python.is_file():
        out.warn("shell env missing; no tdd-source loader written")
        return {}

    found = subprocess.run(
        [str(python), "-m", "tabsdata_dev.shell", "loaders"],
        capture_output=True,
        text=True,
    )
    if found.returncode != 0:
        out.warn(f"no tdd-source loader written: {found.stderr.strip()}")
        return {}

    written: dict[str, pathlib.Path] = {}
    for family, (name, template) in sorted(json.loads(found.stdout).items()):
        target = dir_ / name
        target.write_text(
            template.replace("__TDD_DIR__", str(dir_)),
            encoding="utf-8",
        )
        target.chmod(0o644)
        out.debug(f"wrote {target}", family=family)
        written[name] = target
    return written
