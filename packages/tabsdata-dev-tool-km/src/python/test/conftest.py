#
# Copyright 2026 Tabsdata Inc.
#

import pathlib

import pytest

RESOURCES = pathlib.Path(__file__).parents[2] / "resources" / "test"


@pytest.fixture
def resource_folder(request) -> pathlib.Path:
    """src/resources/test/<test module>/: the files of the requesting module."""
    return RESOURCES / request.path.stem
