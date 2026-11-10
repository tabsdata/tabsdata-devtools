#
# Copyright 2026 Tabsdata Inc.
#

"""``SqlDatabase`` -- the nature of SQL databases: a domain is a database with
its own owner, administered and loaded over SQLAlchemy.

A concrete SQL system (mysql, postgres, oracle, db2, mssqlserver, clickhouse,
starrocks, …) supplies only its *dialect hooks*: the SQLAlchemy driver and
identifier quote, the CREATE/DROP-domain SQL and the schema-listing query, and
the set of the server's own schemas that must never be treated as domains. Its
hosting supplies the rest (for a container: image, server flags, readiness).
TCP admin over SQLAlchemy, per-domain provisioning, model/data loading and delta
application live here once.

The per-model DDL for a system lives beside its backend under
``<slug>/domain/models/<model>/<slug>.ddl`` (a model is available for the system
iff that file exists), so the same generic ``models`` / ``create-model`` /
``create-data`` / ``modify-data`` commands work for every dialect.
"""

from __future__ import annotations

import hashlib
import inspect
from contextlib import contextmanager
from pathlib import Path

from tabsdata_dev.common.systems import constants, datagen, emit
from tabsdata_dev.common.systems.diagnostics import db_failure
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.shell import validate_name
from tabsdata_dev.common.systems.sql_runner import (
    as_written,
    run_sql_schedule,
    run_sql_text,
    run_sql_transactions,
)
from tabsdata_dev.common.systems.systems._common.hosting.endpoint import (
    DEFAULT_HOSTNAME,
    Admin,
)
from tabsdata_dev.common.systems.systems._common.nature.server._base import Server

# How long a statement of a concurrent schedule may wait for a row lock before
# the dialect gives up on it (where the dialect has such a timeout). The
# schedule is one thread, so a wait is never for a session that will move:
# only another of the run's own open transactions can hold the lock, and it
# cannot commit until the waiting statement returns. Any wait at all is the
# error; the seconds only have to exceed a statement's own latency.
LOCK_WAIT_SECONDS = 10


