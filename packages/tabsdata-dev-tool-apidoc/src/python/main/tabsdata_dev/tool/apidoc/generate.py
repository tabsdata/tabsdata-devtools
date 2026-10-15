#
# Copyright 2026 Tabsdata Inc.
#

"""The generator: a Python package's public API, read statically with griffe,
as one JSON document.

Ported from tabsdata-os's ``tdx-apidocgen`` (tabsdata-toolkit,
``tabsdatax/generator/apidoc/cli.py``) with the extraction left as it was, so
the two produce the same document. What changed is only what the house
contract demands: progress and warnings are renderer events rather than
prints, a bad spec is a ToolError rather than SystemExit, and the package is
found on the current venv's ``sys.path`` handed in by the caller rather than
on this process's own -- this tool runs in a toolset venv where the documented
package is not installed. The spec format, the output shape and the rules
behind them are in the package's README.md.
"""

from __future__ import annotations

import re
import textwrap
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Callable, Optional

import griffe
from griffe import (
    Attribute,
    Class,
    Docstring,
    Expr,
    ExprAttribute,
    ExprBinOp,
    ExprList,
    ExprName,
    ExprSet,
    ExprSubscript,
    ExprTuple,
    Function,
    Module,
    Parser,
)

from tabsdata_dev.common.core.errors import ToolError

# Bumped when the output schema or extraction semantics change. Emitted into
# every generated document under "generator" for provenance.
# The version is the output schema's, carried over from tdx-apidocgen: the
# document is the same one, so a consumer keyed on it sees no change.
GENERATOR_NAME = "tdd-apidoc"
GENERATOR_VERSION = "1.3.0"


# --------------------------------------------------------------------------- #
# Stub (.pyi) policy: pyi wins, no merge
# --------------------------------------------------------------------------- #

_STUB_POLICY_INSTALLED = False


def install_pyi_wins_policy() -> None:
    """Make ``.pyi`` stubs authoritative.

    Griffe's default is to load the ``.py`` module and *merge* a sibling ``.pyi``
    into it (stub signatures win, but the ``.py`` docstrings win and members are
    unioned). We ship stubs and keep the docstrings in the ``.pyi``, so the rule
    is: **for each module, if a ``.pyi`` exists use it exclusively (its
    signatures AND docstrings); otherwise use the ``.py``. Never merge the two.**

    This is done by replacing griffe's ``merge_stubs`` at its two call sites
    (the package-init merge in the loader, and the submodule-pair merge in the
    collection mixin) with a function that returns the stub module as-is —
    keeping only the regular module's *submodules* (separate files, not content).
    Modules that have no stub are unaffected.
    """
    global _STUB_POLICY_INSTALLED
    if _STUB_POLICY_INSTALLED:
        return

    import griffe._internal.loader as _loader
    import griffe._internal.mixins as _mixins

    # Merge options (e.g. ``prefer_stubs_docs``) are moot: nothing is merged.
    def pyi_wins(mod1: Any, mod2: Any, **_options: Any) -> Any:
        try:
            mod1_is_stub = mod1.filepath.suffix == ".pyi"
            mod2_is_stub = mod2.filepath.suffix == ".pyi"
        except Exception:
            return mod1
        if mod1_is_stub:
            stubs, regular = mod1, mod2
        elif mod2_is_stub:
            stubs, regular = mod2, mod1
        else:
            # Preserve griffe's contract for two regular modules.
            raise ValueError("cannot merge regular (non-stubs) modules together")
        # Graft in submodules (separate files) the stub can't declare itself.
        # Only real ``Module`` members: ``isinstance`` never resolves, whereas
        # ``member.is_module`` on an import alias (e.g. ``pl`` -> ``polars``)
        # would raise ``AliasResolutionError`` — which griffe's ``set_member``
        # swallows, silently abandoning the merge and letting the ``.py`` win.
        for member_name, member in list(regular.members.items()):
            if member_name not in stubs.members and isinstance(member, Module):
                stubs.set_member(member_name, member)
        return stubs

    _loader.merge_stubs = pyi_wins
    _mixins.merge_stubs = pyi_wins
    _STUB_POLICY_INSTALLED = True


# --------------------------------------------------------------------------- #
# Docstring helpers
# --------------------------------------------------------------------------- #

# A custom field tag line, e.g. ``:categories: publisher, subscriber``.
_TAG_RE = re.compile(r"^[ \t]*:([A-Za-z][\w-]*):[ \t]*(.*?)[ \t]*$")

# Inline RST roles that must NOT be mistaken for field tags when they happen to
# open a line (e.g. ``:class:`tabsdata.X```).
_RST_INLINE_ROLES = {
    "class",
    "func",
    "meth",
    "mod",
    "ref",
    "attr",
    "obj",
    "data",
    "exc",
    "py",
    "term",
    "doc",
    "envvar",
    "option",
    "kbd",
    "math",
    "eq",
    "abbr",
    "command",
    "code",
    "file",
    "sub",
    "super",
}

# Google-style section headers Griffe recognises. Griffe requires a blank line
# *before* a section header; source docstrings frequently omit it (e.g. an
# ``Args:`` block immediately followed by ``Returns:``), so we normalise first.
_GOOGLE_SECTIONS = {
    "args",
    "arguments",
    "parameters",
    "params",
    "keyword args",
    "keyword arguments",
    "other args",
    "other arguments",
    "other parameters",
    "raises",
    "exceptions",
    "returns",
    "return",
    "yields",
    "yield",
    "receives",
    "warns",
    "warnings",
    "warning",
    "attributes",
    "functions",
    "methods",
    "classes",
    "modules",
    "examples",
    "example",
    "note",
    "notes",
    "todo",
    "todos",
    "deprecated",
    "see also",
    "references",
    "important",
    "tip",
    "hint",
    "caution",
    "danger",
    "error",
    "attention",
}
_SECTION_HEADER_RE = re.compile(r"^([ \t]*)([A-Za-z][A-Za-z ]*?):[ \t]*$")


