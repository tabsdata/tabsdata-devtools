#
# Copyright 2026 Tabsdata Inc.
#

"""What a system is: the nature axis.

A nature owns the domains and the data -- the domain lifecycle (password, meta,
provision, destroy, status, entities, purge), the data plane (models, schema,
load, changes) and the capability flags that gate those verbs. It reads the
endpoint its hosting (``_common.hosting``) wrote into the system meta, and
nothing else. A nature paired with an attached hosting also supplies
``complete_plan`` and ``probe_system``.

- ``server`` -- natures served by a process at HOST:PORT (SQL, document,
  messaging).
- ``messaging`` / ``document_database`` -- a message broker / a document
  database on such a server.
- ``file_store`` / ``object_store`` -- staged data files under a root: a local
  directory, or a bucket prefix.
- ``credential_account`` -- an account reached with credentials alone; its
  natures ``ai_provider``, ``application`` and ``synthetic``.
"""
