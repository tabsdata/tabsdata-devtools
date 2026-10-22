#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd pycache`` -- purge packages from the uv and pip caches.

    tdd pycache clean [--package-prefixes tabsdata[,other...]] [--all]

Every first-party wheel keeps its filename across rebuilds -- same VERSION, new
contents -- and uv caches wheels by filename, so yesterday's build can be served
to today's install; a republished index package does the same. Purging by name
prefix is the cure. `uv cache clean` takes exact names and there is no `uv cache
list` to get them from, so the names are derived from what the cache holds.

This was a shell command until 2026-09-18, for no better reason than sitting
beside `venv` in the same toolbox. Changing the calling shell is the only thing
a shell command is for, and this changes nothing there, so it is a tool.
"""

from __future__ import annotations

import argparse
import fnmatch
import itertools
import os
import pathlib
import re
import shutil
import subprocess
import sys

from tabsdata_dev.common.core import cli, proc, render
from tabsdata_dev.common.core.errors import ToolError

NAME = "pycache"
DESCRIPTION = (
    "clean the uv and pip caches, by package prefix (default tabsdata) or all of it"
)

CLEAN = "clean"
DEFAULT_PREFIXES = "tabsdata"

#: What a cached distribution entry's name carries after the version: an index
#: record, a wheel, an sdist. Stripped before the version itself is.
SUFFIX = re.compile(r"\.(rkyv|msgpack|http|rev|whl|tar\.gz|zip)$")
VERSION_TAIL = re.compile(r"-[0-9].*$")
DIST_INFO = ".dist-info"


# ------------------------------------------------------------------ the cache
def cache_dir() -> pathlib.Path:
    """Where uv keeps its cache, asked of uv rather than guessed: it moves with
    UV_CACHE_DIR and differs per platform."""
    done = proc.run(["uv", "cache", "dir"], capture_output=True, encoding="utf-8")
    if done.returncode != 0 or not (done.stdout or "").strip():
        raise ToolError(
            "uv could not say where its cache is", (done.stderr or done.stdout or "")
        )
    return pathlib.Path(done.stdout.strip())


def entry_patterns(prefixes: list[str]) -> list[str]:
    """A versioned distribution entry of each prefix: `<prefix>*-<digit>...`.

    Requiring the version is what keeps a wheel's top-level import package
    (`tabsdata_dev/`) from posing as a distribution called `tabsdata-dev`.
    Lower-case because the match is case-insensitive, as `find -iname` was.
    """
    return [f"{prefix.lower()}*-[0-9]*" for prefix in prefixes]


def scan(root: pathlib.Path, prefixes: list[str]) -> list[pathlib.Path]:
    """Every cache path whose own name is a versioned entry of one of
    `prefixes`, relative to the cache root.

    One walk answers all three questions asked of the cache -- which
    distributions to name, which shards to sweep, what is left afterwards --
    where the shell half ran a separate `find` per prefix per question.
    """
    patterns = entry_patterns(prefixes)
    hits: list[pathlib.Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = pathlib.Path(dirpath).relative_to(root)
        for name in itertools.chain(dirnames, filenames):
            low = name.lower()
            if any(fnmatch.fnmatchcase(low, pattern) for pattern in patterns):
                hits.append(here / name)
    return sorted(hits)


def inside_environment(parts: tuple[str, ...]) -> bool:
    """Whether an entry sits inside a cached environment
    (`archive-v*/<id>/lib/python3.12/site-packages/...`).

    `uv cache clean` cannot address those by name and the archive holding a
    whole environment is uv's to prune, so they are reported, never removed.
    Something has to follow the interpreter directory for the entry to be
    *inside* one, which is what the range leaves room for.
    """
    return any(
        parts[i] == "lib" and parts[i + 1].startswith("python")
        for i in range(len(parts) - 2)
    )


def distribution_name(entry: str) -> str:
    """The name uv knows an entry by: the version and whatever follows it
    dropped, then normalized the way uv normalizes (lower-case, `-` for `_`)."""
    name = entry.removesuffix(DIST_INFO)
    name = SUFFIX.sub("", name)
    name = VERSION_TAIL.sub("", name)
    return name.replace("_", "-").lower()


def sweepable(hits: list[pathlib.Path]) -> list[pathlib.Path]:
    """The shards `uv cache clean` leaves behind, relative to the cache root.

    It keys editable and path builds by the hash of their source directory
    rather than by name, so a name-keyed clean skips them, and `uv cache prune`
    calls them in use. They are exactly what a devtools developer wants gone:
    the per-source shard under `sdists-v*/<kind>/`, and any `archive-v*/<id>`
    whose top level is a matching `.dist-info` -- an unpacked wheel. An archive
    holding a whole environment has no `.dist-info` at its top level and is
    left alone.
    """
    shards: set[pathlib.Path] = set()
    for hit in hits:
        parts = hit.parts
        if fnmatch.fnmatchcase(parts[0], "sdists-v*") and len(parts) >= 4:
            shards.add(pathlib.Path(*parts[:3]))
        elif (
            fnmatch.fnmatchcase(parts[0], "archive-v*")
            and len(parts) == 3
            and parts[-1].endswith(DIST_INFO)
        ):
            shards.add(pathlib.Path(*parts[:2]))
    # Never a bare top-level cache directory, whatever the patterns matched.
    return sorted(s for s in shards if len(s.parts) >= 2)


# -------------------------------------------------------------------- the pip
def search_path() -> str:
    """PATH without the venv this tool is running from.

    tdd puts the toolset's `bin/` first, and that venv is tdd's own: it carries
    a `python3` and no pip, so it must not answer "which pip". Everything after
    it is the user's PATH, the active managed venv's `bin/` included -- which is
    the pip whose cache the user means.
    """
    own = str(pathlib.Path(sys.executable).parent)
    return os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep) if p and p != own
    )


def pip_command() -> list[str] | None:
    """Which pip to drive: a pip on PATH, else `python3 -m pip`, else none."""
    path = search_path()
    pip = shutil.which("pip", path=path)
    if pip and _answers([pip, "--version"]):
        return [pip]
    python = shutil.which("python3", path=path)
    if python and _answers([python, "-m", "pip", "--version"]):
        return [python, "-m", "pip"]
    return None


def _answers(argv: list[str]) -> bool:
    try:
        return _pip_run(argv).returncode == 0
    except OSError:
        return False


def _pip_run(argv: list[str]) -> subprocess.CompletedProcess:
    """Run pip on the user's PATH, deliberately not through `proc.run`.

    pip is optional here: it is found at run time and its absence is a
    supported outcome, a warning and a uv-only clean. `bin-reqs.txt` cannot say
    that -- a declared binary is refused *before* the tool starts when it is
    missing -- so declaring pip would turn the one case this command is built
    to survive into a refusal to run at all. Nothing is guessed in exchange:
    the binary is one `pip_command()` resolved on the user's own PATH.

    The child gets that same PATH, not the one this process inherited. Choosing
    the binary is not enough: a pyenv shim re-resolves `python3` by name from
    what it is handed, and tdd puts its own toolset `bin/` first, so the shim
    would exec tdd's interpreter -- which has no pip -- and the answer would be
    "no pip found" on a machine that has one.
    """
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PATH": search_path()},
    )


# ------------------------------------------------------------------- the body
def _prefixes(value: str) -> list[str]:
    found = [p for p in (value or "").split(",") if p]
    if not found:
        raise ToolError("--package-prefixes needs at least one prefix")
    return found


def _output(done: subprocess.CompletedProcess) -> str:
    return ((done.stdout or "") + (done.stderr or "")).strip()


def _clean_everything(out: render.Renderer, pip: list[str] | None) -> int:
    out.info("uv cache clean")
    done = proc.run(["uv", "cache", "clean"], capture_output=True, encoding="utf-8")
    if done.returncode != 0:
        raise ToolError("uv cache clean failed", _output(done))
    out.debug("uv cache clean: done")
    if pip is not None:
        out.info("pip cache purge")
        purged = _pip_run([*pip, "cache", "purge"])
        if purged.returncode != 0:
            out.warn(f"pip cache purge: {_output(purged)}")
        out.debug("pip cache purge: done")
    return out.ok(
        "purged the whole uv cache"
        + (" and the whole pip cache" if pip is not None else ""),
        scope="all",
        uv=True,
        pip=pip is not None,
    )


def _clean_prefixes(
    args: argparse.Namespace, out: render.Renderer, pip: list[str] | None
) -> int:
    prefixes = _prefixes(args.package_prefixes)
    root = cache_dir()
    hits = scan(root, prefixes)
    addressable = [h for h in hits if not inside_environment(h.parts)]
    names = sorted({distribution_name(h.name) for h in addressable})
    entries = len(addressable)
    swept = 0

    if names:
        out.info(f"uv cache clean ({len(names)} packages, {entries} entries)")
        done = proc.run(
            ["uv", "cache", "clean", *names], capture_output=True, encoding="utf-8"
        )
        if done.returncode != 0:
            raise ToolError("uv cache clean failed", _output(done))
        out.debug("uv: " + " ".join(names))
        said = _output(done).splitlines()
        out.debug("uv cache clean: " + (said[-1] if said else "done"))
        for shard in sweepable(hits):
            shutil.rmtree(root / shard, ignore_errors=True)
            swept += 1
            out.debug(f"swept {shard}")
        out.debug(
            f"swept {swept} editable/path shards and archives uv cache clean skips"
        )
    else:
        out.debug(f"uv: nothing cached under {args.package_prefixes}")

    # Say what is still there rather than claim a purge.
    left = [str(h) for h in scan(root, prefixes)]
    if left:
        out.warn(
            f"{len(left)} uv cache entries still match {args.package_prefixes}; they "
            "sit inside cached environments uv still references (uv cache prune "
            "removes them once unused, --all removes everything): "
            + " ".join(left[:3]),
            left=left,
        )

    if pip is not None:
        # pip matches wheel file names, where `-` became `_`; try both.
        for prefix in prefixes:
            out.info(f"pip cache remove {prefix}*")
            said = [
                _output(_pip_run([*pip, "cache", "remove", glob])).replace("\n", " ")
                for glob in (f"{prefix}*", f"{prefix.replace('-', '_')}*")
            ]
            out.debug("pip: " + " ".join(s for s in said if s))
            out.debug(f"pip cache remove {prefix}*: done")

    pip_note = (
        "; pip: purged matching wheels"
        if pip is not None
        else "; pip: not found, skipped"
    )
    head = (
        f"uv: purged {len(names)} packages ({entries} entries) under "
        f"{args.package_prefixes}"
        if names
        else f"uv: nothing cached under {args.package_prefixes}"
    )
    return out.ok(
        head + pip_note,
        scope="prefixes",
        prefixes=prefixes,
        uv_packages=names,
        pip=pip is not None,
        uv_entries=entries,
        uv_swept=swept,
    )


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action != CLEAN:
        raise ToolError(f"a subcommand is required: {CLEAN} (see --help)")
    pip = pip_command()
    if pip is None:
        out.warn("no pip found; only the uv cache will be cleaned")
    if args.all:
        return _clean_everything(out, pip)
    return _clean_prefixes(args, out, pip)


def _common(sub: argparse.ArgumentParser) -> None:
    """The options every command has, repeated on the subcommand.

    argparse takes a top-level option only before the subcommand word, and the
    guidelines say everything after the command word is the command's -- so
    `tdd pycache clean --all --format json` has to work. SUPPRESS so an unused
    copy here does not overwrite what was given before the word.
    """
    sub.add_argument(
        "--format",
        choices=("json", "view"),
        default=argparse.SUPPRESS,
        help="json is JSON Lines, one event per line (default: view)",
    )
    sub.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show debug events too",
    )


def configure(p: argparse.ArgumentParser) -> None:
    p.epilog = f"example: tdd {NAME} {CLEAN} --package-prefixes tabsdata,td-"
    sub = p.add_subparsers(dest="action", metavar="SUBCOMMAND")
    clean = sub.add_parser(
        CLEAN,
        help="purge the caches, by package name prefix or entirely",
        description=(
            "Remove packages from the uv cache and the pip cache. Package names come "
            "from the versioned entries the caches hold, since `uv cache clean` wants "
            "exact names; editable and path builds are keyed by source hash rather "
            "than by name, so uv skips them and they are swept by hand, along with "
            "their unpacked archives. An entry inside a cached environment uv still "
            "references is reported, not removed (`uv cache prune` takes those once "
            "unused, and --all takes everything). pip is done by prefix too, in both "
            "the - and _ spellings, and no pip on PATH is a warning and a uv-only "
            "clean."
        ),
    )
    clean.add_argument(
        "--package-prefixes",
        default=DEFAULT_PREFIXES,
        metavar="PREFIXES",
        help=(
            "comma-separated name prefixes; every cached package whose name starts "
            f"with one is purged (default: {DEFAULT_PREFIXES})"
        ),
    )
    clean.add_argument(
        "--all",
        action="store_true",
        help="purge both caches entirely instead",
    )
    _common(clean)


def main() -> int:
    return cli.run(NAME, DESCRIPTION, body, configure=configure)
