#
# Copyright 2026 Tabsdata Inc.
#

"""The PostgreSQL binaries a ``postgresnative`` system runs, and the pgvector a
``postgresnativepgvector`` one installs in them, for this machine's platform.

**PostgreSQL** is theseus-rs's build (``postgresql-binaries``), fetched the way
tabsdata-os's ``devutils/automation/tasks/makers/td-scripts/cache_postgresql.py``
primes its cache, into the same cache (``~/.theseus/postgresql``) under the same
name (``postgresql-<version>-<target>.tar.gz``), so an archive either one fetched
serves both. The version is the one that script pins, overridden the same way
(``TD_POSTGRESQL_VERSION``). What is not carried over is its Linux bundling: it
rewrites the archive with the libraries it links so the tree runs on any glibc
distro, which a server started on the machine that fetched it does not need. An
archive it did bundle is still a tree that runs, and one tdd left unbundled is
bundled by that script the next time it looks.

**pgvector** is not built by theseus-rs, and nobody publishes one build for all
three systems, so it comes from the places that keep it current for PostgreSQL 18,
each picked for the widest reach on its system:

- macOS: Homebrew's bottle (``ghcr.io/homebrew/core/pgvector``), addressed by its
  version tag. A bottle carries one build per PostgreSQL major Homebrew ships
  (``lib/postgresql@<major>/``); the bottle for the oldest macOS is taken, which
  every newer one runs. Its digest is the blob's name, so the download is checked
  against it.
- Linux: the PostgreSQL project's own apt package (PGDG,
  ``postgresql-<major>-pgvector``), built for Ubuntu 22.04. It links libc alone,
  at glibc 2.17 symbols, so it loads on any glibc distro theseus's build runs on;
  Homebrew's Linux bottle wants glibc 2.38 (no Ubuntu 22.04, Debian 12 or RHEL 9).
  A ``.deb`` is an ``ar`` archive around a tarball, both read with the standard
  library.
- Windows: ``andreiramani/pgvector_pgsql_windows``, one release per
  version and major (``<version>_<major>``).

theseus-rs's own ``postgresql_extensions`` knows a third (portal-corp's
``pgvector_compiled``), which stops at PostgreSQL 16. The two are cached beside
the PostgreSQL archive and installed into a system's own tree the way that crate
installs an extension: libraries into ``lib/``, ``.control`` and ``.sql`` into
``share/extension/``.
"""

from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import tarfile
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.systems._common.hosting.native import download

THESEUS_REPOSITORY = "theseus-rs/postgresql-binaries"
#: The PostgreSQL theseus-rs build a system runs: tabsdata-os's pin, which
#: matches the postgres container's image (images.POSTGRES).
PINNED_VERSION = "18.6.0"
#: tabsdata-os's override of that pin, honoured here so a developer who set it
#: runs the server the product embeds.
ENV_VERSION = "TD_POSTGRESQL_VERSION"
RELEASE_DOWNLOAD = (
    f"https://github.com/{THESEUS_REPOSITORY}/releases/download"
    "/{version}/postgresql-{version}-{target}.tar.gz"
)

#: The pgvector a postgresnativepgvector system installs: the one in the
#: postgrespgvector container's image (images.POSTGRESPGVECTOR). Both sources must publish it for
#: the PostgreSQL major in use: Homebrew's bottle tags and the Windows releases.
PGVECTOR_VERSION = "0.8.6"
HOMEBREW_PGVECTOR = "https://ghcr.io/v2/homebrew/core/pgvector"
#: ghcr's anonymous token: Homebrew's bottles are public, but the registry API
#: still wants a bearer.
HOMEBREW_HEADERS = {"Authorization": "Bearer QQ=="}
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
#: PGDG's build of it: the package revision, for the oldest distribution PGDG
#: still builds it for -- the lowest glibc.
PGDG_PGVECTOR_BUILD = "1.pgdg22.04+2"
PGDG_PGVECTOR_DOWNLOAD = (
    "https://apt.postgresql.org/pub/repos/apt/pool/main/p/pgvector"
    "/postgresql-{major}-pgvector_{version}-{build}_{arch}.deb"
)
WINDOWS_PGVECTOR_REPOSITORY = "andreiramani/pgvector_pgsql_windows"
WINDOWS_PGVECTOR_DOWNLOAD = (
    f"https://github.com/{WINDOWS_PGVECTOR_REPOSITORY}/releases/download"
    "/{version}_{major}/vector.v{version}-pg{major}.zip"
)

#: An extension's files, by where an install puts them.
_LIBRARY = re.compile(r"\.(dll|dylib|so)$")
_EXTENSION = re.compile(r"\.(control|sql)$")


def cache_directory() -> Path:
    """tabsdata-os's cache, shared with it."""
    return Path.home() / ".theseus" / "postgresql"


def resolve_version() -> str:
    return os.environ.get(ENV_VERSION, "").strip() or PINNED_VERSION


def major_of(version: str) -> str:
    return version.split(".", 1)[0]


