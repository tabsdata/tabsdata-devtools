#
# Copyright 2026 Tabsdata Inc.
#

"""What a smoke run reads about a project's workers: which ones finished
(`tdd _smoke finished-workers`, from `tdk worker list --format json`), and
whether the log `tdk worker logs` returned for one came whole from an archive
once its pod was gone (`tdd _smoke archived-logs`), after no pod of it is
left (`tdd _smoke worker-pods-gone`).

An archive is where a worker's log is kept after its pod is deleted. Each
writes it in its own shape, so each is told apart by that shape: the kminus pod
runner opens every pod with a `POD STARTED <time> <pod>` line and every
container with `--- container <name> ---`, which the live Kubernetes log never
does. The cloud readers (CloudWatch, Cloud Logging, Log Analytics) write the
live log's own `container: <name>` headers, so theirs is told apart only by
the pod being gone when it is read -- and is judged against the live log the
smoke read while the pod was still there (`tdd _smoke live-workers`, `tdd
_smoke live-log`): line for line, from where the archive starts.
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import difflib
import json
import re

#: Worker states a run ends in, as the API codes them and as tdk names them.
FINISHED = frozenset({"d", "e", "f", "done", "error", "failed"})

POD_RUNNER = "pod-runner"
CLOUDWATCH = "cloudwatch"
CLOUD_LOGGING = "cloud-logging"
LOG_ANALYTICS = "log-analytics"
#: The archives whose reader writes the live log's container headers.
HEADED = (CLOUDWATCH, CLOUD_LOGGING, LOG_ANALYTICS)
ARCHIVES = (POD_RUNNER, *HEADED)

#: The label every pod of a worker carries, valued with the worker's id.
WORKER_ID_LABEL = "tabsdata.com/worker-id"

#: The number of every worker pod's last container (`1000-end-execution` in a
#: function's, `1000-cron-publisher`, `1000-stream-source-plugin`): a log that
#: has it was kept to the end.
LAST_CONTAINER = "1000-"

#: The container whose start the cloud readers' window is counted from: they
#: read from 30s before the worker's `started_on`, which it reports, so lines of
#: the setup containers before it may be missing from their copy.
BEGIN_EXECUTION = "-begin-execution"

#: The phases of a pod whose containers have all ended.
TERMINAL_PHASES = frozenset({"Succeeded", "Failed"})

#: At most this many lines of a live/archived diff are shown.
DIFF_LINES = 20

_RULE = "=" * 50
_HEADER_NAME = re.compile(r"^container: (\S+)$")

_POD_RUNNER_POD = re.compile(r"^POD STARTED \S+ \S+$", re.MULTILINE)
_POD_RUNNER_CONTAINER = re.compile(r"^--- container (\S+) ---$", re.MULTILINE)
_HEADER_CONTAINER = re.compile(r"^container: (\S+)$", re.MULTILINE)

#: What the apiserver's archive readers answer instead of a log.
REFUSALS = (
    "no logs kept for worker",
    "no logs found for worker",
    "no pod found for worker",
    "no access to",
    "has no kubernetes metadata",
)

#: The refusals waiting can clear: entries not ingested yet, a grant not in
#: effect yet (an Azure role assignment takes up to 15 minutes to apply).
PASSING_REFUSALS = ("no logs found for worker", "no access to")

#: Lines of one container whose leading timestamps are this close may come
#: back in either order: a reader that orders by time cannot tell apart the
#: stdout and stderr lines a container wrote within the same few milliseconds.
REORDER_TOLERANCE = datetime.timedelta(milliseconds=10)

_TIMESTAMP = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d))(?:\s|$)"
)


@dataclasses.dataclass(frozen=True)
class Verdict:
    """Why a log is not one the archive kept whole, nothing when it is, and
    whether waiting can change that: a log still arriving can, one holding
    a line the live log lacks cannot."""

    problems: list[str]
    lasting: bool = False


def finished(listing: str) -> list[str]:
    """The ids of the finished workers in a `tdk worker list --format json`."""
    workers = json.loads(listing) if listing.strip() else []
    if isinstance(workers, dict):
        workers = workers.get("data") or []
    return [
        str(worker["id"])
        for worker in workers
        if str(worker.get("status", "")).strip().lower() in FINISHED
    ]


def containers(text: str, archive: str) -> list[str]:
    """The containers an archived log holds, in order."""
    if archive == POD_RUNNER:
        return _POD_RUNNER_CONTAINER.findall(text)
    if archive in HEADED:
        return _HEADER_CONTAINER.findall(text)
    raise ValueError(f"unknown archive: {archive}")


def _refused(text: str) -> list[str]:
    lowered = text.lower()
    return [r for r in REFUSALS if r in lowered]


def _refusals(text: str) -> list[str]:
    return [f"the reader answered: {r}" for r in _refused(text)]


def _has_last(held: list[str]) -> bool:
    return any(name.startswith(LAST_CONTAINER) for name in held)


def judge(text: str, archive: str, live: str | None = None) -> Verdict:
    """Whether a log is one the archive kept whole. A headed archive is
    judged against LIVE, the log read while the pod was there; the pod
    runner's, which no live log outlasts, by its shape, and never as
    lasting: its check keeps the wait it always had."""
    found = _refusals(text)
    if archive == POD_RUNNER:
        if not _POD_RUNNER_POD.search(text):
            found.append("no POD STARTED line: not served by the pod runner's archive")
        held = containers(text, archive)
        if not _has_last(held):
            found.append(f"no {LAST_CONTAINER}* container (a pod's last)")
        if len(held) < 2:
            found.append(f"{len(held)} container(s), at least 2 expected")
        return Verdict(found)
    if archive not in HEADED:
        raise ValueError(f"unknown archive: {archive}")
    if live is None:
        raise ValueError(f"{archive} is judged against the live log: none given")
    lasting = any(r not in PASSING_REFUSALS for r in _refused(text))
    if _POD_RUNNER_POD.search(text):
        found.append(f"a POD STARTED line: served by the pod runner, not {archive}")
        lasting = True
    compared = mismatches(live, text)
    return Verdict([*found, *compared.problems], lasting or compared.lasting)


def live_problems(text: str) -> list[str]:
    """Why a log read while its pod was there is no reference: a refusal, or
    a pod that had not run to its last container."""
    found = _refusals(text)
    if not _has_last([name for name, _ in sections(text)]):
        found.append(f"no {LAST_CONTAINER}* container: the pod had not finished")
    return found


def _normal(line: str) -> str:
    """A line as every reader agrees on it: without the `\\r` a terminal
    wrote, and a JSON object in one spelling -- Cloud Logging writes a
    `jsonPayload` back with its own key order and spacing."""
    line = line.rstrip("\r")
    if line.startswith("{"):
        try:
            value = json.loads(line)
        except ValueError:
            return line
        if isinstance(value, dict):
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return line


def sections(text: str) -> list[tuple[str, list[str]]]:
    """The containers of a `tdk worker logs` text in order, each with its
    lines. A header follows a container's last line even when that line has
    no newline, so a rule may close the line before it. Blank lines are left
    out: whether an empty line is an entry is each reader's own choice."""
    lines = text.split("\n")
    found: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        name = _HEADER_NAME.match(lines[i + 1]) if i + 2 < len(lines) else None
        if name and line.endswith(_RULE) and lines[i + 2] == _RULE:
            before = line[: -len(_RULE)]
            if before.strip() and found:
                found[-1][1].append(_normal(before))
            found.append((name.group(1), []))
            i += 3
            continue
        if found and line.strip():
            found[-1][1].append(_normal(line))
        i += 1
    return found


