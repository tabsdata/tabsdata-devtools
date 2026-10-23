#
# Copyright 2026 Tabsdata Inc.
#

"""``ObjectStore`` -- the nature of object stores (s3, gcs, azureblob, and their
local emulators): a :class:`FileStore` whose root is a bucket prefix.

Its connection config (bucket/container, secrets, ``SYS_PATH`` staging-root)
is resolved from the declared ``options()`` (env-sourced by default) **at
create time** and baked into the (encrypted) descriptor; every later op reads
it back from that descriptor via :meth:`configure` — the only environment
variable read at use time is the crypto key. Staged files live at
``<bucket>/<SYS_PATH>/<domain>/<fmt>/<entity>_<stamp>.<fmt>``. Subclasses
implement the five ``store_*`` primitives with their SDK plus ``_bucket`` (the
bucket / container name shown in URIs), declare their connection ``options()``
and their ``uri_scheme`` (``s3`` / ``gs`` / ``az``).
"""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.nature.file._base import (
    FileStore,
    squash_slashes,
)


class ObjectStore(FileStore):
    nature = "object_store"

    env_prefix: str = ""  # S3 / GCS / AZ
    uri_scheme: str = ""  # URI scheme for the location URI; defaults to the slug

    _bound: dict[str, str] | None = None

    def configure(self, meta: dict[str, str]) -> None:
        self._bound = dict(meta)

    def _cfg(self, key: str, *, required: bool = True) -> str:
        """A config value from the bound descriptor (create binds it before
        provisioning; every later op binds it from the loaded descriptor)."""
        return (self._bound or {}).get(key, "")

    def _bucket(self) -> str:
        raise NotImplementedError

    def _location(self, prefix: str) -> str:
        return f"{self.uri_scheme or self.slug}://{self._bucket()}/{prefix}"

    def _uri(self, dest: str) -> str:
        return self._location(dest)  # s3:// / gs:// / az:// bucket/prefix

    def join(self, root: str, child: str) -> str:
        root = squash_slashes(root).strip("/")
        return squash_slashes(f"{root}/{child}") if root else squash_slashes(child)

    def complete_plan(self, name: str, meta: dict[str, str]) -> dict[str, str]:
        root = squash_slashes(meta.get("SYS_PATH") or "").strip("/")
        planned = {"SYS_PATH": root, "ENV_PREFIX": self.env_prefix}
        for opt in self.options():
            if opt.name != "SYS_PATH":
                planned[opt.name] = meta.get(opt.name, "")
        self.configure(planned)  # so _bucket()/_cfg read the planned config
        planned["LOCATION"] = self._location(root)
        return planned

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        # super() sets URI via the polymorphic _uri (== _location for cloud)
        meta = super().domain_meta(sys_meta, entity_name, password)
        for key in self.store_keys():  # forward baked config so the domain
            if key in sys_meta:  # descriptor is self-contained too
                meta[key] = sys_meta[key]
        return meta

    def store_keys(self) -> tuple[str, ...]:
        """The system-meta keys a domain descriptor carries over to reach the
        store on its own. Default: the declared options (a cloud system's
        config); a system that plans its config itself (an emulator) names
        them."""
        return tuple(opt.name for opt in self.options())
