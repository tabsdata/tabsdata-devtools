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
import json
import os
import pathlib
import sys

from tabsdata_dev.common.core import cli, errors, render

from . import (
    aks,
    configs,
    display,
    eks,
    forward,
    gke,
    indexes,
    instances,
    screen,
    status,
    workers,
)

DESCRIPTION = (
    "plumbing of the smoke scripts: the config edits, masking and status "
    "parsing both shell families of their engine share"
)

#: What `pods-ready` answers; the script judges. A check retried until pods
#: come up is not a failure each time it says no, so it never ends in an
#: error event and its failure log.
READY = "ready"
NOT_READY = "not ready"
#: What `archived-logs` answers when waiting cannot change its no, so the
#: script stops retrying.
FAILED = "failed"

#: What `gke-has-binding` answers: an absent binding is to be added, not an error.
PRESENT = "present"
ABSENT = "absent"

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

    found = sub.add_parser(
        "instance-pids",
        help="the pids of a local instance's processes, by the folder on their command line",
    )
    found.add_argument("--instance", required=True)

    stop = sub.add_parser(
        "instance-stop",
        help="stop an instance a previous run left running, and wait every process out",
    )
    stop.add_argument("--instance", required=True)
    stop.add_argument(
        "--tdd-dir", required=True, help="where the previous run's tdkserver may be"
    )
    stop.add_argument(
        "options", nargs="*", metavar="OPTION", help="tdkserver stop's own, after --"
    )

    gone = sub.add_parser(
        "instance-gone",
        help="fail while a process of the instance or its folder is left",
    )
    gone.add_argument("--instance", required=True)

    win = sub.add_parser(
        "window",
        help="redraw the last lines a running command wrote to the log, on stderr, "
        "until the stop file exists",
    )
    win.add_argument("--log", required=True)
    win.add_argument(
        "--from", dest="offset", type=int, required=True, help="byte offset"
    )
    win.add_argument("--lines", type=int, required=True)
    win.add_argument("--stop", required=True, help="the file whose creation ends it")
    win.add_argument("--parent", type=int, required=True, help="ends with this pid too")
    win.add_argument("--dim", action="store_true", help="draw the lines dimmed")

    look = sub.add_parser(
        "pointers",
        help="LABEL PATH for each log file a command named in the log since an offset",
    )
    look.add_argument("--log", required=True)
    look.add_argument(
        "--from", dest="offset", type=int, required=True, help="byte offset"
    )

    for name, what in (
        (
            "forward-start",
            "start kubectl port-forward under a supervisor; up once LOCAL answers",
        ),
        ("forward-ensure", "LOCAL answers, or the forward is started afresh"),
        ("forward-stop", "end the forward and its kubectl, if one is up"),
        (forward.SUPERVISE, "the supervisor itself, which forward-start runs"),
    ):
        _forward_options(sub.add_parser(name, help=what))

    page = sub.add_parser(
        "paint-help",
        help="a help page read from stdin, painted; the REQUIRED options red",
    )
    page.add_argument(
        "--required", default="", help="the required options, space separated"
    )
    page.add_argument(
        "--tty",
        action="store_true",
        help="paint as for a terminal: the caller knows, and stdout is its pipe",
    )

    done = sub.add_parser(
        "finished-workers",
        help="the ids of the finished workers in `tdk worker list --format json` "
        "read from stdin, one per line",
    )
    done.add_argument(
        "--max", type=int, default=3, help="at most this many (default: 3)"
    )

    kept = sub.add_parser(
        "archived-logs",
        help="ready when the worker log read from stdin came whole from ARCHIVE "
        "once its pod was gone; not ready while it may still arrive, failed when "
        "waiting cannot change that",
    )
    kept.add_argument("--worker", required=True, help="the worker, for the log")
    kept.add_argument("--archive", required=True, choices=workers.ARCHIVES)
    kept.add_argument(
        "--live",
        help="a file: the worker's log read while its pod was there, which a "
        "cloud archive's must match (required but for pod-runner)",
    )

    ended = sub.add_parser(
        "live-workers",
        help="the WORKERS whose pod in the `kubectl get pods --output json` read "
        "from stdin has ended, one per line: their live log is whole and readable",
    )
    ended.add_argument(
        "--workers", required=True, help="the worker ids, whitespace separated"
    )

    reference = sub.add_parser(
        "live-log",
        help="ready when the worker log read from stdin, read while its pod was "
        "there, ran to the pod's last container; not ready otherwise",
    )
    reference.add_argument("--worker", required=True, help="the worker, for the log")

    left = sub.add_parser(
        "worker-pods-gone",
        help="ready when no pod of WORKERS is left in the `kubectl get pods "
        "--output json` read from stdin; not ready otherwise",
    )
    left.add_argument(
        "--workers", required=True, help="the worker ids, whitespace separated"
    )

    sub.add_parser(
        "eks-cluster",
        help="the EKS cluster and region, `NAME REGION`, of the `kubectl config "
        "view --minify --output json` read from stdin",
    )

    role = sub.add_parser(
        "eks-role-documents",
        help="write the trust and permission policies of an instance's "
        "apiserver role, which reads its worker logs from CloudWatch",
    )
    role.add_argument("--caller-arn", required=True, help="who makes the role")
    role.add_argument("--issuer", required=True, help="the cluster's OIDC issuer")
    role.add_argument("--namespace", required=True, help="the instance's")
    role.add_argument("--region", required=True, help="the cluster's")
    role.add_argument("--trust", required=True, help="the trust policy's file")
    role.add_argument("--permissions", required=True, help="the permissions' file")

    sub.add_parser(
        "gke-cluster",
        help="the GKE project, location and cluster, `PROJECT LOCATION CLUSTER`, "
        "of the `kubectl config view --minify --output json` read from stdin",
    )

    bucket = sub.add_parser(
        "gke-log-bucket",
        help="the bucket the Tabsdata container logs land in, `BUCKET LOCATION`",
    )
    bucket.add_argument(
        "--sinks",
        required=True,
        help="a file: `gcloud logging sinks list --format json`",
    )
    bucket.add_argument(
        "--buckets",
        required=True,
        help="a file: `gcloud logging buckets list --format json`",
    )

    account = sub.add_parser(
        "gke-service-account",
        help="the id of an instance's apiserver Google service account",
    )
    account.add_argument("--namespace", required=True, help="the instance's")

    held = sub.add_parser(
        "gke-has-binding",
        help="present when the IAM policy read from stdin grants ROLE to MEMBER "
        "(under exactly EXPRESSION, if given); absent otherwise",
    )
    held.add_argument("--role", required=True)
    held.add_argument("--member", required=True)
    held.add_argument("--expression", help="the binding's condition")

    aks_cluster = sub.add_parser(
        "aks-cluster",
        help="the AKS cluster of `--clusters` whose API server the `kubectl "
        "config view --minify --output json` read from stdin names: `SUBSCRIPTION "
        "GROUP NAME ISSUER WORKLOAD-IDENTITY WORKSPACE`; nothing when none is",
    )
    aks_cluster.add_argument(
        "--clusters", required=True, help="a file: `az aks list --output json`"
    )

    cond = sub.add_parser(
        "aks-condition",
        help="the role condition limiting Log Analytics Data Reader to the "
        "ContainerLogV2 rows of a namespace",
    )
    cond.add_argument("--namespace", required=True)

    assigned = sub.add_parser(
        "aks-has-assignment",
        help="present (and its id), absent or different: the principal's Log "
        "Analytics Data Reader assignment in the `az role assignment list "
        "--output json` read from stdin, under the namespace's condition",
    )
    assigned.add_argument("--principal", required=True, help="its object id")
    assigned.add_argument("--namespace", required=True)

    index = sub.add_parser(
        "uv-index",
        help="the URL a --uv-index value stands for: @dev, @dev:NAME, "
        "@local[::PORT][:NAME], @prod, a URL; nothing for an unknown @marker",
    )
    index.add_argument("--value", required=True)
    index.add_argument(
        "--no-local",
        action="store_true",
        help="refuse @local: the index goes to a cluster's pods, for which "
        "localhost is themselves",
    )


