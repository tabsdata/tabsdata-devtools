#
# Copyright 2026 Tabsdata Inc.
#

"""``SqlWarehouse`` -- the nature of SQL warehouses (snowflake, databricks,
bigquery): a :class:`SqlDatabase` whose domain is a SCHEMA inside the account's
namespace (a ``DATABASE`` / ``CATALOG``), administered over the account's own
connection.

It reuses the whole :class:`SqlDatabase` data plane (install-schema / load /
modify-data over SQLAlchemy). Create reads the connection from the declared
``options()`` (env-sourced by default), bakes it into the descriptor and probes
it with ``SELECT 1``. Subclasses supply the connection ``options()``, the dialect
``_url`` and identifier ``sql_quote``, and -- where the case differs --
``_schema``; ``_extra_domain_sql`` adds any per-domain setup (e.g. a Volume).
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.sql_runner import as_written
from tabsdata_dev.common.systems.systems._common.nature.database.sql import (
    SqlDatabase,
)


class SqlWarehouse(SqlDatabase):
    # A warehouse is no place for a concurrent schedule: Databricks has no
    # multi-statement transaction at all, and Snowflake's DML takes a lock on
    # the table, so a second transaction's UPDATE waits for the first's commit.
    supports_trx_modes = False
    env_prefix: str = ""
    namespace_meta: str = (
        "DATABASE"  # meta key naming the DB/catalog the schema sits in
    )

    def options(self) -> tuple[options.Option, ...]:
        return ()  # subclass declares its connection options

    # ---- connection ----------------------------------------------------

    def _schema(self, name: str) -> str:
        return name

    def _url(self, meta: dict[str, str], schema: str = "") -> str:
        raise NotImplementedError

    def _location(self, meta: dict[str, str]) -> str:
        return f"{self.slug}://{meta.get(self.namespace_meta, '')}"

    def _qualified(self, ns: str, schema: str) -> str:
        q = self.sql_quote
        return f"{q}{ns}{q}.{q}{schema}{q}"

    def _extra_domain_sql(self, sys_meta: dict[str, str], schema: str) -> list[str]:
        return []

    def _exec(self, url: str, statements: list[str]) -> None:
        from sqlalchemy import create_engine

        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                for stmt in statements:
                    as_written(conn, stmt)
        except Exception as exc:
            raise TdxError(f"{self.label} SQL failed: {exc}") from exc
        finally:
            engine.dispose()

    def _query(self, url: str, sql: str) -> list[str]:
        from sqlalchemy import create_engine

        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                rows = as_written(conn, sql).fetchall()
        except Exception as exc:
            raise TdxError(f"{self.label} query failed: {exc}") from exc
        finally:
            engine.dispose()
        return [str(r[0]).strip() for r in rows if r and r[0] is not None]

    # ---- system hooks (for the attached hosting) -----------------------

    def complete_plan(self, name: str, meta: dict[str, str]) -> dict[str, str]:
        meta["LOCATION"] = self._location(meta)
        return meta

    def probe_system(self, meta: dict[str, str]) -> tuple[bool, str]:
        try:
            self._exec(self._url(meta), ["SELECT 1"])
        except TdxError as exc:
            return False, f"cannot reach {self.label}: {exc}"
        return True, f"{self.label} at {self._location(meta)}"

    # ---- domain lifecycle (a schema in the namespace) ------------------

    def new_domain_password(self) -> str:
        return ""

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        schema = self._schema(entity_name)
        meta = {opt.name: sys_meta.get(opt.name, "") for opt in self.options()}
        meta["DB"] = schema
        meta["SQLALCHEMY_URI"] = self._url(sys_meta, schema)
        meta["URI"] = f"{self._location(sys_meta)}/{schema}"
        return meta

    def provision_domain(
        self,
        sys_meta: dict[str, str],
        entity_name: str,
        domain_meta: dict[str, str],
        *,
        force: bool = False,
    ) -> None:
        schema = self._schema(entity_name)
        ns = sys_meta[self.namespace_meta]
        url = self._url(sys_meta)
        exists = schema.lower() in {
            s.lower() for s in self.list_domain_entities(sys_meta)
        }
        if exists and not force:
            raise TdxError(f"schema '{schema}' already exists (use --force)")
        if exists or force:
            self._exec(
                url, [f"DROP SCHEMA IF EXISTS {self._qualified(ns, schema)} CASCADE"]
            )
        self._exec(
            url,
            [
                f"CREATE SCHEMA {self._qualified(ns, schema)}",
                *self._extra_domain_sql(sys_meta, schema),
            ],
        )

    def destroy_domain(self, domain_meta: dict[str, str]) -> None:
        ns, schema = domain_meta[self.namespace_meta], domain_meta["DB"]
        self._exec(
            self._url(domain_meta),
            [f"DROP SCHEMA IF EXISTS {self._qualified(ns, schema)} CASCADE"],
        )

    def domain_status(self, domain_meta: dict[str, str]) -> tuple[bool, str]:
        try:
            self._exec(self._url(domain_meta), ["SELECT 1"])
        except TdxError as exc:
            return False, f"cannot reach {self.label}: {exc}"
        return True, f"{self.label} schema {domain_meta.get('DB', '')}"

    def list_domain_entities(self, sys_meta: dict[str, str]) -> list[str]:
        ns = sys_meta[self.namespace_meta]
        q = self.sql_quote
        names = self._query(
            self._url(sys_meta),
            f"SELECT SCHEMA_NAME FROM {q}{ns}{q}.INFORMATION_SCHEMA.SCHEMATA",
        )
        return [n for n in names if n.lower() not in self.system_schemas]

    def purge_domain_entity(self, sys_meta: dict[str, str], name: str) -> None:
        if name.lower() in self.system_schemas:
            raise TdxError(f"refusing to purge {self.label} system schema '{name}'")
        ns = sys_meta[self.namespace_meta]
        self._exec(
            self._url(sys_meta),
            [f"DROP SCHEMA IF EXISTS {self._qualified(ns, name)} CASCADE"],
        )
