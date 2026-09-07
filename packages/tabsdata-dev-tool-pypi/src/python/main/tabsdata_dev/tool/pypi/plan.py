#
# Copyright 2026 Tabsdata Inc.
#

"""The dry-run engine shared by every lane of push.

Plan (a list of Actions) -> report (print it) -> execute (confirm, then do it).
Nothing here uploads without first having been printed.
"""

from __future__ import annotations

import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .config import DEFAULT_PARALLEL, Lane
from .tree import INDEX

IMMUTABLE = "public, max-age=31536000, immutable"
INDEX_CACHE = "public, max-age=60"

#: Every object push writes carries its sha256 here, so the next push can tell
#: "same bytes" from one HEAD instead of downloading or trusting an ETag.
SHA_META = "sha256"

PUT, SKIP, DELETE = "put", "skip", "delete"


@dataclass(frozen=True)
class Action:
    verb: str
    key: str
    reason: str
    size: int = 0
    path: Path | None = None
    immutable: bool = False
    sha256: str | None = None
    #: run by itself, as a barrier: nothing before it may still be in flight and
    #: nothing after it starts until it is done. The index, first and last.
    alone: bool = False


@dataclass(frozen=True)
class Remote:
    """One object as the bucket describes it: the listing's ETag and size, plus
    the sha256 metadata a previous push stamped on it (None for objects written
    by anything else)."""

    etag: str
    size: int
    sha256: str | None


@dataclass(frozen=True)
class Local:
    """One file as the tree describes it."""

    path: Path
    size: int
    sha256: str


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def object_differs(path: Path, size: int, etag: str, listed_size: int) -> str | None:
    """-> why the listed object no longer matches the local file, or None.

    The fallback for objects with no sha256 metadata -- written before this tool
    stamped one, or by `aws s3 cp`. Size first: it comes free from the listing.
    When the sizes agree the ETag is the only signal left; every object this
    tool writes goes up in one put_object, so its ETag is the content MD5. An
    ETag carrying a part count is not an MD5 at all, so there is nothing to
    compare and size has to stand on its own.
    """
    if listed_size != size:
        return f"{listed_size} -> {size} bytes"
    if "-" in etag:
        return None
    local = _md5_file(path)
    return None if local == etag else f"same size, md5 {etag[:12]} -> {local[:12]}"


def remote_index(s3, bucket: str, prefix: str = "") -> dict[str, tuple[str, int]]:
    """{key: (etag, size)} for a bucket or prefix, in one paginated pass."""
    out: dict[str, tuple[str, int]] = {}
    kwargs = {"Bucket": bucket}
    if prefix:
        kwargs["Prefix"] = prefix
    for page in s3.get_paginator("list_objects_v2").paginate(**kwargs):
        for obj in page.get("Contents", []):
            out[obj["Key"]] = (obj["ETag"].strip('"'), obj["Size"])
    return out


def remote_objects(
    s3,
    bucket: str,
    prefix: str = "",
    parallel: int = DEFAULT_PARALLEL,
    with_sha: bool = True,
) -> dict[str, Remote]:
    """The listing, plus one HEAD per object for its sha256 metadata.

    HEADs run `parallel` at a time; 600 objects take a couple of seconds.
    with_sha=False skips them for callers that will delete everything anyway.
    """
    listed = remote_index(s3, bucket, prefix)
    if not with_sha or not listed:
        return {k: Remote(etag, size, None) for k, (etag, size) in listed.items()}

    def head(key: str) -> tuple[str, str | None]:
        meta = s3.head_object(Bucket=bucket, Key=key).get("Metadata", {})
        return key, meta.get(SHA_META)

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        shas = dict(pool.map(head, listed))
    return {k: Remote(etag, size, shas.get(k)) for k, (etag, size) in listed.items()}


