#
# Copyright 2026 Tabsdata Inc.
#

"""The structural contract every system backend satisfies.

Command modules receive a backend as ``ctx.system`` and call these methods; a
new system is a class that implements this Protocol (plus its command files).
``meta`` dicts are the descriptor's connection settings (see ``descriptor``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tabsdata_dev.common.systems.datagen import Transaction
    from tabsdata_dev.common.systems.emit import Table


class Backend(Protocol):
    slug: str
    label: str
    kind: str  # SYSTEM_KIND baked into the descriptor (v1: sql/file/service/…)
    # The system's two coordinates: where it runs (container / remote / managed
    # / local) and what it is (sql_database / object_store / ai_provider / …).
    hosting: str
    nature: str
    domain_word: str
    max_entity_name_length: int
    weight: int  # 1..3 scheduling weight; batch runs the heaviest targets first
    exclusive: bool

    # Managed venvs (see ``_venv``): the env a verb re-execs into. ``sys_toolset``
    # covers the verbs that only touch the system from the outside (create /
    # destroy / status / restart / fetch-bin); ``dom_toolset`` the ones that reach
    # inside it — every domain verb, plus ``purge``.
    sys_toolset: str
    dom_toolset: str

    # capability flags — the dispatcher gates verb availability on these.
    is_container: bool
    # restart: a system tdd runs (a container, a native process) and can start
    # again after the machine or docker restarted.
    supports_restart: bool
    # fetch-bin: the system has binaries to get onto this machine ahead of a
    # create -- a container's images, a native system's archives.
    fetches_binaries: bool
    # --sys-hostname: the system's port is on this machine, so another name for
    # the machine is something its descriptor can advertise.
    advertises_host: bool
    supports_purge: bool
    supports_models: bool
    supports_data: bool
    supports_changes: bool
    # modify-data's --trx-mode: the backend applies a run's transactions
    # interleaved or nested over concurrent connections (the SQL engines).
    supports_trx_modes: bool
    # capture-table / release-table: the backend registers a table of the
    # domain for change capture on demand (a test's own CDC source table).
    supports_table_capture: bool

    def docker_images(self) -> list[tuple[str, str]]: ...

    def fetch_bin(self, done: set[str]) -> None:
        """Get the system's binaries onto this machine (``fetches_binaries``),
        skipping what `done` names and adding what it fetched."""

    def configure(self, meta: dict[str, str]) -> None:
        """Bind a resolved descriptor's ``meta`` to the backend before its verb
        runs, so a backend that would otherwise read its config from the
        environment at use time (object stores) works from the descriptor alone
        — the only environment variable ever read at use time is the crypto key.
        Optional: backends that already build every op from ``meta`` don't
        implement it (the dispatcher binds only when present)."""

    def options(self) -> tuple:
        """Declarative create options (see ``options.Option``); ``()`` = none."""

    def synth_default(self, name: str, sys_name: str) -> str:
        """The SYNTH-source default for option `name` (backends with such options
        implement it)."""

    def use_ports(self, ports: list[int]) -> None:
        """Pin the host ports for this create (``--ports``), used in order before
        the system's own port slot. Only port-using backends implement it."""

    def next_free_port(self) -> int:
        """A host port for the create: the next pinned one, else the first free
        port of this system type's slot not handed out yet (every type owns a
        fixed slot, so parallel creates never compete). Only port-using backends
        implement it."""

    def use_hostname(self, host: str) -> None:
        """Bind the hostname this create advertises instead of 127.0.0.1
        (``--sys-hostname``), so the endpoints ``plan_system`` records are usable
        from other machines. Only backends that publish one implement it (see
        ``systems._common.hosting.container.hostname``)."""

    # system lifecycle. `overrides` carries the resolved create options (see
    # `options`) — every declared option is present, so the backend reads its
    # connection settings from here rather than the environment.
    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]: ...
    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]: ...
    def destroy_system(self, meta: dict[str, str]) -> None: ...
    def system_status(self, meta: dict[str, str]) -> tuple[bool, str]: ...
    def restart_system(self, meta: dict[str, str]) -> str: ...

    # domain lifecycle
    def new_domain_password(self) -> str: ...
    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]: ...
    def provision_domain(
        self,
        sys_meta: dict[str, str],
        entity_name: str,
        domain_meta: dict[str, str],
        *,
        force: bool = False,
    ) -> None: ...
    def destroy_domain(self, domain_meta: dict[str, str]) -> None: ...
    def domain_status(self, domain_meta: dict[str, str]) -> tuple[bool, str]: ...
    def list_domain_entities(self, sys_meta: dict[str, str]) -> list[str]: ...
    def purge_domain_entity(self, sys_meta: dict[str, str], name: str) -> None: ...

    # data plane
    def data_plane_uri(self, meta: dict[str, str]):
        """A context manager yielding the opaque handle the generic data-plane
        commands pass to ``install_schema`` / ``load_tables`` / ``apply_changes``
        — the SQLAlchemy URL for SQL backends, the staging destination for file
        backends. A context manager because a handle may need something on disk
        that nothing should keep once the connection is done with it (a managed
        instance's root certificate)."""

    def has_model(self, model: str) -> bool: ...
    def available_models(self) -> list[str]: ...
    def install_schema(
        self, meta: dict[str, str], model: str, *, force: bool = False
    ) -> None: ...
    def uninstall_schema(self, meta: dict[str, str], model: str) -> None:
        """Remove `model`'s entities from the domain, rows and all -- the
        inverse of ``install_schema``, which ``delete-model`` calls."""

    def load_tables(self, uri: str, tables: list[Table]) -> dict[str, int]:
        """Load `tables`; return the ``entities`` to record — ``{table: rows}`` for
        SQL, ``{file_path: rows}`` for file backends."""

    def apply_changes(
        self,
        uri: str,
        transactions: list[Transaction],
        before: dict[str, int],
        *,
        label: str = "modify-data",
        schedule=None,
    ) -> dict[str, int]:
        """Apply `transactions` and return the new ``entities`` map (SQL: `before`
        adjusted by the net row deltas; file: `before` plus the new files).
        `label` is the verb a failure is reported under. `schedule` (a
        ``trx.Schedule``) says how the transactions are applied; ``None`` is
        serial, and a backend without ``supports_trx_modes`` refuses any other."""

    def drop_all_tables(self, uri: str) -> None: ...
