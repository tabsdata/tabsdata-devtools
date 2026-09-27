#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd ci`` -- GitHub Actions runs.

    tdd ci download --action N [--repo ORG/REPO] [--workflow NAME]
                    [--parallel P] [--dir PATH] [--unzip]

`download` fetches every unexpired artifact of run #N, each into its own
folder ``PATH/<artifact>`` (PATH defaults to the current directory), P at a
time; ``--unzip`` then unpacks the archives an artifact holds. A run is known by
its number -- what the Actions page and a PR's checks show -- but the API
addresses runs by id, so the number is looked up first among the repository's
latest runs; two workflows can each have a run #N, and ``--workflow`` picks
one. All of it goes through ``gh``: its login is the credential.
"""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import shutil
import tarfile
import threading
import zipfile
from dataclasses import dataclass

from tabsdata_dev.common.core import cli, parallel, proc, render
from tabsdata_dev.common.core.errors import ToolError

NAME = "ci"
DESCRIPTION = "GitHub Actions runs: download a run's artifacts, in parallel"

DOWNLOAD = "download"
DEFAULT_REPO = "tabsdata/tabsdata-ee"
DEFAULT_PARALLEL = 8
#: How many of the latest runs a run number is looked for among; `gh run list`
#: has no filter by number.
RUN_WINDOW = 1000


@dataclass(frozen=True)
class Run:
    id: int
    number: int
    workflow: str


@dataclass(frozen=True)
class Artifact:
    name: str
    size: int
    expired: bool


def _gh(*args: str) -> str:
    """`gh ARGS`, its stdout; a failure is a ToolError carrying gh's words."""
    done = proc.run(["gh", *args], capture_output=True, encoding="utf-8")
    if done.returncode != 0:
        said = (done.stderr or done.stdout or "").strip()
        first = said.splitlines()[0] if said else f"exit {done.returncode}"
        raise ToolError(f"gh {args[0]} {args[1]} failed: {first}", said)
    return done.stdout or ""


# ------------------------------------------------------------------ lookups
def find_run(repo: str, number: int, workflow: str | None) -> Run:
    """Run #`number` of `repo`, among its latest RUN_WINDOW runs."""
    argv = ["run", "list", "-R", repo, "--limit", str(RUN_WINDOW)]
    if workflow:
        argv += ["-w", workflow]
    argv += ["--json", "number,databaseId,workflowName"]
    runs = [
        Run(r["databaseId"], r["number"], r.get("workflowName", ""))
        for r in json.loads(_gh(*argv) or "[]")
        if r["number"] == number
    ]
    scope = f" of workflow {workflow!r}" if workflow else ""
    if not runs:
        raise ToolError(
            f"run #{number}{scope} not found in {repo} "
            f"(looked among the latest {RUN_WINDOW} runs)"
        )
    if len(runs) > 1:
        which = ", ".join(f"{r.workflow!r} (id {r.id})" for r in runs)
        raise ToolError(
            f"run #{number} is ambiguous in {repo}: {which} -- pass --workflow"
        )
    return runs[0]


def list_artifacts(repo: str, run_id: int) -> list[Artifact]:
    """Every artifact of the run, expired ones included, one API page after
    another (--paginate), each as one JSON line (--jq)."""
    text = _gh(
        "api",
        f"repos/{repo}/actions/runs/{run_id}/artifacts",
        "--paginate",
        "--jq",
        ".artifacts[] | {name, size_in_bytes, expired}",
    )
    out = []
    for line in text.splitlines():
        if line.strip():
            a = json.loads(line)
            out.append(Artifact(a["name"], int(a["size_in_bytes"]), bool(a["expired"])))
    return out


# ------------------------------------------------------------------ download
def download(
    repo: str,
    run_id: int,
    artifacts: list[Artifact],
    dest: pathlib.Path,
    workers: int,
    out: render.Renderer,
    *,
    unzip: bool = False,
) -> list[tuple[str, str]]:
    """Each artifact into `dest/<name>`, `workers` at a time, its archives
    unpacked there when `unzip`. Every one is tried; returns the (name, why)
    of those that failed."""
    lock = threading.Lock()

    def one(a: Artifact) -> tuple[str, str] | None:
        with lock:
            out.info(f"downloading {a.name} ({_size(a.size)})", artifact=a.name)
        argv = [
            "gh",
            "run",
            "download",
            str(run_id),
            "-R",
            repo,
            "-n",
            a.name,
            "-D",
            str(dest / a.name),
        ]
        done = proc.run(argv, capture_output=True, encoding="utf-8")
        if done.returncode != 0:
            said = (done.stderr or done.stdout or "").strip()
            why = said.splitlines()[-1] if said else f"exit {done.returncode}"
            with lock:
                out.warn(f"{a.name}: {why}", artifact=a.name)
            return a.name, said or why
        if unzip:
            try:
                unpacked = unpack_all(dest / a.name)
            except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
                with lock:
                    out.warn(f"{a.name}: unpacking failed: {exc}", artifact=a.name)
                return a.name, f"unpacking failed: {exc}"
            if unpacked:
                with lock:
                    out.info(
                        f"unpacked {', '.join(unpacked)} in {a.name}",
                        artifact=a.name,
                        unpacked=unpacked,
                    )
        return None

    return [f for f in parallel.map_bounded(one, artifacts, workers) if f]


# ------------------------------------------------------------------ unzip
#: What --unzip unpacks, by suffix, longest first so `.tar.gz` is not taken
#: for `.gz`.
_TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar")


