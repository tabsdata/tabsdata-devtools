#
# Copyright 2026 Tabsdata Inc.
#

"""Shared fixtures: synthetic wheels, a temp workspace, and a fake S3 client."""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tabsdata_dev.tool.pypi.model import Dist


def build_wheel(
    directory: Path,
    name: str = "tabsdata",
    version: str = "0.9.6",
    tag: str = "cp311-cp311-manylinux_2_28_x86_64",
    requires_python: str | None = ">=3.10",
    payload: bytes = b"x" * 1024,
) -> Path:
    """A wheel real enough that pip and uv will resolve *and install* it.

    RECORD and a tagged WHEEL matter: without them resolution still succeeds but
    installation fails, which would make a smoke test look like an index bug.
    """
    filename = f"{name}-{version}-{tag}.whl"
    path = directory / filename
    directory.mkdir(parents=True, exist_ok=True)

    lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
    ]
    if requires_python:
        lines.append(f"Requires-Python: {requires_python}")
    metadata = "\n".join(lines) + "\n\nA test distribution.\n"

    dist_info = f"{name}-{version}.dist-info"
    wheel = (
        "Wheel-Version: 1.0\n"
        "Generator: tdd pypi-tests\n"
        "Root-Is-Purelib: false\n"
        f"Tag: {tag}\n"
    )
    members = {
        f"{name}/__init__.py": b"",
        f"{name}/_payload.bin": payload,
        f"{dist_info}/METADATA": metadata.encode(),
        f"{dist_info}/WHEEL": wheel.encode(),
    }

    def record_line(member: str, body: bytes) -> str:
        digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest())
        return f"{member},sha256={digest.decode().rstrip('=')},{len(body)}"

    record = "\n".join(record_line(m, b) for m, b in members.items())
    record += f"\n{dist_info}/RECORD,,\n"

    with zipfile.ZipFile(path, "w") as zf:
        for member, body in members.items():
            zf.writestr(member, body)
        zf.writestr(f"{dist_info}/RECORD", record)
    return path


def write_manifest(version_dir: Path, names: list[str] | None = None) -> Path:
    if names is None:
        names = sorted(p.name for p in version_dir.glob("*.whl"))
    path = version_dir / "MANIFEST"
    path.write_text("\n".join(names) + "\n")
    return path


#: This package's test resources: src/resources/test/<test module>/.
RESOURCES = Path(__file__).parents[2] / "resources" / "test"


@pytest.fixture
def resource_folder(request) -> Path:
    """src/resources/test/<test module>/: the files of the requesting module."""
    return RESOURCES / request.path.stem


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "raw-wheels").mkdir()
    (tmp_path / "pypi-wheels").mkdir()
    return tmp_path


@pytest.fixture
def raw(workspace: Path) -> Path:
    return workspace / "raw-wheels"


@pytest.fixture
def tree(workspace: Path) -> Path:
    """The root under which the lane trees live: pypi-wheels/{staging,prod}/."""
    return workspace / "pypi-wheels"


@pytest.fixture
def staging(tree: Path) -> Path:
    return tree / "staging"


@pytest.fixture
def prod(tree: Path) -> Path:
    return tree / "prod"


def make_dist(
    version: str = "0.9.6",
    tag: str = "cp311-cp311-manylinux_2_28_x86_64",
    project: str = "tabsdata",
    yanked: str | None = None,
    requires_python: str | None = ">=3.10",
) -> Dist:
    filename = f"{project}-{version}-{tag}.whl"
    return Dist(
        filename=filename,
        release=version,
        project=project,
        version=version,
        sha256=hashlib.sha256(filename.encode()).hexdigest(),
        size=1234,
        requires_python=requires_python,
        core_metadata_sha256="ab" * 32,
        added_at="2026-08-12T10:00:00Z",
        yanked=yanked,
    )


class FakePaginator:
    def __init__(self, objects: dict[str, tuple[str, int]]):
        self._objects = objects

    def paginate(self, **kwargs):
        prefix = kwargs.get("Prefix", "")
        contents = [
            {"Key": k, "ETag": f'"{etag}"', "Size": size}
            for k, (etag, size) in sorted(self._objects.items())
            if k.startswith(prefix)
        ]
        # two pages, to exercise pagination
        mid = len(contents) // 2
        yield {"Contents": contents[:mid]}
        yield {"Contents": contents[mid:]}


