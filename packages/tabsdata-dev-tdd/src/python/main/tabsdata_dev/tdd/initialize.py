#
# Copyright 2026 Tabsdata Inc.
#

"""Materializing a tdd dir: one venv per toolset, plus the shell env.

Standard library only.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from . import catalog as catalog_mod
from . import generate as generate_mod
from . import paths
from . import version as version_mod

LOCK_SUFFIX = ".lock"
SHELL_DIST = "tabsdata-dev-shell"
SHELL_ENV = "shells"
TDD_DIST = "tabsdata-dev-tdd"
TDD_ENV = "tdd"
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


def initialize(
    dir_: pathlib.Path, relock: bool = False, from_wheels: bool = False
) -> int:
    """Materialize one venv per toolset, the shell env, and tdd-source.sh.

    Two modes. The default builds from the source checkout with editable
    installs -- the development loop, where a source edit is live everywhere at
    once. `from_wheels` installs prebuilt wheels and their exported locks out of
    <dir>/wheels instead, needs no checkout at all, and is how a pinned tool set
    travels to a teammate or a CI runner.
    """
    paths.require_uv()
    return _from_wheels(dir_) if from_wheels else _from_source(dir_, relock)


# --------------------------------------------------------------- source mode


def _from_source(dir_: pathlib.Path, relock: bool) -> int:
    root = paths.repo_root()
    if root is None:
        print(
            "tdd: no source repo found; a wheel-installed tdd cannot build envs "
            "from source. Use `tdd-install --from-wheels`.",
            file=sys.stderr,
        )
        return 1

    catalog = generate_mod.generate(root)
    envs = paths.venvs_dir(dir_)
    envs.mkdir(parents=True, exist_ok=True)

    for toolset in catalog["toolsets"]:
        project = root / "packages" / (generate_mod.TOOLSET_PREFIX + toolset)
        target = envs / toolset
        print(f"  syncing toolset {toolset} -> {target}")
        # uv sync would create the env itself, but not relocatably; make it
        # first so sync populates a relocatable venv instead.
        if not target.exists():
            code = _make_venv(target)
            if code != 0:
                return code
        env = _uv_env(UV_PROJECT_ENVIRONMENT=str(target))
        argv = ["uv", "sync", "--quiet", "--project", str(project)]
        if relock:
            argv.append("--upgrade")
        result = subprocess.run(argv, env=env)
        if result.returncode != 0:
            print(f"tdd: failed to sync toolset {toolset}", file=sys.stderr)
            return result.returncode

    # tdd-exe and the shell commands get their own envs inside the tdd dir, so
    # nothing has to be installed globally and no venv has to be active for
    # `tdd` to work.
    for env_name, dist, label in (
        (TDD_ENV, TDD_DIST, "tdd-exe"),
        (SHELL_ENV, SHELL_DIST, "shell commands"),
    ):
        target = envs / env_name
        print(f"  installing {label} -> {target}")
        # Neither is a uv project, so unlike the toolsets they must be created
        # before anything can be installed into them.
        code = _make_venv(target)
        if code != 0:
            return code
        code = _venv_install(target, ["--editable", str(root / "packages" / dist)])
        if code != 0:
            return code

    return _finish(dir_, catalog)


# --------------------------------------------------------------- wheels mode


def _from_wheels(dir_: pathlib.Path) -> int:
    """Install each toolset from wheels plus exported locks in <dir>/wheels."""
    wheels = dir_ / "wheels"
    if not wheels.is_dir() or not any(wheels.glob("*.whl")):
        print(
            f"tdd: no wheels in {wheels}; run `cargo make install` "
            f"(or `cargo make install -- --dir {dir_}`) first",
            file=sys.stderr,
        )
        return 1

    # The shipped catalog is the source of truth here -- there is no repo to
    # discover from, which is the whole point of this mode.
    catalog = catalog_mod.shipped()
    envs = paths.venvs_dir(dir_)
    envs.mkdir(parents=True, exist_ok=True)

    for toolset in catalog["toolsets"]:
        code = _install_locked(
            envs / toolset,
            wheels,
            wheels / f"{toolset}{LOCK_SUFFIX}",
            catalog["members"][toolset],
            label=f"toolset {toolset}",
        )
        if code != 0:
            return code

    for env_name, dist, label in (
        (TDD_ENV, TDD_DIST, "tdd-exe"),
        (SHELL_ENV, SHELL_DIST, "shell commands"),
    ):
        code = _install_locked(
            envs / env_name,
            wheels,
            wheels / f"{env_name}{LOCK_SUFFIX}",
            [dist],
            label=label,
        )
        if code != 0:
            return code

    return _finish(dir_, catalog)


def _install_locked(
    target: pathlib.Path,
    wheels: pathlib.Path,
    lock: pathlib.Path,
    dists: list[str],
    label: str,
) -> int:
    """Install `dists` into `target` against an exported lock.

    Third-party dependencies come from the lock -- pinned and hashed, straight
    off the toolset's committed uv.lock. The first-party wheels then go in with
    --no-deps, so the resolver never reopens a decision the lock already made.
    That is what makes wheels mode reproducible rather than a fresh resolution.
    """
    if not lock.is_file():
        print(
            f"tdd: missing {lock.name} beside the wheels; "
            f"rebuild with `cargo make wheels`",
            file=sys.stderr,
        )
        return 1

    print(f"  installing {label} -> {target}")
    code = _make_venv(target)
    if code != 0:
        return code

    if lock.read_text().strip() and not _lock_is_empty(lock):
        code = _venv_install(target, ["--require-hashes", "-r", str(lock)])
        if code != 0:
            print(f"tdd: failed to install {lock.name}", file=sys.stderr)
            return code

    # --refresh because uv caches wheels by filename, and a rebuilt first-party
    # wheel keeps its name (same VERSION) while its contents change. Without it
    # the env silently gets the previous build. Third-party wheels above are
    # immutable per version, so they keep using the cache.
    code = _venv_install(
        target, ["--refresh", "--no-deps", "--find-links", str(wheels), *dists]
    )
    if code != 0:
        print(f"tdd: failed to install {label}", file=sys.stderr)
    return code


def _lock_is_empty(lock: pathlib.Path) -> bool:
    """An export with no third-party dependencies is comments only."""
    return not any(
        line.strip() and not line.lstrip().startswith("#")
        for line in lock.read_text().splitlines()
    )


def _venv_install(target: pathlib.Path, args: list[str]) -> int:
    return subprocess.run(
        ["uv", "pip", "install", "--quiet", "--python", str(target), *args],
        env=_uv_env(),
    ).returncode


def _uv_env(**extra: str) -> dict[str, str]:
    return dict(os.environ, **RELOCATABLE_ENV, **extra)


def _make_venv(target: pathlib.Path) -> int:
    """Create a relocatable venv. Copies rather than hardlinks from the cache,
    so the result survives being archived or moved to another filesystem.

    --clear because re-running init over an existing tdd dir is the documented
    way to pick up a dependency change, and uv refuses to overwrite a venv
    without it. A rebuilt env starts empty, which is what "re-init" should mean.
    """
    return subprocess.run(
        ["uv", "venv", "--quiet", "--clear", "--relocatable", str(target)],
        env=_uv_env(),
    ).returncode


# --------------------------------------------------------------- shared tail


def _finish(dir_: pathlib.Path, catalog: dict) -> int:
    catalog_mod.write(dir_ / catalog_mod.CATALOG_NAME, catalog)
    # Stamp what was built here, so `tdd --version` describes this dir rather
    # than whatever checkout tdd-exe happens to be linked to.
    version_mod.stamp(dir_)

    config = dir_ / "config.toml"
    if not config.is_file():
        config.write_text(CONFIG_STUB)

    written = _write_source(dir_)

    print(
        f"  initialized {dir_} "
        f"({len(catalog['tools'])} tools, {len(catalog['toolsets'])} toolsets)"
    )
    if written:
        print(f"\n  source it to get the `tdd` function:\n\n    source {written}\n")
    return 0


def _write_source(dir_: pathlib.Path) -> pathlib.Path | None:
    """Install tdd-source.sh, with this tdd dir baked in.

    The template ships inside the shell package, so it is versioned with the
    commands it loads. Baking the dir is what lets several tdd dirs each have a
    tdd-source.sh that points at itself.
    """
    python = paths.venvs_dir(dir_) / SHELL_ENV / "bin" / "python"
    if not python.is_file():
        print("tdd: shell env missing; tdd-source.sh not written", file=sys.stderr)
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
        print(f"tdd: {found.stderr.strip()}", file=sys.stderr)
        return None

    target = dir_ / SOURCE_NAME
    target.write_text(found.stdout.replace("__TDD_DIR__", str(dir_)))
    target.chmod(0o644)
    return target
