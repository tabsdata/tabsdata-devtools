#
# Copyright 2026 Tabsdata Inc.
#

"""Create a domain (a topic prefix) in a redpandasasl system.

redpanda's own command, unchanged: the dispatcher looks a type's commands up by
its slug, not its base class, so without this module redpandasasl would get the
shared one instead.
"""

from tabsdata_dev.common.systems.systems.redpanda.domain.create import (
    add_arguments,
    run,
)

__all__ = ["add_arguments", "run"]
