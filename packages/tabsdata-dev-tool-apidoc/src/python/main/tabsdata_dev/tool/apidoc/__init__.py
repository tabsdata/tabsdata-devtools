#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd apidoc`` -- a Python package's public API as one structured JSON
document (or a Markdown descriptions file), read statically with griffe.

The port of tabsdata-os's ``tdx-apidocgen``, and it finds the package the way
that tool does: on the ``sys.path`` of the current venv. griffe parses the
source and never imports it, but it still has to find it, and tdx-apidocgen
let griffe search its own interpreter's ``sys.path`` -- whatever tabsdata that
venv has installed, a regular install or an editable one whose ``.pth`` files
put every ``src/main/python`` of a checkout on the path. This tool runs in its
toolset venv instead, which has griffe and no tabsdata, so it asks the venv
active in the caller's shell for its ``sys.path`` and hands griffe exactly that.

The spec is a file of the caller's, or the one this package carries (a copy of
tabsdata-os's ``variant/config/apidoc-spec.json``); ``export-spec`` writes that
copy out to edit. README.md beside pyproject.toml documents the spec.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import shutil
import tempfile
from importlib import resources

from tabsdata_dev.common.core import cli, errors, managedvenv, proc, render

DESCRIPTION = "generates a Python package's API as JSON, for documentation generation"

#: The spec this package carries: tabsdata-os's variant/config/apidoc-spec.json.
SPEC_NAME = "apidoc-spec.json"


def bundled_spec() -> pathlib.Path:
    """The carried spec. Package data, found through importlib.resources, so the
    wheel and an editable install read it from the same place."""
    return pathlib.Path(
        str(resources.files("tabsdata_dev.tool.apidoc") / "specs" / SPEC_NAME)
    )


