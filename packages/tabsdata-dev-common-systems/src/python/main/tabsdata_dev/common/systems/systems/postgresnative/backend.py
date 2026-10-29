#
# Copyright 2026 Tabsdata Inc.
#

"""PostgreSQL run natively -- the dialect (:class:`PostgresDialect`) on this
machine, from theseus-rs's binaries, with pgvector installed beside them.

The ``postgres`` container's twin: the same options (port, password,
``--sys-hostname``), the same server settings (``SERVER_SETTINGS``), the same
info block and models -- its DDL is the plain system's -- but no docker. Each
system owns ``<tdd_dir>/data/system-native/<system>/``::

    postgresql/       its own copy of the binaries, pgvector installed in it
    data/             the cluster (initdb), tdd.conf and pg_hba.conf in it
    postgresql.log    the server's log
    pg_ctl.log        what pg_ctl said, for a start that failed

so two systems share nothing but the download cache. The server is driven with
the tree's own ``pg_ctl`` and listens on TCP alone; the superuser authenticates
like everyone else.

A domain is created with pgvector off; ``domain create --pgvector on`` runs
``CREATE EXTENSION vector`` in its database (as the superuser: pgvector is not a
trusted extension) and records ``PGVECTOR`` in the domain's meta.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

from tabsdata_dev.common.core import resources
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.shell import port_open
from tabsdata_dev.common.systems.systems._common.hosting.endpoint import (
    DEFAULT_HOSTNAME,
    Admin,
)
from tabsdata_dev.common.systems.systems._common.hosting.native._base import (
    EXE_SUFFIX,
    NATIVE_DIR_KEY,
    NativeHosting,
)
from tabsdata_dev.common.systems.systems.postgres.backend import SERVER_SETTINGS
from tabsdata_dev.common.systems.systems.postgres.dialect import PostgresDialect
from tabsdata_dev.common.systems.systems.postgresnative import binaries

#: This package, whose resources hold the configuration it writes.
PACKAGE = "tabsdata_dev.common.systems"

#: The system meta key holding the pgvector its tree carries.
PGVECTOR_VERSION_KEY = "PGVECTOR_VERSION"
#: The domain meta key saying whether its database has pgvector.
PGVECTOR_KEY = "PGVECTOR"
PGVECTOR_ON = "on"
PGVECTOR_OFF = "off"

# The directory's parts (see the module docstring).
TREE = "postgresql"
DATA = "data"
SERVER_LOG = "postgresql.log"
PG_CTL_LOG = "pg_ctl.log"
PWFILE = ".initdb-password"

#: pg_ctl status: 0 running, 3 not running, 4 no usable data directory.
_PG_CTL_RUNNING = 0
_STOP_TIMEOUT = 60


class PostgresNative(NativeHosting, PostgresDialect):
    slug = "postgresnative"
    label = "PostgreSQL (native)"
    ddl_from_slug = "postgres"

    # What `domain create --pgvector` chose for the domain it is creating.
    _pgvector: str = PGVECTOR_OFF

    # ---- paths ----------------------------------------------------------

    @staticmethod
    def _root(meta: dict[str, str]) -> Path:
        value = meta.get(NATIVE_DIR_KEY, "")
        if not value:
            raise TdxError(f"the descriptor has no {NATIVE_DIR_KEY}")
        return Path(value)

    @staticmethod
    def _program(root: Path, name: str) -> str:
        return str(root / TREE / "bin" / f"{name}{EXE_SUFFIX}")

    # ---- the server's programs -----------------------------------------

    @staticmethod
    def _environment() -> dict[str, str]:
        """This process's environment without libpq's variables: a PGDATA,
        PGPORT or PGOPTIONS a developer exported for another server must not
        reach this one's programs."""
        return {k: v for k, v in os.environ.items() if not k.startswith("PG")}

    def _run(self, root: Path, name: str, *args: str) -> subprocess.CompletedProcess:
        # The tree's own programs, by path: tdd downloaded them into the
        # system's directory, which makes them this system's, as a toolset's bin/
        # is the toolset's -- not a requirement on the machine, so not run
        # through proc.run's bin-reqs check.
        return subprocess.run(
            [self._program(root, name), *args],
            capture_output=True,
            text=True,
            env=self._environment(),
            check=False,
        )

    def _pg_ctl(self, root: Path, *args: str) -> int:
        """Run pg_ctl with its output in ``pg_ctl.log``, never a pipe: the server
        it starts may inherit what pg_ctl was given, and a pipe held open by a
        server that never exits is a read that never returns."""
        with open(root / PG_CTL_LOG, "ab") as log:
            return subprocess.run(
                [self._program(root, "pg_ctl"), *args, "-D", str(root / DATA)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=self._environment(),
                check=False,
            ).returncode

    def _tail(self, root: Path) -> str:
        """The end of both logs, for a failure: what pg_ctl and the server said."""
        out: list[str] = []
        for name in (PG_CTL_LOG, SERVER_LOG):
            path = root / name
            if path.is_file():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                out.append(f"{path}:\n  " + "\n  ".join(lines[-30:]))
        return "\n".join(out)

    def _running(self, root: Path) -> bool:
        # `status` starts nothing, so its output can come back over a pipe.
        if not (root / DATA).is_dir():
            return False
        cp = self._run(root, "pg_ctl", "status", "-D", str(root / DATA))
        return cp.returncode == _PG_CTL_RUNNING

    def _start(self, root: Path) -> None:
        print(f">>> starting {self.label} from {root}")
        rc = self._pg_ctl(
            root,
            "start",
            "-w",
            "-t",
            str(self.ready_timeout),
            "-l",
            str(root / SERVER_LOG),
        )
        if rc != 0:
            raise TdxError(
                f"{self.label} did not start (pg_ctl exited {rc})", self._tail(root)
            )

    def _stop(self, root: Path) -> None:
        if not self._running(root):
            return
        print(f">>> stopping {self.label} in {root}")
        rc = self._pg_ctl(root, "stop", "-m", "fast", "-w", "-t", str(_STOP_TIMEOUT))
        if rc != 0:
            raise TdxError(
                f"{self.label} did not stop (pg_ctl exited {rc})", self._tail(root)
            )

    # ---- system lifecycle ----------------------------------------------

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        o = overrides or {}
        # One address, recorded under both names, as a container does.
        host = self.hostname
        meta = {
            "INTERNAL_HOST": host,
            "EXTERNAL_HOST": host,
            "PORT": o.get("PORT") or str(self.next_free_port()),
            "DATABASE": self.admin_db,
            "USER": self.root_user,
            "PASSWORD": o.get("PASSWORD") or self.generate_password(),
            "VERSION": "",  # filled in by the probe once the server is up
            NATIVE_DIR_KEY: str(self.native_dir(name)),
            PGVECTOR_VERSION_KEY: binaries.PGVECTOR_VERSION,
        }
        self._plane_keys(meta, self.admin_db, meta["USER"], meta["PASSWORD"])
        return meta

    def fetch_bin(self, done: set[str]) -> None:
        version, target = binaries.resolve_version(), binaries.target_triple()
        key = f"postgresql-{version}-{target}"
        if key in done:
            return
        binaries.fetch_all(version, target)
        done.add(key)

    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]:
        root = self._root(meta)
        if root.exists():
            if not force:
                raise TdxError(f"{root} already exists (use --force)")
            self._stop(root)
            self.remove_dir(root)
            print(f">>> --force: removed {root}")
        version, target = binaries.resolve_version(), binaries.target_triple()
        binaries.build_tree(version, target, root / TREE)
        self._initdb(root, meta, binaries.major_of(version))
        self._configure(root, meta)
        self._start(root)
        return {"VERSION": self._probe_version(meta)}

    def _initdb(self, root: Path, meta: dict[str, str], major: str) -> None:
        print(f">>> initdb {root / DATA}")
        pwfile = root / PWFILE
        # initdb reads the superuser's password from a file, never argv, where
        # every process listing would show it.
        pwfile.write_text(meta["PASSWORD"] + "\n", encoding="utf-8")
        pwfile.chmod(0o600)
        locale = ["--locale=C", "--encoding=UTF8"]
        if int(major) >= 17:
            # Code-point order like C, but upper()/lower() that know Unicode,
            # and the same on every machine: no libc locale to be missing.
            locale += ["--locale-provider=builtin", "--builtin-locale=C.UTF-8"]
        try:
            cp = self._run(
                root,
                "initdb",
                "-D",
                str(root / DATA),
                "-U",
                meta["USER"],
                f"--pwfile={pwfile}",
                "--auth=scram-sha-256",
                *locale,
            )
        finally:
            pwfile.unlink(missing_ok=True)
        print(cp.stdout)
        if cp.returncode != 0:
            raise TdxError(
                f"initdb failed (exit {cp.returncode})", cp.stderr or cp.stdout
            )

    def _configure(self, root: Path, meta: dict[str, str]) -> None:
        """tdd's settings in ``tdd.conf``, included at the end of the
        postgresql.conf initdb wrote, and the pg_hba.conf the system needs."""
        data = root / DATA
        everywhere = self.listens_everywhere(meta)
        (data / "tdd.conf").write_text(
            resources.render(
                PACKAGE,
                "postgresnative/tdd.conf",
                listen_addresses="*" if everywhere else "localhost",
                port=meta["PORT"],
                settings=SERVER_SETTINGS,
            ),
            encoding="utf-8",
        )
        with open(data / "postgresql.conf", "a", encoding="utf-8") as conf:
            conf.write("\ninclude = 'tdd.conf'\n")
        (data / "pg_hba.conf").write_text(
            resources.render(
                PACKAGE, "postgresnative/pg_hba.conf", everywhere=everywhere
            ),
            encoding="utf-8",
        )

    def destroy_system(self, meta: dict[str, str]) -> None:
        root = self._root(meta)
        if not root.exists():
            raise TdxError(f"{root} does not exist")
        self._stop(root)
        self.remove_dir(root)

    def system_status(self, meta: dict[str, str]) -> tuple[bool, str]:
        root = self._root(meta)
        if not (root / DATA).is_dir():
            return False, f"{root} holds no {self.label} cluster"
        if not self._running(root):
            return False, f"{self.label} in {root} is stopped"
        port = meta.get("PORT", "")
        host = meta.get("EXTERNAL_HOST", DEFAULT_HOSTNAME)
        if port.isdigit() and port_open(host, int(port)):
            return True, f"{self.label} on {host}:{port}"
        return False, f"{self.label} is running but {host}:{port} does not answer"

    def restart_system(self, meta: dict[str, str]) -> str:
        """Restart a running server, or start one the machine's restart (or a
        crash) left stopped -- which is what restart is for."""
        root = self._root(meta)
        if not (root / DATA).is_dir():
            raise TdxError(f"{root} holds no {self.label} cluster")
        if self._running(root):
            self._stop(root)
            self._start(root)
            return "restarted"
        self._start(root)
        return "started"

    # ---- domains ----------------------------------------------------------

    def use_pgvector(self, choice: str) -> None:
        """Bind ``--pgvector`` for the domain this create makes (on or off)."""
        if choice not in (PGVECTOR_ON, PGVECTOR_OFF):
            raise TdxError(
                f"--pgvector takes {PGVECTOR_ON} or {PGVECTOR_OFF}, not {choice!r}"
            )
        self._pgvector = choice

    def provider_meta(self, sys_meta: dict[str, str]) -> dict[str, str]:
        return {PGVECTOR_VERSION_KEY: sys_meta.get(PGVECTOR_VERSION_KEY, "")}

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        meta = super().domain_meta(sys_meta, entity_name, password)
        meta[PGVECTOR_KEY] = self._pgvector
        return meta

    def provision_domain(
        self,
        sys_meta: dict[str, str],
        entity_name: str,
        domain_meta: dict[str, str],
        *,
        force: bool = False,
    ) -> None:
        super().provision_domain(sys_meta, entity_name, domain_meta, force=force)
        if domain_meta.get(PGVECTOR_KEY) == PGVECTOR_ON:
            self._enable_pgvector(self._admin(sys_meta), entity_name)

    def _enable_pgvector(self, admin: Admin, db: str) -> None:
        print(f">>> pgvector: CREATE EXTENSION vector in '{db}'")
        self._run_admin(
            replace(admin, db=db), ["CREATE EXTENSION IF NOT EXISTS vector"]
        )