class SqlDatabase(Server):
    nature: str = "sql_database"

    # ---- capability flags (drive verb availability in the dispatcher) ----
    supports_models: bool = True
    supports_data: bool = True
    supports_changes: bool = True
    # A SQL engine takes concurrent transactions on concurrent connections, so
    # modify-data's interleaved and nested schedules apply as planned. A
    # subclass that has no multi-statement transactions, or that locks a whole
    # table for a write, says False.
    supports_trx_modes: bool = True
    # The dialect's DELETE locks every row it scans, not only the rows it removes
    # (MySQL InnoDB, Db2): on a table with no key and no unique index it scans it
    # all, and waits on any row another open transaction wrote. Postgres reads row versions and waits only on the rows
    # its WHERE matches, so it says False.
    scan_locks: bool = False

    # ---- shape (subclass sets these) ----
    kind: str = "sql"
    domain_word: str = "database"
    max_entity_name_length: int = 63
    login_maxlen: int = 32

    # ---- dialect hooks (subclass overrides) ----
    driver: str = ""  # SQLAlchemy driver, e.g. "mysql+pymysql"
    sql_quote: str = '"'
    # Lower-case words the dialect refuses as a bare column name; the generated
    # INSERT/UPDATE/DELETE quote them, as the system's DDL has to.
    sql_reserved: frozenset[str] = frozenset()
    system_schemas: frozenset[str] = frozenset()
    admin_db: str = ""  # maintenance DB the admin connection targets (pg: postgres)
    admin_autocommit: bool = False  # some DBs can't CREATE/DROP DATABASE in a txn
    ddl_from_slug: str = ""  # borrow another system's DDL (CDC reuses the plain one)
    # Rows per INSERT for the initial load; 1 = one INSERT per row (Oracle has no
    # multi-row VALUES). Higher = fewer round-trips where the dialect allows it.
    insert_batch: int = 500

    # ---- naming ---------------------------------------------------------

    # The domain-meta keys holding the address tdx connects to and the domain's
    # own database. One endpoint and one word for a database need no qualifier,
    # so a domain says HOST and DB; a family that names its networks and spells
    # the word out points these at its own keys (see Postgres).
    domain_db_key: str = "DB"

    def _login(self, name: str) -> str:
        # The owner user is named after the domain, capped at the dialect's
        # identifier limit. A plain truncation collides when sibling domains
        # share a prefix longer than the cap (their distinguishing suffix is
        # cut off), so past the cap keep a prefix and append a hash of the full
        # name to stay unique. Deterministic, so create and delete agree.
        if len(name) <= self.login_maxlen:
            return name
        digest = hashlib.sha1(name.encode()).hexdigest()[:8]
        return f"{name[: self.login_maxlen - len(digest) - 1]}_{digest}"

    def _package_dir(self) -> Path:
        return Path(inspect.getfile(type(self))).parent

    # ---- dialect hooks with defaults ------------------------------------

    def session_setup(self) -> list[str]:
        """Statements run first on every data-plane connection (DDL install, load,
        modify-data) — e.g. Oracle sets NLS_*_FORMAT so the ISO date/timestamp
        literals the generator emits parse. Default: nothing."""
        return []

    def concurrent_session_setup(self) -> list[str]:
        """Statements run after :meth:`session_setup` on every connection of a
        concurrent schedule (modify-data's interleaved and nested modes), and
        nowhere else: the dialect's lock-wait timeout of ``LOCK_WAIT_SECONDS``,
        so a statement blocked by another of the run's own open transactions
        fails instead of waiting forever, and whatever else keeps two
        connections writing different rows of one table out of each other's
        way. Default: nothing (Oracle: no timeout exists for a DML lock wait;
        its row locks do not block a scan, so only a shared target waits)."""
        return []

    def create_domain_sql(self, db: str, user: str, password: str) -> list[str]:
        """Admin statements that create the domain container + owner."""
        raise NotImplementedError

    def delete_domain_sql(self, name: str) -> list[str]:
        raise NotImplementedError

    def list_schemas_sql(self) -> str:
        """Query returning one row per domain-container name (server schemas are
        filtered out by :attr:`system_schemas`)."""
        raise NotImplementedError

    # ---- URLs -----------------------------------------------------------

    def sqlalchemy_url(
        self, host: str, port: str, db: str = "", user: str = "", password: str = ""
    ) -> str:
        creds = f"{user}:{password}@" if user else ""
        tail = f"/{db}" if db else ""
        return f"{self.driver}://{creds}{host}:{port}{tail}"

    # ---- system lifecycle ----------------------------------------------

    # ---- domain lifecycle ----------------------------------------------

    def _admin_url(self, admin: Admin) -> str:
        return self.sqlalchemy_url(
            admin.host,
            admin.port,
            db=admin.db or self.admin_db,
            user=admin.user,
            password=admin.password,
        )

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        admin = self._admin(sys_meta)
        login = self._login(entity_name)
        uri = self.sqlalchemy_url(
            admin.host, admin.port, db=entity_name, user=login, password=password
        )
        uri_no_creds = self.sqlalchemy_url(admin.host, admin.port, db=entity_name)
        return {
            "HOST": admin.host,
            "PORT": admin.port,
            "USER": login,
            "PASSWORD": password,
            "DB": entity_name,
            "SQLALCHEMY_URI": uri,
            "URI": uri_no_creds,
            "IMAGE": sys_meta.get("IMAGE", ""),
            "SYS_DOCKER_CONTAINER_NAME": sys_meta.get("DOCKER_CONTAINER_NAME", ""),
            "SYS_DOCKER_CONTAINER_ID": sys_meta.get("DOCKER_CONTAINER_ID", ""),
            "SYS_ADMIN_USER": admin.user,
            "SYS_ADMIN_PASSWORD": admin.password,
        }

    def provision_domain(
        self,
        sys_meta: dict[str, str],
        entity_name: str,
        domain_meta: dict[str, str],
        *,
        force: bool = False,
    ) -> None:
        validate_name(entity_name, label=self.domain_word)
        admin = self._admin(sys_meta)
        exists = any(d.lower() == entity_name.lower() for d in self._do_list(admin))
        if exists and not force:
            raise TdxError(
                f"{self.domain_word} '{entity_name}' already exists (use --force)"
            )
        if exists:
            self._do_delete(admin, entity_name)
            print(f">>> --force: removed existing {self.domain_word} '{entity_name}'")
        elif force:
            try:
                self._do_delete(admin, entity_name)
            except TdxError:
                pass
        self._do_create(
            admin,
            domain_meta[self.domain_db_key],
            domain_meta["USER"],
            domain_meta["PASSWORD"],
        )

    def destroy_domain(self, domain_meta: dict[str, str]) -> None:
        admin = Admin(
            host=domain_meta.get(self.domain_host_key, DEFAULT_HOSTNAME),
            port=domain_meta.get("PORT", ""),
            user=domain_meta.get("SYS_ADMIN_USER", self.root_user),
            password=domain_meta.get("SYS_ADMIN_PASSWORD", ""),
        )
        self._do_delete(admin, domain_meta[self.domain_db_key])

    def list_domain_entities(self, sys_meta: dict[str, str]) -> list[str]:
        return self._do_list(self._admin(sys_meta))

    def purge_domain_entity(self, sys_meta: dict[str, str], name: str) -> None:
        if name.lower() in self.system_schemas:
            raise TdxError(f"refusing to purge {self.label} system schema '{name}'")
        self._do_delete(self._admin(sys_meta), name)

    # ---- admin DDL (over TCP) ------------------------------------------

    def _do_create(self, admin: Admin, db: str, user: str, password: str) -> None:
        self._run_admin(admin, self.create_domain_sql(db, user, password))

    def _do_delete(self, admin: Admin, name: str) -> None:
        self._run_admin(admin, self.delete_domain_sql(name))

    def _do_list(self, admin: Admin) -> list[str]:
        names = self._query_admin(admin, self.list_schemas_sql())
        return [n for n in names if n.lower() not in self.system_schemas]

    def _run_admin(self, admin: Admin, statements: list[str]) -> None:
        from sqlalchemy import create_engine

        url = self._admin_url(admin)
        engine = create_engine(url)
        running = ""
        try:
            if self.admin_autocommit:
                with engine.connect() as conn:
                    conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                    for st in statements:
                        running = st
                        as_written(conn, st)
            else:
                with engine.begin() as conn:
                    for st in statements:
                        running = st
                        as_written(conn, st)
        except Exception as exc:
            raise TdxError(
                f"{self.label} admin SQL failed: {exc}",
                db_failure(exc, statement=running, url=url, label="admin SQL"),
            ) from exc
        finally:
            engine.dispose()

    def _query_admin(self, admin: Admin, query: str) -> list[str]:
        from sqlalchemy import create_engine

        url = self._admin_url(admin)
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                rows = as_written(conn, query).fetchall()
        except Exception as exc:
            raise TdxError(
                f"{self.label} admin query failed: {exc}",
                db_failure(exc, statement=query, url=url, label="admin query"),
            ) from exc
        finally:
            engine.dispose()
        return [str(r[0]).strip() for r in rows if r and r[0] is not None]

    # ---- data plane -----------------------------------------------------

    @contextmanager
    def data_plane_uri(self, meta: dict[str, str]):
        """The URI the loader connects on, for the length of the block.

        A context manager because a connection may need something on disk that
        nothing should keep afterwards -- a managed instance's root certificate,
        which libpq takes as a path (see ManagedPostgres). A container has
        nothing to set up, so the default just hands the URI over."""
        yield meta["SQLALCHEMY_URI"]

    def _ddl_dir(self, model: str) -> Path:
        root = self._package_dir()
        if self.ddl_from_slug:
            root = root.parent / self.ddl_from_slug
        return root / "domain" / "models" / model

    def after_install_schema(self, meta: dict[str, str], model: str) -> None:
        """Hook run after the model DDL is installed (default: nothing), given the
        domain `meta`. CDC variants use it to prep the tables for capture (e.g.
        REPLICA IDENTITY FULL, or ASN registration inside the container)."""

    def has_model(self, model: str) -> bool:
        d = self._ddl_dir(model)
        return d.is_dir() and any(d.glob("*.ddl"))

    def available_models(self) -> list[str]:
        return [m for m in datagen.list_models() if self.has_model(m)]

    def ddl_text(self, model: str) -> str:
        d = self._ddl_dir(model)
        files = sorted(d.glob("*.ddl"))
        if not files:
            raise TdxError(f"model '{model}' has no {self.label} DDL (looked in {d})")
        return "\n\n".join(f.read_text(encoding="utf-8") for f in files)

    def install_schema(
        self, meta: dict[str, str], model: str, *, force: bool = False
    ) -> None:
        with self.data_plane_uri(meta) as uri:
            if force:
                self.drop_all_tables(uri)
            print(f">>> creating schema for model '{model}' …")
            setup = "".join(f"{s};\n" for s in self.session_setup())
            run_sql_text(uri, setup + self.ddl_text(model))
            self.after_install_schema(meta, model)
        print(">>> schema ready")

    def uninstall_schema(self, meta: dict[str, str], model: str) -> None:
        with self.data_plane_uri(meta) as uri:
            self.drop_all_tables(uri)
        print(f">>> model '{model}' removed")

    def load_tables(self, uri: str, tables: list[emit.Table]) -> dict[str, int]:
        statements: list[str] = []
        counts: dict[str, int] = {}
        for tbl in tables:
            counts[tbl.name] = len(tbl.rows)
            statements.extend(
                emit.iter_insert_statements(
                    tbl.name,
                    tbl.columns,
                    tbl.rows,
                    batch=self.insert_batch,
                    quote=self.sql_quote,
                    reserved=self.sql_reserved,
                )
            )
        if statements:
            print(
                f">>> loading {sum(counts.values())} rows into {len(tables)} tables …"
            )
            run_sql_transactions(uri, [self.session_setup() + statements], label="load")
        return counts

    def apply_changes(
        self,
        uri: str,
        transactions: list,
        before: dict[str, int],
        *,
        label: str = "modify-data",
        schedule=None,
    ) -> dict[str, int]:
        from tabsdata_dev.common.systems import trx

        rendered = [
            [
                datagen.render_sql(c, quote=self.sql_quote, reserved=self.sql_reserved)
                for c in txn
            ]
            for txn in transactions
        ]
        if schedule is None or schedule.mode is trx.TrxMode.SERIAL:
            run_sql_transactions(
                uri, [self.session_setup() + stmts for stmts in rendered], label=label
            )
        else:
            if not self.supports_trx_modes:
                raise TdxError(
                    f"{self.label} applies {label} serially only "
                    f"({constants.OPT_TRX_MODE} {trx.TrxMode.SERIAL.value})"
                )
            if self.scan_locks:
                self._refuse_scan_waits(uri, transactions, schedule, label)
            print(
                f">>> {schedule.transactions} transaction(s) {schedule.mode.value}, "
                f"{schedule.concurrency} open at once: {schedule.summary} …"
            )
            run_sql_schedule(
                uri,
                rendered,
                schedule.steps,
                setup=self.session_setup() + self.concurrent_session_setup(),
                label=label,
            )
        new = dict(before)
        for table, delta in datagen.net_row_deltas(transactions).items():
            new[table] = max(0, new.get(table, 0) + delta)
        return new

    def reflect_schema(self, uri: str) -> str | None:
        """The schema a domain's tables are reflected in; None is the
        connection's default, right wherever the domain is a database."""
        return None

    def keyless_tables(self, uri: str, tables: set[str]) -> set[str]:
        """Those of `tables` with no primary key and no unique index or
        constraint -- the ones an UPDATE or DELETE has to scan whole."""
        from sqlalchemy import create_engine, inspect

        engine = create_engine(uri)
        schema = self.reflect_schema(uri)
        out: set[str] = set()
        try:
            insp = inspect(engine)
            for t in sorted(tables):
                if insp.get_pk_constraint(t, schema=schema).get("constrained_columns"):
                    continue
                if any(i.get("unique") for i in insp.get_indexes(t, schema=schema)):
                    continue
                try:
                    if insp.get_unique_constraints(t, schema=schema):
                        continue
                except NotImplementedError:  # a dialect that reports them as indexes
                    pass
                out.add(t)
        except Exception as exc:
            raise TdxError(
                f"{self.label}: cannot read the tables' keys: {exc}",
                db_failure(exc, statement="(reflection)", url=uri, label="keys"),
            ) from exc
        finally:
            engine.dispose()
        return out

    def _refuse_scan_waits(self, uri: str, transactions: list, schedule, label: str):
        """Refuse a schedule that would wait on its own run before it starts:
        the one thread cannot commit what a statement waits for, so the
        dialect's lock timeout would end it half applied, after seconds."""
        from tabsdata_dev.common.systems import trx

        written = {c.table for txn in transactions for c in txn}
        hit = trx.scan_waits(transactions, schedule, self.keyless_tables(uri, written))
        if hit is None:
            return
        txn, table, other = hit
        raise TdxError(
            f"{self.label} cannot apply this {label} as {schedule.label}: transaction "
            f"{txn} deletes from {table}, which has no key or unique index, so "
            f"{self.label} scans it whole and locks every row it reads -- and transaction "
            f"{other}, open beside it, has written rows there it cannot commit until the "
            f"statement returns. Leave {table} out of this run ({constants.OPT_ENTITY}) "
            f"and change it in a serial one, or use {constants.OPT_TRX_MODE} serial or "
            f"nested"
        )

    def drop_all_tables(self, uri: str) -> None:
        from sqlalchemy import MetaData, create_engine

        engine = create_engine(uri)
        try:
            md = MetaData()
            md.reflect(bind=engine)
            if md.tables:
                print(f">>> dropping {len(md.tables)} existing table(s) …")
                md.drop_all(bind=engine)
        finally:
            engine.dispose()
