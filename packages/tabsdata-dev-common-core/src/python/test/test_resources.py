#
# Copyright 2026 Tabsdata Inc.
#

import sys

import jinja2
import pytest

from tabsdata_dev.common.core import resources

PACKAGE = "rsprobe.tool.thing"


def _package(root):
    """An importable ``rsprobe.tool.thing`` under ``root``."""
    module = root.joinpath(*PACKAGE.split("."))
    module.mkdir(parents=True)
    for folder in (module, module.parent, module.parent.parent):
        (folder / "__init__.py").write_text("")
    return module


@pytest.fixture
def importable(monkeypatch):
    """Put a root on sys.path, and forget the probe package afterwards so the
    next test imports its own."""
    yield lambda root: monkeypatch.syspath_prepend(str(root))
    for name in [n for n in sys.modules if n.split(".")[0] == "rsprobe"]:
        del sys.modules[name]


@pytest.fixture
def checkout(tmp_path, importable):
    """The editable layout: the resources stay in <pkg>/src/resources/main."""
    pkg = tmp_path / "rsprobe-pkg"
    _package(pkg / "src" / "python" / "main")
    folder = pkg / "src" / "resources" / "main"
    folder.mkdir(parents=True)
    importable(pkg / "src" / "python" / "main")
    return folder


def test_a_wheel_finds_its_resources_beside_the_module(tmp_path, importable):
    module = _package(tmp_path / "site")
    (module / "resources").mkdir()
    (module / "resources" / "a.txt").write_text("wheel\n")
    importable(tmp_path / "site")
    assert resources.text(PACKAGE, "a.txt") == "wheel\n"


def test_a_checkout_finds_them_where_they_are_edited(checkout):
    (checkout / "sub").mkdir()
    (checkout / "sub" / "a.txt").write_text("checkout\n")
    assert resources.main_folder(PACKAGE) == checkout
    assert resources.text(PACKAGE, "sub/a.txt") == "checkout\n"


def test_a_missing_resource_names_itself(checkout):
    with pytest.raises(FileNotFoundError, match="nope.txt"):
        resources.path(PACKAGE, "nope.txt")


def test_a_template_renders_its_values_and_keeps_the_last_newline(checkout):
    (checkout / "t.sh").write_text("{% for t in tables %}echo {{ t }}\n{% endfor %}")
    assert resources.render(PACKAGE, "t.sh", tables=["a", "b"]) == "echo a\necho b\n"


def test_a_value_the_template_uses_but_nobody_passed_is_an_error(checkout):
    (checkout / "t.sql").write_text("select {{ column }} from t\n")
    with pytest.raises(jinja2.UndefinedError, match="column"):
        resources.render(PACKAGE, "t.sql")


def test_only_html_is_escaped(checkout):
    (checkout / "t.html").write_text("<p>{{ v }}</p>")
    (checkout / "t.sh").write_text("{{ v }}")
    assert resources.render(PACKAGE, "t.html", v="a<b") == "<p>a&lt;b</p>"
    assert resources.render(PACKAGE, "t.sh", v="a<b") == "a<b"
