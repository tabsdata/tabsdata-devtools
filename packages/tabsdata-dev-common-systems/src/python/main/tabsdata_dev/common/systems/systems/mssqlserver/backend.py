#
# Copyright 2026 Tabsdata Inc.
#

"""Microsoft SQL Server backend — a docker-run container, one database per domain.

A domain is a database with a dedicated login/user (db_owner). Admin runs as
``sa`` against ``master`` in autocommit (``CREATE DATABASE`` can't run in a
multi-statement transaction), over pyodbc + ODBC Driver 18. Only the SQL Server
dialect hooks live here.
"""

from __future__ import annotations

from tabsdata_dev.common.systems.shell import docker_exec_check
from tabsdata_dev.common.systems.systems._common.hosting.container import images
from tabsdata_dev.common.systems.systems._common.hosting.endpoint import Admin
from tabsdata_dev.common.systems.systems._common.sql import (
    LOCK_WAIT_SECONDS,
    SqlDatabaseContainerBackend,
)

_ODBC = "driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"


class Mssqlserver(SqlDatabaseContainerBackend):
    slug = "mssqlserver"
    label = "Microsoft SQL Server"
    domain_word = "database"
    entity_aliases = ("SCHEMA",)  # fixtures also expose the domain db as `schema`
    max_entity_name_length = 128  # sysname limit
    login_maxlen = 128

    image = images.MSSQLSERVER.ref
    image_platform = images.MSSQLSERVER.platform
    internal_port = 1433
    root_user = "sa"
    driver = "mssql+pyodbc"
    admin_db = "master"
    admin_autocommit = True
    system_schemas = frozenset({"master", "tempdb", "model", "msdb"})

    def concurrent_session_setup(self) -> list[str]:
        # Milliseconds. Under the default READ COMMITTED a write that scans a
        # table (no index to seek) waits on a row another open transaction
        # inserted; that wait ends here, as an error naming the statement.
        return [f"SET LOCK_TIMEOUT {LOCK_WAIT_SECONDS * 1000}"]

    def sqlalchemy_url(
        self, host: str, port: str, db: str = "", user: str = "", password: str = ""
    ) -> str:
        creds = f"{user}:{password}@" if user else ""
        return f"{self.driver}://{creds}{host}:{port}/{db}?{_ODBC}"

    def env_vars(self, password: str) -> dict[str, str]:
        return {"ACCEPT_EULA": "Y", "MSSQL_SA_PASSWORD": password}

    def check_ready(self, container: str, password: str) -> bool:
        return docker_exec_check(
            container,
            "/opt/mssql-tools18/bin/sqlcmd",
            "-S",
            "localhost",
            "-U",
            self.root_user,
            "-P",
            password,
            "-Q",
            "SELECT 1",
            "-C",
            "-N",
            "-l",
            "5",
            "-b",
        )

    def create_domain_sql(self, db: str, user: str, password: str) -> list[str]:
        # No GO batches over pyodbc; USE switches DB context for the CREATE USER.
        return [
            f"CREATE DATABASE [{db}]",
            f"CREATE LOGIN [{user}] WITH PASSWORD = '{password}', CHECK_POLICY = OFF",
            f"USE [{db}]",
            f"CREATE USER [{user}] FOR LOGIN [{user}]",
            f"ALTER ROLE db_owner ADD MEMBER [{user}]",
        ]

    def delete_domain_sql(self, name: str) -> list[str]:
        return [
            f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE",
            f"DROP DATABASE [{name}]",
            f"DROP LOGIN [{name}]",
        ]

    def _do_delete(self, admin: Admin, name: str) -> None:
        # No IF EXISTS for DROP DATABASE / LOGIN here — skip if already gone.
        if name in self._do_list(admin):
            super()._do_delete(admin, name)

    def list_schemas_sql(self) -> str:
        return (
            "SELECT name FROM sys.databases "
            "WHERE name NOT IN ('master','tempdb','model','msdb') ORDER BY name"
        )
