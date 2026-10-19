#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd _smoke`` -- the Python half of the smoke scripts' shared engine.

The engine exists once per shell family (`_common.sh`, `_common.ps1`), and
what it does beyond keeping the stages -- the algorithms -- is here, once, so
the two cannot drift. Plumbing: the leading underscore keeps it out of `tdd
help`; the scripts call it, a person does not.

A helper that answers with a value makes it the ok message, which the view
format writes alone on stdout -- `$(tdd _smoke ...)` reads it in either family
-- and everything else on stderr, into the run's log. A value that is a
credential arrives in the environment, never as an argument.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

from tabsdata_dev.common.core import cli, errors, render

from . import configs, display, status

DESCRIPTION = (
    "plumbing of the smoke scripts: the config edits, masking and status "
    "parsing both shell families of their engine share"
)

#: What `pods-ready` answers; the script judges. A check retried until pods
#: come up is not a failure each time it says no, so it never ends in an
#: error event and its failure log.
READY = "ready"
NOT_READY = "not ready"

#: Where `fill-placeholder` and `fill-pem` read their value: a credential, a
#: PEM, never a command-line argument.
VALUE_ENV = "_TDD_SMOKE_VALUE"


def _value() -> str:
    if VALUE_ENV not in os.environ:
        raise errors.ToolError(f"no value to fill with: {VALUE_ENV} is not set")
    return os.environ[VALUE_ENV]


def configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", metavar="SUBCOMMAND")

    uv = sub.add_parser(
        "set-uv-index", help="point a tabsdata.yaml's UV_INDEX at a URI"
    )
    uv.add_argument("--file", required=True, help="the tabsdata.yaml")
    uv.add_argument("--uri", required=True, help="the index URL")

    fn = sub.add_parser(
        "set-fn-resources",
        help="size the function pods in a tabsdata.yaml, and only them",
    )
    fn.add_argument("--file", required=True, help="the tabsdata.yaml")
    fn.add_argument("--memory", required=True, help="pods.function.resources.memory")
    fn.add_argument("--disk", required=True, help="pods.function.resources.disk")

    for name, what in (
        ("fill-placeholder", "replace a placeholder in config files, literally"),
        ("fill-pem", "replace a `key: PLACEHOLDER` line with a YAML block scalar"),
    ):
        fill = sub.add_parser(name, help=f"{what}; the value is ${VALUE_ENV}")
        fill.add_argument("--placeholder", required=True, help="e.g. ${{secret:pw}}")
        fill.add_argument("files", nargs="+", metavar="FILE", help="the config files")

    st = sub.add_parser(
        "fill-storage",
        help="the per-mount ${{secret}} of apiserver.storage.yaml, from STORD__* and STORS__*",
    )
    st.add_argument("--file", required=True, help="the apiserver.storage.yaml")
    st.add_argument("--cloud", required=True, choices=configs.CLOUDS)

    left = sub.add_parser(
        "placeholders-left",
        help="fail while a required placeholder remains in DIR/*.yaml",
    )
    left.add_argument("--dir", required=True, help="the configs folder")

    ev = sub.add_parser(
        "event-field",
        help="a list field of the ok event in JSON Lines read from stdin, one per line",
    )
    ev.add_argument("--field", required=True, help="the field, e.g. dirs")

    show = sub.add_parser(
        "display", help="a command line as text, every credential in it masked"
    )
    show.add_argument("words", nargs="*", metavar="WORD", help="the command, after --")

    state = sub.add_parser(
        "instance-state",
        help="running, stopped or missing: what `tdkserver status` read from stdin says",
    )
    state.add_argument("--instance", required=True, help="the instance, for the log")

    ready = sub.add_parser(
        "pods-ready",
        help="ready when every SERVICE has a Running, Ready pod in `tdkserver status` "
        "read from stdin and no pod is in another state; not ready otherwise",
    )
    ready.add_argument("--instance", required=True, help="the instance, for the log")
    ready.add_argument("services", nargs="+", metavar="SERVICE")


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action == "set-uv-index":
        configs.set_uv_index(pathlib.Path(args.file), args.uri)
        return out.ok(f"UV_INDEX: {args.uri}", file=args.file)
    if args.action == "set-fn-resources":
        configs.set_fn_resources(pathlib.Path(args.file), args.memory, args.disk)
        return out.ok(f"function pods: memory {args.memory}, disk {args.disk}")
    if args.action == "fill-placeholder":
        paths = [pathlib.Path(f) for f in args.files]
        hits = configs.fill_placeholder(paths, args.placeholder, _value())
        return out.ok(f"filled {args.placeholder} in {hits} file(s)", files=hits)
    if args.action == "fill-pem":
        paths = [pathlib.Path(f) for f in args.files]
        n = configs.fill_pem(paths, args.placeholder, _value())
        return out.ok(f"filled {args.placeholder} with {n} lines of PEM")
    if args.action == "fill-storage":
        found = configs.fill_storage(pathlib.Path(args.file), args.cloud)
        if found["empty"]:
            out.warn(f"no value for: {', '.join(found['empty'])}")
        if found["unknown"]:
            out.warn(
                f"not filled (unknown to fill-storage): {', '.join(found['unknown'])}"
            )
        return out.ok(f"filled: {', '.join(found['filled']) or '(nothing)'}", **found)
    if args.action == "placeholders-left":
        left = configs.placeholders_left(pathlib.Path(args.dir))
        if left:
            for line in left:
                out.info(f"  {line}")
            return out.error("required placeholders still to fill", left=left)
        return out.ok(f"no required placeholder left in {args.dir}")
    if args.action == "event-field":
        values = configs.event_field(sys.stdin.readlines(), args.field)
        return out.ok("\n".join(values), values=values)
    if args.action == "display":
        return out.ok(display.display(args.words))
    if args.action == "instance-state":
        found = status.state(sys.stdin.read())
        return out.ok(found, instance=args.instance)
    if args.action == "pods-ready":
        return _pods_ready(args.instance, args.services, sys.stdin.read(), out)
    return out.error("no action given (see --help)")


def _pods_ready(
    instance: str, services: list[str], text: str, out: render.Renderer
) -> int:
    listed = status.pods(text)
    if not listed:
        out.info(text.rstrip("\n"))
        out.info(f"no pods listed for instance {instance}")
        return out.ok(NOT_READY, instance=instance)
    out.info("pods:")
    for pod in listed:
        out.info(f"  {pod.name} {pod.status} {pod.ready}")
    missing, bad = status.unready(listed, services)
    if missing:
        out.info(f"no Running, Ready pod for: {' '.join(missing)}")
    if bad:
        out.info(f"pods not Running/Ready: {' '.join(str(p) for p in bad)}")
    if missing or bad:
        return out.ok(NOT_READY, instance=instance, missing=missing)
    out.info(f"every expected service pod is Running and Ready: {' '.join(services)}")
    return out.ok(READY, instance=instance)


def main() -> int:
    return cli.run("_smoke", DESCRIPTION, body, configure=configure)
