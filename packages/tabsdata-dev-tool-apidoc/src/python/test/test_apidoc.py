#
# Copyright 2026 Tabsdata Inc.
#

import json

import pytest
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool import apidoc
from tabsdata_dev.tool.apidoc import generate, markdown


@pytest.fixture
def pkg(tmp_path, resource_folder):
    """A package exercising every rule the generator applies (the resources'
    src/docpkg): a .pyi beside its .py, a re-export on the allow-list and one
    off it, nested type aliases, categories, and a Google docstring with an
    Examples block."""
    import shutil

    src = tmp_path / "src"
    shutil.copytree(resource_folder / "src", src)
    spec = {
        "root_package": "docpkg",
        "modules": ["docpkg", "docpkg.aliases", "docpkg.stubbed"],
        "re_exports": {"docpkg._impl.Widget": "docpkg.Widget"},
        "categories": {"source": "Sources", "destination": "Destinations"},
        "category_groups": {"connectors": ["Connectors", ["source", "destination"]]},
    }
    return src, spec


def test_generate_applies_the_spec(pkg):
    src, spec = pkg
    data = generate.generate(spec, [str(src)])
    assert data["generator"] == {"name": "tdd-apidoc", "version": "1.3.0"}
    assert data["spec"] == spec
    top = data["modules"]["docpkg"]

    # the allow-listed re-export is kept and pointed at its documented path;
    # the other is dropped and recorded
    [widget] = top["classes"]
    assert widget["canonical_path"] == "docpkg.Widget" and widget["reexported"]
    assert widget["categories"] == [["connectors", "destination"]]
    assert {"name": "Hidden", "target": "docpkg._impl.Hidden"} in top[
        "ignored_reexports"
    ]
    # the class Args: documents the constructor parameter it lacks docs for
    assert widget["constructor"]["parameters"][0]["description"] == "What it shows."
    assert [m["name"] for m in widget["methods"]] == ["spin"]
    assert [p["name"] for p in widget["properties"]] == ["size"]

    [fn] = top["functions"]
    assert fn["categories"] == [["connectors", "source"]]
    assert [p["description"] for p in fn["parameters"]] == [
        "How many rows.",
        "What to call them.",
    ]
    assert fn["returns"]["description"] == "The name used."
    assert fn["examples"] == [
        {"description": "Plainly:"},
        {"code-block:: python": "publish(3)"},
    ]

    # a nested alias resolves through to its definition, metadata stripped
    names = {a["name"]: a for a in data["modules"]["docpkg.aliases"]["attributes"]}
    assert names["Names"]["kind"] == "type_alias"
    assert names["Names"]["type"] == "list[Name]"
    assert names["Names"]["type_resolved"] == "list[str]"

    # the stub wins outright: its signature and its docstrings
    stubbed = data["modules"]["docpkg.stubbed"]
    assert stubbed["summary"] == "from the pyi"
    assert stubbed["functions"][0]["summary"] == "pyi doc"
    assert stubbed["functions"][0]["parameters"][0]["type"] == "int"

    by_cat = data["crossreferences"]["by_category"]
    assert [e["name"] for e in by_cat["source"]] == ["publish"]
    assert [e["name"] for e in by_cat["destination"]] == ["Widget"]


def test_markdown_heads_every_description_with_its_path(pkg):
    src, spec = pkg
    text = markdown.render_markdown(generate.generate(spec, [str(src)]))
    assert "### `docpkg.publish` — function" in text
    assert "- `count` — How many rows." in text
    assert "#### `docpkg.Widget.spin` — function · re-export" in text


def test_a_category_the_spec_does_not_define_fails(pkg):
    src, spec = pkg
    spec["categories"].pop("source")
    spec["category_groups"]["connectors"][1].remove("source")
    with pytest.raises(ToolError, match="'source' \\(1x\\): docpkg.publish"):
        generate.generate(spec, [str(src)])


@pytest.mark.parametrize(
    "groups, message",
    [
        ({"g": ["G", ["source"]]}, "not assigned to any group: destination"),
        ({"g": ["G", ["source", "destination", "nope"]]}, "undefined categories: nope"),
        ({"g": ["G", "source"]}, "must be \\[label, \\[category_id, ...\\]\\]"),
    ],
)
def test_the_category_groups_must_cover_the_categories(pkg, groups, message):
    src, spec = pkg
    spec["category_groups"] = groups
    with pytest.raises(ToolError, match=message):
        generate.generate(spec, [str(src)])


def test_a_package_not_in_the_venv_says_so(pkg, tmp_path):
    _src, spec = pkg
    with pytest.raises(ToolError, match="not installed in the current venv"):
        generate.generate(spec, [str(tmp_path / "empty")])


def test_no_search_paths_is_refused_not_read_as_this_process_sys_path(pkg):
    # griffe reads [] as "none given" and would search the toolset venv
    _src, spec = pkg
    with pytest.raises(ToolError, match="no search paths"):
        generate.generate(spec, [])


def test_the_cwd_is_never_searched(pkg, tmp_path, monkeypatch, resource_folder):
    """A `docpkg/` in the directory the tool runs from is not the package:
    griffe's default would load it as a relative path, a slice of the real
    one, without a word."""
    _src, spec = pkg
    import shutil

    shutil.copytree(resource_folder / "cwd", tmp_path / "cwd")
    monkeypatch.chdir(tmp_path / "cwd")
    with pytest.raises(ToolError, match="not installed in the current venv"):
        generate.generate(spec, [str(tmp_path / "empty")])