def _forward_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--kubeconfig", required=True)
    p.add_argument("--namespace", required=True)
    p.add_argument("--service", required=True)
    p.add_argument("--local", type=int, required=True, help="the port tdk logs in to")
    p.add_argument("--remote", type=int, required=True, help="the service's port")
    p.add_argument("--state", required=True, help="where the supervisor's pid is kept")
    p.add_argument("--stop", required=True, help="the file whose creation ends it")
    p.add_argument("--log", required=True, help="the run's log, kubectl's output too")
    p.add_argument("--parent", type=int, required=True, help="the forward ends with it")
    p.add_argument(
        "--steady",
        type=float,
        default=10,
        help="seconds up after which a kubectl exit is a dropped tunnel, relaunched at once",
    )


def _forward(args: argparse.Namespace, out: render.Renderer) -> int:
    target = forward.Forward(
        args.kubeconfig, args.namespace, args.service, args.local, args.remote
    )
    run = forward.Run(
        pathlib.Path(args.state),
        pathlib.Path(args.stop),
        pathlib.Path(args.log),
        args.parent,
        args.steady,
    )
    if args.action == forward.SUPERVISE:
        forward.supervise(target, run)
        return out.ok("supervisor ended")
    if args.action == "forward-stop":
        forward.stop(target, run, out.info)
        return out.ok("no forward")
    act = forward.start if args.action == "forward-start" else forward.ensure
    if not act(target, run, out.info):
        return out.error(f"no port-forward on 127.0.0.1:{args.local}")
    return out.ok(f"127.0.0.1:{args.local} answering")


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action and args.action.startswith("forward-"):
        return _forward(args, out)
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
    if args.action == "instance-pids":
        pids = instances.pids(args.instance)
        return out.ok(" ".join(map(str, pids)), pids=pids)
    if args.action == "instance-stop":
        tdd_dir = pathlib.Path(args.tdd_dir)
        if not instances.stop(args.instance, tdd_dir, args.options, out.info):
            return out.error(f"instance {args.instance} still has processes")
        return out.ok(f"no process of instance {args.instance} left")
    if args.action == "instance-gone":
        if not instances.gone(args.instance, out.info):
            return out.error(f"instance {args.instance} is not gone")
        return out.ok(f"instance {args.instance} is gone")
    if args.action == "window":
        dim = (screen.DIM, render.RESET) if args.dim else ("", "")
        screen.window(
            pathlib.Path(args.log),
            args.offset,
            args.lines,
            pathlib.Path(args.stop),
            args.parent,
            out.live,
            dim,
        )
        return out.ok("window closed")
    if args.action == "pointers":
        found = screen.pointers(
            screen.written_since(pathlib.Path(args.log), args.offset)
        )
        return out.ok("\n".join(found), pointers=found)
    if args.action == "paint-help":
        text = sys.stdin.read().removesuffix("\n")
        required = set(args.required.split())
        tty = args.tty or sys.stdout.isatty()
        return out.ok(screen.paint_help(text, required, tty))
    if args.action == "finished-workers":
        ids = workers.finished(sys.stdin.read())[: args.max]
        return out.ok("\n".join(ids), workers=ids)
    if args.action == "archived-logs":
        live = pathlib.Path(args.live).read_text() if args.live else None
        return _archived_logs(args.worker, args.archive, sys.stdin.read(), live, out)
    if args.action == "live-workers":
        ended = workers.terminal(sys.stdin.read(), args.workers.split())
        return out.ok("\n".join(ended), workers=ended)
    if args.action == "live-log":
        found = workers.live_problems(sys.stdin.read())
        for problem in found:
            out.info(f"worker {args.worker}: {problem}")
        if found:
            return out.ok(NOT_READY, worker=args.worker, problems=found)
        return out.ok(READY, worker=args.worker)
    if args.action == "worker-pods-gone":
        left = workers.pods_left(sys.stdin.read(), args.workers.split())
        if left:
            out.info(f"pods of the workers still there: {' '.join(left)}")
            return out.ok(NOT_READY, pods=left)
        out.info(f"no pod left of: {args.workers}")
        return out.ok(READY, pods=left)
    if args.action == "eks-cluster":
        try:
            name, region = eks.cluster(sys.stdin.read())
        except ValueError as e:
            raise errors.ToolError(str(e)) from e
        return out.ok(f"{name} {region}", cluster=name, region=region)
    if args.action == "eks-role-documents":
        try:
            trust, permissions = eks.role_documents(
                args.caller_arn, args.issuer, args.namespace, args.region
            )
        except ValueError as e:
            raise errors.ToolError(str(e)) from e
        pathlib.Path(args.trust).write_text(json.dumps(trust, indent=2) + "\n")
        pathlib.Path(args.permissions).write_text(
            json.dumps(permissions, indent=2) + "\n"
        )
        return out.ok(f"{args.trust} {args.permissions}")
    if args.action == "gke-cluster":
        try:
            project, location, name = gke.cluster(sys.stdin.read())
        except ValueError as e:
            raise errors.ToolError(str(e)) from e
        return out.ok(
            f"{project} {location} {name}",
            project=project,
            location=location,
            cluster=name,
        )
    if args.action == "gke-log-bucket":
        name, location = gke.log_bucket(
            pathlib.Path(args.sinks).read_text(),
            pathlib.Path(args.buckets).read_text(),
        )
        return out.ok(f"{name} {location}", bucket=name, location=location)
    if args.action == "gke-service-account":
        return out.ok(gke.service_account(args.namespace))
    if args.action == "gke-has-binding":
        present = gke.has_binding(
            sys.stdin.read(), args.role, args.member, args.expression
        )
        return out.ok(PRESENT if present else ABSENT, present=present)
    if args.action == "aks-cluster":
        try:
            found = aks.cluster(
                sys.stdin.read(), pathlib.Path(args.clusters).read_text()
            )
        except ValueError as e:
            raise errors.ToolError(str(e)) from e
        return out.ok(" ".join(found) if found else "", cluster=found)
    if args.action == "aks-condition":
        return out.ok(aks.condition(args.namespace))
    if args.action == "aks-has-assignment":
        state, assignment = aks.assignment(
            sys.stdin.read(), args.principal, args.namespace
        )
        return out.ok(f"{state} {assignment}".strip(), state=state, id=assignment)
    if args.action == "uv-index":
        if args.no_local and indexes.is_local(args.value):
            return out.error(
                f"--uv-index {args.value}: @local is not for a cluster run -- the "
                "index goes to the pods, for which localhost is themselves; serve "
                "it from a namespace instead (tdd pypi push --at NAME, @dev:NAME)"
            )
        url = indexes.resolve(args.value)
        return out.ok(url or "", known=url is not None)
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


def _archived_logs(
    worker: str, archive: str, text: str, live: str | None, out: render.Renderer
) -> int:
    held = workers.containers(text, archive)
    try:
        verdict = workers.judge(text, archive, live)
    except ValueError as e:
        raise errors.ToolError(str(e)) from e
    out.info(f"worker {worker}: containers {' '.join(held) or '(none)'}")
    if verdict.problems:
        for problem in verdict.problems:
            out.info(f"  {problem}")
        if verdict.lasting:
            out.info(f"worker {worker}: waiting cannot change this")
        answer = FAILED if verdict.lasting else NOT_READY
        return out.ok(answer, worker=worker, problems=verdict.problems)
    said = "the live log, line for line" if live is not None else "its whole log"
    out.info(f"worker {worker}: {said}, from the {archive} archive")
    return out.ok(READY, worker=worker, containers=held)


def main() -> int:
    return cli.run("_smoke", DESCRIPTION, body, configure=configure)
