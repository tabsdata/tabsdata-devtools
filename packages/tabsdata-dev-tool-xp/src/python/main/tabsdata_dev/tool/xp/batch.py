#
# Copyright 2026 Tabsdata Inc.
#
"""A one-shot over many suite selectors: ``--suite ALL`` (every suite dir) or a
comma list of selectors. Each selector is a full ``tdd xp one-shot --suite SEL``
of its own, run as a child through the generic batch -- one at a time unless
``TDD_PARALLELISM`` is set, since every child provisions domains on the same
systems and instance. Its output streams as ``[SEL] line`` rows as it is
written; ``--fail-fast`` and ``--report`` mean what they mean for ``tdd system``
and ``tdd domain`` lists.
"""

from __future__ import annotations

import argparse
import os
import pathlib

from tabsdata_dev.common.core import batch as core_batch
from tabsdata_dev.common.core import render

from . import domains, shell, state, suites
from .lanes import child_argv

ALL = "ALL"


def _names(spec: str) -> list[str]:
    return list(
        dict.fromkeys(n.strip().strip("/") for n in spec.split(",") if n.strip())
    )


def _is_all(spec: str) -> bool:
    names = _names(spec)
    return len(names) == 1 and names[0].upper() == ALL


def is_batch(spec: str) -> bool:
    """Whether --suite names many selectors (a comma list or ALL)."""
    return len(_names(spec)) > 1 or _is_all(spec)


def selectors(spec: str, root: pathlib.Path) -> list[str]:
    """ALL: every suite dir under `root` holding a definition, by name. A list:
    its selectors, each resolved up front so a typo fails before anything runs."""
    if _is_all(spec):
        return sorted(
            p.name for p in root.iterdir() if p.is_dir() and suites.lane_files(p)
        )
    names = _names(spec)
    for name in names:
        suites.resolve(name, root)
    return names


def _passthrough(args: argparse.Namespace) -> list[str]:
    words: list[str] = []
    if getattr(args, "suites_dir", None):
        words += [
            "--suites-dir",
            str(pathlib.Path(args.suites_dir).expanduser().resolve()),
        ]
    for flag, value in (
        ("--tags", getattr(args, "tags", None)),
        ("--skip-tags", getattr(args, "skip_tags", None)),
        ("--profile", getattr(args, "profile", None)),
    ):
        if value:
            words += [flag, value]
    secret_env = getattr(args, "secret_env", None)
    if secret_env and secret_env != state.DEFAULT_SECRET_ENV:
        words += ["--secret-env", secret_env]
    for flag, on in (
        ("--keep", getattr(args, "keep", False)),
        ("--no-actions", getattr(args, "no_actions", False)),
        ("--fail-fast", getattr(args, "fail_fast", False)),
        ("--dry-run", getattr(args, "dry_run", False)),
        ("--verbose", getattr(args, "verbose", False)),
    ):
        if on:
            words.append(flag)
    return words


def _workers(count: int) -> int:
    if os.environ.get(core_batch.ENV_PARALLELISM, "").strip():
        return max(1, min(count, core_batch.parallelism()))
    return 1


class Reporter(core_batch.Reporter):
    """`[SEL] line` rows as each child writes them, and a line per selector as
    it ends; the run's opening line and outcome are the command's own."""

    def __init__(self, out: render.Renderer):
        super().__init__(out, "one-shot", "suite")

    def begin(self, tasks, workers, heaviest_first) -> None:
        pass

    def start(self, task: core_batch.Task) -> None:
        self.out.info(f"▶ one-shot --suite {task.name}", suite=task.name)

    def line(self, task: core_batch.Task, line: str) -> None:
        text = f"[{task.name}] {line}"
        if self.out.fmt == "json":
            self.out.info(text, suite=task.name, line=line)
            return
        print(text, file=self.out.out, flush=True)

    def end(self, task: core_batch.Task, done: int, total: int) -> None:
        text = f"[{done}/{total}] {task.name} {task.status.upper()} ({task.seconds}s)"
        fields = dict(suite=task.name, status=task.status, seconds=task.seconds)
        (self.out.info if task.status == "ok" else self.out.warn)(text, **fields)


def cmd_one_shot(args: argparse.Namespace) -> tuple[str, dict]:
    for flag, value in (
        ("--suite-run", getattr(args, "suite_run", None)),
        ("--project", getattr(args, "project", None)),
    ):
        if value:
            state.die(
                f"{flag} names a single suite run; --suite {args.suite} runs many"
            )
    root = suites.suites_dir(getattr(args, "suites_dir", None))
    names = selectors(args.suite, root)
    if not names:
        state.die(f"no suite dirs under {root}")
    domains.require_crypto_key()
    shell.require_login()
    passthrough = _passthrough(args)
    tasks = [
        core_batch.Task(
            name, 0, [child_argv("one-shot", "--suite", name, *passthrough)]
        )
        for name in names
    ]
    workers = _workers(len(tasks))
    out = state.run.out
    out.info(
        f"one-shot: {len(tasks)} suite selector(s), "
        + ("one at a time" if workers == 1 else f"{workers} at a time")
        + f": {', '.join(names)}",
        suites=names,
        parallelism=workers,
    )
    core_batch.execute(
        "one-shot",
        tasks,
        None,
        out,
        role="suite",
        fail_fast=bool(getattr(args, "fail_fast", False)),
        report_path=getattr(args, "report", None),
        final=False,
        workers=workers,
        heaviest_first=False,
        reporter=Reporter(out),
    )
    failed = [t.name for t in tasks if t.status == "fail"]
    stopped = [t.name for t in tasks if t.status in ("aborted", "skipped")]
    if failed or stopped:
        message = f"{len(failed)} of {len(tasks)} suite selector(s) failed"
        if failed:
            message += f": {', '.join(failed)}"
        if stopped:
            message += f"; not run after the failure: {', '.join(stopped)}"
        state.die(message)
    return f"{len(tasks)} suite selector(s) passed: {', '.join(names)}", {
        "suites": names
    }