def plan_mirror(
    local: dict[str, Local], remote: dict[str, Remote], lane: Lane, *, full: bool
) -> list[Action]:
    """Make the lane hold exactly the tree: index deleted first, orphans deleted,
    new and changed files put, unchanged skipped, index put last.

    `local` is tree-relative and MUST include INDEX. `full` does not compare at
    all: every remote object is deleted first (index first), then the whole tree
    is uploaded (index last). A push that changes nothing leaves the index alone
    too -- taking it down and putting it back would make the lane look
    incomplete, and cost an invalidation, for no reason.
    """
    index_key = lane.key(INDEX)
    if full:
        head = []
        if index_key in remote:
            head = [Action(DELETE, index_key, "--full: index first", alone=True)]
        deletes = [
            Action(DELETE, k, "--full: everything goes first")
            for k in sorted(remote)
            if k != index_key
        ]
        puts = [
            _put_action(lane.key(rel), rel, local[rel], "--full: everything")
            for rel in sorted(local)
            if rel != INDEX
        ]
        tail = [
            _put_action(index_key, INDEX, local[INDEX], "index last: push complete")
        ]
        return head + deletes + puts + tail  # _put_action marks the index alone

    deletes: list[Action] = []
    puts: list[Action] = []
    skips: list[Action] = []
    for key in sorted(remote):
        if key == index_key:
            continue
        rel = key[len(lane.prefix) :]
        if rel not in local:
            deletes.append(Action(DELETE, key, "not in the tree"))
        else:
            f = local[rel]
            r = remote[key]
            if r.sha256 == f.sha256:
                skips.append(Action(SKIP, key, "unchanged"))
            elif r.sha256 is None:
                puts.append(_put_action(key, rel, f, "no sha256 recorded"))
            else:
                why = f"changed {r.sha256[:12]} -> {f.sha256[:12]}"
                puts.append(_put_action(key, rel, f, why))

    for rel in sorted(local):
        if rel == INDEX:
            continue
        key = lane.key(rel)
        if key not in remote:
            puts.append(_put_action(key, rel, local[rel], "new"))

    r = remote.get(index_key)
    if not deletes and not puts and r is not None and r.sha256 == local[INDEX].sha256:
        return skips + [Action(SKIP, index_key, "unchanged")]

    head = (
        [Action(DELETE, index_key, "index first: absent while pushing", alone=True)]
        if r
        else []
    )
    tail = [
        _put_action(
            index_key, INDEX, local[INDEX], "index last: marks the push complete"
        )
    ]
    return head + deletes + skips + puts + tail


def _put_action(key: str, rel: str, f: Local, reason: str) -> Action:
    return Action(
        PUT,
        key,
        reason,
        f.size,
        f.path,
        immutable=rel.startswith("files/"),
        sha256=f.sha256,
        alone=rel == INDEX,
    )


def _human(size: int) -> str:
    if size >= 1_000_000:
        return f"{size / 1e6:>7.1f} MB"
    if size:
        return f"{size / 1e3:>7.1f} KB"
    return " " * 10


def report(
    actions: list[Action], bucket: str, out: Renderer, distribution: str = "-"
) -> None:
    """The plan, one event per action. Nothing writes before this is shown --
    in view it reads as the old table did, and in json it is a line each, which
    a printed table never was."""
    out.info(f"plan for s3://{bucket}   (distribution {distribution})")
    width = min(max((len(a.key) for a in actions), default=10), 70)
    for a in actions:
        out.info(f"  {a.verb:<7} {a.key:<{width}}  {_human(a.size)}  {a.reason}")

    puts = [a for a in actions if a.verb == PUT]
    dels = [a for a in actions if a.verb == DELETE]
    skips = len(actions) - len(puts) - len(dels)
    total = sum(a.size for a in puts)
    out.info(
        f"  {len(puts)} put ({total / 1e6:.1f} MB) | {skips} skip | {len(dels)} delete"
    )


