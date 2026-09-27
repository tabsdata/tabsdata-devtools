#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd ci`` -- GitHub Actions runs.

    tdd ci download --action N [--repo ORG/REPO] [--workflow NAME]
                    [--parallel P] [--dir PATH] [--expand]

`download` fetches every unexpired artifact of run #N and extracts it straight
into PATH (default: the current directory), P at a time; ``--expand`` also
expands the archives an artifact's zip holds, so a zip holding a tar.gz is
expanded twice and PATH is left with the tar's contents. A run is known by
its number -- what the Actions page and a PR's checks show -- but the API
addresses runs by id, so the number is looked up first among the repository's
latest runs; two workflows can each have a run #N, and ``--workflow`` picks
one. All of it goes through ``gh``: its login is the credential.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass

from tabsdata_dev.common.core import cli, parallel, proc, render
from tabsdata_dev.common.core.errors import ToolError

NAME = "ci"
DESCRIPTION = "GitHub Actions runs: download a run's artifacts, in parallel"

DOWNLOAD = "download"
DEFAULT_REPO = "tabsdata/tabsdata-ee"
DEFAULT_PARALLEL = 8
#: How many of the latest runs a run number is looked for among, a page at a
#: time; the runs API has no filter by number.
RUN_WINDOW = 1000
RUN_PAGE = 100


@dataclass(frozen=True)
class Run:
    id: int
    number: int
    workflow: str


