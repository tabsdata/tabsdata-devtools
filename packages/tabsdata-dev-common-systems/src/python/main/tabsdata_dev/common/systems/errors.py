#
# Copyright 2026 Tabsdata Inc.
#

"""Application errors for the system / domain commands.

``TdxError`` is the family's expected, user-facing failure -- a ``ToolError``, so
the shared runner renders it as one ``error`` event without a traceback.
"""

from __future__ import annotations

from tabsdata_dev.common.core.errors import ToolError


class TdxError(ToolError):
    pass


class DecryptError(TdxError):
    """A descriptor is one of ours (PEM armor present) but won't decrypt with the
    active ``$TD_BACKENDS_CRYPTO_KEY`` -- the key is wrong, or the file is corrupt,
    or it carries a foreign PEM label. Distinct from TdxError so enumeration can
    surface a bad key instead of skipping the file as a non-descriptor."""


class LegacyDescriptorError(TdxError):
    """A descriptor is in the superseded ``TDX2`` format. It is intact and the key
    is fine -- it just has to be converted by ``system upgrade`` / ``domain
    upgrade`` before anything will read it. Distinct from DecryptError so callers
    can tell "run the migration" from "your key is wrong"."""