def load_spec(path: pathlib.Path | None) -> tuple[dict, pathlib.Path]:
    spec_path = (path or bundled_spec()).expanduser()
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise errors.ToolError(f"cannot read spec {spec_path}: {exc.strerror}") from exc
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as exc:
        raise errors.ToolError(
            f"spec {spec_path} is not JSON: line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(spec, dict):
        raise errors.ToolError(f"spec {spec_path} is not a JSON object")
    return spec, spec_path


def root_package(spec: dict) -> str:
    """The package the spec documents: `root_package`, else the first module's
    top level -- the rule generate() applies."""
    modules = spec.get("modules") or []
    name = spec.get("root_package") or (modules[0].split(".")[0] if modules else "")
    if not name:
        raise errors.ToolError("spec error: no 'root_package' and no 'modules'")
    return name


def current_venv() -> tuple[str, pathlib.Path]:
    """(how it was found, directory) of the venv active in the caller's shell.

    The one the launchers run tdk in -- the venv last activated, managed by
    `tdd venv` or not (`managedvenv.select`): `VIRTUAL_ENV` (uv, pyenv, `python
    -m venv`), else a conda env other than base (`CONDA_PREFIX`), unless a
    `_TDD_VENV` set by hand names a managed one. tdx-apidocgen ran in whatever
    venv the shell had, so this does not insist on a managed one. The
    dispatcher runs this tool from its toolset venv but leaves both variables
    as the shell set them.
    """
    venv = managedvenv.select(required=False)
    if venv is not None:
        if venv.name:
            return f"managed venv {venv.name}", venv.path
        return ("CONDA_PREFIX" if venv.manager == "conda" else "VIRTUAL_ENV"), venv.path
    raise errors.ToolError(
        "no venv is active: apidoc reads the package from the current venv, as "
        "tdx-apidocgen does -- activate one that has it installed "
        "(tdd venv activate --name NAME, or source a venv's bin/activate)"
    )


def venv_search_paths(out: render.Renderer) -> list[str]:
    """The current venv's own sys.path, asked of its interpreter.

    Asked rather than derived from the layout: it is what that venv's `import`
    would search -- the interpreter's stdlib, site-packages and every `.pth` an
    editable install added -- which is exactly what tdx-apidocgen's griffe
    searched, and griffe needs the stdlib too to resolve `typing`, `datetime`
    and the like.
    """
    how, path = current_venv()
    # python.exe in a Windows conda env's root, else bin/ or Scripts\
    python = managedvenv.program(path, "python")
    if python is None and (path / "python.exe").is_file():
        python = path / "python.exe"
    if python is None:
        raise errors.ToolError(f"{how}: no interpreter in {managedvenv.bin_dir(path)}")
    done = proc.run(
        [str(python), "-c", "import json, sys; print(json.dumps(sys.path))"],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise errors.ToolError(
            f"could not read sys.path from {python} (exit {done.returncode})",
            details=done.stderr,
        )
    paths = [p for p in json.loads(done.stdout) if p]
    if not paths:
        # griffe reads an empty list as "none given" and falls back to this
        # process's own sys.path -- the toolset venv, which has no tabsdata
        raise errors.ToolError(f"{python} reports an empty sys.path")
    out.info(f"venv: {path} ({how}, {len(paths)} sys.path entries)")
    for entry in paths:
        out.debug(f"sys.path {entry}")
    return paths


class _ToDebug(logging.Handler):
    """griffe's own logging (unresolved aliases, `__all__` notes) as debug events:
    detail for chasing a surprise in the output, noise on every other run."""

    def __init__(self, out: render.Renderer):
        super().__init__(logging.DEBUG)
        self.out = out

    def emit(self, record: logging.LogRecord) -> None:
        self.out.debug(f"griffe: {record.getMessage()}")


def write_atomic(dest: pathlib.Path, text: str) -> None:
    """A temporary file beside `dest` and one rename, so a failed run never
    leaves a half-written document where the last good one was."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, dest)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def cmd_generate(args: argparse.Namespace, out: render.Renderer) -> int:
    # imported here so --help, export-spec and config work without griffe loaded
    from tabsdata_dev.tool.apidoc import generate, markdown

    spec, spec_path = load_spec(pathlib.Path(args.spec) if args.spec else None)
    out.info(f"spec: {spec_path}" + ("" if args.spec else " (bundled)"))
    package = root_package(spec)
    paths = venv_search_paths(out)
    griffe_log = logging.getLogger("griffe")
    handler = _ToDebug(out)
    griffe_log.addHandler(handler)
    griffe_log.propagate = False
    try:
        data = generate.generate(spec, paths, out)
    finally:
        griffe_log.removeHandler(handler)
    if args.doc_format == "markdown":
        text = markdown.render_markdown(data)
    else:
        text = json.dumps(data, indent=args.indent, ensure_ascii=False)
    dest = pathlib.Path(args.out).expanduser()
    write_atomic(dest, text.rstrip("\n") + "\n")
    counts = {
        kind: sum(len(m[kind]) for m in data["modules"].values())
        for kind in ("classes", "functions", "attributes")
    }
    return out.ok(
        f"wrote {dest} ({args.doc_format}): {len(data['modules'])} module(s), "
        f"{counts['classes']} classes, {counts['functions']} functions, "
        f"{counts['attributes']} attributes",
        out=str(dest),
        doc_format=args.doc_format,
        spec=str(spec_path),
        root_package=package,
        modules=len(data["modules"]),
        **counts,
    )


def cmd_export_spec(args: argparse.Namespace, out: render.Renderer) -> int:
    target = pathlib.Path(args.dir).expanduser()
    if target.exists() and not target.is_dir():
        return out.error(f"not a directory: {target}")
    dest = target / SPEC_NAME
    if dest.exists() and not args.force:
        return out.error(
            f"already there: {dest} -- pass --force to overwrite (an edited copy would be lost)"
        )
    if not target.exists():
        target.mkdir(parents=True)
        out.info(f"created {target}")
    shutil.copyfile(bundled_spec(), dest)
    return out.ok(
        f"exported {SPEC_NAME} to {target}; generate from it with "
        f"`tdd apidoc generate --spec {dest} --out FILE`",
        dir=str(target),
        file=str(dest),
    )


def configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", metavar="SUBCOMMAND")
    gen = sub.add_parser(
        "generate",
        help="write the API document for a spec",
        description=(
            "Read the package the spec names, statically with griffe (it parses, "
            "never imports), and write its public API to --out: the structured "
            "JSON document, or with --doc-format markdown every description under "
            "a heading locating its docstring. The package is read from the "
            "current venv, as tdx-apidocgen does: the sys.path of the `tdd venv` "
            "managed venv that is active, else of the venv VIRTUAL_ENV (or a "
            "conda env's CONDA_PREFIX) names -- so install tabsdata there, "
            "regularly or editable from a checkout, and activate it first. The "
            "spec is --spec, else the bundled one (tabsdata-os "
            "variant/config/apidoc-spec.json); its format is in the tool's "
            "README.md."
        ),
    )
    gen.add_argument(
        "--out", required=True, metavar="FILE", help="where to write the document"
    )
    gen.add_argument(
        "--spec",
        metavar="FILE",
        help="the JSON spec (default: the bundled tabsdata one; `export-spec` writes it out)",
    )
    gen.add_argument(
        "--doc-format",
        choices=("json", "markdown"),
        default="json",
        help="json: the full structured document; markdown: the descriptions only, "
        "each under a heading naming its docstring (default: json)",
    )
    gen.add_argument(
        "--indent",
        type=int,
        default=2,
        metavar="N",
        help="JSON indentation (default: 2; json only)",
    )
    exp = sub.add_parser(
        "export-spec",
        help="copy the bundled spec into a directory of your own",
        description=(
            f"Copy the bundled {SPEC_NAME} into DIR to read and edit, then "
            "generate from it with --spec."
        ),
    )
    exp.add_argument("--dir", required=True, help="where to write it")
    exp.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="overwrite a spec already there (default: refuse, so an edited copy survives)",
    )


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action == "generate":
        return cmd_generate(args, out)
    if args.action == "export-spec":
        return cmd_export_spec(args, out)
    return out.error("no action given (see --help)")


def main() -> int:
    return cli.run("apidoc", DESCRIPTION, body, configure=configure)
