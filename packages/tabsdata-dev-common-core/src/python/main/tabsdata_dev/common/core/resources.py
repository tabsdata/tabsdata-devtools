#
# Copyright 2026 Tabsdata Inc.
#
"""Resource files shipped inside a package: scripts, templates and data that the
package's code reads from a file instead of holding them as string literals.

Each package keeps its resource files in ``<pkg>/src/resources/main/``. Building
a wheel copies that folder next to the package's modules, as ``resources/``
(force-include, declared in the package's pyproject). An editable install
copies nothing, so there the files stay where they are edited. ``main_folder()``
handles both cases: it looks for the copy first, then for the checkout folder.

Templates are rendered with Jinja2 under ``StrictUndefined``, so a value the
template uses but the caller did not pass is an error, never an empty string.
Use a template only when the text itself changes shape (a loop, a conditional,
one block per table). A script that only needs a value receives it as an
argument or an environment variable instead; that also keeps quoting out of
the template.
"""

from __future__ import annotations

import pathlib
from importlib.resources import files

import jinja2

#: The folder name a wheel uses, next to the package's modules.
WHEEL_FOLDER = "resources"
#: The folder the checkout uses, relative to the package root.
CHECKOUT_FOLDER = pathlib.Path("src", "resources", "main")
#: How many levels the package root sits above ``src/python/main``.
_MAIN_DEPTH = 3


def main_folder(package: str) -> pathlib.Path:
    """The resources folder of ``package`` (a dotted module name, e.g.
    ``tabsdata_dev.tool.xp``), in a wheel or in a checkout."""
    here = pathlib.Path(str(files(package)))
    beside = here / WHEEL_FOLDER
    if beside.is_dir():
        return beside
    # .../<pkg>/src/python/main/tabsdata_dev/... -> one parent per dotted part
    root = here.parents[len(package.split(".")) - 1 + _MAIN_DEPTH]
    checkout = root / CHECKOUT_FOLDER
    if checkout.is_dir():
        return checkout
    raise FileNotFoundError(
        f"resources of {package} not found at {beside} nor {checkout}"
    )


def path(package: str, name: str) -> pathlib.Path:
    """One resource file; ``name`` is relative to the folder and uses ``/``."""
    found = main_folder(package) / name
    if not found.is_file():
        raise FileNotFoundError(f"resource {name} of {package} not found")
    return found


def text(package: str, name: str) -> str:
    return path(package, name).read_text(encoding="utf-8")


def render(package: str, name: str, /, **values: object) -> str:
    """Render the Jinja2 template ``name`` with ``values``. HTML and XML are
    autoescaped; every other kind is emitted as written."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(main_folder(package)),
        undefined=jinja2.StrictUndefined,
        autoescape=jinja2.select_autoescape(["html", "xml"], default=False),
        keep_trailing_newline=True,
    )
    return env.get_template(name).render(**values)