def _flat(held: list[tuple[str, list[str]]]) -> list[str]:
    return [f"{name} | {line}" for name, lines in held for line in lines]


def _stamp(entry: str) -> datetime.datetime | None:
    found = _TIMESTAMP.match(entry.split(" | ", 1)[1])
    return datetime.datetime.fromisoformat(found.group(1)) if found else None


def _may_swap(entry: str, other: str) -> bool:
    """Whether two lines may come back in either order: both of one
    container, both stamped, within REORDER_TOLERANCE of each other."""
    if entry.split(" | ", 1)[0] != other.split(" | ", 1)[0]:
        return False
    one, two = _stamp(entry), _stamp(other)
    return one is not None and two is not None and abs(one - two) <= REORDER_TOLERANCE


def _diff(reference: list[str], got: list[str]) -> list[str]:
    diff = list(
        difflib.unified_diff(reference, got, "live", "archived", n=1, lineterm="")
    )
    shown = [f"  {line}" for line in diff[:DIFF_LINES]]
    if len(diff) > DIFF_LINES:
        shown.append(f"  ... {len(diff) - DIFF_LINES} more diff line(s)")
    return shown


def mismatches(live: str, archived: str) -> Verdict:
    """How the ARCHIVED log differs from the LIVE one. It passes as the live
    log from some line on, starting no later than the first line of the
    `*-begin-execution` container, where lines may only have swapped with
    lines `_may_swap` allows. One rule for every cloud reader: those that read
    from `started_on` may lose the setup containers' earlier lines, those that
    order by time may swap lines written together, and one that reads the
    whole stream in order passes it too.

    Lines the archive lacks may still arrive, so only they leave the verdict
    open; a line the live log lacks, a container split in two or a line out
    of its place are there to stay."""
    want = _flat(sections(live))
    held = sections(archived)
    got = _flat(held)
    found = [
        f"container {name} appears {count} times"
        for name, count in collections.Counter(name for name, _ in held).items()
        if count > 1
    ]
    lasting = bool(found)
    if not got:
        return Verdict([*found, "the archive holds no line yet"], lasting)
    begins = [
        i
        for i, entry in enumerate(want)
        if entry.split(" | ", 1)[0].endswith(BEGIN_EXECUTION)
    ]
    anchor = begins[0] if begins else 0
    start = len(want) - len(got)
    if 0 <= start <= anchor and got == want[start:]:
        return Verdict(found, lasting)
    # compare from where the archive's first line is in the live log, if it is
    # there by the anchor, else from the anchor: what precedes is the window
    starts = [i for i in range(min(anchor + 1, len(want))) if want[i] == got[0]]
    reference = want[starts[0] if starts else anchor :]

    # Lines out of the longest common order: a deleted line that is also
    # inserted moved, past the reference lines between its two places; one
    # only deleted is missing, one only inserted is extra.
    deleted: list[tuple[int, str]] = []
    inserted: dict[str, list[int]] = collections.defaultdict(list)
    matcher = difflib.SequenceMatcher(None, reference, got, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            deleted.extend((i, reference[i]) for i in range(i1, i2))
        if tag in ("replace", "insert"):
            for j in range(j1, j2):
                inserted[got[j]].append(i1)
    missing = 0
    misplaced: list[tuple[str, str]] = []
    for i, entry in deleted:
        if not inserted[entry]:
            missing += 1
            continue
        to = inserted[entry].pop(0)
        passed = reference[to:i] if to <= i else reference[i + 1 : to]
        misplaced.extend(
            (entry, other) for other in passed if not _may_swap(entry, other)
        )
    extra = sum(len(places) for places in inserted.values())

    if extra:
        found.append(f"{extra} line(s) not in the live log")
    if misplaced:
        entry, other = misplaced[0]
        found.append(
            f"{len(misplaced)} line pair(s) in another order, beyond lines of one "
            f"container stamped within {REORDER_TOLERANCE.total_seconds() * 1000:g}ms: "
            f"first {entry!r} before {other!r}"
        )
    lasting = lasting or bool(extra or misplaced)
    if missing:
        found.append(f"{missing} live line(s) not in the archive (yet)")
    if not found:
        return Verdict([])
    return Verdict([*found, *_diff(reference, got)], lasting)


def _unpadded(worker: str) -> str:
    """A worker id as its pods' label holds it: the counter after the last `-`
    without the zeros the padded form adds."""
    head, sep, counter = worker.rpartition("-")
    if not sep or not counter.isdigit():
        return worker
    return f"{head}{sep}{int(counter)}"


def _pods(listing: str) -> list[dict]:
    return (json.loads(listing).get("items") or []) if listing.strip() else []


def terminal(listing: str, worker_ids: list[str]) -> list[str]:
    """The workers, as given, whose pod in a `kubectl get pods -o json` has
    ended: there, its live log is whole and still readable."""
    ended = set()
    for pod in _pods(listing):
        labels = pod["metadata"].get("labels") or {}
        phase = (pod.get("status") or {}).get("phase")
        if WORKER_ID_LABEL in labels and phase in TERMINAL_PHASES:
            ended.add(_unpadded(labels[WORKER_ID_LABEL]))
    return [w for w in worker_ids if _unpadded(w) in ended]


def pods_left(listing: str, worker_ids: list[str]) -> list[str]:
    """The pods of these workers still in a `kubectl get pods -o json`."""
    wanted = {_unpadded(w) for w in worker_ids}
    left = []
    for pod in _pods(listing):
        labels = pod["metadata"].get("labels") or {}
        if WORKER_ID_LABEL in labels and _unpadded(labels[WORKER_ID_LABEL]) in wanted:
            left.append(pod["metadata"]["name"])
    return left
