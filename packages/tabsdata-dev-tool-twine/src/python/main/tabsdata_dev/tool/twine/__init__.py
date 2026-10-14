#
# Copyright 2026 Tabsdata Inc.
#

"""twine -- `tdd twine ARGS` is twine itself, from the twine toolset.

The tool's entry point is twine's own (``twine.__main__:main``), so nothing
here runs: this module only names what the package is for. Credentials come
from the environment twine already reads -- ``tdd env set --pypi-twine`` puts
TWINE_USERNAME and TWINE_PASSWORD there.
"""

#: What `[project.scripts]` points `twine` at -- twine's own entry point; a
#: test holds the two in step.
ENTRY_POINT = "twine.__main__:main"