def archive_kind(path: pathlib.Path) -> str | None:
    """`tar`, `zip` or `gz` for a file --unzip unpacks, else None."""
    name = path.name.lower()
    if name.endswith(_TAR_SUFFIXES):
        return "tar"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".gz"):
        return "gz"
    return None


def unpack_all(folder: pathlib.Path) -> list[str]:
    """Unpack every archive at the top of `folder` into it and remove the
    archive, as gunzip does. gh has already unzipped the artifact itself --
    GitHub serves each as a zip -- so what is left is what the workflow
    packed: a tarball of logs, a zip of reports. Members that would land
    outside `folder` are refused (tar's `data` filter; zip names checked).
    Returns the archives' names."""
    done = []
    for path in sorted(folder.iterdir()):
        kind = archive_kind(path) if path.is_file() else None
        if kind is None:
            continue
        if kind == "tar":
            with tarfile.open(path) as tf:
                tf.extractall(folder, filter="data")
        elif kind == "zip":
            with zipfile.ZipFile(path) as zf:
                root = folder.resolve()
                for member in zf.namelist():
                    if not (folder / member).resolve().is_relative_to(root):
                        raise zipfile.BadZipFile(f"{path.name}: {member} escapes")
                zf.extractall(folder)
        else:
            with gzip.open(path) as src, open(path.with_suffix(""), "wb") as dst:
                shutil.copyfileobj(src, dst)
        path.unlink()
        done.append(path.name)
    return done


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    size = n / 1024
    for unit in ("KiB", "MiB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


# ------------------------------------------------------------------ command
def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action_cmd != DOWNLOAD:
        raise ToolError(f"a subcommand is required: {DOWNLOAD} (see --help)")
    if args.parallel < 1:
        raise ToolError("--parallel must be at least 1")
    if "/" not in args.repo.strip("/"):
        raise ToolError(f"--repo must be ORG/REPO, got {args.repo!r}")
    run = find_run(args.repo, args.action, args.workflow)
    out.info(
        f"run #{run.number} ({run.workflow}) is id {run.id}",
        run_number=run.number,
        run_id=run.id,
        workflow=run.workflow,
    )
    every = list_artifacts(args.repo, run.id)
    expired = [a.name for a in every if a.expired]
    if expired:
        out.warn(f"{len(expired)} expired artifact(s) skipped: {', '.join(expired)}")
    live = [a for a in every if not a.expired]
    dest = pathlib.Path(args.dir)
    if not live:
        raise ToolError(f"run #{run.number} has no artifacts to download")
    failed = download(
        args.repo, run.id, live, dest, args.parallel, out, unzip=args.unzip
    )
    got = [a.name for a in live if a.name not in {n for n, _ in failed}]
    if failed:
        names = ", ".join(n for n, _ in failed)
        details = "\n\n".join(f"== {n}\n{why}" for n, why in failed)
        return out.error(
            f"{len(failed)} of {len(live)} artifact(s) failed: {names}",
            details=details,
            downloaded=got,
            failed=[n for n, _ in failed],
            dir=str(dest),
        )
    return out.ok(
        f"{len(got)} artifact(s) of run #{run.number} -> {dest}",
        run_id=run.id,
        run_number=run.number,
        dir=str(dest),
        artifacts=got,
        expired=expired,
    )


def _common(sub: argparse.ArgumentParser) -> None:
    """--format/--verbose after the subcommand word too (see pycache)."""
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
    p.epilog = f"example: tdd {NAME} {DOWNLOAD} --action 1234"
    # `action` is the option's dest, so the subcommand word goes elsewhere.
    sub = p.add_subparsers(dest="action_cmd", metavar="SUBCOMMAND")
    dl = sub.add_parser(
        DOWNLOAD,
        help="download a run's artifacts, each into its own folder",
        description=(
            "Download every unexpired artifact of an Actions run, each into "
            "PATH/<artifact name>, several at a time. The run is found by its number "
            f"among the repository's latest {RUN_WINDOW} runs; when two workflows "
            "each have that number, --workflow picks one. Expired artifacts are "
            "reported and skipped; a failed download does not stop the others."
        ),
    )
    dl.add_argument(
        "--action",
        required=True,
        type=int,
        metavar="N",
        help="the run number (the #N the Actions page shows)",
    )
    dl.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        metavar="ORG/REPO",
        help=f"the repository (default: {DEFAULT_REPO})",
    )
    dl.add_argument(
        "--workflow",
        default=None,
        metavar="NAME",
        help="the workflow the run belongs to, by name or file name, "
        "when the number alone is ambiguous",
    )
    dl.add_argument(
        "--parallel",
        type=int,
        default=DEFAULT_PARALLEL,
        metavar="P",
        help=f"downloads at a time (default: {DEFAULT_PARALLEL})",
    )
    dl.add_argument(
        "--dir",
        default=".",
        metavar="PATH",
        help="where to download them, each artifact into PATH/<name> "
        "(default: the current directory)",
    )
    dl.add_argument(
        "--unzip",
        action="store_true",
        help="unpack the archives each artifact holds (.zip, .tar.gz/.tgz, .tar, "
        ".tar.bz2, .tar.xz, .gz) into its folder, removing the archive",
    )
    _common(dl)


def main() -> int:
    return cli.run(NAME, DESCRIPTION, body, configure=configure)


if __name__ == "__main__":
    raise SystemExit(main())
