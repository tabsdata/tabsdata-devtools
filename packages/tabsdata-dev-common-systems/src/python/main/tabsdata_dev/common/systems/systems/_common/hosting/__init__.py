#
# Copyright 2026 Tabsdata Inc.
#

"""Where a system runs, and who starts and stops it: the hosting axis.

A hosting owns the system lifecycle (plan, provision, destroy, status, restart,
images, ports) and writes the endpoint into the system meta; the system's
nature (``_common.nature``) reads only that meta to build its domains.

- ``container`` -- local Docker: one container, or a compose stack.
- ``native`` -- a process on this machine, from binaries tdd downloads, each
  system in a directory of its own.
- ``attached`` -- systems that exist on their own, which tdd attaches to
  but never runs: remote services, provider-managed instances, and the host
  machine itself.
"""
