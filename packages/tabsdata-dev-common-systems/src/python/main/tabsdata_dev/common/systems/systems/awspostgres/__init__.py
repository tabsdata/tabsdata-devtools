#
# Copyright 2026 Tabsdata Inc.
#

# AWS RDS PostgreSQL system: a managed remote instance; domains are databases
# with a dedicated owner role. Only the backend is system-specific; every verb
# runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.awspostgres.backend import AwsPostgres

__all__ = ["AwsPostgres"]
