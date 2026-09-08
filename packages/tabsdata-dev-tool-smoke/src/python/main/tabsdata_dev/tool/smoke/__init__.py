#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd smoke`` -- the end-to-end smoke test scripts, carried as data.

A smoke run is a long shell script: it drives `tdd`, `tdkserver`, `kubectl` and
`xp` through a couple of dozen stages against a real cluster. That is a shell
program, not a Python one, and rewriting it as a tool would buy nothing -- so
the scripts ship inside this package the way xp's suites ship inside xp, and the
one thing the tool does is put them somewhere a person can run them.

Exporting rather than running them is the point. They are meant to be read and
edited while a run is being chased -- a stage commented out, a `--stop-after`
moved -- and a copy the user owns is the honest way to allow that. It also means
a machine with a tdd install and no checkout can run one.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
from importlib import resources

from tabsdata_dev.common.core import cli, render

#: Every script the export writes. `_common.sh` is not a smoke test but the
#: shared stage engine all of them source, so exporting without it produces four
#: scripts that cannot run.
SHARED = "_common.sh"


def scripts_dir() -> pathlib.Path:
    """The packaged scripts, found the way every resource here is found."""
    return pathlib.Path(str(resources.files("tabsdata_dev.tool.smoke") / "scripts"))


def scripts() -> list[pathlib.Path]:
    """`_common.sh` first, then each smoke script by name."""
    found = sorted(scripts_dir().glob("*.sh"))
    shared = [p for p in found if p.name == SHARED]
    return shared + [p for p in found if p.name != SHARED]


def export(target: pathlib.Path, force: bool, out: render.Renderer) -> int:
    target = target.expanduser()
    found = scripts()
    if not found:
        return out.error(f"no scripts packaged at {scripts_dir()}")
    if not target.exists():
        target.mkdir(parents=True)
        out.info(f"created {target}")
    elif not target.is_dir():
        return out.error(f"not a directory: {target}")
    clashes = [p.name for p in found if (target / p.name).exists()]
    if clashes and not force:
        return out.error(
            f"already in {target}: {', '.join(clashes)} -- "
            f"pass --force to overwrite (an edited copy would be lost)"
        )
    for script in found:
        dest = target / script.name
        shutil.copyfile(script, dest)
        # the mode does not survive the wheel, and a smoke script that cannot be
        # executed is the first thing a person would have to fix by hand
        dest.chmod(0o755)
        out.debug(f"wrote {dest}")
    names = ", ".join(p.name for p in found if p.name != SHARED)
    return out.ok(
        f"exported {len(found)} file(s) to {target}: {names} (and {SHARED})",
        dir=str(target),
        files=[p.name for p in found],
    )


def configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", metavar="SUBCOMMAND")
    export_p = sub.add_parser(
        "export-scripts",
        help="copy the smoke scripts into a directory of your own",
        description=(
            "Copy the packaged smoke scripts into DIR, ready to run. They are "
            "yours once exported: read them, edit them, keep them."
        ),
    )
    export_p.add_argument("--dir", required=True, help="where to write them")
    export_p.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="overwrite scripts already there (default: refuse, so an edited copy survives)",
    )
    sub.add_parser(
        "list-scripts",
        help="the scripts this tool carries",
        description="List the packaged smoke scripts without writing anything.",
    )


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action == "export-scripts":
        return export(pathlib.Path(args.dir), args.force, out)
    if args.action == "list-scripts":
        found = scripts()
        for script in found:
            out.info(script.name)
        return out.ok(f"{len(found)} file(s)", files=[p.name for p in found])
    return out.error("no action given (see --help)")


def main() -> int:
    return cli.run(
        "smoke",
        "the end-to-end smoke test scripts: export them somewhere to run them",
        body,
        configure=configure,
    )
