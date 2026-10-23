#
# Copyright 2026 Tabsdata Inc.
#

"""The endpoint a hosting hands to a nature: how to reach a system's server
as its administrator."""

from __future__ import annotations

from dataclasses import dataclass

# Where an endpoint lives when nothing says otherwise: the loopback address of
# the machine that ran docker. It is ``127.0.0.1`` rather than the name
# ``localhost``: the SQL Server ODBC driver connects to the machine's own
# hostname for ``localhost``, and a network's DNS can resolve that hostname to
# another device, so every connection times out.
DEFAULT_HOSTNAME = "127.0.0.1"


@dataclass
class Admin:
    host: str
    port: str
    user: str
    password: str
    # The maintenance database this connection targets. Empty = the class's
    # `admin_db`; a family that records the database in its meta (Postgres) puts
    # it here, so a server whose default database is not the usual one is reached
    # at the one it actually has.
    db: str = ""
    # TLS for this connection, where the dialect takes it on the URL and the
    # setting is the system's rather than the class's (see ManagedPostgres);
    # every container backend leaves these empty. `ca_pem` is the certificate
    # itself -- `sslrootcert` is filled in with a path to it only for as long as
    # a connection needs one.
    sslmode: str = ""
    sslrootcert: str = ""
    ca_pem: str = ""
