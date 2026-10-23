#
# Copyright 2026 Tabsdata Inc.
#

"""``FileStore`` -- the nature of systems that stage data files under a root.

A file system has no container and no schema: the "system" is a staging root, a
"domain" is a prefix/folder under it, and a model's data is staged as one file
per entity per format (:data:`emit.FILE_FORMATS` — csv / ndjson / parquet), each
named ``<entity>_<YYYYMMDD>T<hhmmss_mmm>.<fmt>`` after the command's invocation
time. ``modify-data`` is **insert-only** — each run writes the inserted rows as
NEW (freshly timestamped) files alongside the seed, never mutating existing ones.
Concrete systems (fs, and through :class:`ObjectStore` s3, gcs, azureblob)
implement only the five storage primitives; everything else lives here once.

The generic data-plane commands take the domain's staging destination from
:meth:`data_plane_uri` (the opaque ``BASE_PATH`` — a path for fs, a bucket key for
object stores). The descriptor's ``URI`` is the connector-facing location URI
(``file://`` / ``s3://`` / ``gs://`` / ``az://``); a file domain has no
``SQLALCHEMY_URI``, and its ``entities`` are the staged file paths (relative to
the domain root) mapped to their row counts.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tabsdata_dev.common.systems import constants, datagen, emit
from tabsdata_dev.common.systems.datagen import OpKind
from tabsdata_dev.common.systems.errors import TdxError


def squash_slashes(path: str) -> str:
    """Collapse every run of ``/`` down to a single ``/`` so a stray ``//`` in a
    configured ``SYS_PATH`` never reaches a composed key/path (the connectors
    reject empty path segments). A single leading ``/`` is preserved."""
    while "//" in path:
        path = path.replace("//", "/")
    return path


def normalise_prefix(prefix: str) -> str:
    """An object-store key prefix: no leading ``/``, a single trailing ``/`` when
    non-empty (so ``prefix + rel`` is a valid key)."""
    p = squash_slashes((prefix or "").strip()).lstrip("/")
    if p and not p.endswith("/"):
        p += "/"
    return p


def walk_files(local_dir: str) -> Iterator[tuple[Path, str]]:
    """Yield ``(absolute_file, posix_relpath)`` for every file under `local_dir`."""
    base = Path(local_dir)
    for src in sorted(base.rglob("*")):
        if src.is_file():
            yield src, src.relative_to(base).as_posix()


class FileStore:
    nature: str = "file_store"

    # ---- capability flags ----
    supports_purge: bool = True
    supports_models: bool = True
    supports_data: bool = True
    supports_changes: bool = True  # insert-only (enforced in apply_changes)
    supports_trx_modes: bool = (
        False  # a change set is one staging; nothing to interleave
    )
    supports_table_capture: bool = False

    # Staging data files needs the frame writer.
    dom_toolset: str = constants.TOOLSET_SYSTEMS

    kind: str = "file"
    domain_word: str = "prefix"
    max_entity_name_length: int = 255

    # ---- storage primitives (subclass implements) ----

    def store_status(self, root: str) -> None:
        """Raise if the staging root isn't reachable."""
        raise NotImplementedError

    def store_exists(self, dest: str) -> bool:
        """True if `dest` already holds objects."""
        raise NotImplementedError

    def store_children(self, root: str) -> list[str]:
        """Immediate child prefix/folder names under `root` (the domains)."""
        raise NotImplementedError

    def store_clear(self, dest: str) -> None:
        """Remove every object under `dest`."""
        raise NotImplementedError

    def store_upload(self, dest: str, local_dir: str) -> int:
        """Upload the `local_dir` tree under `dest`; return the file count."""
        raise NotImplementedError

    def join(self, root: str, child: str) -> str:
        return squash_slashes(f"{root.rstrip('/')}/{child}")

    # ---- system hooks (for the attached hosting) -----------------------

    def complete_plan(self, name: str, meta: dict[str, str]) -> dict[str, str]:
        return meta

    def probe_system(self, meta: dict[str, str]) -> tuple[bool, str]:
        root = meta.get("SYS_PATH", "")
        try:
            self.store_status(root)
        except Exception as exc:  # noqa: BLE001
            return False, f"cannot reach {self.slug}: {exc}"
        return True, f"{self.label} root '{root}' reachable"

    # ---- domain lifecycle ----

    def new_domain_password(self) -> str:
        return ""  # file domains have no credentials

    @contextmanager
    def data_plane_uri(self, meta: dict[str, str]):
        yield meta["BASE_PATH"]  # the opaque staging destination; nothing to set up

    def _uri(self, dest: str) -> str:
        """The connector-facing location URI for storage destination `dest`."""
        return Path(dest).as_uri()  # fs: file:///abs/path

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        root = sys_meta["SYS_PATH"]
        dest = self.join(root, entity_name)
        return {
            "SYS_PATH": root,
            "BASE_PATH": dest,  # the opaque staging destination (data_plane_uri)
            "DB": entity_name,
            "URI": self._uri(dest),
        }

    def provision_domain(
        self,
        sys_meta: dict[str, str],
        entity_name: str,
        domain_meta: dict[str, str],
        *,
        force: bool = False,
    ) -> None:
        dest = domain_meta["BASE_PATH"]
        if self.store_exists(dest):
            if force:
                self.store_clear(dest)
            else:
                raise TdxError(
                    f"{self.domain_word} has objects: {dest} (use --force to clear)"
                )

    def destroy_domain(self, domain_meta: dict[str, str]) -> None:
        self.store_clear(domain_meta["BASE_PATH"])

    def domain_status(self, domain_meta: dict[str, str]) -> tuple[bool, str]:
        try:
            self.store_status(domain_meta.get("SYS_PATH", ""))
        except Exception as exc:  # noqa: BLE001
            return False, f"cannot reach {self.slug}: {exc}"
        return True, f"{self.label} domain at {domain_meta.get('BASE_PATH', '')}"

    def list_domain_entities(self, sys_meta: dict[str, str]) -> list[str]:
        return self.store_children(sys_meta["SYS_PATH"])

    def purge_domain_entity(self, sys_meta: dict[str, str], name: str) -> None:
        self.store_clear(self.join(sys_meta["SYS_PATH"], name))

    # ---- data plane ----

    def has_model(self, model: str) -> bool:
        return model in datagen.list_models()  # any model — no per-system DDL

    def available_models(self) -> list[str]:
        return datagen.list_models()

    def install_schema(
        self, meta: dict[str, str], model: str, *, force: bool = False
    ) -> None:
        if force:
            with self.data_plane_uri(meta) as dest:
                self.store_clear(dest)
        print(">>> file domain: no schema to install")

    def uninstall_schema(self, meta: dict[str, str], model: str) -> None:
        # A file domain's model IS its staged files: removing it clears them.
        with self.data_plane_uri(meta) as dest:
            self.store_clear(dest)
        print(f">>> file domain: model '{model}' files removed")

    def _stage_and_upload(
        self, dest: str, tables: list[emit.Table], stamp: str
    ) -> dict[str, int]:
        """Stage each table as ``<fmt>/<entity>_<stamp>.<fmt>`` for every format,
        upload the tree under `dest`, and return ``{relative_path: row_count}``."""
        entities: dict[str, int] = {}
        with tempfile.TemporaryDirectory(prefix="tdx-files-") as tmp:
            root = Path(tmp)
            for fmt in emit.FILE_FORMATS:
                for tbl in tables:
                    rel = f"{fmt}/{tbl.name}_{stamp}.{fmt}"
                    emit.write_frame(tbl, root / rel, fmt)
                    entities[rel] = len(tbl.rows)
            self.store_upload(dest, str(root))
        return entities

    def load_tables(self, uri: str, tables: list[emit.Table]) -> dict[str, int]:
        stamp = emit.file_stamp()
        print(
            f">>> staging {sum(len(t.rows) for t in tables)} rows as "
            f"{len(emit.FILE_FORMATS)} format(s) -> {uri} …"
        )
        return self._stage_and_upload(uri, tables, stamp)

    def apply_changes(
        self,
        uri: str,
        transactions: list,
        before: dict[str, int],
        *,
        label: str = "modify-data",
        schedule=None,
    ) -> dict[str, int]:
        changes = [c for txn in transactions for c in txn]
        if any(c.kind is not OpKind.INSERT for c in changes):
            raise TdxError(
                f"{self.slug} domains support only inserts for {label} "
                f"(a change is a new file) — use --ops Insert"
            )
        if schedule is not None and schedule.mode.value != "serial":
            raise TdxError(
                f"{self.slug} domains apply {label} as one staging: "
                f"{constants.OPT_TRX_MODE} serial only"
            )
        by_table: dict[str, tuple[list, list]] = {}
        for c in changes:
            by_table.setdefault(c.table, (c.columns, []))[1].append(c.row)
        tables = [
            emit.Table(name=t, columns=cols, rows=rows)
            for t, (cols, rows) in by_table.items()
        ]
        stamp = emit.file_stamp()
        print(f">>> staging {len(changes)} inserted row(s) -> {uri} …")
        staged = self._stage_and_upload(uri, tables, stamp)
        return {**before, **staged}  # accumulate the new files onto the prior ones

    def drop_all_tables(self, uri: str) -> None:
        self.store_clear(uri)
