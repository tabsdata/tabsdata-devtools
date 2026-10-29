#
# Copyright 2026 Tabsdata Inc.
#

"""Fetching a native system's archives over HTTPS, the way tabsdata-os's
``cache_postgresql.py`` primes its cache: a bounded number of attempts with a
growing pause, a ``.partial`` file renamed into place only once complete, and
the equivalent ``curl`` in the failure, so a person can reproduce it outside tdd.

Two things differ. A 4xx other than 429 fails at once -- a release asset that is
not there will not appear on the eighth try, and eight backed-off attempts take
two minutes to say so. And the partial file is named after the process, so two
creates fetching the same archive at once never write into one file.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from tabsdata_dev.common.systems.errors import TdxError

DOWNLOAD_ATTEMPTS = 8
DOWNLOAD_BACKOFF_SECONDS = 4
DOWNLOAD_CHUNK_BYTES = 64 * 1024
CONNECT_TIMEOUT_SECONDS = 32
REQUEST_TIMEOUT_SECONDS = 128
#: How often a progress line is written while a download runs, in bytes.
_PROGRESS_EVERY = 8 * 1024 * 1024


def equivalent_curl(
    url: str, headers: dict[str, str] | None = None, output: Path | None = None
) -> str:
    """The ``curl`` that fetches what :func:`fetch` does, for a failure message."""
    parts = ["curl", "--fail", "--location", "--show-error"]
    parts += ["--retry", str(DOWNLOAD_ATTEMPTS)]
    parts += ["--retry-delay", str(DOWNLOAD_BACKOFF_SECONDS), "--retry-all-errors"]
    parts += ["--connect-timeout", str(CONNECT_TIMEOUT_SECONDS)]
    parts += ["--max-time", str(REQUEST_TIMEOUT_SECONDS)]
    for key, value in (headers or {}).items():
        parts += ["-H", f"{key}: {value}"]
    if output is not None:
        parts += ["-o", str(output)]
    parts.append(url)
    return " ".join(shlex.quote(part) for part in parts)


def _open(url: str, headers: dict[str, str] | None):
    request = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(
        request, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl.create_default_context()
    )


def _permanent(error: Exception) -> bool:
    """A refusal no retry will change: a 4xx other than too-many-requests."""
    return (
        isinstance(error, urllib.error.HTTPError)
        and 400 <= error.code < 500
        and error.code != 429
    )


def _attempts(url: str, headers: dict[str, str] | None, what: str, action):
    """Run ``action(attempt)`` until it returns, retrying what a retry can fix."""
    last: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            return action(attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
            print(f">>> {what}: attempt {attempt}/{DOWNLOAD_ATTEMPTS} failed: {error}")
            if _permanent(error) or attempt == DOWNLOAD_ATTEMPTS:
                break
            time.sleep(DOWNLOAD_BACKOFF_SECONDS * attempt)
    raise TdxError(
        f"could not fetch {what} from {url}: {last}",
        f"the same request with curl:\n  {equivalent_curl(url, headers)}",
    )


def read(url: str, *, what: str, headers: dict[str, str] | None = None) -> bytes:
    """The body at `url`: a small document, such as a registry index."""

    def once(_attempt: int) -> bytes:
        with _open(url, headers) as response:
            return response.read()

    return _attempts(url, headers, what, once)


def fetch(
    url: str,
    destination: Path,
    *,
    what: str,
    headers: dict[str, str] | None = None,
    sha256: str = "",
) -> Path:
    """Download `url` to `destination`, which appears only once complete and,
    when `sha256` is given, only when the bytes hash to it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.partial-{os.getpid()}")

    def once(attempt: int) -> Path:
        print(f">>> downloading {what} (attempt {attempt}/{DOWNLOAD_ATTEMPTS}): {url}")
        digest = hashlib.sha256()
        done = 0
        try:
            with _open(url, headers) as response, open(partial, "wb") as out:
                total = response.headers.get("Content-Length") or "?"
                mark = _PROGRESS_EVERY
                while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if done >= mark:
                        print(f">>>   {done} of {total} bytes")
                        mark += _PROGRESS_EVERY
            if sha256 and digest.hexdigest() != sha256.lower():
                raise TdxError(
                    f"{what} from {url} does not match its checksum "
                    f"(sha256 {digest.hexdigest()}, expected {sha256})"
                )
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
        print(f">>> {what}: {done} bytes, cached at {destination}")
        return destination

    return _attempts(url, headers, what, once)
