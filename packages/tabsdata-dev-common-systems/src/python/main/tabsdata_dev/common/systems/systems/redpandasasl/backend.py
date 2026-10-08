#
# Copyright 2026 Tabsdata Inc.
#

"""Redpanda with SASL on.

A thin variant of the plain ``redpanda`` system -- same image, model and data
plane -- whose broker every Kafka client authenticates to (what ``redpanda``
gives with ``--sasl on``), so the authenticated setup is a type of its own:
``create --type ALL`` makes it and it owns a port slot beside the plain one.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.systems.redpanda.backend import SASL_ON, Redpanda


class Redpandasasl(Redpanda):
    slug = "redpandasasl"
    label = "Redpanda (SASL)"
    ddl_from_slug = "redpanda"

    def options(self) -> tuple[options.Option, ...]:
        return tuple(o for o in super().options() if o.name != "SASL")

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        return super().plan_system(name, {**(overrides or {}), "SASL": SASL_ON})
