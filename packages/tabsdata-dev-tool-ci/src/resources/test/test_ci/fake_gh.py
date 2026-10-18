#
# Copyright 2026 Tabsdata Inc.
#
"""Stands in for `gh`: answers the three calls `tdd ci download` makes from
the JSON state in $FAKE_GH_STATE, and appends every call to $FAKE_GH_LOG."""

import io
import json
import os
import pathlib
import sys
import tarfile
import zipfile


def runs(state: dict, endpoint: str) -> None:
    """repos/O/R/actions/runs?per_page=P&page=N, newest first, as the jq wants."""
    query = dict(kv.split("=") for kv in endpoint.split("?")[1].split("&"))
    size, page = int(query["per_page"]), int(query["page"])
    for run in state["runs"][(page - 1) * size : page * size]:
        listed = {
            "id": run["databaseId"],
            "run_number": run["number"],
            "name": run["workflowName"],
            "path": ".github/workflows/" + run["workflowName"] + ".yml",
        }
        print(json.dumps(listed))


def packed(name: str) -> bytes:
    """Every packed artifact ships the same archive name, as each assembly of a
    release run ships tabsdata-assembly-devpi.tar.gz; the tar has no top-level
    dir."""
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w:gz") as archive:
        for member in (name + ".whl", "logs/" + name + ".log"):
            data = name.encode()
            info = tarfile.TarInfo(member)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return tar.getvalue()


def artifact_zip(state: dict, endpoint: str) -> None:
    """repos/O/R/actions/artifacts/<id>/zip: the artifact, zipped, on stdout."""
    art_id = int(endpoint.split("/")[-2])
    name = next(a["name"] for a in state["artifacts"] if a["id"] == art_id)
    if name in state.get("broken", []):
        sys.exit("error downloading " + name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if name.startswith("packed"):
            zf.writestr("bundle.tar.gz", packed(name))
        elif name.startswith("clash"):
            zf.writestr("shared.txt", name)
        else:
            zf.writestr(name + ".txt", name)
    sys.stdout.buffer.write(buf.getvalue())


def main() -> None:
    state = json.loads(pathlib.Path(os.environ["FAKE_GH_STATE"]).read_text())
    args = sys.argv[1:]
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(json.dumps(args) + "\n")
    if args[0] == "api" and "/actions/runs?" in args[1]:
        runs(state, args[1])
    elif args[0] == "api" and args[1].endswith("/zip"):
        artifact_zip(state, args[1])
    elif args[0] == "api":
        for artifact in state["artifacts"]:
            print(json.dumps(artifact))
    else:
        sys.exit("unexpected: " + " ".join(args))


main()