def split_field_tags(raw: str, list_tags: set[str]) -> tuple[dict[str, list[str]], str]:
    """Pull custom ``:tag: value`` field lines out of a raw docstring.

    Returns ``(tags, cleaned_docstring)``. Lines that look like inline RST roles
    (value starting with a backtick, or a known role name) are left in place.
    Tags named in ``list_tags`` have their value tokenised on commas/whitespace,
    and duplicate tokens are dropped while preserving first-seen order (source
    docstrings occasionally repeat a ``:categories:`` line).
    """
    tags: dict[str, list[str]] = {}
    kept: list[str] = []
    for line in (raw or "").splitlines():
        m = _TAG_RE.match(line)
        if m:
            name, value = m.group(1), m.group(2)
            if name.lower() not in _RST_INLINE_ROLES and not value.startswith("`"):
                if name in list_tags:
                    tokens = [t for t in re.split(r"[,\s]+", value) if t]
                    tags.setdefault(name, []).extend(tokens)
                else:
                    tags.setdefault(name, []).append(value)
                continue
        kept.append(line)
    for name in list_tags:
        if name in tags:
            tags[name] = list(dict.fromkeys(tags[name]))
    return tags, "\n".join(kept).strip()


def normalise_sections(doc: str) -> str:
    """Ensure a blank line precedes every Google section header."""
    lines = doc.splitlines()
    out: list[str] = []
    for line in lines:
        m = _SECTION_HEADER_RE.match(line)
        if m and m.group(2).strip().lower() in _GOOGLE_SECTIONS:
            if out and out[-1].strip() != "":
                out.append("")
        out.append(line)
    return "\n".join(out)


_EXAMPLES_HEAD_RE = re.compile(r"^(\s*)Examples?:\s*$")
_CODE_BLOCK_RE = re.compile(r"^\s*\.\.\s+code-block::\s*(\w+)\s*$")


def split_off_examples(doc: str) -> tuple[Optional[str], str]:
    """Split the ``Examples:`` section off a docstring.

    Returns ``(examples_body, docstring_without_examples)``. The body is the
    raw, dedented content of the section (``None`` when absent); the section is
    removed so griffe parses only summary / description / Args / Returns /
    Raises (it does not understand ``.. code-block::``).
    """
    lines = doc.split("\n")
    for i, line in enumerate(lines):
        m = _EXAMPLES_HEAD_RE.match(line)
        if not m:
            continue
        head = len(m.group(1))
        j = i + 1
        while j < len(lines) and not (
            lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip())) <= head
        ):
            j += 1
        body = textwrap.dedent("\n".join(lines[i + 1 : j])).strip("\n")
        rest = "\n".join(lines[:i] + lines[j:]).rstrip()
        return (body or None, rest)
    return (None, doc)


def parse_examples(body: str) -> list[dict[str, str]]:
    """Parse an ``Examples:`` body into an ordered list of items.

    Each item is either ``{"description": <prose>}`` or
    ``{"code-block:: <lang>": <code>}`` (the key is the reST directive
    section verbatim). Blocks are ``.. code-block:: <lang>`` directives
    (``lang`` one of python / sql / text / bash / csv / json); ``>>>``
    doctest lines are captured as ``code-block:: python``.
    """
    lines = body.split("\n")
    items: list[dict[str, str]] = []
    prose: list[str] = []
    i = 0

    def flush() -> None:
        text = "\n".join(prose).strip()
        if text:
            items.append({"description": text})
        prose.clear()

    while i < len(lines):
        line = lines[i]
        m = _CODE_BLOCK_RE.match(line)
        if m:
            lang = m.group(1).lower()
            flush()
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            code: list[str] = []
            base: Optional[int] = None
            while i < len(lines):
                cur = lines[i]
                if cur.strip() == "":
                    code.append("")
                    i += 1
                    continue
                indent = len(cur) - len(cur.lstrip())
                if base is None:
                    base = indent
                if indent < base:
                    break
                code.append(cur)
                i += 1
            items.append(
                {f"code-block:: {lang}": textwrap.dedent("\n".join(code)).strip("\n")}
            )
        elif line.lstrip().startswith(">>>"):
            flush()
            code = []
            while i < len(lines) and lines[i].lstrip()[:3] in (">>>", "..."):
                code.append(re.sub(r"^\s*(?:>>>|\.\.\.)\s?", "", lines[i]))
                i += 1
            items.append({"code-block:: python": "\n".join(code).strip("\n")})
        else:
            prose.append(line)
            i += 1
    flush()
    return items


# --------------------------------------------------------------------------- #
# Annotation rendering + type reference collection
# --------------------------------------------------------------------------- #


def render_annotation(
    expr: Any,
    refs: list[tuple[str, str]],
    resolve_alias: Any = None,
    _seen: frozenset[str] = frozenset(),
) -> str:
    """Render an annotation expression to a *lean* string.

    ``Annotated[T, <metadata>]`` collapses to ``T`` (dropping pydantic-style
    validators and other metadata). Every referenced name is appended to
    ``refs`` as ``(display_name, canonical_path)`` so links can be resolved.

    When ``resolve_alias`` is given (a ``canonical_path -> replacement Expr | None``
    callable), any name it maps to a replacement — the right-hand side of a
    documented type alias — is expanded in place of the name and rendered
    recursively, until only non-alias types remain, and ``Union[A, B]`` /
    ``Optional[X]`` are normalised to ``A | B`` / ``X | None``. ``_seen`` guards
    against alias cycles. This is how the ``type_resolved`` form is produced;
    leave ``resolve_alias`` unset for the plain lean ``type``.
    """
    if expr is None:
        return ""
    if isinstance(expr, str):
        return expr
    if isinstance(expr, (ExprName, ExprAttribute)):
        text = expr.name if isinstance(expr, ExprName) else str(expr)
        canonical = _safe_canonical(expr)
        if resolve_alias is not None and canonical not in _seen:
            replacement = resolve_alias(canonical)
            if replacement is not None:
                return render_annotation(
                    replacement, refs, resolve_alias, _seen | {canonical}
                )
        refs.append((text, canonical))
        return text
    if isinstance(expr, ExprSubscript):
        if isinstance(expr.left, ExprName) and expr.left.name == "Annotated":
            sl = expr.slice
            first = sl.elements[0] if isinstance(sl, ExprTuple) else sl
            return render_annotation(first, refs, resolve_alias, _seen)
        # Only for the resolved form: normalise `Union[A, B]` to `A | B` and
        # `Optional[X]` to `X | None`.
        if resolve_alias is not None:
            head = _subscript_head(expr)
            if head == "Union":
                sl = expr.slice
                members = sl.elements if isinstance(sl, ExprTuple) else [sl]
                return " | ".join(
                    render_annotation(e, refs, resolve_alias, _seen) for e in members
                )
            if head == "Optional":
                inner = render_annotation(expr.slice, refs, resolve_alias, _seen)
                return f"{inner} | None"
        base = render_annotation(expr.left, refs, resolve_alias, _seen)
        inner = render_annotation(expr.slice, refs, resolve_alias, _seen)
        return f"{base}[{inner}]"
    if isinstance(expr, ExprBinOp):
        left = render_annotation(expr.left, refs, resolve_alias, _seen)
        right = render_annotation(expr.right, refs, resolve_alias, _seen)
        return f"{left} {expr.operator} {right}"
    if isinstance(expr, ExprTuple):
        return ", ".join(
            render_annotation(e, refs, resolve_alias, _seen) for e in expr.elements
        )
    if isinstance(expr, ExprList):
        return (
            "["
            + ", ".join(
                render_annotation(e, refs, resolve_alias, _seen) for e in expr.elements
            )
            + "]"
        )
    if isinstance(expr, ExprSet):
        return (
            "{"
            + ", ".join(
                render_annotation(e, refs, resolve_alias, _seen) for e in expr.elements
            )
            + "}"
        )
    # Fallback: render as-is but still try to harvest names for linking.
    if isinstance(expr, Expr):
        try:
            for el in expr.iterate(flat=True):
                if isinstance(el, ExprName):
                    refs.append((el.name, _safe_canonical(el)))
        except Exception:
            pass
    return str(expr)


