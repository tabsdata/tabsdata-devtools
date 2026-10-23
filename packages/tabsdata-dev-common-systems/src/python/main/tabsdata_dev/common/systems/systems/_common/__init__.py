#
# Copyright 2026 Tabsdata Inc.
#

"""Shared system logic reused by concrete systems via subclassing (backends) and
delegation (the generic command modules).

Every system sits at two coordinates, and names both as its bases -- e.g.
``class Postgres(SingleContainerHosting, ...)``, ``class S3(RemoteHosting,
ObjectStore)``:

- ``hosting`` — where it runs, and who starts and stops it: local Docker
  (``container``: one container or a compose stack, plus their images,
  hostname and port slots) or a system tdd attaches to
  (``attached``: remote, managed or local). Owns the system lifecycle.
- ``nature`` — what it is: a server (``server``: messaging), a database on one
  (``database``: SQL database, SQL warehouse, document database), staged files
  (``file``: file store, object store) or a credential account (``credential``:
  AI provider, application, synthetic). Owns the domains and the data.
- ``commands`` — the generic verb ``add_arguments``/``run`` implementations every
  system's command modules re-export.
"""