class FakeS3:
    """Just enough S3 for plan/report/execute."""

    def __init__(self, objects=None, sse: str = "AES256", versioned: bool = True):
        self.objects: dict[str, tuple[str, int]] = dict(objects or {})
        self.bodies: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.heads: list[str] = []
        self.sse = sse
        self.versioned = versioned
        self.puts: list[dict] = []
        self.gets: list[str] = []
        self.deletes: list[str] = []
        self.invalidations: list[dict] = []

    def get_paginator(self, _name):
        return FakePaginator(self.objects)

    def get_bucket_encryption(self, Bucket):
        rule = {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": self.sse}}
        return {"ServerSideEncryptionConfiguration": {"Rules": [rule]}}

    def get_bucket_versioning(self, Bucket):
        return {"Status": "Enabled"} if self.versioned else {}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        body = kwargs["Body"]
        self.objects[kwargs["Key"]] = (hashlib.md5(body).hexdigest(), len(body))
        self.bodies[kwargs["Key"]] = body
        self.metadata[kwargs["Key"]] = dict(kwargs.get("Metadata") or {})
        return {}

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        if Key not in self.objects:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
            )
        etag, size = self.objects[Key]
        return {
            "ETag": f'"{etag}"',
            "ContentLength": size,
            "LastModified": datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
            "Metadata": dict(self.metadata.get(Key, {})),
        }

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        return {"Body": io.BytesIO(self.bodies[Key])}

    def download_file(self, Bucket, Key, Filename):
        self.gets.append(Key)
        Path(Filename).write_bytes(self.bodies[Key])

    def delete_object(self, Bucket, Key):
        self.deletes.append(Key)
        self.objects.pop(Key, None)
        self.bodies.pop(Key, None)
        self.metadata.pop(Key, None)
        return {}

    def create_invalidation(self, **kwargs):
        self.invalidations.append(kwargs)
        return {"Invalidation": {"Id": "I000", "Status": "InProgress"}}


def make_lane(name: str = "staging", base_path: str = "pypi"):
    from tabsdata_dev.tool.pypi.config import POLICY, Lane

    return Lane(
        name=name,
        bucket=f"td-pypi-{name}",
        base_path=base_path,
        distribution="EXXXX",
        vanilla_domain="dxxxx.cloudfront.net",
        domain=f"pypi-{name}.tabsdata.com",
        policy=POLICY[name],
    )


def make_cfg(base_path: str = "pypi"):
    from tabsdata_dev.tool.pypi.config import Archive, Config

    return Config(
        account="123456789012",
        region="us-east-1",
        release_ref="origin/main",
        archive=Archive(bucket="td-raw-wheels", base_path="wheels"),
        lanes={
            "staging": make_lane("staging", base_path),
            "prod": make_lane("prod", base_path),
        },
    )


def release(raw: Path, version: str = "0.9.6", tags=None, payload: bytes | None = None):
    """A raw-wheels/<version>/ with one wheel per tag and a MANIFEST."""
    tags = tags or ["cp311-cp311-manylinux_2_28_x86_64"]
    d = raw / version
    for tag in tags:
        build_wheel(
            d, version=version, tag=tag, payload=payload or (version.encode() * 300)
        )
    write_manifest(d)
    return d


# --------------------------------------------------------------- the renderer


#: The command layer hands every function a Renderer; the tests do the same.
#: Events go to a StringIO rather than the terminal, so a test can assert on
#: what was said without a run being a wall of output.
class Events:
    """A Renderer writing into memory, plus what it wrote."""

    def __init__(self):
        from tabsdata_dev.common.core.render import Renderer

        self.out_buf, self.err_buf = io.StringIO(), io.StringIO()
        self.renderer = Renderer(
            "pypi", fmt="view", verbose=True, out=self.out_buf, err=self.err_buf
        )

    @property
    def text(self) -> str:
        return self.out_buf.getvalue() + self.err_buf.getvalue()

    def said(self, needle: str) -> bool:
        return needle in self.text


@pytest.fixture
def events() -> Events:
    return Events()


@pytest.fixture
def out(events: Events):
    """The Renderer itself -- what almost every test needs."""
    return events.renderer


@pytest.fixture(autouse=True)
def _no_repo_guard(monkeypatch, request):
    """The guard belongs to the command layer, and every test here runs in a
    tmp_path rather than a clone of pypi-repo, so it is patched out of the way.

    A module that marks itself `real_repo_guard` gets the real one -- which is
    how test_repo.py can test it at all."""
    if request.node.get_closest_marker("real_repo_guard"):
        return
    from tabsdata_dev.tool.pypi import repo

    monkeypatch.setattr(repo, "require_root", lambda _url: Path.cwd())


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_repo_guard: do not patch repo.require_root out"
    )