def _safe_canonical(expr: Any) -> str:
    try:
        return expr.canonical_path
    except Exception:
        return str(expr)


def _subscript_head(expr: ExprSubscript) -> Optional[str]:
    """Leaf name of a subscript's base (``Union[...]`` / ``typing.Union[...]``
    -> ``Union``), or ``None`` when it is not a plain name/attribute."""
    left = expr.left
    if isinstance(left, ExprName):
        return left.name
    if isinstance(left, ExprAttribute):
        return str(left).rsplit(".", 1)[-1]
    return None


def _dedup_refs(refs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# --------------------------------------------------------------------------- #
# Intersphinx-style link resolution
# --------------------------------------------------------------------------- #

_BUILTIN_NAMES = {
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "bytearray",
    "complex",
    "list",
    "tuple",
    "dict",
    "set",
    "frozenset",
    "object",
    "type",
    "None",
    "True",
    "False",
    "Ellipsis",
    "range",
    "slice",
    "memoryview",
    "callable",
    "Any",
}


class LinkResolver:
    """Resolves external type references to documentation URLs.

    Merges all configured intersphinx inventories into a single
    ``fqname -> url`` map (like Sphinx, which searches every inventory), with a
    per-module ``url_template`` fallback when a name is not in any inventory.
    """

    def __init__(
        self,
        root_package: str,
        intersphinx: dict[str, Any],
        warn: Callable[[str], Any] = lambda _msg: None,
    ):
        self.root = root_package
        self.inventory: dict[str, str] = {}
        self.templates: list[tuple[set[str], str, str]] = []

        for label, entry in (intersphinx or {}).items():
            url = entry.get("url", "").rstrip("/")
            modules = set(entry.get("modules") or [label])
            template = entry.get("url_template")
            if template:
                self.templates.append((modules, template, url))

            inv = entry.get("inventory")
            inv_source: Optional[str] = None
            if inv is True:
                inv_source = f"{url}/objects.inv"
            elif isinstance(inv, str):
                inv_source = inv
            if inv_source:
                loaded = load_inventory(inv_source, url, warn)
                for fqname, target in loaded.items():
                    self.inventory.setdefault(fqname, target)

    def resolve(self, name: str, canonical_path: str) -> dict[str, Any]:
        """Resolve one type reference.

        Every ref carries both a ``link`` (a full external URL, or null) and a
        ``ref`` ([package, module, name] triple pointing inside this JSON, or
        null). External/builtin refs get ``link``; internal refs get ``ref``
        filled in by a later pass once every documented entity is known.
        """
        cp = canonical_path or name
        root = cp.split(".", 1)[0]

        # Internal to the documented package -> resolved to a triple later.
        if root == self.root:
            return {
                "name": name,
                "target": cp,
                "scope": "internal",
                "link": None,
                "ref": None,
            }

        # Builtins / typing specials without a module prefix.
        if "." not in cp:
            link = self.inventory.get(cp) or self.inventory.get(f"builtins.{cp}")
            scope = "builtin" if cp in _BUILTIN_NAMES else "external"
            return {
                "name": name,
                "target": cp,
                "scope": scope,
                "link": link,
                "ref": None,
            }

        # Inventory lookup (authoritative, searches all inventories).
        link = self.inventory.get(cp)
        if not link:
            # Template fallback, scoped by top-level module.
            for modules, template, url in self.templates:
                if root in modules:
                    link = template.format(
                        url=url,
                        fqname=cp,
                        path=cp.replace(".", "/"),
                        name=cp.rsplit(".", 1)[-1],
                    )
                    break
        return {
            "name": name,
            "target": cp,
            "scope": "external",
            "link": link,
            "ref": None,
        }

    def resolve_all(self, refs: list[tuple[str, str]]) -> list[dict[str, Any]]:
        return [self.resolve(n, cp) for n, cp in _dedup_refs(refs)]


def _fetch_bytes(source: str, warn: Callable[[str], Any]) -> Optional[bytes]:
    try:
        if source.startswith(("http://", "https://")):
            with urllib.request.urlopen(source, timeout=20) as resp:  # noqa: S310
                return resp.read()
        return Path(source).read_bytes()
    except Exception as exc:  # network down, 404, missing file ...
        warn(f"could not load inventory {source!r}: {exc}")
        return None


def load_inventory(
    source: str, base_url: str, warn: Callable[[str], Any] = lambda _msg: None
) -> dict[str, str]:
    """Parse a Sphinx ``objects.inv`` (v2) into ``fqname -> absolute URL``."""
    data = _fetch_bytes(source, warn)
    if not data:
        return {}
    try:
        # 4 header lines, then zlib-compressed payload.
        header_end = 0
        newlines = 0
        for i, byte in enumerate(data):
            if byte == 0x0A:  # \n
                newlines += 1
                if newlines == 4:
                    header_end = i + 1
                    break
        header = data[:header_end].decode("utf-8", "replace")
        if "version 2" not in header.splitlines()[0].lower():
            warn(f"unsupported inventory version for {source!r}")
            return {}
        payload = zlib.decompress(data[header_end:])
    except Exception as exc:
        warn(f"could not parse inventory {source!r}: {exc}")
        return {}

    base = base_url.rstrip("/")
    result: dict[str, str] = {}
    line_re = re.compile(r"(?x)(.+?)\s+(\S+)\s+(-?\d+)\s+(\S*)\s+(.*)")
    for raw_line in payload.decode("utf-8", "replace").splitlines():
        m = line_re.match(raw_line)
        if not m:
            continue
        name, domain_role, _prio, location, _disp = m.groups()
        if location.endswith("$"):
            location = location[:-1] + name
        url = f"{base}/{location}"
        # Prefer python-domain entries when a name appears more than once.
        if name not in result or domain_role.startswith("py:"):
            result[name] = url
    return result


# --------------------------------------------------------------------------- #
# Entity extraction
# --------------------------------------------------------------------------- #


def _is_private(name: str) -> bool:
    """A leaf name (possibly dotted) is private if its last component starts
    with a single underscore. ``__init__`` and other dunders count as private."""
    return name.rsplit(".", 1)[-1].startswith("_")


def _is_type_alias(attr: Any) -> bool:
    """True for a classic type alias ``X: TypeAlias = <RHS>`` — detected by its
    annotation being ``TypeAlias`` (or ``typing.TypeAlias``)."""
    annotation = getattr(attr, "annotation", None)
    if annotation is None:
        return False
    try:
        return str(annotation).rsplit(".", 1)[-1] == "TypeAlias"
    except Exception:
        return False


class Extractor:
    def __init__(
        self,
        root_package: str,
        resolver: LinkResolver,
        inherited_classes: set[str],
        list_tags: set[str],
        category_to_group: dict[str, str],
        re_exports: dict[str, str],
        modules_collection: Any,
        include_private: bool = False,
    ):
        self.root = root_package
        self.resolver = resolver
        self.inherited_classes = inherited_classes
        self.list_tags = list_tags
        self.category_to_group = category_to_group
        # canonical_path -> qualified_name allow-list of re-exports to keep.
        self.re_exports = re_exports
        # Whole loaded tree, keyed by canonical path — used to expand type aliases.
        self.modules_collection = modules_collection
        self.include_private = include_private
        # category id -> [qualified_name, ...] where it was seen (for validation).
        self.used_categories: dict[str, list[str]] = {}
        # canonical paths from re_exports that actually matched a re-export.
        self.matched_reexports: set[str] = set()
        # canonical_path -> alias RHS expr (or None when not a type alias).
        self._alias_cache: dict[str, Any] = {}

    def alias_value(self, canonical_path: str) -> Any:
        """The right-hand side expression of the documented type alias named by
        ``canonical_path``, or ``None`` when it does not name a type alias.

        Used to expand nested aliases for the ``type_resolved`` rendering.
        """
        if not canonical_path:
            return None
        if canonical_path not in self._alias_cache:
            value = None
            try:
                node = self.modules_collection[canonical_path]
            except Exception:
                node = None
            if isinstance(node, Attribute) and _is_type_alias(node):
                value = node.value
            self._alias_cache[canonical_path] = value
        return self._alias_cache[canonical_path]

    def category_pairs(
        self, raw_categories: list[str], where: str
    ) -> list[list[Optional[str]]]:
        """Turn raw category ids from a docstring into ``[group, category]``
        pairs (group is ``None`` when no groups are configured), recording each
        occurrence for later validation. Empty list when the entity has none."""
        pairs: list[list[Optional[str]]] = []
        for category in raw_categories:
            self.used_categories.setdefault(category, []).append(where)
            pairs.append([self.category_to_group.get(category), category])
        return pairs

    def _base_head(self, expr: Any) -> Optional[str]:
        """The head class name of a base expression (``_Base[T]`` -> ``_Base``)."""
        if isinstance(expr, str):
            return expr.rsplit(".", 1)[-1]
        if isinstance(expr, ExprName):
            return expr.name
        if isinstance(expr, ExprSubscript):
            return self._base_head(expr.left)
        if isinstance(expr, ExprAttribute):
            return str(expr).rsplit(".", 1)[-1]
        return None

    # -- annotation -> serialisable ------------------------------------- #
    def type_field(self, annotation: Any) -> Optional[dict[str, Any]]:
        if annotation is None:
            return None
        refs: list[tuple[str, str]] = []
        lean = render_annotation(annotation, refs)
        full = str(annotation)
        resolved = render_annotation(annotation, [], resolve_alias=self.alias_value)
        field: dict[str, Any] = {"type": lean}
        if full != lean:
            field["type_full"] = full
        if resolved != lean:
            field["type_resolved"] = resolved
        field["type_refs"] = self.resolver.resolve_all(refs)
        return field

    # -- docstring -> serialisable -------------------------------------- #
    def docstring_info(self, obj: Any) -> dict[str, Any]:
        info: dict[str, Any] = {
            "summary": None,
            "description": None,
            "tags": {},
            "categories": [],
            "param_docs": {},
            "attr_docs": {},
            "returns_doc": None,
            "raises": [],
            "examples": [],
        }
        doc_obj: Optional[Docstring] = getattr(obj, "docstring", None)
        if not doc_obj or not doc_obj.value:
            return info

        tags, cleaned = split_field_tags(doc_obj.value, self.list_tags)
        # Categories are promoted to a dedicated, group-annotated field.
        info["categories"] = tags.pop("categories", [])
        info["tags"] = tags
        cleaned = normalise_sections(cleaned)
        ex_body, cleaned = split_off_examples(cleaned)
        info["examples"] = parse_examples(ex_body) if ex_body else []

        try:
            # warnings=False silences griffe's docstring-vs-signature lint
            # ("param X not in signature", "no type/annotation for X"): the tool
            # reads annotations from the real signature, and dataclass-style
            # classes legitimately document their fields in an ``Args:`` block.
            sections = Docstring(cleaned, parent=obj).parse(
                Parser.google, warnings=False
            )
        except Exception:
            info["description"] = cleaned
            info["summary"] = (
                cleaned.strip().splitlines()[0] if cleaned.strip() else None
            )
            return info

        text_parts: list[str] = []
        for section in sections:
            kind = section.kind.value
            if kind == "text":
                text_parts.append(section.value)
            elif kind == "parameters":
                for p in section.value:
                    info["param_docs"][p.name] = (p.description or "").strip()
            elif kind == "attributes":
                for a in section.value:
                    info["attr_docs"][a.name] = (a.description or "").strip()
            elif kind == "returns":
                rets = section.value
                if rets:
                    info["returns_doc"] = (rets[0].description or "").strip()
            elif kind in ("raises", "exceptions"):
                for r in section.value:
                    info["raises"].append(
                        {
                            "exception": str(r.annotation) if r.annotation else None,
                            "description": (r.description or "").strip(),
                        }
                    )
            # `Examples:` was split off before griffe (see split_off_examples).

        description = "\n\n".join(t.strip() for t in text_parts if t.strip()).strip()
        info["description"] = description or None
        info["summary"] = description.splitlines()[0].strip() if description else None
        return info

    # -- functions / methods -------------------------------------------- #
    def function_entity(
        self,
        func: Function,
        module: str,
        qualname: str,
        reexported: bool,
        canonical: str,
        fallback_param_docs: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        # `qualname` is the within-module path (e.g. "Class.method" or "publisher");
        # `name` is just the leaf, `qualified_name` the full dotted path.
        name = qualname.rsplit(".", 1)[-1]
        qualified = f"{module}.{qualname}"
        doc = self.docstring_info(func)
        params = []
        for p in func.parameters:
            if p.name == "self" or p.name == "cls":
                continue
            description = doc["param_docs"].get(p.name)
            if not description and fallback_param_docs:
                description = fallback_param_docs.get(p.name)
            entry: dict[str, Any] = {
                "name": p.name,
                "kind": p.kind.value if p.kind else None,
                "required": p.default is None and p.kind not in _VARIADIC_KINDS,
                "default": None if p.default is None else str(p.default),
                "description": description or None,
            }
            tf = self.type_field(p.annotation)
            if tf:
                entry.update(tf)
            params.append(entry)

        result: dict[str, Any] = {
            "name": name,
            "kind": "function",
            "module": module,
            "qualified_name": qualified,
            "canonical_path": canonical,
            "reexported": reexported,
            "labels": sorted(func.labels),
            "summary": doc["summary"],
            "description": doc["description"],
            "categories": self.category_pairs(doc["categories"], qualified),
            "tags": doc["tags"],
            "parameters": params,
            "raises": doc["raises"],
            "examples": doc["examples"],
        }
        ret = self.type_field(func.returns)
        if ret is not None:
            ret["description"] = doc["returns_doc"]
            result["returns"] = ret
        elif doc["returns_doc"]:
            result["returns"] = {
                "type": None,
                "type_refs": [],
                "description": doc["returns_doc"],
            }
        return result

    # -- attributes / constants / type aliases -------------------------- #
    def attribute_entity(
        self,
        attr: Attribute,
        module: str,
        qualname: str,
        reexported: bool,
        canonical: str,
    ) -> dict[str, Any]:
        name = qualname.rsplit(".", 1)[-1]
        qualified = f"{module}.{qualname}"
        doc = self.docstring_info(attr)
        is_type_alias = _is_type_alias(attr)
        is_constant = name.isupper() and not is_type_alias
        kind = (
            "type_alias"
            if is_type_alias
            else ("constant" if is_constant else "attribute")
        )
        result: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "module": module,
            "qualified_name": qualified,
            "canonical_path": canonical,
            "reexported": reexported,
            "labels": sorted(attr.labels),
            "summary": doc["summary"],
            "description": doc["description"],
            "examples": doc["examples"],
            "categories": self.category_pairs(doc["categories"], qualified),
            "tags": doc["tags"],
        }
        if is_type_alias:
            # For `X: TypeAlias = <RHS>`, the useful "type" is what it aliases to
            # (leaned: Annotated[...] metadata stripped), not the `TypeAlias` marker.
            tf = self.type_field(attr.value)
            if tf:
                result.update(tf)
        else:
            tf = self.type_field(attr.annotation)
            if tf:
                result.update(tf)
            if attr.value is not None:
                # Not just for ALL_CAPS constants: a lowercase class-attribute
                # default (e.g. `port: PortSpec = "8123"`) needs its value
                # recorded too, or downstream tooling has nothing to show as
                # the parameter's default in a synthesized constructor
                # signature.
                result["value"] = str(attr.value)
        return result

    # -- classes -------------------------------------------------------- #
    def class_entity(
        self, cls: Class, module: str, name: str, reexported: bool, canonical: str
    ) -> dict[str, Any]:
        doc = self.docstring_info(cls)

        # Bases. A private super class (leaf name starting with "_") is dropped
        # from the output unless --private is set. Inherited-member pulling below
        # is independent, so a class can still surface the public API it inherits
        # from a private base.
        bases: list[dict[str, Any]] = []
        for base in cls.bases:
            head = self._base_head(base)
            if not self.include_private and head and _is_private(head):
                continue
            tf = self.type_field(base)
            if tf:
                bases.append(tf)

        # Field docs from the class docstring. Google style documents dataclass
        # fields and/or __init__ parameters in the class's ``Args:`` (and
        # sometimes ``Attributes:``) section, so these feed both the attribute
        # entities (dataclass fields) and the constructor parameters.
        field_docs: dict[str, str] = {}
        field_docs.update(doc["param_docs"])
        field_docs.update(doc["attr_docs"])

        methods, properties, attributes = [], [], []
        constructor = None

        def consider(member_name: str, member: Any, inherited: bool):
            nonlocal constructor
            if member.is_alias:
                try:
                    member = member.target
                except Exception:
                    return
            member_canonical = _safe_canonical(member)
            if member_name == "__init__" and isinstance(member, Function):
                constructor = self.function_entity(
                    member,
                    module,
                    f"{name}.__init__",
                    reexported,
                    member_canonical,
                    fallback_param_docs=field_docs,
                )
                return
            if not self.include_private and member_name.startswith("_"):
                return
            if isinstance(member, Function):
                ent = self.function_entity(
                    member,
                    module,
                    f"{name}.{member_name}",
                    reexported,
                    member_canonical,
                )
                ent["inherited"] = inherited
                methods.append(ent)
            elif isinstance(member, Attribute):
                ent = self.attribute_entity(
                    member,
                    module,
                    f"{name}.{member_name}",
                    reexported,
                    member_canonical,
                )
                ent["inherited"] = inherited
                # Fall back to the class docstring's field docs when the attribute
                # has no docstring of its own (the common dataclass case).
                if not ent.get("description") and field_docs.get(member_name):
                    ent["description"] = field_docs[member_name]
                    ent["summary"] = field_docs[member_name].splitlines()[0].strip()
                if "property" in member.labels:
                    ent["kind"] = "property"
                    properties.append(ent)
                else:
                    attributes.append(ent)
            elif isinstance(member, Class):
                # Nested class: document as an attribute-like reference.
                nested_doc = self.docstring_info(member)
                attributes.append(
                    {
                        "name": member_name,
                        "kind": "class",
                        "module": module,
                        "qualified_name": f"{module}.{name}.{member_name}",
                        "canonical_path": member_canonical,
                        "inherited": inherited,
                        "summary": nested_doc["summary"],
                        "description": nested_doc["description"],
                        "examples": nested_doc["examples"],
                        "categories": self.category_pairs(
                            nested_doc["categories"], f"{module}.{name}.{member_name}"
                        ),
                        "tags": nested_doc["tags"],
                    }
                )

        for member_name, member in cls.members.items():
            consider(member_name, member, inherited=False)

        if name in self.inherited_classes:
            own = set(cls.members.keys())
            try:
                inherited_members = cls.inherited_members
            except Exception:
                inherited_members = {}
            for member_name, member in inherited_members.items():
                if member_name in own:
                    continue
                if (
                    not self.include_private
                    and member_name.startswith("_")
                    and member_name != "__init__"
                ):
                    continue
                try:
                    target_path = (
                        member.target_path
                        if member.is_alias
                        else _safe_canonical(member)
                    )
                except Exception:
                    target_path = ""
                if not target_path.startswith(self.root + "."):
                    continue
                consider(member_name, member, inherited=True)

        return {
            "name": name,
            "kind": "class",
            "module": module,
            "qualified_name": f"{module}.{name}",
            "canonical_path": canonical,
            "reexported": reexported,
            "labels": sorted(cls.labels),
            "summary": doc["summary"],
            "description": doc["description"],
            "examples": doc["examples"],
            "categories": self.category_pairs(doc["categories"], f"{module}.{name}"),
            "tags": doc["tags"],
            "bases": bases,
            "constructor": constructor,
            "properties": properties,
            "attributes": attributes,
            "methods": methods,
        }

    # -- module --------------------------------------------------------- #
    def module_entity(self, mod: Module, module_name: str) -> dict[str, Any]:
        classes, functions, attributes = [], [], []
        ignored: list[dict[str, str]] = []

        for member_name, member in mod.members.items():
            if not self.include_private and member_name.startswith("_"):
                continue

            qualified = f"{module_name}.{member_name}"
            if member.is_alias:
                try:
                    resolved = member.target
                except Exception:
                    # Unresolvable alias (usually a re-export of a name from an
                    # unloaded external package, e.g. polars) -> drop it.
                    try:
                        ignored.append(
                            {
                                "name": member_name,
                                "target": member.target_path,
                            }
                        )
                    except Exception:
                        pass
                    continue
            else:
                resolved = member

            canonical = _safe_canonical(resolved)

            # A name whose real definition path (canonical) differs from where it
            # is documented (qualified) is a re-export. Re-exports are dropped
            # unless the `re_exports` allow-list maps this canonical path to
            # exactly this documented path.
            reexported = canonical != qualified
            if reexported:
                if self.re_exports.get(canonical) == qualified:
                    self.matched_reexports.add(canonical)
                else:
                    ignored.append({"name": member_name, "target": canonical})
                    continue

            if isinstance(resolved, Class):
                classes.append(
                    self.class_entity(
                        resolved, module_name, member_name, reexported, canonical
                    )
                )
            elif isinstance(resolved, Function):
                functions.append(
                    self.function_entity(
                        resolved, module_name, member_name, reexported, canonical
                    )
                )
            elif isinstance(resolved, Attribute):
                attributes.append(
                    self.attribute_entity(
                        resolved, module_name, member_name, reexported, canonical
                    )
                )
            # Modules re-exported as names (import x) are skipped implicitly.

        mod_doc = self.docstring_info(mod)
        return {
            "name": module_name,
            "summary": mod_doc["summary"],
            "description": mod_doc["description"],
            "examples": mod_doc["examples"],
            "categories": self.category_pairs(mod_doc["categories"], module_name),
            "tags": mod_doc["tags"],
            "classes": classes,
            "functions": functions,
            "attributes": attributes,
            "ignored_reexports": ignored,
        }


_VARIADIC_KINDS = set()  # filled after import (ParameterKind values)
try:
    from griffe import ParameterKind

    _VARIADIC_KINDS = {ParameterKind.var_positional, ParameterKind.var_keyword}
except Exception:
    pass


# --------------------------------------------------------------------------- #
# Internal cross-reference resolution
# --------------------------------------------------------------------------- #


def build_entity_index(
    out_modules: dict[str, Any], root_package: str
) -> dict[str, list[tuple[str, str, bool]]]:
    """Map ``canonical_path -> [(module, name, reexported), ...]`` for every
    top-level documented entity (classes, functions, attributes/constants).

    Type references only ever point at module-level names, so methods and other
    nested members are not indexed.
    """
    index: dict[str, list[tuple[str, str, bool]]] = {}
    for module_name, mod in out_modules.items():
        for group in ("classes", "functions", "attributes"):
            for ent in mod.get(group, []):
                cp = ent.get("canonical_path")
                if cp:
                    index.setdefault(cp, []).append(
                        (
                            module_name,
                            ent["name"],
                            bool(ent.get("reexported")),
                        )
                    )
    return index


def _best_triple(
    index: dict[str, list[tuple[str, str, bool]]],
    canonical_path: str,
    root_package: str,
) -> Optional[list[str]]:
    """Pick the best [package, module, name] triple for a canonical path.

    Prefers an occurrence where the entity is defined (not re-exported), then
    the shallowest module (top-level public location), then alphabetical — so a
    name exported from several modules resolves to a single, stable target.
    """
    candidates = index.get(canonical_path)
    if not candidates:
        return None
    module_name, name, _ = sorted(
        candidates, key=lambda t: (t[2], t[0].count("."), t[0])
    )[0]
    return [root_package, module_name, name]


def resolve_internal_refs(
    node: Any, index: dict[str, list[tuple[str, str, bool]]], root_package: str
) -> None:
    """Walk the output and fill the ``ref`` triple of every internal ref that
    points at an entity present in this JSON."""
    if isinstance(node, dict):
        for ref in node.get("type_refs", []):
            if ref.get("scope") == "internal":
                ref["ref"] = _best_triple(index, ref.get("target", ""), root_package)
        for value in node.values():
            resolve_internal_refs(value, index, root_package)
    elif isinstance(node, list):
        for value in node:
            resolve_internal_refs(value, index, root_package)


# --------------------------------------------------------------------------- #
# Re-export target remapping (spec-driven allow-list)
# --------------------------------------------------------------------------- #

# Fields whose value is a canonical path and so must follow the remapping: the
# entity's own identity (``canonical_path``) and every reference to it (``target``).
_REMAPPED_FIELDS = ("canonical_path", "target")


def remap_reexport_paths(
    node: Any, re_exports: dict[str, str], counts: dict[str, dict[str, int]]
) -> None:
    """Rewrite every ``canonical_path`` and ``target`` that equals an allowed
    re-export's canonical path to the documented ``qualified_name`` (the
    allow-list value), tallying replacements per canonical path and field in
    ``counts`` (``{canonical: {field: n}}``)."""
    if isinstance(node, dict):
        for field in _REMAPPED_FIELDS:
            value = node.get(field)
            if isinstance(value, str) and value in re_exports:
                node[field] = re_exports[value]
                bucket = counts.setdefault(value, {})
                bucket[field] = bucket.get(field, 0) + 1
        for value in node.values():
            remap_reexport_paths(value, re_exports, counts)
    elif isinstance(node, list):
        for value in node:
            remap_reexport_paths(value, re_exports, counts)


def report_reexports(
    re_exports: dict[str, str],
    matched: set[str],
    counts: dict[str, dict[str, int]],
    out: Any,
) -> None:
    """Report the re-export remapping and how many ``canonical_path`` /
    ``target`` occurrences were rewritten for each (debug, one line per entry),
    warning about allow-list entries that matched no re-export -- a spec entry
    that does nothing is one the code has moved away from."""
    unmatched = 0
    for canonical in sorted(re_exports):
        qualified = re_exports[canonical]
        bucket = counts.get(canonical, {})
        defs = bucket.get("canonical_path", 0)
        refs = bucket.get("target", 0)
        plural = "" if refs == 1 else "s"
        if canonical not in matched:
            unmatched += 1
            out.warn(f"re_exports: no re-export matched {canonical} (-> {qualified})")
            continue
        out.debug(
            f"re-export {canonical} -> {qualified} "
            f"({defs} canonical_path, {refs} target ref{plural} replaced)"
        )
    out.info(
        f"re-exports: {len(re_exports) - unmatched} of {len(re_exports)} "
        "allow-list entries matched"
    )


# --------------------------------------------------------------------------- #
# Cross-reference index
# --------------------------------------------------------------------------- #


def _xref_entry(
    root_package: str, module_name: str, ent: dict[str, Any]
) -> dict[str, Any]:
    # Locate by the within-module path (e.g. "Class.method"), since an entity's
    # own `name` is now just the leaf.
    qualified = ent.get("qualified_name", "")
    prefix = module_name + "."
    qualpath = qualified[len(prefix) :] if qualified.startswith(prefix) else ent["name"]
    kind = ent.get("kind")
    if kind == "function" and "." in qualpath:
        kind = "method"
    return {
        "name": qualpath,
        "kind": kind,
        "ref": [root_package, module_name, qualpath],
        "categories": ent.get("categories") or [],
    }


def build_crossreferences(
    out_modules: dict[str, Any], root_package: str
) -> dict[str, Any]:
    """Build cross-reference views over the documented surface:

      * ``alphabetical`` — every top-level entity (class / function / constant),
        sorted A-Z by name.
      * ``by_module``    — module -> its top-level entities.
      * ``by_category``  — category -> every entity carrying it, *including* class
        methods / properties (categories can live on members too).

    Each list item is ``{name, kind, ref: [package, module, name], categories}``,
    where ``ref`` locates the full entity inside ``modules`` (same triple form as
    internal type references).
    """
    top_entries: list[dict[str, Any]] = []
    categorized: list[dict[str, Any]] = []

    for module_name, mod in out_modules.items():
        for group in ("classes", "functions", "attributes"):
            for ent in mod.get(group, []):
                entry = _xref_entry(root_package, module_name, ent)
                top_entries.append(entry)
                if entry["categories"]:
                    categorized.append(entry)
                if group == "classes":
                    for sub_group in ("methods", "properties", "attributes"):
                        for sub in ent.get(sub_group, []):
                            sub_entry = _xref_entry(root_package, module_name, sub)
                            if sub_entry["categories"]:
                                categorized.append(sub_entry)

    def by_name(e):
        return (
            e["name"].rsplit(".", 1)[-1].lower(),
            e["name"].lower(),
            e["ref"][1],
        )

    alphabetical = sorted(top_entries, key=by_name)

    by_module: dict[str, list[dict[str, Any]]] = {}
    for entry in top_entries:
        by_module.setdefault(entry["ref"][1], []).append(entry)
    for entries in by_module.values():
        entries.sort(key=by_name)

    by_category: dict[str, list[dict[str, Any]]] = {}
    for entry in categorized:
        for _group, category in entry["categories"]:
            by_category.setdefault(category, []).append(entry)
    for entries in by_category.values():
        entries.sort(key=by_name)

    return {
        "by_category": {k: by_category[k] for k in sorted(by_category)},
        "by_module": by_module,
        "alphabetical": alphabetical,
    }


# --------------------------------------------------------------------------- #
# Categories & groups (spec-driven)
# --------------------------------------------------------------------------- #


def parse_category_spec(spec: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Read the ``categories`` and ``category_groups`` spec sections.

    Returns ``(categories, category_to_group)`` and validates their mutual
    consistency (a group referencing an undefined category, or a defined
    category that no group contains, is a hard error).

      "categories":       { "publisher": "Publisher", ... }
      "category_groups":  { "function": ["Functions", ["publisher", ...]], ... }
    """
    categories: dict[str, str] = dict(spec.get("categories") or {})
    groups: dict[str, Any] = dict(spec.get("category_groups") or {})

    category_to_group: dict[str, str] = {}
    for group_id, value in groups.items():
        if not (
            isinstance(value, list) and len(value) == 2 and isinstance(value[1], list)
        ):
            raise ToolError(
                f"spec error: category_groups[{group_id!r}] must be "
                f"[label, [category_id, ...]]"
            )
        for category_id in value[1]:
            if category_id in category_to_group:
                raise ToolError(
                    f"spec error: category {category_id!r} is in more than one "
                    f"group ({category_to_group[category_id]!r} and {group_id!r})"
                )
            category_to_group[category_id] = group_id

    if groups:
        grouped = set(category_to_group)
        defined = set(categories)
        unknown = grouped - defined
        if unknown:
            raise ToolError(
                "spec error: category_groups reference undefined categories: "
                + ", ".join(sorted(unknown))
            )
        ungrouped = defined - grouped
        if ungrouped:
            raise ToolError(
                "spec error: these categories are not assigned to any group: "
                + ", ".join(sorted(ungrouped))
            )

    return categories, category_to_group


def validate_used_categories(
    used: dict[str, list[str]], defined: dict[str, str]
) -> None:
    """Fail if any category found in the code's docstrings is not defined in the
    spec's ``categories`` section, listing where each offender was found."""
    unknown = {c: locs for c, locs in used.items() if c not in defined}
    if not unknown:
        return
    lines = [
        "error: undefined categories found in docstrings "
        "(add them to the spec's 'categories' section or fix the source):"
    ]
    for category in sorted(unknown):
        locations = unknown[category]
        shown = ", ".join(locations[:5]) + (" ..." if len(locations) > 5 else "")
        lines.append(f"  - {category!r} ({len(locations)}x): {shown}")
    raise ToolError("\n".join(lines))


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


class _Silent:
    """A renderer that says nothing, for callers that only want the document."""

    def info(self, *_a: Any, **_k: Any) -> None: ...
    def warn(self, *_a: Any, **_k: Any) -> None: ...
    def debug(self, *_a: Any, **_k: Any) -> None: ...


def generate(
    spec: dict[str, Any],
    search_paths: list[str],
    out: Any = None,
) -> dict[str, Any]:
    """The document for `spec`, the package found on `search_paths` -- the
    current venv's sys.path, as the caller read it; nothing of this process's
    own is added, and the cwd is never searched. `out` is a renderer --
    ``info``/``warn``/``debug`` -- for progress and warnings."""
    out = out or _Silent()
    if "modules" not in spec:
        raise ToolError("spec error: 'modules' is missing")
    modules: list[str] = spec["modules"]
    if not modules:
        raise ToolError("spec error: 'modules' is empty")
    root_package = spec.get("root_package") or modules[0].split(".")[0]
    inherited = set(spec.get("inherited") or [])
    list_tags = set(spec.get("list_tags") or ["categories"])
    intersphinx = spec.get("intersphinx") or {}
    include_private = bool(spec.get("private", False))
    re_exports: dict[str, str] = dict(spec.get("re_exports") or {})
    categories_def, category_to_group = parse_category_spec(spec)

    out.info(
        f"loading {root_package!r} (static) from {len(search_paths)} search path(s)"
    )
    # `.pyi` stubs are authoritative (pyi wins, no merge) — see the module docstring.
    install_pyi_wins_policy()
    # Load the whole package once so alias targets resolve across submodules.
    if not search_paths:
        # griffe reads an empty list as "none given" and searches this process's
        # own sys.path instead -- the toolset venv, not the one documented
        raise ToolError("no search paths to load the package from")
    try:
        root = griffe.load(
            root_package,
            submodules=True,
            allow_inspection=False,
            search_paths=list(search_paths),
            # Never the cwd: griffe would otherwise load a `tabsdatak/` folder
            # in the directory it is run from as the whole package -- one
            # distribution's slice of it, silently.
            try_relative_path=False,
        )
    except ModuleNotFoundError as exc:
        raise ToolError(
            f"{root_package!r} is not installed in the current venv ({exc}); "
            "install it there, or activate the venv that has it",
            details="search paths:\n" + "\n".join(search_paths),
        ) from exc

    resolver = LinkResolver(root_package, intersphinx, warn=out.warn)
    extractor = Extractor(
        root_package,
        resolver,
        inherited,
        list_tags,
        category_to_group,
        re_exports,
        root.modules_collection,
        include_private=include_private,
    )

    out_modules: dict[str, Any] = {}
    for module_name in modules:
        rel = (
            module_name[len(root_package) + 1 :] if module_name != root_package else ""
        )
        try:
            mod = root[rel] if rel else root
        except Exception as exc:
            out.warn(f"skipping {module_name!r}: {exc}")
            continue
        if not isinstance(mod, Module):
            out.warn(f"{module_name!r} is not a module, skipping")
            continue
        out_modules[module_name] = extractor.module_entity(mod, module_name)

    # Fail if the code uses categories the spec does not define.
    validate_used_categories(extractor.used_categories, categories_def)

    # Resolve internal cross-references to [package, module, name] triples now
    # that every documented entity is known. This runs before the re-export
    # remapping so refs still resolve via the real (canonical) target.
    index = build_entity_index(out_modules, root_package)
    resolve_internal_refs(out_modules, index, root_package)

    # Point every `canonical_path` / `target` at an allowed re-export's
    # documented qualified name.
    if re_exports:
        counts: dict[str, dict[str, int]] = {}
        remap_reexport_paths(out_modules, re_exports, counts)
        report_reexports(re_exports, extractor.matched_reexports, counts, out)

    return {
        "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        "spec": spec,
        "root_package": root_package,
        "categories": categories_def,
        "category_groups": spec.get("category_groups") or {},
        "modules": out_modules,
        "crossreferences": build_crossreferences(out_modules, root_package),
    }
