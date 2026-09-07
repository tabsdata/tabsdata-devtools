#
# Copyright 2026 Tabsdata Inc.
#

"""The download side shared by every lane of fetch: verified, parallel, biggest
first."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .plan import object_differs


@dataclass(frozen=True)
class Pull:
    """One object to bring down: where it is, what the listing says about it,
    where it goes, and how to name it in the output."""

    key: str
    etag: str
    size: int
    dst: Path
    label: str


def pull_one(s3, bucket: str, p: Pull, force: bool = False) -> str:
    """-> 'have' or 'fetched'. Raises on a download whose bytes disagree.

    force re-downloads even when the local file already matches."""
    if p.dst.exists() and not force:
        if object_differs(p.dst, p.dst.stat().st_size, p.etag, p.size) is None:
            return "have"

    # Download beside the target and rename, so an interrupted run never leaves a
    # truncated file under a real name for `generate` or `push` to trust.
    p.dst.parent.mkdir(parents=True, exist_ok=True)
    part = p.dst.with_name(p.dst.name + ".part")
    part.unlink(missing_ok=True)
    try:
        s3.download_file(bucket, p.key, str(part))
        why = object_differs(part, part.stat().st_size, p.etag, p.size)
        if why is not None:
            raise RuntimeError(
                f"{p.label}: downloaded bytes differ from the bucket: {why}"
            )
        os.replace(part, p.dst)
    finally:
        part.unlink(missing_ok=True)
    return "fetched"


def pull_all(
    s3,
    bucket: str,
    pulls: list[Pull],
    parallel: int,
    out: Renderer,
    *,
    force: bool = False,
) -> tuple[dict[str, int], list[str]]:
    """Download every Pull, `parallel` at a time, reporting each as it lands.

    Biggest first: with a fixed number of workers the long downloads start
    immediately and the small ones fill in around them, instead of one 200 MB
    wheel being left to run alone at the end while the other workers sit idle.

    -> ({'have': n, 'fetched': n}, [failure messages]). One failure does not
    stop the others; the caller decides what a partial result means.
    """
    if parallel < 1:
        raise ToolError("--parallel must be at least 1")

    ordered = sorted(pulls, key=lambda p: (-p.size, p.key))
    total = sum(p.size for p in ordered)
    out.info(
        f"{len(ordered)} object(s), {total / (1 << 20):.0f} MB, "
        f"{parallel} at a time, biggest first"
    )

    counts = {"have": 0, "fetched": 0}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(pull_one, s3, bucket, p, force): p for p in ordered}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                outcome = fut.result()
            except Exception as exc:  # noqa: BLE001 - report every failure, then exit
                failures.append(str(exc))
                out.warn(f"FAILED   {p.label}: {exc}")
                continue
            counts[outcome] += 1
            out.info(f"  {outcome:<8} {p.label}")

    out.info(f"{counts['fetched']} fetched, {counts['have']} already present")
    return counts, failures
