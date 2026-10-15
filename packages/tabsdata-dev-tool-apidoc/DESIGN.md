<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-tool-apidoc

`tdd apidoc` — a Python package's public API as structured JSON, read statically with griffe:
the port of tabsdata-os's `tdx-apidocgen` (tabsdata-toolkit,
`tabsdatax/generator/apidoc/cli.py`, schema 1.3.0). The spec format and the output are in
[README.md](README.md); this is what the code does not show.

## Shape

```
tdd apidoc generate --out FILE [--spec FILE] [--doc-format json|markdown] [--indent N]
tdd apidoc export-spec --dir DIR [--force]
```

Toolset `launchers`, with `griffe==2.3.2` added to `deps-launchers` — the pin tdx-apidocgen runs
on. griffe is pure Python with one dependency (colorama), so a toolset venv of its own would have
cost a whole environment for it, the reason `pycache` joined `launchers` too. No `bin-reqs`: the
one program it runs is the current venv's `python`, a name the toolset's own `bin/` has.

## Decisions

**A port, not a rewrite.** `generate.py` and `markdown.py` are the original with its extraction
left alone, so the two tools write the same document: checked on 2026-09-25 against tabsdata-os
`064c2c66c`, from the `nyc-taxi` venv (tabsdata 2.1.0) and from a checkout's source roots,
identical but for `generator.name` (and the generated-by comment of the Markdown). What changed
is the house contract: prints are events (progress `info`, the re-export tally `debug`, an
unmatched allow-list entry or an unloadable inventory `warn`), griffe's own logging is `debug`,
a bad spec is a `ToolError` instead of `SystemExit`, and the document is written through a
temporary file and one rename. `generator.version` stays `1.3.0`: it versions the schema, which
did not move. A change to extraction belongs in both tools until tdx-apidocgen retires.

**The package comes from the current venv, as the original's does.** tdx-apidocgen let griffe
search its own interpreter's `sys.path`, so it documented whatever was installed in the venv it
ran in. This process's `sys.path` is the toolset venv's -- griffe and no tabsdata, or worse
whatever tabsdata some other tool pulled in -- so the tool asks the venv active in the caller's
shell for *its* `sys.path` and passes exactly that as griffe's search paths: the venv the
launchers would run tdk in, the last activated (`managedvenv.select`: `VIRTUAL_ENV`, else a
non-base `CONDA_PREFIX`, unless a hand-set `_TDD_VENV` names a managed one; the dispatcher leaves
the variables as the shell set them). Asked of the interpreter rather than derived from the layout, because
that is the only way to get an editable install's `.pth` entries and the stdlib griffe needs for
`typing`. A checkout is documented by installing it editable, which is how tabsdata-os works
anyway. There were `--search-path` and `--source-tree` options (a depth-limited walk for every
`src/main/python`); they were dropped at the user's request, so the tool finds the package the
way the original does. Two guards the original lacks: `try_relative_path=False`, so a `tabsdatak/` in the cwd is
never loaded as the package (griffe's default, and a silent partial document); and an empty
`sys.path` is refused, since griffe reads `[]` as "none given" and would search the toolset venv.

**`--doc-format`, not `--format`.** The guidelines extend `--format` with a command's own shapes,
but `json` is already the event stream's there: `--format json` could not mean both. The document
goes to `--out`, never stdout, so the event stream stays the only thing on stdout; `--out` is
required rather than defaulted, since a document is only useful where the caller put it.

**The spec is package data, not a force-included tree.** The smoke scripts and xp's suites are
edited where they live, at the repo root. This spec is edited in tabsdata-os
(`variant/config/apidoc-spec.json`, copied from `064c2c66c`); `specs/apidoc-spec.json` is the
copy the tool ships, found with `importlib.resources` in both install layouts. Refresh it by
copying the file over — a test checks it stays consistent (every category grouped), not that it
matches upstream, which a test here cannot see. `export-spec` refuses an existing file without
`--force`: the reason to export is to edit.

**The stub policy patches griffe's internals.** `install_pyi_wins_policy` replaces
`merge_stubs` in `griffe._internal.loader` and `griffe._internal.mixins`, as the original does;
those are private modules, which is why the pin is exact and a bump means re-running the stub
test.
