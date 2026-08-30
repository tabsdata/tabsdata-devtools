#
# Copyright 2026 Tabsdata Inc.
#

"""Materializing a tdd dir: one venv per toolset, plus the shell env.

Standard library only. Everything it says goes through the renderer it is
given -- docs/command-cli-guidelines.md -- so `tdd-install --format json` is a
stream of events and a failure is one error with uv's output in the log.
"""

from __future__ import annotations

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
SOURCE_TEMPLATE = "tddsrc.sh"

# Every env tdd creates is relocatable: uv rewrites the console-script shebangs
# to resolve the interpreter relatively, so the whole tdd dir can be moved,
# copied or zipped without reinstalling. See docs/design.md for what this does
# and does not buy you.
RELOCATABLE_ENV = {"UV_VENV_RELOCATABLE": "1", "UV_LINK_MODE": "copy"}

CONFIG_STUB = """\
# Reserved for per-tool configuration. `tdd` does NOT read the envs location
# from here -- that arrives via --dir, $TDD_DIR, or the ~/.tdd default.
"""


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

    for toolset in catalog["toolsets"]:
        project = root / "packages" / (generate_mod.TOOLSET_PREFIX + toolset)
        target = envs / toolset
        python = catalog.get("python", {}).get(toolset)
        out.info(
            f"syncing toolset {toolset} -> {target}"
            + (f" (python {python})" if python else ""),
            step="sync",
            toolset=toolset,
            python=python,
        )
        # uv sync would create the env itself, but not relocatably; make it
        # first so sync populates a relocatable venv instead.
        if not target.exists():
            _make_venv(target, out, python)
        argv = ["uv", "sync", "--quiet", "--project", str(project)]
        if relock:
            argv.append("--upgrade")
        _uv(
            argv,
            out,
            f"failed to sync toolset {toolset}",
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
        _make_venv(target, out)
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

    for toolset in catalog["toolsets"]:
        _install_locked(
            envs / toolset,
            wheels,
            wheels / f"{toolset}{LOCK_SUFFIX}",
            catalog["members"][toolset],
            f"toolset {toolset}",
            out,
            python=catalog.get("python", {}).get(toolset),
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
        )
    return catalog


def _install_locked(
    target: pathlib.Path,
    wheels: pathlib.Path,
    lock: pathlib.Path,
    dists: list[str],
    label: str,
    out: render.Renderer,
    python: str | None = None,
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


def _uv(argv: list[str], out: render.Renderer, failure: str, **extra_env: str) -> None:
    """Run one uv step with its output captured.

    In json mode nothing but events may reach the terminal, and in view mode
    uv's chatter is noise on success -- so the output goes to debug when the
    step works and into the error log when it does not.
    """
    out.debug(" ".join(argv))
    result = subprocess.run(
        argv,
        env=dict(os.environ, **RELOCATABLE_ENV, **extra_env),
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


def _make_venv(
    target: pathlib.Path, out: render.Renderer, python: str | None = None
) -> None:
    """Create a relocatable venv. Copies rather than hardlinks from the cache,
    so the result survives being archived or moved to another filesystem.

    --clear because re-running init over an existing tdd dir is the documented
    way to pick up a dependency change, and uv refuses to overwrite a venv
    without it. A rebuilt env starts empty, which is what "re-init" should mean.
    `python` pins the interpreter minor a toolset's bundle asked for; uv finds
    or fetches it.
    """
    argv = ["uv", "venv", "--quiet", "--clear", "--relocatable"]
    if python:
        argv += ["--python", python]
    _uv([*argv, str(target)], out, f"failed to create the venv {target}")


# --------------------------------------------------------------- shared tail


def _finish(dir_: pathlib.Path, catalog: dict, out: render.Renderer) -> int:
    catalog_mod.write(dir_ / catalog_mod.CATALOG_NAME, catalog)
    # Stamp what was built here, so `tdd --version` describes this dir rather
    # than whatever checkout tdd-exe happens to be linked to.
    version_mod.stamp(dir_)

    config = dir_ / "config.toml"
    if not config.is_file():
        config.write_text(CONFIG_STUB)

    written = _write_source(dir_, out)
    summary = f"initialized {dir_} ({len(catalog['tools'])} tools, {len(catalog['toolsets'])} toolsets)"
    if written:
        summary += (
            f"\n\n  source it to get the `tdd` function:\n\n    source {written}\n"
        )
    return out.ok(
        summary,
        tdd_dir=str(dir_),
        tools=len(catalog["tools"]),
        toolsets=catalog["toolsets"],
        source=str(written) if written else None,
        version=version_mod.shipped(),
    )


def _write_source(dir_: pathlib.Path, out: render.Renderer) -> pathlib.Path | None:
    """Install tdd-source.sh, with this tdd dir baked in.

    The template ships inside the shell package, so it is versioned with the
    commands it loads. Baking the dir is what lets several tdd dirs each have a
    tdd-source.sh that points at itself.
    """
    python = paths.venvs_dir(dir_) / SHELL_ENV / "bin" / "python"
    if not python.is_file():
        out.warn("shell env missing; tdd-source.sh not written")
        return None

    found = subprocess.run(
        [
            str(python),
            "-c",
            "from tabsdata_dev.shell import source_template;"
            "print(source_template(), end='')",
        ],
        capture_output=True,
        text=True,
    )
    if found.returncode != 0:
        out.warn(f"tdd-source.sh not written: {found.stderr.strip()}")
        return None

    target = dir_ / SOURCE_NAME
    target.write_text(found.stdout.replace("__TDD_DIR__", str(dir_)))
    target.chmod(0o644)
    return target
