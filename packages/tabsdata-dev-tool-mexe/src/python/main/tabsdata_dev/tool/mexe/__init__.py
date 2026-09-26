#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd mexe`` -- run a shell command in several directories.

    tdd mexe --dirs DIR[,DIR...] [--execution parallel|serial]
             [--on-error continue|abort] [--output immediate|on-completion]
             [--] COMMAND [ARG...]

Everything after mexe's own options is the command, options included:
`tdd mexe --dirs a,b git log --oneline -3`. Several words are one command,
each word passed as typed; one argument is a shell line, verbatim, which is
how pipes, redirections and `&&` get through the caller's shell:
`tdd mexe --dirs a,b "git log -1 | head -3"`.

The shell is the family tdd is loaded in, not the OS: `pwsh` under PowerShell
(macOS, Linux or Windows), `$SHELL` (else `sh`) under the POSIX loader. The
environment is the caller's, with tdd's own toolset `bin/` taken back off PATH
and the managed venv of `tdd venv`, when one is active, put first -- so
`python` in a command is the user's, never tdd's.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import shlex
import shutil
import sys

from tabsdata_dev.common.core import batch, cli, config, managedvenv, render
from tabsdata_dev.common.core.errors import ToolError

NAME = "mexe"
DESCRIPTION = "run shell commands in several directories, in parallel or serial (one after the other)"

PARALLEL, SERIAL = "parallel", "serial"
CONTINUE, ABORT = "continue", "abort"
IMMEDIATE, ON_COMPLETION = "immediate", "on-completion"

#: Exported by each loader (reqs.FAMILY_ENV in tabsdata-dev-tdd, which this
#: package cannot import): the shell the user is in, not the OS it runs on.
FAMILY_ENV = "_TDD_SHELL_FAMILY"
POWERSHELL = "powershell"

#: The last lines of a failed directory's output that the failure log keeps
#: per directory; the terminal already showed them all.
TAIL = 40


# ------------------------------------------------------------------ the shell
def user_path() -> list[str]:
    """PATH without the venv this tool runs from.

    tdd puts the toolset's `bin/` first, and that venv is tdd's own: a command
    finding `python` there would run tdd's interpreter. Everything after it is
    the user's PATH, the active venv's `bin/` included.
    """
    own = str(pathlib.Path(sys.executable).parent)
    return [p for p in os.environ.get("PATH", "").split(os.pathsep) if p and p != own]


#: Put before a pwsh command so what it writes is UTF-8 (see shell_argv).
PWSH_UTF8 = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "


def powershell() -> bool:
    """Whether commands run in pwsh: the family the loader exported, and on
    Windows with none exported too -- there is no POSIX shell to assume."""
    family = os.environ.get(FAMILY_ENV, "").strip()
    return family == POWERSHELL or (not family and os.name == "nt")


def shell_argv(command: str, path: list[str]) -> list[str]:
    """The argv that runs `command` in the user's shell.

    Not through `proc.run` and not in bin-reqs.txt: the shell is whichever one
    the user is in, known only at run time, and a declared binary is a fixed
    name. It is always present -- it is what the user typed `tdd` into.
    """
    search = os.pathsep.join(path)
    if powershell():
        pwsh = shutil.which("pwsh", path=search)
        if not pwsh:
            raise ToolError("pwsh is not on PATH; the PowerShell family needs it")
        # -NoProfile: a profile is the user's interactive setup, slow and
        # chatty, and a command meant for several directories must not depend
        # on it -- the POSIX side's `-c` reads no rc file either. UTF-8 out,
        # since the batch reads it as UTF-8: pwsh on Windows writes a pipe in
        # the console's code page, and any non-ASCII line came back mangled.
        return [
            pwsh,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"{PWSH_UTF8}{command}",
        ]
    shell = os.environ.get("SHELL", "").strip() or shutil.which("sh", path=search)
    if not shell:
        raise ToolError("no shell to run the commands in: $SHELL is unset, no sh")
    return [shell, "-c", command]


#: A word PowerShell reads as itself in argument position. Narrower than
#: POSIX's: `,` makes an array, `@` splats, `$` expands, `;` ends a statement.
PWSH_SAFE = re.compile(r"^[\w./\\:=+-]+$")


def pwsh_quote(word: str) -> str:
    if PWSH_SAFE.match(word):
        return word
    return "'" + word.replace("'", "''") + "'"


def command_line(words: list[str]) -> str:
    """What the shell is handed: one word as the line it is, several as one
    command whose words each reach the program as typed.

    One argument is how a user writes shell syntax -- the caller's shell would
    otherwise act on a `|` itself -- so it is kept verbatim. Several were
    already split by the caller's shell, and joining them bare would split
    `-m "a message"` a second time, so each is quoted for the shell that runs
    it. PowerShell runs a quoted program name only through `&`.
    """
    if len(words) == 1:
        return words[0]
    if powershell():
        quoted = [pwsh_quote(w) for w in words]
        head = "& " if quoted[0] != words[0] else ""
        return head + " ".join(quoted)
    return shlex.join(words)


