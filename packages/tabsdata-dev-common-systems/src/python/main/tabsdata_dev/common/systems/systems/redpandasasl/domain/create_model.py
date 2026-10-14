#
# Copyright 2026 Tabsdata Inc.
#

"""Create a model's topics in a redpandasasl domain, one per entity.

redpanda's own command, unchanged: the dispatcher looks a type's commands up by
its slug, not its base class, so without this module redpandasasl would get the
shared one instead.
"""

from tabsdata_dev.common.systems.systems.redpanda.domain.create_model import (
    add_arguments,
    run,
)

__all__ = ["add_arguments", "run"]
