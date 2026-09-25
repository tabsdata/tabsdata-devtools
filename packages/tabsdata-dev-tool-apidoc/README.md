<!--
Copyright 2026 Tabsdata Inc.
-->

# tdd apidoc

A Python package's public API as one structured JSON document — or a Markdown file of its
descriptions — read **statically** with [griffe](https://mkdocstrings.github.io/griffe/): the
source is parsed, never imported, so no package code runs. It is tabsdata-os's `tdx-apidocgen`,
brought into tdd; given the same spec and the same source it writes the same document.

```bash
tdd venv activate --name work                                        # a venv with tabsdata installed
tdd apidoc generate --out api.json                                   # bundled spec
tdd apidoc generate --doc-format markdown --out descriptions.md      # descriptions only
tdd apidoc export-spec --dir ~/apidoc                                # the bundled spec, to edit
tdd apidoc generate --spec ~/apidoc/apidoc-spec.json --out api.json  # ... and generate from it
```

## Where the package is found: the current venv

The package is read from the **current venv**, the way `tdx-apidocgen` reads it. griffe parses
the source and never imports it, but it still has to *find* it: `tdx-apidocgen` let griffe search
its own interpreter's `sys.path`, so the package had to be installed in the venv it ran in.
`tdd apidoc` runs in its own toolset venv (which has griffe and no tabsdata), so it asks the venv
active in your shell for its `sys.path` and hands griffe exactly that — the same paths the
original would have searched had it run there.

The current venv is, first found:

1. the `tdd venv` managed venv that is active (`_TDD_VENV`, set by `tdd venv activate`, or a
   managed venv entered by hand);
2. any venv `VIRTUAL_ENV` names (uv, pyenv, `python -m venv`);
3. the conda env `CONDA_PREFIX` names, unless it is `base`.

With none, `generate` refuses and says to activate one. So, to document:

- **a release** — install it in a venv (`pip install "tabsdata[all]"`) and activate it. The
  installed tree is one merged `site-packages/tabsdatak/`, stubs included;
- **a checkout** — install it editable in a venv. Its `.pth` files put every distribution's
  `src/main/python` on `sys.path`, and griffe merges the namespace package across them, so
  uncommitted changes are what gets documented.

The directory you run from is never searched: a `tabsdatak/` folder in the cwd is not the
package (griffe's default would load it as one — a single distribution's slice of it).

## The spec file

A JSON object naming what to document and how. `--spec FILE` reads one; without it the tool
uses the one it carries, a copy of tabsdata-os's `variant/config/apidoc-spec.json`
(`export-spec` writes it out). Every key but `modules` is optional.

```json
{
  "root_package": "tabsdatak",
  "modules": ["tabsdatak.api", "tabsdatak.tableframe", "tabsdatak.dataquality"],
  "private": false,
  "inherited": ["TableFrame"],
  "list_tags": ["categories"],
  "re_exports": {
    "tabsdatak.dataquality._classifier.IsIn": "tabsdatak.dataquality.IsIn"
  },
  "categories": { "source": "Sources", "destination": "Destinations", "error": "Errors" },
  "category_groups": {
    "connectors": ["Connectors", ["source", "destination"]],
    "errors": ["Errors", ["error"]]
  },
  "intersphinx": {
    "python": { "url": "https://docs.python.org/3", "inventory": true },
    "polars": {
      "url": "https://docs.pola.rs/api/python/stable",
      "inventory": false,
      "modules": ["polars"],
      "url_template": "{url}/reference/{path}.html"
    }
  }
}
```

| key | default | meaning |
|---|---|---|
| `modules` | *(required)* | the modules to document, each by its dotted name. A name that is not a module is skipped with a warning |
| `root_package` | first module's top level | the package griffe loads — whole, so an alias in one module resolves to its definition in another. A type reference inside it is *internal* |
| `private` | `false` | also document the private surface: `_` names, dunders, private base classes |
| `inherited` | `[]` | class names (leaf names) that also document the members they inherit from a base inside `root_package` — for a public class built on a private base |
| `list_tags` | `["categories"]` | docstring field tags whose value is a comma/space separated list rather than one string |
| `re_exports` | `{}` | the re-exports to **keep**: `canonical_path` (where the name is defined) → `qualified_name` (where it is documented). Every other re-export is dropped. See below |
| `categories` | `{}` | every valid category: id → display label. A docstring using an id not listed here **fails the run**, naming where it was used |
| `category_groups` | `{}` | group id → `[label, [category_id, ...]]`. When present, every category must be in exactly one group and every grouped id must be a category, or the run fails |
| `intersphinx` | `{}` | external documentation sites that type references link to. See below |

### Categories

A docstring declares its categories with a field line, anywhere in it:

```python
def pull(...):
    """Read a table from the source.

    :categories: source, credentials
    """
```

Each entity then carries `"categories": [[group, category], ...]` — the group is the category's
group id, `null` when the spec has no groups — or `[]`. Other `:tag: value` lines go into the
entity's `tags`; lines that are inline RST roles (`:class:`…``) are left in the text.

### Re-exports

A name whose definition path (`canonical_path`) differs from the path it is documented under
(`qualified_name`) is a re-export — `tabsdatak.dataquality.IsIn`, defined in
`tabsdatak.dataquality._classifier`. Re-exports are dropped unless `re_exports` maps that
canonical path to exactly that documented path; each one dropped is recorded under its module's
`ignored_reexports`. For a kept one, its `canonical_path`, and every `target` elsewhere in the
document that refers to it, are rewritten to the documented name — so the private module never
appears in the output. An allow-list entry that matches nothing is a warning: the code has moved
away from the spec.

### Links (`intersphinx`)

Each entry is one documentation site, keyed by a label:

| field | meaning |
|---|---|
| `url` | the site's base URL |
| `inventory` | where its Sphinx `objects.inv` is: a URL, a local path, `true` (`<url>/objects.inv`) or `false` (none — use `url_template`) |
| `modules` | the top-level modules the entry covers (default: the label itself) |
| `url_template` | the link for a name no inventory has, for a name under `modules`. Placeholders: `{url}`, `{fqname}` (dotted), `{path}` (dots → `/`), `{name}` (last component) |

External names resolve the way Sphinx does: looked up in all the inventories merged, then by
the template. An inventory that cannot be fetched is a warning, and its names get no link.

## What it reads

- **`.pyi` stubs are authoritative.** A module with a stub is read from the stub alone — its
  signatures *and* its docstrings; one without is read from its `.py`. The two are never
  merged (griffe's default merges them and keeps the `.py` docstrings). Put the docstrings in
  the `.pyi`.
- **Docstrings are Google style** (`Args:`, `Returns:`, `Raises:`, `Examples:`). A missing blank
  line before a section header is tolerated. A class's `Args:`/`Attributes:` document its fields
  and constructor parameters, and are carried onto whichever lack docs of their own.
- **Examples** become a list of `{"description": text}` and `{"code-block:: <lang>": code}`
  items, from `.. code-block::` directives and `>>>` doctest lines.
- **Types** are rendered three ways: `type` with `Annotated[...]` metadata (pydantic validators
  and the like) stripped; `type_full`, the raw annotation, when it differs; and
  `type_resolved`, every documented type alias expanded until none is left (`TableNamesSpec` →
  `list[str]`), when it differs. A `X: TypeAlias = RHS` is an entity of kind `type_alias` whose
  type is `RHS`.

## The document

`--doc-format json` (the default) writes one object:

| key | |
|---|---|
| `generator` | `{"name": "tdd-apidoc", "version": ...}` — the version is the output schema's |
| `spec` | the spec, verbatim |
| `root_package`, `categories`, `category_groups` | from the spec |
| `modules` | module name → its `classes`, `functions` and `attributes`, each entity with `name` (the leaf), `kind`, `qualified_name`, `canonical_path`, `reexported`, `summary`, `description`, `categories`, `tags`, `examples`, and per kind `parameters`/`returns`/`raises`, `bases`/`constructor`/`methods`/`properties`/`attributes`, or `type`/`value` |
| `crossreferences` | three views: `by_category` (category → entities, class members included), `by_module` (module → its top-level entities) and `alphabetical` (every top-level entity, A–Z) |

Every type reference (`type_refs`) carries `link` — the documentation URL of an external type,
else `null` — and `ref`: for an internal type documented in this same document, the
`[package, module, name]` triple that finds it (`data["modules"][module]`), else `null`. A
cross-reference item is `{name, kind, ref, categories}` with the same triple.

`--doc-format markdown` writes the descriptions only: every module, entity and member with prose
becomes a section headed by its dotted path, with labelled Parameters / Returns / Raises /
Example N blocks. The heading is the marker: an edit beneath it says exactly which docstring to
change in the source.