def split_presets(
    words: list[str], tables: dict[str, dict]
) -> tuple[list[str], dict[str, object]]:
    """The command without the presets tdd appended to it, and those presets.

    tdd merges `<tdd_dir>/mexe.toml` in by appending every option not typed
    (tabsdata_dev.tdd.defaults), and after a command given without `--` the
    end of the line is the command's: they would run as its arguments. They
    are appended in the table's order, so they are peeled off in reverse, each
    only when the line ends with exactly its tokens. With `--` tdd puts them
    before it, and there is nothing to peel.
    """
    found: dict[str, object] = {}
    for key, value in reversed(list(tables.get("", {}).items())):
        tokens = config.to_argv(key, value)
        if tokens and len(words) > len(tokens) and words[-len(tokens) :] == tokens:
            words = words[: -len(tokens)]
            found[key.replace("-", "_")] = value
    return words, found


# ------------------------------------------------------------------- the venv
def venv_dirs(manager: str, where: pathlib.Path) -> list[pathlib.Path]:
    """The directories activating the venv puts first on PATH."""
    if os.name == "nt":
        if manager == "conda":
            return [where, where / "Scripts", where / "Library" / "bin"]
        return [where / "Scripts"]
    return [where / "bin"]


def child_env() -> tuple[dict[str, str], str | None]:
    """The commands' environment, and the managed venv it is in (or None).

    A managed venv is the one `tdd venv` exported in `_TDD_VENV`, or the one
    the environment is in by path (`managedvenv.adopted`). Its directories go
    first on PATH, as activation puts them, rather than running each command
    through the venv's manager as the launchers do: the program here is a
    shell, and `conda run`/`uv run` would wrap a shell in a shell for nothing.
    A venv named but broken is an error -- the user believes they are in it.
    """
    env = dict(os.environ)
    # tdd warns off a _TDD_TOOL found exported in a shell; a nested tdd-exe
    # would otherwise enforce this tool's bin-reqs against itself.
    env.pop("_TDD_TOOL", None)
    path = user_path()
    name = os.environ.get(managedvenv.ENV_ACTIVE, "").strip() or managedvenv.adopted()
    if name:
        manager, where = managedvenv.resolve(name)
        first = [str(d) for d in venv_dirs(manager, where)]
        path = first + [p for p in path if p not in first]
        env["CONDA_PREFIX" if manager == "conda" else "VIRTUAL_ENV"] = str(where)
    env["PATH"] = os.pathsep.join(path)
    return env, name or None


# ------------------------------------------------------------------ the runs
def parse_dirs(value: str) -> list[batch.Task]:
    """One task per directory in `value`, each checked before anything runs:
    a typo found after half the directories ran is half a run to undo. The
    directory as given is the task's name and its `[DIR]` label."""
    labels: list[str] = []
    for raw in (value or "").split(","):
        label = raw.strip().rstrip("/\\") or raw.strip()
        if label and label not in labels:
            labels.append(label)
    if not labels:
        raise ToolError("--dirs needs at least one directory")
    tasks = [
        batch.Task(label, 0, cwd=pathlib.Path(label).expanduser()) for label in labels
    ]
    missing = [t.name for t in tasks if not t.cwd.is_dir()]  # type: ignore[union-attr]
    if missing:
        raise ToolError(f"not a directory: {', '.join(missing)}")
    return tasks


def as_dict(task: batch.Task) -> dict:
    return {
        "dir": task.name,
        "status": task.status,
        "returncode": task.returncode,
        "seconds": task.seconds,
    }


class Reporter(batch.Reporter):
    """mexe's wording on the batch's run: `[DIR] line` rows, as they arrive or
    per directory when it finishes, and a line only for a directory that did
    not succeed."""

    def __init__(self, out: render.Renderer, immediate: bool):
        super().__init__(out, NAME, "dir")
        self.immediate = immediate

    def _row(self, task: batch.Task, line: str) -> None:
        text = f"[{task.name}] {line}"
        if self.out.fmt == "json":
            self.out.info(text, dir=task.name, line=line)
            return
        # In view, the commands' output is the result, so it goes where the
        # result goes -- stdout, for `| grep` -- as it arrives: an `ok` message
        # would hold it until the end. Written as is, like a launcher passing
        # its program's output through; the renderer keeps stdout for `ok`.
        print(text, file=self.out.out, flush=True)

    def begin(self, tasks, workers, heaviest_first) -> None:
        pass  # the body has said it, with the venv

    def start(self, task: batch.Task) -> None:
        pass

    def line(self, task: batch.Task, line: str) -> None:
        if self.immediate:
            self._row(task, line)

    def end(self, task: batch.Task, done: int, total: int) -> None:
        if not self.immediate and task.output:
            for line in task.output.split("\n"):
                self._row(task, line)
        took = f"{task.seconds:.1f}s"
        if task.status == "ok":
            self.out.debug(f"[{task.name}] ok ({took})", **as_dict(task))
        elif task.status == "fail":
            self.out.warn(
                f"[{task.name}] failed, exit {task.returncode} ({took})",
                **as_dict(task),
            )
        else:
            self.out.warn(f"[{task.name}] {task.status}", **as_dict(task))


