#
# Copyright 2026 Tabsdata Inc.
#

"""``NativeHosting`` -- a server tdd runs as a process on this machine.

What a container is to docker, a directory is here: each system owns
``<tdd_dir>/data/system-native/<system>/`` and keeps everything in it -- its own
copy of the binaries, its configuration, its data, its log -- so two systems
never share anything but the download cache, and destroying one is stopping its
process and removing its directory. The directory is recorded in the descriptor
(``NATIVE_DIR``), as a container's name is: it is what every later verb acts on.

The lifecycle a system implements is the container's -- plan, provision, destroy,
status, restart -- and the host side is the same too: a port from the type's own
slot, a password, and ``--sys-hostname`` to advertise another name (a native
server then listens on every address rather than on loopback alone).
``fetch-bin`` puts the system's archives in the cache, as it pulls a container's
images.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from tabsdata_dev.common.core import datadir
from tabsdata_dev.common.systems import constants, options
from tabsdata_dev.common.systems.shell import gen_password
from tabsdata_dev.common.systems.systems._common.hosting.container.hostname import (
    HostMixin,
)
from tabsdata_dev.common.systems.systems._common.hosting.container.ports import (
    PortRangeMixin,
)
from tabsdata_dev.common.systems.systems._common.hosting.endpoint import (
    DEFAULT_HOSTNAME,
)

#: The system meta key holding the system's own directory.
NATIVE_DIR_KEY = "NATIVE_DIR"
#: ``<tdd_dir>/data/<this>/<system>``: beside the descriptor store, and like it
#: user state that tdd-install never touches.
NATIVE_DATA = "system-native"
#: A program's suffix on this platform, as the archives lay their binaries out.
EXE_SUFFIX = ".exe" if os.name == "nt" else ""
#: The names that mean "this machine only": a server advertised as one of them
#: listens on loopback, any other name makes it listen on every address.
LOOPBACK_NAMES = frozenset({DEFAULT_HOSTNAME, "localhost", "::1"})


def native_root() -> Path:
    """Where every native system's directory lives."""
    return datadir.data_dir(NATIVE_DATA)


class NativeHosting(PortRangeMixin, HostMixin):
    hosting: str = "native"
    is_container: bool = False
    # A process stops with the machine, as a container stops with docker; both
    # come back with `restart`.
    supports_restart: bool = True
    # `fetch-bin` caches its archives, as it pulls a container's images.
    fetches_binaries: bool = True
    # Its port is on this machine, so `--sys-hostname` has something to name.
    advertises_host: bool = True

    slug: str = ""
    label: str = ""
    weight: int = 1
    exclusive: bool = False

    sys_toolset: str = constants.TOOLSET_SYSTEMS

    ready_timeout: int = 120

    def options(self) -> tuple[options.Option, ...]:
        return (
            options.Option("PORT", "port", options.PORT, "a free host port"),
            options.Option(
                "PASSWORD",
                "password",
                options.RANDOM,
                "a generated password",
                secret=True,
            ),
        )

    def generate_password(self) -> str:
        return gen_password()

    def docker_images(self) -> list[tuple[str, str]]:
        return []

    def native_dir(self, sys_name: str) -> Path:
        return native_root() / sys_name

    def listens_everywhere(self, meta: dict[str, str]) -> bool:
        """Whether the server should accept connections from other machines:
        only when it was advertised under a name that is not this machine's."""
        return meta.get("EXTERNAL_HOST", DEFAULT_HOSTNAME) not in LOOPBACK_NAMES

    def fetch_bin(self, done: set[str]) -> None:
        """Put this system's archives in the download cache, skipping those in
        `done` and adding what it fetched."""
        raise NotImplementedError

    @staticmethod
    def remove_dir(root: Path) -> None:
        """Remove a system's directory, the binaries' read-only files included
        (Windows refuses to delete those as they are)."""

        def writable_then_retry(func, path, _exc):
            os.chmod(path, 0o700)
            func(path)

        shutil.rmtree(root, onexc=writable_then_retry)
