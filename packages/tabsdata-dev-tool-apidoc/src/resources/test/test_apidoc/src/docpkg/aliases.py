#
# Copyright 2026 Tabsdata Inc.
#
from typing import Annotated, TypeAlias

Name: TypeAlias = str
"""One name."""

Names: TypeAlias = Annotated[list[Name], "strict"]
"""Several names."""