# ------------------------------------------------------------------- the body
def _details(tasks: list[batch.Task]) -> str:
    blocks = []
    for task in tasks:
        if task.status != "fail":
            continue
        tail = task.output.split("\n")[-TAIL:]
        blocks.append(
            f"[{task.name}] exit {task.returncode}\n"
            f"cwd: {task.cwd.resolve()}\n" + "\n".join(tail)  # type: ignore[union-attr]
        )
    return "\n\n".join(blocks)


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    words = list(args.command)
    if words[:1] == ["--"]:
        words = words[1:]
    else:
        words, presets = split_presets(words, config.options_in(NAME))
        for key, value in presets.items():
            setattr(args, key, value)
    if not args.dirs:
        raise ToolError("--dirs is required (see --help)")
    tasks = parse_dirs(args.dirs)
    if not words or not "".join(words).strip():
        raise ToolError("no command to run (see --help)")
    command = command_line(words)
    env, venv = child_env()
    argv = shell_argv(command, env["PATH"].split(os.pathsep))
    for task in tasks:
        task.steps = [argv]
    workers = min(batch.parallelism(), len(tasks)) if args.execution == PARALLEL else 1
    out.debug(f"shell: {argv[0]}")
    out.debug(f"venv: {venv or 'none'}")
    out.debug(f"command: {command}")
    out.info(
        f"{len(tasks)} dir(s), "
        + (f"{workers} at a time" if workers > 1 else "one at a time")
        + (f", venv {venv}" if venv else "")
    )
    batch.execute(
        NAME,
        tasks,
        None,  # streamed: the batch launches each shell, in its directory
        out,
        final=False,
        workers=workers,
        heaviest_first=False,
        kill_on_fail=args.on_error == ABORT,
        env=env,
        reporter=Reporter(out, immediate=args.output == IMMEDIATE),
    )

    fields = {
        "command_line": command,
        "venv": venv,
        "dirs": [as_dict(t) for t in tasks],
    }
    failed = [t.name for t in tasks if t.status == "fail"]
    stopped = [t.name for t in tasks if t.status in ("aborted", "skipped")]
    if failed:
        message = f"{len(failed)} of {len(tasks)} dir(s) failed: {', '.join(failed)}"
        if stopped:
            message += f"; not finished after the abort: {', '.join(stopped)}"
        return out.error(message, details=_details(tasks), **fields)
    return out.ok(f"{len(tasks)} dir(s): every command succeeded", **fields)


def configure(p: argparse.ArgumentParser) -> None:
    p.description = (
        f"{DESCRIPTION}. Everything after mexe's options is the command, its own "
        "options included, so mexe's options come first (`--` ends them when the "
        "command starts with a dash or shares their names). Several words are one "
        "command, each word passed as typed; a single quoted argument is a shell "
        "line, verbatim -- the way to pipe, redirect or chain with && or ;, which "
        "the calling shell would otherwise act on itself. The shell is pwsh "
        "under tdd's PowerShell loader, $SHELL (else sh) under the POSIX one; with "
        "a managed venv active (tdd venv) the commands run inside it. Output lines "
        "are prefixed with [DIR]."
    )
    p.epilog = (
        "examples:\n"
        f"  tdd {NAME} --dirs repo-a,repo-b git log --oneline -3\n"
        f'  tdd {NAME} --dirs a,b --execution serial "uv sync && pytest -q | tail -1"'
    )
    # Not required=True: a --dirs preset in mexe.toml arrives after the command
    # (see split_presets), where argparse cannot see it; the body checks.
    p.add_argument(
        "--dirs",
        metavar="DIR[,DIR...]",
        help="comma-separated directories to run the command in",
    )
    p.add_argument(
        "--execution",
        choices=(PARALLEL, SERIAL),
        default=PARALLEL,
        help="run the directories at the same time (bounded by TDD_PARALLELISM) "
        f"or one after another (default: {PARALLEL})",
    )
    p.add_argument(
        "--on-error",
        choices=(CONTINUE, ABORT),
        default=CONTINUE,
        help="on a directory's failure, let the others finish, or stop them and "
        f"start no more (default: {CONTINUE})",
    )
    p.add_argument(
        "--output",
        choices=(IMMEDIATE, ON_COMPLETION),
        default=IMMEDIATE,
        help="print each line as it comes, or a directory's whole output when it "
        f"finishes (default: {IMMEDIATE})",
    )
    p.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="COMMAND ...",
        help='the command and its arguments, or one quoted shell line: "ls | wc -l"',
    )


def main() -> int:
    return cli.run(NAME, DESCRIPTION, body, configure=configure)
