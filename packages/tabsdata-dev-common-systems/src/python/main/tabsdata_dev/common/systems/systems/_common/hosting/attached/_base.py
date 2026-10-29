#
# Copyright 2026 Tabsdata Inc.
#

"""``AttachedHosting`` -- the base of systems that exist on their own, which tdd
attaches to but never runs.

There is nothing to start or stop, so the lifecycle is the same wherever the
system lives: create resolves the system's declared ``options()`` into the meta
(the nature adds what it derives from them in ``complete_plan``) and checks the
system answers; status checks again; destroy leaves the externally owned system
alone. How to check is the nature's business (``probe_system``): a SQL
``SELECT 1``, a bucket lookup, credentials being present.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import constants
from tabsdata_dev.common.systems.errors import TdxError


class AttachedHosting:
    hosting: str = ""
    is_container: bool = False
    # Nothing here runs, so nothing restarts, nothing is fetched and no port of
    # this machine's is advertised.
    supports_restart: bool = False
    fetches_binaries: bool = False
    advertises_host: bool = False

    slug: str = ""
    label: str = ""
    weight: int = 1
    exclusive: bool = False

    sys_toolset: str = constants.TOOLSET_SYSTEMS

    def docker_images(self) -> list[tuple[str, str]]:
        return []

    # ---- system lifecycle ----------------------------------------------
    # The system's nature supplies `options()`, `complete_plan(name, meta)` (the
    # planned meta, given the resolved options) and `probe_system(meta)` (whether
    # the system answers, and what to say about it). No hosting defines them: a
    # system lists its hosting first, so a hosting default would shadow them.

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        o = overrides or {}
        return self.complete_plan(
            name, {opt.name: o.get(opt.name, "") for opt in self.options()}
        )

    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]:
        ok, detail = self.probe_system(meta)
        if not ok:
            raise TdxError(detail)
        return {}

    def destroy_system(self, meta: dict[str, str]) -> None:
        return None  # externally owned -- never removed

    def system_status(self, meta: dict[str, str]) -> tuple[bool, str]:
        return self.probe_system(meta)

    def restart_system(self, meta: dict[str, str]) -> str:
        raise TdxError(f"{self.slug} is not a container (nothing to restart)")