@dataclass(frozen=True)
class Artifact:
    id: int
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
def find_run(
    repo: str,
    number: int,
    workflow: str | None,
    on_page: Callable[[int], None] | None = None,
) -> Run:
    """Run #`number` of `repo`, among its latest RUN_WINDOW runs.

    The runs API has no filter by number, so it is paged through newest
    first, RUN_PAGE at a time, and the search stops at the first page that
    holds the number: a run someone has in hand is recent, and `gh run list
    --limit 1000` fetched all ten pages every time, twenty-odd seconds. Two
    workflows can each have a run #N; the ones on that page are refused as
    ambiguous, and otherwise the newest wins and its workflow is named.
    `workflow` matches a run's workflow name or file name. `on_page` hears
    how many runs have been searched after each page."""
    searched = 0
    for page in range(1, RUN_WINDOW // RUN_PAGE + 1):
        text = _gh(
            "api",
            f"repos/{repo}/actions/runs?per_page={RUN_PAGE}&page={page}",
            "--jq",
            ".workflow_runs[] | {id, run_number, name, path}",
        )
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        searched += len(rows)
        if on_page is not None:
            on_page(searched)
        runs = [
            Run(int(r["id"]), int(r["run_number"]), r.get("name") or "")
            for r in rows
            if r["run_number"] == number and _is_workflow(r, workflow)
        ]
        if len(runs) > 1:
            which = ", ".join(f"{r.workflow!r} (id {r.id})" for r in runs)
            raise ToolError(
                f"run #{number} is ambiguous in {repo}: {which} -- pass --workflow"
            )
        if runs:
            return runs[0]
        if len(rows) < RUN_PAGE:
            break  # the repository has no more runs
    scope = f" of workflow {workflow!r}" if workflow else ""
    raise ToolError(
        f"run #{number}{scope} not found in {repo} "
        f"(looked among the latest {searched} runs)"
    )


def _is_workflow(run: dict, workflow: str | None) -> bool:
    if not workflow:
        return True
    path = run.get("path") or ""
    return workflow in (run.get("name"), path, path.rsplit("/", 1)[-1])


def list_artifacts(repo: str, run_id: int) -> list[Artifact]:
    """Every artifact of the run, expired ones included, one API page after
    another (--paginate), each as one JSON line (--jq)."""
    text = _gh(
        "api",
        f"repos/{repo}/actions/runs/{run_id}/artifacts",
        "--paginate",
        "--jq",
        ".artifacts[] | {id, name, size_in_bytes, expired}",
    )
    out = []
    for line in text.splitlines():
        if line.strip():
            a = json.loads(line)
            out.append(
                Artifact(
                    int(a["id"]), a["name"], int(a["size_in_bytes"]), bool(a["expired"])
                )
            )
    return out


# ------------------------------------------------------------------ progress
#: Seconds between progress lines while anything is in flight: printed as
#: events where the output scrolls (a pipe, a log, JSON), redrawn in place on
#: a terminal, where it can be often.
TICK_SECS = 5.0
LIVE_TICK_SECS = 0.5
CHUNK = 1 << 20


class Progress:
    """The work in flight, and a line for each piece saying how far it has
    got -- a 250 MiB artifact takes a minute to fetch and another to expand,
    and a command that says nothing for that long reads as hung. On a
    terminal the lines are a status block the renderer redraws in place every
    LIVE_TICK_SECS (`Renderer.live`); anywhere else they are info events every
    TICK_SECS. Each piece is a phase of one artifact (downloading,
    extracting, expanding X) with a byte total, advanced by `add` or read
    from `poll`. Every event the download emits goes through `say`, under the
    one lock, so the workers' lines and the ticker's never interleave."""

    def __init__(self, out: render.Renderer, tick: float | None = None) -> None:
        self.out = out
        self.in_place = out.can_live()
        if tick is None:
            tick = LIVE_TICK_SECS if self.in_place else TICK_SECS
        self.tick = tick
        self.lock = threading.Lock()
        self._tasks: dict[int, _Task] = {}
        self._next = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Progress:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self.lock:
            self.out.live([])

    def say(self, kind: str, message: str, **fields: object) -> None:
        with self.lock:
            getattr(self.out, kind)(message, **fields)

    def start(
        self,
        artifact: str,
        phase: str,
        total: int,
        poll: Callable[[], int] | None = None,
    ) -> int:
        with self.lock:
            key = self._next
            self._next += 1
            self._tasks[key] = _Task(artifact, phase, total, poll, time.monotonic())
            return key

    def add(self, key: int, n: int) -> None:
        with self.lock:
            self._tasks[key].done += n

    def finish(self, key: int) -> float:
        """Ends the piece; returns how long it took, in seconds."""
        with self.lock:
            task = self._tasks.pop(key)
        return time.monotonic() - task.started

    def _loop(self) -> None:
        while not self._stop.wait(self.tick):
            self.report()

    def report(self) -> None:
        """One line per piece in flight -- what the ticker shows."""
        with self.lock:
            lines = []
            for t in self._tasks.values():
                done = t.current()
                pct = min(100, 100 * done // t.total) if t.total else 0
                took = time.monotonic() - t.started
                rate = f", {_size(int(done / took))}/s" if took > 0 else ""
                line = (
                    f"{t.artifact}: {t.phase} {pct}% "
                    f"({_size(done)} of {_size(t.total)}{rate})"
                )
                if self.in_place:
                    # Numbers first: a line wider than the terminal is cut at
                    # its end, and artifact names are long.
                    lines.append(
                        f"{pct:>3}% {_size(done):>9} of {_size(t.total):<9}"
                        f"{rate[2:]:>12}  {t.phase}  {t.artifact}"
                    )
                else:
                    self.out.info(
                        line,
                        artifact=t.artifact,
                        phase=t.phase,
                        done=done,
                        total=t.total,
                    )
            if self.in_place:
                self.out.live(lines)


@dataclass
class _Task:
    artifact: str
    phase: str
    total: int
    poll: Callable[[], int] | None
    started: float
    done: int = 0

    def current(self) -> int:
        if self.poll is None:
            return self.done
        try:
            return self.poll()
        except (OSError, ValueError):  # the file was closed under the poll
            return self.done


# ------------------------------------------------------------------ download
def download(
    repo: str,
    artifacts: list[Artifact],
    dest: pathlib.Path,
    workers: int,
    out: render.Renderer,
    *,
    expand: bool = False,
    tick: float | None = None,
) -> list[tuple[str, str]]:
    """Each artifact extracted into `dest`, `workers` at a time, the archives
    it holds expanded too when `expand`. Every one is tried; returns the
    (name, why) of those that failed."""
    claims = _Claims()
    with Progress(out, tick) as progress:

        def one(a: Artifact) -> tuple[str, str] | None:
            try:
                fetch(repo, a, dest, progress, expand=expand, claims=claims)
            except _Failed as exc:
                progress.say("warn", f"{a.name}: {exc}", artifact=a.name)
                return a.name, exc.details or str(exc)
            except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
                progress.say("warn", f"{a.name}: {exc}", artifact=a.name)
                return a.name, str(exc)
            return None

        return [f for f in parallel.map_bounded(one, artifacts, workers) if f]


class _Failed(Exception):
    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.details = details


class _Claims:
    """Which artifact put each file into PATH during this run. Artifacts
    share PATH, and two of them holding the same file -- every assembly of a
    release run ships its own `tabsdata-assembly-devpi.tar.gz` -- would
    otherwise overwrite each other silently, the last one winning."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: dict[pathlib.PurePath, str] = {}

    def take(self, artifact: str, files: list[pathlib.PurePath]) -> None:
        """All of `files` for `artifact`, or none of them."""
        with self._lock:
            taken = [f for f in files if self._owner.get(f, artifact) != artifact]
            if taken:
                first = taken[0]
                more = f" and {len(taken) - 1} more" if len(taken) > 1 else ""
                raise _Failed(
                    f"{first}{more} already came from artifact "
                    f"{self._owner[first]}; two artifacts cannot put the same file "
                    f"in one --dir"
                )
            for f in files:
                self._owner[f] = artifact


def fetch(
    repo: str,
    a: Artifact,
    dest: pathlib.Path,
    progress: Progress,
    *,
    expand: bool = False,
    claims: _Claims | None = None,
) -> None:
    """Artifact `a` extracted into `dest`, with the bytes counted on their
    way: GitHub serves the artifact as a zip, `gh api` streams it (gh holds
    the login). The zip is extracted -- and with `expand`, the archives it
    held expanded and removed -- in a staging dir of this artifact's own,
    then its files are moved into `dest`: parallel artifacts never see each
    other's half-extracted files, and `claims` refuses a file another
    artifact of the run already put there."""
    claims = claims or _Claims()
    dest.mkdir(parents=True, exist_ok=True)
    staging = dest / f".{a.name}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    part = dest / f".{a.name}.zip.part"
    progress.say("info", f"{a.name}: downloading {_size(a.size)}", artifact=a.name)
    key = progress.start(a.name, "downloading", a.size)
    finished = False
    try:
        with tempfile.TemporaryFile() as err, part.open("wb") as sink:
            child = proc.popen(
                ["gh", "api", f"repos/{repo}/actions/artifacts/{a.id}/zip"],
                stdout=subprocess.PIPE,
                stderr=err,
            )
            assert child.stdout is not None
            try:
                while chunk := child.stdout.read1(CHUNK):
                    sink.write(chunk)
                    progress.add(key, len(chunk))
            finally:
                child.stdout.close()
                code = child.wait()
            if code != 0:
                err.seek(0)
                said = err.read().decode("utf-8", "replace").strip()
                why = said.splitlines()[-1] if said else f"exit {code}"
                raise _Failed(f"download failed: {why}", said)
        took = progress.finish(key)
        finished = True
        got = part.stat().st_size
        rate = f", {_size(int(got / took))}/s" if took > 0 else ""
        progress.say(
            "info",
            f"{a.name}: downloaded {_size(got)} in {took:.0f}s{rate}",
            artifact=a.name,
            bytes=got,
            seconds=round(took, 1),
        )
        with zipfile.ZipFile(part) as zf:
            _extract_zip(zf, staging, progress, a.name, "extracting")
        part.unlink()
        if expand:
            expand_all(staging, progress, a.name)
        _merge(staging, dest, a.name, claims)
    finally:
        if not finished:
            progress.finish(key)
        part.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def _merge(
    staging: pathlib.Path, dest: pathlib.Path, artifact: str, claims: _Claims
) -> None:
    """Every file under `staging` moved to the same place under `dest`, once
    `claims` has granted them all; a file already there from an earlier run
    is replaced. The staging dir is on the same filesystem, so a move is a
    rename."""
    files = sorted(
        pathlib.PurePath(f.relative_to(staging))
        for f in staging.rglob("*")
        if not f.is_dir()
    )
    claims.take(artifact, files)
    for d in sorted(f for f in staging.rglob("*") if f.is_dir()):
        (dest / d.relative_to(staging)).mkdir(parents=True, exist_ok=True)
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        (staging / rel).replace(target)


def _extract_zip(
    zf: zipfile.ZipFile,
    folder: pathlib.Path,
    progress: Progress,
    artifact: str,
    phase: str,
) -> int:
    """Every member into `folder`, refusing one that would land outside it,
    the bytes counted as they are written. Returns the member count."""
    root = folder.resolve()
    members = zf.infolist()
    for m in members:
        if not (folder / m.filename).resolve().is_relative_to(root):
            raise zipfile.BadZipFile(f"{m.filename} would land outside {folder}")
    key = progress.start(artifact, phase, sum(m.file_size for m in members))
    try:
        for m in members:
            target = folder / m.filename
            if m.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, target.open("wb") as dst:
                while chunk := src.read(CHUNK):
                    dst.write(chunk)
                    progress.add(key, len(chunk))
    finally:
        progress.finish(key)
    return len(members)


# ------------------------------------------------------------------ expand
#: What --expand expands, by suffix, longest first so `.tar.gz` is not taken
#: for `.gz`.
_TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar")


def archive_kind(path: pathlib.Path) -> str | None:
    """`tar`, `zip` or `gz` for a file --expand expands, else None."""
    name = path.name.lower()
    if name.endswith(_TAR_SUFFIXES):
        return "tar"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".gz"):
        return "gz"
    return None


def expand_all(
    folder: pathlib.Path, progress: Progress | None = None, artifact: str = ""
) -> list[str]:
    """Expand every archive at the top of `folder` into it and remove the
    archive, as gunzip does. The artifact's own zip is already open by now,
    so what is left is what the workflow packed: a tarball of logs, a zip of
    reports -- the second expansion. Archives inside those are left alone.
    Members that would land outside `folder` are refused (tar's `data`
    filter; zip names checked). Returns the archives' names."""
    progress = progress or Progress(render.Renderer(NAME, err=io.StringIO()))
    artifact = artifact or folder.name
    done = []
    for path in sorted(folder.iterdir()):
        kind = archive_kind(path) if path.is_file() else None
        if kind is None:
            continue
        phase = f"expanding {path.name}"
        progress.say("info", f"{artifact}: {phase}", artifact=artifact)
        if kind == "zip":
            with zipfile.ZipFile(path) as zf:
                _extract_zip(zf, folder, progress, artifact, phase)
        else:
            # Progress is how far into the compressed file the reader is.
            with path.open("rb") as raw:
                key = progress.start(artifact, phase, path.stat().st_size, raw.tell)
                try:
                    if kind == "tar":
                        with tarfile.open(fileobj=raw) as tf:
                            tf.extractall(folder, filter="data")
                    else:
                        with (
                            gzip.GzipFile(fileobj=raw) as src,
                            open(path.with_suffix(""), "wb") as dst,
                        ):
                            shutil.copyfileobj(src, dst, CHUNK)
                finally:
                    progress.finish(key)
        path.unlink()
        done.append(path.name)
        progress.say(
            "info",
            f"{artifact}: expanded {path.name}",
            artifact=artifact,
            expanded=path.name,
        )
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
    # Both lookups take seconds -- the first pages through a thousand runs --
    # so each says what it is doing before it starts.
    scope = f" of workflow {args.workflow!r}" if args.workflow else ""
    out.info(
        f"looking for the id of run #{args.action}{scope} in {args.repo} "
        f"(among its latest {RUN_WINDOW} runs)"
    )
    run = find_run(
        args.repo,
        args.action,
        args.workflow,
        on_page=lambda n: out.live([f"searched {n} runs for #{args.action}"]),
    )
    out.live([])
    out.info(
        f"found run #{run.number} ({run.workflow}): id {run.id}",
        run_number=run.number,
        run_id=run.id,
        workflow=run.workflow,
    )
    out.info(f"looking for the artifacts of run #{run.number} (id {run.id})")
    every = list_artifacts(args.repo, run.id)
    live = [a for a in every if not a.expired]
    out.info(
        f"found {len(live)} artifact(s) to download, "
        f"{_size(sum(a.size for a in live))} in all",
        artifacts=[a.name for a in live],
        bytes=sum(a.size for a in live),
    )
    expired = [a.name for a in every if a.expired]
    if expired:
        out.warn(f"{len(expired)} expired artifact(s) skipped: {', '.join(expired)}")
    dest = pathlib.Path(args.dir)
    if not live:
        raise ToolError(f"run #{run.number} has no artifacts to download")
    failed = download(args.repo, live, dest, args.parallel, out, expand=args.expand)
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
            "Download every unexpired artifact of an Actions run and extract it "
            "into PATH, several at a time. The run is found by its number "
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
        help="where to extract them (default: the current directory); an "
        "artifact's files land in PATH itself, not in a folder of its own",
    )
    dl.add_argument(
        "--expand",
        action="store_true",
        help="also expand the archives each artifact's zip holds (.zip, "
        ".tar.gz/.tgz, .tar, .tar.bz2, .tar.xz, .gz) into PATH and remove them: "
        "a zip holding a tar.gz is expanded twice, leaving the tar's contents",
    )
    _common(dl)


def main() -> int:
    return cli.run(NAME, DESCRIPTION, body, configure=configure)


if __name__ == "__main__":
    raise SystemExit(main())