def target_triple(
    system: str | None = None, machine: str | None = None, libc: str | None = None
) -> str:
    """The Rust target triple theseus-rs names its archives by, for this machine
    (the arguments are for tests). tabsdata-os asks ``rustc``; a machine running
    tdd need not have a Rust toolchain, and the five triples a developer can be on
    follow from the platform alone."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = {"arm64": "aarch64", "aarch64": "aarch64"}.get(machine)
    arch = arch or {"x86_64": "x86_64", "amd64": "x86_64"}.get(machine)
    if arch is None:
        raise TdxError(f"no PostgreSQL build for a {machine} machine")
    if system == "Darwin":
        return f"{arch}-apple-darwin"
    if system == "Linux":
        # musl reports no glibc version; theseus-rs builds both.
        flavour = (
            "gnu" if (platform.libc_ver()[0] if libc is None else libc) else "musl"
        )
        return f"{arch}-unknown-linux-{flavour}"
    if system == "Windows" and arch == "x86_64":
        return "x86_64-pc-windows-msvc"
    raise TdxError(f"no PostgreSQL build for {system} on {machine}")


# ---- PostgreSQL ---------------------------------------------------------


def postgresql_archive_name(version: str, target: str) -> str:
    return f"postgresql-{version}-{target}.tar.gz"


def postgresql_archive(version: str, target: str) -> Path:
    """The cached PostgreSQL archive, downloaded once. A fresh download is
    checked against the ``.sha256`` theseus-rs publishes beside it; one already
    in the cache is not, since tabsdata-os rewrites the Linux one in place."""
    path = cache_directory() / postgresql_archive_name(version, target)
    if path.is_file() and path.stat().st_size > 0:
        print(f">>> PostgreSQL {version} ({target}) already cached at {path}")
        return path
    url = RELEASE_DOWNLOAD.format(version=version, target=target)
    checksum = download.read(f"{url}.sha256", what=f"the checksum of {path.name}")
    return download.fetch(
        url,
        path,
        what=f"PostgreSQL {version} ({target})",
        sha256=checksum.decode("utf-8").split()[0],
    )


# ---- pgvector -------------------------------------------------------------


def pgvector_archive_name(version: str, major: str, target: str) -> str:
    if target.endswith("windows-msvc"):
        return f"pgvector-{version}-pg{major}-{target}.zip"
    if target.endswith("linux-gnu"):
        return f"pgvector-{version}-pg{major}-{target}.deb"
    # a bottle holds every major Homebrew ships, so one file serves them all
    return f"pgvector-{version}-{target}.bottle.tar.gz"


def _arch(target: str) -> str:
    """The architecture as Homebrew and Debian both spell it."""
    return "arm64" if target.startswith("aarch64") else "amd64"


def _homebrew_platform(target: str) -> tuple[str, str]:
    if target.endswith("apple-darwin"):
        return "darwin", _arch(target)
    raise TdxError(f"no Homebrew pgvector bottle is taken for {target}: macOS only")


def _os_version(entry: dict) -> tuple[int, ...]:
    text = entry.get("platform", {}).get("os.version", "")
    return tuple(int(n) for n in re.findall(r"\d+", text)) or (0,)


def select_bottle(index: dict, version: str, target: str) -> str:
    """The digest of the bottle for `target` in an OCI index of Homebrew's: the
    one for this system and architecture, the oldest macOS when there are
    several (a bottle runs on the macOS it was built for and every later one)."""
    os_name, arch = _homebrew_platform(target)
    found = [
        m
        for m in index.get("manifests", [])
        if m.get("platform", {}).get("os") == os_name
        and m.get("platform", {}).get("architecture") == arch
        and m.get("annotations", {}).get("sh.brew.bottle.digest")
    ]
    if not found:
        raise TdxError(
            f"Homebrew has no pgvector {version} bottle for {os_name}/{arch}"
        )
    oldest = min(found, key=_os_version)
    return oldest["annotations"]["sh.brew.bottle.digest"]


def pgvector_archive(version: str, major: str, target: str) -> Path:
    """The cached pgvector build for `target` and PostgreSQL `major`."""
    path = cache_directory() / pgvector_archive_name(version, major, target)
    if path.is_file() and path.stat().st_size > 0:
        print(f">>> pgvector {version} ({target}) already cached at {path}")
        return path
    what = f"pgvector {version} ({target})"
    if target.endswith("windows-msvc"):
        url = WINDOWS_PGVECTOR_DOWNLOAD.format(version=version, major=major)
        return download.fetch(url, path, what=what)
    if target.endswith("linux-gnu"):
        url = PGDG_PGVECTOR_DOWNLOAD.format(
            major=major,
            version=version,
            build=urllib.parse.quote(PGDG_PGVECTOR_BUILD),
            arch=_arch(target),
        )
        return download.fetch(url, path, what=what)
    if not target.endswith("apple-darwin"):
        raise TdxError(f"no pgvector build is published for {target}")
    index = json.loads(
        download.read(
            f"{HOMEBREW_PGVECTOR}/manifests/{version}",
            what=f"Homebrew's pgvector {version} index",
            headers={**HOMEBREW_HEADERS, "Accept": OCI_INDEX},
        )
    )
    digest = select_bottle(index, version, target)
    return download.fetch(
        f"{HOMEBREW_PGVECTOR}/blobs/sha256:{digest}",
        path,
        what=what,
        headers=HOMEBREW_HEADERS,
        sha256=digest,
    )


# ---- into a system's own tree --------------------------------------------


def expand_postgresql(archive: Path, tree: Path) -> None:
    """Unpack the PostgreSQL archive as `tree` (``bin/``, ``lib/``,
    ``share/``...). The archive holds one top-level directory named after
    itself; it is unpacked beside `tree` and renamed, so a failure halfway leaves
    no tree behind for a later step to mistake for a whole one."""
    tree.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tree.parent, prefix=".unpack-") as scratch:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(scratch, filter="data")
        roots = [p for p in Path(scratch).iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "bin").is_dir():
            raise TdxError(
                f"{archive} is not a PostgreSQL tree: expected one top-level "
                f"directory holding bin/, found {sorted(p.name for p in roots)}"
            )
        roots[0].rename(tree)


def deb_data(deb: bytes) -> bytes:
    """The data tarball of a ``.deb``: an ``ar`` archive of 60-byte headers,
    each followed by its member, padded to an even length."""
    if not deb.startswith(b"!<arch>\n"):
        raise TdxError("not a Debian package (no ar signature)")
    pos = 8
    while pos + 60 <= len(deb):
        header = deb[pos : pos + 60]
        name = header[:16].decode("ascii", "replace").strip().rstrip("/")
        size = int(header[48:58].decode("ascii").strip())
        if name.startswith("data.tar"):
            return deb[pos + 60 : pos + 60 + size]
        pos += 60 + size + (size & 1)
    raise TdxError("a Debian package without its data.tar")


def _tar_members(tar: tarfile.TarFile, keep: re.Pattern) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for member in tar.getmembers():
        if member.isfile() and keep.search(member.name):
            handle = tar.extractfile(member)
            out.append((member.name, handle.read() if handle else b""))
    return out


def _extension_members(archive: Path, major: str) -> list[tuple[str, bytes]]:
    """``(name, content)`` of every file of the build for PostgreSQL `major` in
    a pgvector archive: a bottle's builds sit under ``postgresql@<major>``, a
    Debian package's under ``postgresql/<major>``, and a Windows zip holds one."""
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            return [(i.filename, zf.read(i)) for i in zf.infolist() if not i.is_dir()]
    if archive.suffix == ".deb":
        data = io.BytesIO(deb_data(archive.read_bytes()))
        with tarfile.open(fileobj=data, mode="r:*") as tar:
            return _tar_members(tar, re.compile(rf"/postgresql/{major}/"))
    with tarfile.open(archive, "r:gz") as tar:
        return _tar_members(tar, re.compile(rf"/postgresql@{major}/"))


