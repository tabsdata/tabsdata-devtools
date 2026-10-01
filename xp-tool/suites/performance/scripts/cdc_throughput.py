#
# Copyright 2026 Tabsdata Inc.
#
"""How fast a CDC stream ingests: the rows it writes to its files, per second.

    cdc_throughput.py COLLECTION --expect ROWS [--time-out 10m] [--poll 5s] [--fail-short]

A CDC stream publisher reads its source into a buffer and spills it to parquet
files, one a table a spill; a trigger later hands a batch of them over as a
manifest, which a transaction commits as table versions. What is measured is
the first half, ingestion: the rows written to those files. The trigger and the
commit after it are latency the thresholds choose, not the stream's speed.

The files are read off the stream worker's log (``tdk worker list --proj
$XP_PROJECT`` for COLLECTION's streaming worker, then ``tdk worker logs``), where
the ledger logs every one it writes -- always, its logger pinned to DEBUG:

    <ts> DEBUG tabsdatak.conn.common._stream._ledger: Wrote <rows> row(s) and
         <bytes> byte(s) of <table> to <file>

(an older tabsdata worded it ``Buffer flush: writen <table> → <file> (<rows>
rows & <bytes> bytes)``, which is read too).

The clock starts when the worker invokes the source plugin's ``run()`` -- the
line the streamer logs before it connects -- and stops at the last file
written. Both times are the worker's own, so another machine's clock does not
enter. The rows are every file's, so an initial load's count carries its LOAD
control row, one a table.

It polls the log until the files hold ROWS or the time-out passes, counted from
when it starts, so a suite fills the source before it registers the stream: the
stream then reads a backlog, as fast as it can, rather than keeping pace with an
insert. It is tolerant: a stream short of ROWS at the time-out is reported, not
failed -- ``PARTIAL`` in the note, what was written and at what rate.
``--fail-short`` makes that exit 1. The figure is the step's note
(``tdd.note``), the per-table detail is in the output (run.log), and the whole
result is written as JSON to ``$XP_WORK_DIR/throughput-COLLECTION.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from tdd import TddError, note, tdd  # on the path: xp runs a python step with it

_STREAMING = "ST"  # tdk's worker_type of a stream publisher's worker
_TS = r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z?"
_STARTED = re.compile(_TS + r" \w+ \S+run_streamer\S*: Invoking \S+\.run\(\)")
# The ledger's line for a file it wrote, as tabsdata words it now and as it
# did: a script reading the old wording alone counted nothing and said PARTIAL.
_WRITTEN = re.compile(
    _TS + r" \w+ \S+_ledger: Wrote (?P<rows>\d+) row\(s\) and (?P<bytes>\d+) "
    r"byte\(s\) of (?P<table>\S+) to (?P<file>\S+)"
)
_WRITTEN_OLD = re.compile(
    _TS + r" \w+ \S+_ledger: Buffer flush: writen (?P<table>\S+) \S+ (?P<file>\S+) "
    r"\((?P<rows>\d+) rows & (?P<bytes>\d+) bytes\)"
)


def duration(text: str) -> float:
    """``<VALUE><UNIT>``, unit s, m or h -- as xp's suites spell a duration."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smh])", text.strip())
    if not m:
        raise argparse.ArgumentTypeError(f"{text!r}: a duration is <VALUE>s|m|h")
    return float(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


def _at(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp()


def worker_logs(proj: str, coll: str) -> list[str]:
    """The logs of COLLECTION's streaming workers, oldest first -- one, unless
    the worker was started again."""
    workers = json.loads(tdd("tdk", "worker", "list", "--proj", proj, "--format", "json"))
    ours = sorted(
        (w for w in workers or [] if w.get("collection") == coll and w.get("worker_type") == _STREAMING),
        key=lambda w: w.get("started_on") or 0,
    )
    return [tdd("tdk", "worker", "logs", "--worker", str(w["id"])) for w in ours]


def parse(logs: list[str]) -> tuple[float | None, list[dict]]:
    """When ``run()`` was first invoked, and every file written, in order."""
    started, files = None, []
    for log in logs:
        for line in log.splitlines():
            if m := _STARTED.search(line):
                started = _at(m.group(1)) if started is None else started
            elif m := _WRITTEN.search(line) or _WRITTEN_OLD.search(line):
                files.append(
                    {"at": _at(m.group(1)), "table": m["table"], "file": m["file"],
                     "rows": int(m["rows"]), "bytes": int(m["bytes"])}
                )
    return started, files


def measure(args) -> int:
    proj = os.environ["XP_PROJECT"]
    deadline = time.monotonic() + args.time_out
    started, files, why = None, [], ""
    while True:
        try:
            started, files = parse(worker_logs(proj, args.collection))
            why = ""
        except (TddError, ValueError) as exc:
            lines = str(exc).strip().splitlines()
            why = lines[-1] if lines else type(exc).__name__
        written = sum(f["rows"] for f in files)
        if written >= args.expect or time.monotonic() >= deadline:
            break
        time.sleep(min(args.poll, max(0.0, deadline - time.monotonic())))
    return report(args, started, files, why)


def report(args, started, files, why) -> int:
    rows = sum(f["rows"] for f in files)
    size = sum(f["bytes"] for f in files)
    done = rows >= args.expect
    secs = files[-1]["at"] - started if files and started is not None else None
    rate = rows / secs if secs else 0.0
    tables: dict[str, dict] = {}
    for f in files:
        t = tables.setdefault(f["table"], {"rows": 0, "files": 0, "bytes": 0})
        t["rows"] += f["rows"]
        t["files"] += 1
        t["bytes"] += f["bytes"]
    for name, t in tables.items():
        print(f"{name}: {t['rows']} rows in {t['files']} file(s), {t['bytes']} bytes")
    if why:
        print(f"last read of the worker log failed: {why}")
    result = {
        "collection": args.collection,
        "complete": done,
        "rows": rows,
        "expected": args.expect,
        "files": len(files),
        "bytes": size,
        "seconds": round(secs, 3) if secs is not None else None,
        "rows_per_second": round(rate, 1),
        "first_file_seconds": round(files[0]["at"] - started, 3) if files and started is not None else None,
        "tables": tables,
        "error": why or None,
    }
    work = Path(os.environ.get("XP_WORK_DIR", "."))
    (work / f"throughput-{args.collection}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if started is None:
        said = f"no stream worker log for {args.collection}" + (f": {why}" if why else "")
    else:
        head = "" if done else f"PARTIAL {rows}/{args.expect} rows, "
        body = f"{rows} rows" if done else ""
        took = f"{secs:.2f}s" if secs is not None else "no file"
        said = f"{head}{body}{', ' if body else ''}{len(files)} files {size / 1e6:.1f}MB in {took}, {rate:.0f} rows/s"
    note(said)
    print(said)
    return 1 if args.fail_short and not done else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cdc_throughput.py")
    ap.add_argument("collection")
    ap.add_argument("--expect", type=int, required=True, help="rows the files must hold")
    ap.add_argument("--time-out", type=duration, default=duration("10m"))
    ap.add_argument("--poll", type=duration, default=duration("5s"))
    ap.add_argument("--fail-short", action="store_true")
    return measure(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
