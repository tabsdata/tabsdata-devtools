#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd smoke`` -- the end-to-end smoke test scripts, carried as data: run one,
or export them to read and edit.

A smoke run is a long shell script: it drives `tdd`, `tdkserver`, `kubectl` and
`xp` through a couple of dozen stages against a real cluster. That is a shell
program, not a Python one, and rewriting it as a tool would buy nothing -- so
the scripts ship inside this package the way xp's suites ship inside xp.

`run` executes the carried copy and hands it every other argument, so a smoke
is one `tdd` command like everything else here; `export-scripts` gives a copy
the user owns, which is what a run being chased needs -- a stage commented out,
an option tried -- and what a machine with a tdd install and no checkout can
run. Both are the same scripts.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import os
import pathlib
import shutil
import sys
from importlib import resources

from tabsdata_dev.common.core import cli, errors, proc, render

DESCRIPTION = (
    "the end-to-end smoke test scripts: run one, or export them to read and edit"
)


#: The scripts of a shell family -- the shell the user is in, not the OS: bash
#: ones under a POSIX shell, PowerShell 7 ones under pwsh. Each family has its
#: own stage engine, `_common`, which every script of it sources: it is not a
#: smoke test, and exporting without it produces scripts that cannot run.
@dataclasses.dataclass(frozen=True)
class Family:
    suffix: str
    runner: tuple[str, ...]

    @property
    def shared(self) -> str:
        return f"_common{self.suffix}"


FAMILIES = {
    "unix": Family(".sh", ("bash",)),
    # -File, not -Command: the path and every argument travel as they are
    "powershell": Family(".ps1", ("pwsh", "-NoProfile", "-File")),
}

#: The bash family's engine, the one that tells the layouts apart.
SHARED = FAMILIES["unix"].shared

#: A smoke script is `smoke-<name>` in its family's suffix; `<name>` is what
#: `run --script` takes.
PREFIX = "smoke-"

#: The checkout keeps them here, at the repo root, where they are edited and
#: run; a wheel build copies them in beside this module (force-include).
CHECKOUT_DIR = "smoke-tool"

RUN = "run"
SCRIPT_OPTION = "--script"
HELP_FLAGS = ("-h", "--help")


def scripts_dir() -> pathlib.Path:
    """Where the scripts actually are.

    A wheel install has them beside this module. An editable install copies
    nothing -- a link has no build step to hook -- so there they are still at
    the repo root, which is where they are meant to be read and edited anyway.
    Both layouts are normal; check for the shared engine to tell them apart.
    """
    beside = pathlib.Path(str(resources.files("tabsdata_dev.tool.smoke") / "scripts"))
    if (beside / SHARED).is_file():
        return beside
    # .../packages/<pkg>/src/python/main/tabsdata_dev/tool/smoke -> the repo
    checkout = pathlib.Path(str(resources.files("tabsdata_dev.tool.smoke")))
    repo = checkout.parents[7] / CHECKOUT_DIR
    if (repo / SHARED).is_file():
        return repo
    raise FileNotFoundError(f"smoke scripts not found beside {beside} nor at {repo}")


def family() -> Family:
    """The family of the shell tdd was called from."""
    return FAMILIES[proc.shell_family()]


def scripts(of: Family | None = None) -> list[pathlib.Path]:
    """The family's engine first, then each of its smoke scripts by name."""
    of = of or family()
    found = sorted(scripts_dir().glob(f"*{of.suffix}"))
    shared = [p for p in found if p.name == of.shared]
    return shared + [p for p in found if p.name != of.shared]


def _bare(path: pathlib.Path) -> str:
    return path.stem[len(PREFIX) :]


def script_names(of: Family | None = None) -> list[str]:
    """What `run --script` takes: `eks`, `aks`, `gke`, `km` -- those the
    family has."""
    of = of or family()
    return [_bare(p) for p in scripts(of) if p.name != of.shared]


def resolve_script(name: str, of: Family | None = None) -> pathlib.Path:
    """`eks`, `smoke-eks` or `smoke-eks.sh` -> the family's carried script;
    anything else names the choices. The engine is not a script to run."""
    of = of or family()
    bare = name
    for suffix in (f.suffix for f in FAMILIES.values()):
        bare = bare.removesuffix(suffix)
    bare = bare.removeprefix(PREFIX)
    path = scripts_dir() / f"{PREFIX}{bare}{of.suffix}"
    if not bare or "/" in bare or "\\" in bare or not path.is_file():
        raise errors.ToolError(
            f"no smoke script {name!r}; one of: {', '.join(script_names(of))}"
        )
    return path


def summary(script: pathlib.Path) -> str:
    """What the script says it is: the first comment line after the licence
    header, cut to its first sentence, its own file name dropped."""
    for raw in script.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("#") or line.startswith("#!"):
            continue
        text = line.lstrip("#").strip()
        if not text or text.startswith("Copyright"):
            continue
        if text.startswith(script.name):
            text = text[len(script.name) :].lstrip(" -")
        return text.split(". ", 1)[0].rstrip(".")
    return ""