def install_pgvector(archive: Path, major: str, tree: Path) -> list[Path]:
    """Install pgvector into the PostgreSQL `tree`: its library into ``lib/``,
    its control file and scripts into ``share/extension/``. Each file goes in
    by its bare name, so nothing in the archive chooses where it lands."""
    lib, ext = tree / "lib", tree / "share" / "extension"
    placed: list[Path] = []
    for name, content in _extension_members(archive, major):
        base = Path(name).name
        where = (
            lib if _LIBRARY.search(base) else ext if _EXTENSION.search(base) else None
        )
        if where is None:
            continue
        where.mkdir(parents=True, exist_ok=True)
        (where / base).write_bytes(content)
        placed.append(where / base)
    if (
        not any(_LIBRARY.search(p.name) for p in placed)
        or not (ext / "vector.control").is_file()
    ):
        raise TdxError(
            f"{archive} has no pgvector build for PostgreSQL {major} "
            f"(a library and vector.control)"
        )
    return placed


def fetch_all(version: str, target: str, *, pgvector: bool) -> tuple[Path, Path | None]:
    """The archives a system needs, from the cache or downloaded into it:
    PostgreSQL's, and pgvector's when the system installs it."""
    return (
        postgresql_archive(version, target),
        pgvector_archive(PGVECTOR_VERSION, major_of(version), target)
        if pgvector
        else None,
    )


def build_tree(version: str, target: str, tree: Path, *, pgvector: bool) -> None:
    """A system's own PostgreSQL tree at `tree`, with pgvector installed in it
    when `pgvector`."""
    pg, vector = fetch_all(version, target, pgvector=pgvector)
    print(f">>> expanding {pg.name} into {tree}")
    expand_postgresql(pg, tree)
    if vector is None:
        return
    try:
        installed = install_pgvector(vector, major_of(version), tree)
    except BaseException:
        shutil.rmtree(tree, ignore_errors=True)
        raise
    print(
        f">>> pgvector {PGVECTOR_VERSION}: {', '.join(p.name for p in installed if _LIBRARY.search(p.name) or p.suffix == '.control')}"
    )