def confirm(prompt: str, *, assume_yes: bool, require_yes: bool = False) -> None:
    """Stop unless the operator said yes -- on the command line, or, where the
    lane allows it, at the keyboard. Never inferred from a non-tty."""
    if require_yes and not assume_yes:
        raise ToolError("this lane requires an explicit --yes")
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise ToolError("not a terminal — pass --yes to confirm")
    # The prompt is the one thing a command may put on the terminal directly:
    # it is a question, not an event, and in --format json there is no terminal
    # to ask (the isatty check above has already refused).
    print(f"\n{prompt} [y/N] ", end="", file=sys.stderr, flush=True)
    if input().strip().lower() != "y":
        raise ToolError("aborted")


def _batches(actions: list[Action]) -> list[list[Action]]:
    """Consecutive actions of the same verb form one batch that may run in
    parallel; an `alone` action is a batch of its own. Skips are dropped. The plan
    order -- index, deletes, puts, index -- is therefore kept between batches and
    ignored within one, which is exactly where it does not matter."""
    out: list[list[Action]] = []
    for a in actions:
        if a.verb == SKIP:
            continue
        if a.alone or not out or out[-1][0].alone or out[-1][0].verb != a.verb:
            out.append([a])
        else:
            out[-1].append(a)
    return out


def _do(s3, bucket: str, a: Action) -> Action:
    if a.verb == PUT:
        _put(s3, bucket, a)
    else:
        s3.delete_object(Bucket=bucket, Key=a.key)
    return a


def execute(
    actions: list[Action],
    bucket: str,
    s3,
    *,
    dry_run: bool,
    assume_yes: bool,
    require_yes: bool,
    parallel: int = DEFAULT_PARALLEL,
    out: Renderer,
) -> bool:
    """-> True if anything was written.

    Runs the plan in batches (see _batches), each batch `parallel` at a time and
    biggest first, so the long uploads start immediately and the small ones fill
    in around them. A failure finishes the batch it is in, is reported with every
    other failure in that batch, and stops there -- so the index, which is always
    last and alone, never goes up over a push that did not complete.
    """
    if dry_run:
        out.info("dry run — nothing uploaded")
        return False

    batches = _batches(actions)
    if not batches:
        out.info("nothing to do")
        return False

    confirm("proceed?", assume_yes=assume_yes, require_yes=require_yes)

    wrote = False
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        for batch in batches:
            ordered = sorted(batch, key=lambda a: (-a.size, a.key))
            futures = {pool.submit(_do, s3, bucket, a): a for a in ordered}
            failures: list[str] = []
            for fut in as_completed(futures):
                a = futures[fut]
                try:
                    fut.result()
                except Exception as exc:  # noqa: BLE001 - report them all, then stop
                    failures.append(f"{a.verb} {a.key}: {exc}")
                    out.warn(f"FAILED  {a.verb} {a.key}: {exc}")
                    continue
                wrote = True
                out.info(f"  {a.verb:<7} {a.key}")
            if failures:
                raise ToolError(
                    f"\n{len(failures)} action(s) failed; stopped before the rest of the "
                    "plan.\n  " + "\n  ".join(failures[:10]) + "\n\nThe index was not "
                    "written, so the lane reports incomplete. Re-run the push to finish."
                )
    return wrote


def _content_type(key: str) -> str:
    if key.endswith(".html"):
        return "text/html; charset=utf-8"
    if key.endswith(".json"):
        return "application/json"
    if key.endswith(".metadata"):
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _put(s3, bucket: str, a: Action) -> None:
    kwargs = {
        "Bucket": bucket,
        "Key": a.key,
        "Body": a.path.read_bytes(),
        "ContentType": _content_type(a.key),
        "CacheControl": IMMUTABLE if a.immutable else INDEX_CACHE,
    }
    if a.sha256:
        kwargs["Metadata"] = {SHA_META: a.sha256}
    s3.put_object(**kwargs)
