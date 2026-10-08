#
# Copyright 2026 Tabsdata Inc.
#

# redpandasasl system: the redpanda system with SASL on, as a type of its own so
# `create --type ALL` makes it and it owns a port slot.

from tabsdata_dev.common.systems.systems.redpandasasl.backend import Redpandasasl

__all__ = ["Redpandasasl"]