def split_run(argv: list[str]) -> tuple[list[str], list[str]]:
    """What the parser sees, and what the script gets.

    `run` owns one option, `--script`, taken from anywhere after the word: `tdd`
    appends a config preset at the END of the line, so it cannot be assumed to
    come first. `-h`/`--help` is the tool's until the script is named; once it
    is, every token is the script's, help included -- the person asking has
    named what they want to read about. A `--` opening the script's part is
    dropped, since the scripts' own parsers would refuse it. A line that is not
    a `run` passes through unchanged.
    """
    action_at = None
    skip = False
    for i, tok in enumerate(argv):
        if skip:
            skip = False
            continue
        if tok == "--format":
            skip = True
            continue
        if tok.startswith("-"):
            continue
        action_at = i
        break
    if action_at is None or argv[action_at] != RUN:
        return list(argv), []
    head, tail = list(argv[: action_at + 1]), []
    rest = argv[action_at + 1 :]
    named = False
    j = 0
    while j < len(rest):
        tok = rest[j]
        if tok == SCRIPT_OPTION:
            head.extend(rest[j : j + 2])
            named = True
            j += 2
        elif tok.startswith(SCRIPT_OPTION + "="):
            head.append(tok)
            named = True
            j += 1
        elif tok in HELP_FLAGS and not named and not tail:
            head.append(tok)
            j += 1
        else:
            tail.append(tok)
            j += 1
    if tail[:1] == ["--"]:
        tail = tail[1:]
    return head, tail


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
    shared = family().shared
    names = ", ".join(p.name for p in found if p.name != shared)
    return out.ok(
        f"exported {len(found)} file(s) to {target}: {names} (and {shared})",
        dir=str(target),
        files=[p.name for p in found],
    )


def run_script(
    script: pathlib.Path, script_args: list[str], out: render.Renderer
) -> int:
    """The carried copy, through its family's shell -- bash, or pwsh -File;
    the wheel keeps no exec bit, and Windows has none to keep -- in the
    user's cwd, on the terminal it was called from. `TDD_DIR` travels on, so the
    script's `--tdd-dir` defaults to the dir this tool runs from; `_TDD_TOOL`
    does not: it is tdd-exe's word to this process, and the sourced `tdd`
    function warns about a shell that carries one. Exit 0 stays 0; anything
    else is one error event with the status, the launchers' way -- the script
    has already said what failed and where its own log is."""
    env = {k: v for k, v in os.environ.items() if k != "_TDD_TOOL"}
    argv = [*family().runner, str(script), *script_args]
    out.debug(f"exec {' '.join(argv)}", script=str(script))
    try:
        done = proc.run(argv, env=env)
    except KeyboardInterrupt:
        out.warn(f"{script.name} interrupted")
        return 1
    if done.returncode != 0:
        return out.error(
            f"{script.name} exited with status {done.returncode}",
            status=done.returncode,
            script=str(script),
        )
    return 0


def configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", metavar="SUBCOMMAND")
    run_p = sub.add_parser(
        RUN,
        help="run one of the carried scripts, handing it every other argument",
        description=(
            "Run the carried copy of smoke-NAME (.sh under a POSIX shell, .ps1 "
            "under PowerShell). Everything on the line other "
            "than --script is the script's, in order: `tdd smoke run --script eks "
            "--name NAME --kube-config FILE ...`, --profile NAME (the tdk "
            "connection, default sm_NAME) included. `--script NAME --help` shows "
            "that script's own page. The script runs in the current directory "
            "against the tdd dir this command runs from; its exit status is the "
            "verdict."
        ),
    )
    run_p.add_argument(
        SCRIPT_OPTION,
        required=True,
        metavar="NAME",
        help="which script: eks, aks, gke or km (smoke-NAME; `tdd smoke list`)",
    )
    run_p.add_argument(
        "script_options",
        nargs="*",
        metavar="SCRIPT-OPTION",
        help="the script's own options, e.g. --name NAME --td-version VERSION",
    )
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
        "list",
        help="the smoke scripts this tool carries, what each is, and how to run it",
        description=(
            "List the packaged smoke scripts without writing anything. The stage "
            "engine they share (_common) is not a script to run and is not "
            "listed; export-scripts carries it along."
        ),
    )


def body(
    args: argparse.Namespace, out: render.Renderer, script_args: list[str] = ()
) -> int:
    if args.action == RUN:
        return run_script(resolve_script(args.script), list(script_args), out)
    if args.action == "export-scripts":
        return export(pathlib.Path(args.dir), args.force, out)
    if args.action == "list":
        # the scripts a person can run; the engine they source is not one of
        # them, and the export is what carries it along
        shared = family().shared
        found = [p for p in scripts() if p.name != shared]
        width = max(len(p.name) for p in found)
        for script in found:
            how = f"tdd smoke run --script {_bare(script)}"
            out.info(f"{script.name:<{width}}  {summary(script)}   ({how})")
        return out.ok(
            f"{len(found)} script(s) at {scripts_dir()}",
            dir=str(scripts_dir()),
            scripts=script_names(),
            engine=shared,
        )
    return out.error("no action given (see --help)")


def main() -> int:
    # The script's arguments never reach the parser: they are the script's.
    head, script_args = split_run(sys.argv[1:])
    return cli.run(
        "smoke",
        DESCRIPTION,
        functools.partial(body, script_args=script_args),
        configure=configure,
        argv=head,
    )
