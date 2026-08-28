#
# Copyright 2026 Tabsdata Inc.
#

from tabsdata_dev.tdd import paths, render


def test_tdd_render_is_byte_identical_to_common_core_render():
    # tdd-exe is standard-library only and cannot import common-core, so it
    # carries its own copy of the event model. One test keeps the two honest.
    root = paths.repo_root()
    twin = (
        root
        / "packages/tabsdata-dev-common-core/src/python/main/tabsdata_dev/common/core/render.py"
    )
    mine = root / "packages/tabsdata-dev-tdd/src/python/main/tabsdata_dev/tdd/render.py"
    assert mine.read_text() == twin.read_text(), "render.py twins have diverged"


def test_kinds_and_colours():
    assert render.KINDS == ("ok", "error", "warn", "info", "debug")
    assert render.COLORS == {"ok": "32", "error": "31", "warn": "33", "debug": "37"}
