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

- ``server`` -- the base of natures served by a process at HOST:PORT, and
  message brokers (``messaging``).
- ``database`` -- databases on such a server: SQL databases (``sql``), SQL
  warehouses (``warehouse``) and document databases (``document``).
- ``file`` -- staged data files under a root: a local directory (``_base``) or
  a bucket prefix (``object``).
- ``credential`` -- accounts reached with credentials alone: AI providers
  (``ai``), applications (``application``) and synthetic data (``synthetic``).
"""