def test_an_unmatched_allow_list_entry_is_a_warning(pkg):
    src, spec = pkg
    spec["re_exports"]["docpkg._impl.Gone"] = "docpkg.Gone"
    events = []

    class Out:
        def info(self, m, **_):
            events.append(("info", m))

        def warn(self, m, **_):
            events.append(("warn", m))

        def debug(self, m, **_):
            events.append(("debug", m))

    generate.generate(spec, [str(src)], Out())
    assert (
        "warn",
        "re_exports: no re-export matched docpkg._impl.Gone (-> docpkg.Gone)",
    ) in events
    assert ("info", "re-exports: 1 of 2 allow-list entries matched") in events


def test_the_bundled_spec_is_consistent():
    spec, path = apidoc.load_spec(None)
    assert path == apidoc.bundled_spec() and path.name == "apidoc-spec.json"
    assert apidoc.root_package(spec) == "tabsdatak"
    categories, to_group = generate.parse_category_spec(spec)
    assert set(to_group) == set(categories)


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["apidoc", *argv])
    return apidoc.main()


def no_venv(monkeypatch):
    for var in (
        "_TDD_VENV",
        "_TDD_VENV_ACTIVATED",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
    ):
        monkeypatch.delenv(var, raising=False)


def fake_venv(resource_folder, root, sys_path):
    """A venv whose interpreter reports `sys_path` -- what apidoc asks of the
    current venv, without building one."""
    import shutil

    python = root / "bin" / "python"
    python.parent.mkdir(parents=True)
    shutil.copy(resource_folder / "fake_python.sh", python)
    python.chmod(0o755)
    (python.parent / "sys_path.json").write_text(json.dumps([str(p) for p in sys_path]))
    return root


def test_the_current_venv_is_managed_then_virtual_env_then_conda(tmp_path, monkeypatch):
    no_venv(monkeypatch)
    monkeypatch.setenv("TDD_DIR", str(tmp_path / "tdd"))
    with pytest.raises(ToolError, match="no venv is active"):
        apidoc.current_venv()
    # conda's base is not a venv of anyone's
    monkeypatch.setenv("CONDA_PREFIX", str(tmp_path / "base"))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
    with pytest.raises(ToolError, match="no venv is active"):
        apidoc.current_venv()
    monkeypatch.setenv("CONDA_PREFIX", str(tmp_path / "c"))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "c")
    assert apidoc.current_venv() == ("CONDA_PREFIX", tmp_path / "c")
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "v"))
    assert apidoc.current_venv() == ("VIRTUAL_ENV", tmp_path / "v")
    # a managed venv wins, by name
    root = tmp_path / "tdd" / "managed-venvs"
    (root / "uv" / "w").mkdir(parents=True)
    (root / "w.json").write_text('{"manager": "uv"}\n')
    monkeypatch.setenv("_TDD_VENV", "w")
    assert apidoc.current_venv() == ("managed venv w", root / "uv" / "w")


def test_generate_reads_the_package_from_the_current_venv(
    pkg, tmp_path, monkeypatch, capsys, resource_folder
):
    src, spec = pkg
    no_venv(monkeypatch)
    venv = fake_venv(resource_folder, tmp_path / "venv", [src])
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    out = tmp_path / "out" / "api.json"
    code = run_cli(
        monkeypatch,
        "--format",
        "json",
        "generate",
        "--spec",
        str(spec_file),
        "--out",
        str(out),
    )
    assert code == 0
    assert json.loads(out.read_text())["root_package"] == "docpkg"
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["event"] == "ok"
    assert events[-1]["classes"] == 1 and events[-1]["functions"] == 2
    venv_line = [e for e in events if e["message"].startswith("venv: ")]
    assert venv_line and "VIRTUAL_ENV, 1 sys.path entries" in venv_line[0]["message"]
    assert not list(out.parent.glob(".*.tmp"))

    md = tmp_path / "api.md"
    code = run_cli(
        monkeypatch,
        "generate",
        "--spec",
        str(spec_file),
        "--out",
        str(md),
        "--doc-format",
        "markdown",
    )
    assert code == 0
    assert md.read_text().startswith("# API descriptions — `docpkg`")


def test_generate_without_a_venv_says_to_activate_one(
    pkg, tmp_path, monkeypatch, capsys
):
    _src, spec = pkg
    no_venv(monkeypatch)
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    code = run_cli(
        monkeypatch,
        "generate",
        "--spec",
        str(spec_file),
        "--out",
        str(tmp_path / "x.json"),
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "no venv is active" in err and "tdd venv activate" in err


def test_the_old_path_options_are_gone(monkeypatch, tmp_path, capsys):
    for option in ("--search-path", "--source-tree"):
        code = run_cli(
            monkeypatch, "generate", option, str(tmp_path), "--out", str(tmp_path / "x")
        )
        assert code == 1
        assert f"unrecognized arguments: {option}" in capsys.readouterr().err


def test_a_bad_spec_is_named(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{ nope")
    assert (
        run_cli(
            monkeypatch, "generate", "--spec", str(bad), "--out", str(tmp_path / "x")
        )
        == 1
    )
    assert f"spec {bad} is not JSON: line 1" in capsys.readouterr().err


def test_export_spec_refuses_to_overwrite_without_force(tmp_path, monkeypatch, capsys):
    target = tmp_path / "specs"
    assert run_cli(monkeypatch, "export-spec", "--dir", str(target)) == 0
    written = target / "apidoc-spec.json"
    assert written.read_bytes() == apidoc.bundled_spec().read_bytes()
    written.write_text("{}")
    assert run_cli(monkeypatch, "export-spec", "--dir", str(target)) == 1
    assert "pass --force" in capsys.readouterr().err
    assert written.read_text() == "{}"
    assert run_cli(monkeypatch, "export-spec", "--dir", str(target), "--force") == 0
    assert written.read_bytes() == apidoc.bundled_spec().read_bytes()
