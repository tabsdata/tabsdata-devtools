#
# Copyright 2026 Tabsdata Inc.
#

"""postgresnative and postgresnativepgvector: the binaries they pick for a
machine, how the latter installs pgvector into a system's own tree, the
configuration they write, and the pgvector types' (postgrespgvector too)
``domain create --pgvector`` -- nothing that downloads or starts a server."""

import hashlib
import io
import json
import tarfile
import urllib.error
import zipfile
from typing import ClassVar

import pytest
from tabsdata_dev.common.systems import descriptor, dispatch, manifest, store, systems
from tabsdata_dev.common.systems.cli import UsageError
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.systems._common.commands import sys_create
from tabsdata_dev.common.systems.systems._common.hosting.native import download
from tabsdata_dev.common.systems.systems.postgresnative import backend as native
from tabsdata_dev.common.systems.systems.postgresnative import binaries

SLUG = "postgresnative"
SLUG_PGVECTOR = "postgresnativepgvector"
#: The types with pgvector installed, and so with `domain create --pgvector`.
PGVECTOR_SLUGS = ("postgrespgvector", SLUG_PGVECTOR)
#: The types without it, whose `domain create` is the shared one.
PLAIN_SLUGS = ("postgres", "postgrescdc", SLUG)


@pytest.fixture
def tdd_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TDD_DIR", str(tmp_path / "tdd"))
    monkeypatch.setattr(binaries, "cache_directory", lambda: tmp_path / "cache")
    return tmp_path / "tdd"


def _tar(path, files: dict[str, bytes]):
    with tarfile.open(path, "w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return path


def _zip(path, files: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


# ---- which binaries -------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "machine", "libc", "triple"),
    [
        ("Darwin", "arm64", "", "aarch64-apple-darwin"),
        ("Darwin", "x86_64", "", "x86_64-apple-darwin"),
        ("Linux", "x86_64", "glibc", "x86_64-unknown-linux-gnu"),
        ("Linux", "aarch64", "glibc", "aarch64-unknown-linux-gnu"),
        ("Linux", "x86_64", "", "x86_64-unknown-linux-musl"),
        ("Windows", "AMD64", "", "x86_64-pc-windows-msvc"),
    ],
)
def test_the_target_triple_names_theseus_archives_for_each_platform(
    system, machine, libc, triple
):
    assert binaries.target_triple(system, machine, libc) == triple


def test_a_platform_theseus_does_not_build_for_is_refused():
    for system, machine in (("Windows", "ARM64"), ("Linux", "riscv64")):
        with pytest.raises(TdxError, match="no PostgreSQL build"):
            binaries.target_triple(system, machine, "glibc")


def test_the_version_is_tabsdata_os_pin_unless_its_override_is_set(monkeypatch):
    monkeypatch.delenv(binaries.ENV_VERSION, raising=False)
    assert binaries.resolve_version() == binaries.PINNED_VERSION == "18.6.0"
    monkeypatch.setenv(binaries.ENV_VERSION, "17.9.0")
    assert binaries.resolve_version() == "17.9.0"
    assert binaries.major_of("17.9.0") == "17"


def test_a_bottle_is_the_one_for_the_platform_and_the_oldest_macos(resource_folder):
    index = json.loads((resource_folder / "pgvector-0.8.6-index.json").read_text())
    digest = {
        m["annotations"]["org.opencontainers.image.ref.name"]: m["annotations"][
            "sh.brew.bottle.digest"
        ]
        for m in index["manifests"]
    }
    pick = binaries.select_bottle
    # sonoma (14) over sequoia (15), tahoe (26) and golden gate (27)
    assert pick(index, "0.8.6", "aarch64-apple-darwin") == digest["0.8.6.arm64_sonoma"]
    assert pick(index, "0.8.6", "x86_64-apple-darwin") == digest["0.8.6.sonoma"]
    # Homebrew's Linux bottle wants glibc 2.38: Linux takes PGDG's package
    with pytest.raises(TdxError, match="macOS only"):
        pick(index, "0.8.6", "x86_64-unknown-linux-gnu")
    with pytest.raises(TdxError, match="no pgvector 0.8.6 bottle"):
        pick({"manifests": []}, "0.8.6", "aarch64-apple-darwin")


def test_archives_are_fetched_into_the_shared_cache_once(tdd_dir, monkeypatch):
    """theseus's archive is checked against the checksum published beside it;
    a bottle against the digest it is named by, and only for a system that
    installs pgvector; a cached file is used as is."""
    reads, fetches = [], []
    index = {
        "manifests": [
            {
                "platform": {"os": "darwin", "architecture": "arm64"},
                "annotations": {"sh.brew.bottle.digest": "ab12"},
            }
        ]
    }

    def read(url, *, what, headers=None):
        reads.append(url)
        if url.endswith(".sha256"):
            return b"CAFE  postgresql-18.6.0-aarch64-apple-darwin.tar.gz\n"
        assert headers["Accept"] == binaries.OCI_INDEX
        return json.dumps(index).encode()

    def fetch(url, destination, *, what, headers=None, sha256=""):
        fetches.append((url, destination.name, sha256))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"x")
        return destination

    monkeypatch.setattr(download, "read", read)
    monkeypatch.setattr(download, "fetch", fetch)
    target = "aarch64-apple-darwin"
    _, vector = binaries.fetch_all("18.6.0", target, pgvector=False)
    assert vector is None
    assert fetches == [
        (
            (
                "https://github.com/theseus-rs/postgresql-binaries/releases/download/"
                "18.6.0/postgresql-18.6.0-aarch64-apple-darwin.tar.gz"
            ),
            "postgresql-18.6.0-aarch64-apple-darwin.tar.gz",
            "CAFE",
        ),
    ]
    fetches.clear()
    binaries.fetch_all("18.6.0", target, pgvector=True)
    assert fetches == [
        (
            "https://ghcr.io/v2/homebrew/core/pgvector/blobs/sha256:ab12",
            "pgvector-0.8.6-aarch64-apple-darwin.bottle.tar.gz",
            "ab12",
        ),
    ]
    assert reads[1] == "https://ghcr.io/v2/homebrew/core/pgvector/manifests/0.8.6"
    # cached now: nothing is read or fetched again
    reads.clear(), fetches.clear()
    binaries.fetch_all("18.6.0", target, pgvector=True)
    assert reads == [] and fetches == []


def test_windows_and_linux_pgvector_come_from_their_builds_for_the_major(
    tdd_dir, monkeypatch
):
    fetched = []

    def fetch(url, destination, *, what, headers=None, sha256=""):
        fetched.append((url, destination.name))
        return destination

    monkeypatch.setattr(download, "fetch", fetch)
    binaries.pgvector_archive("0.8.6", "18", "x86_64-pc-windows-msvc")
    binaries.pgvector_archive("0.8.6", "18", "aarch64-unknown-linux-gnu")
    pool = "https://apt.postgresql.org/pub/repos/apt/pool/main/p/pgvector/"
    assert fetched == [
        (
            (
                "https://github.com/andreiramani/pgvector_pgsql_windows/releases/"
                "download/0.8.6_18/vector.v0.8.6-pg18.zip"
            ),
            "pgvector-0.8.6-pg18-x86_64-pc-windows-msvc.zip",
        ),
        (
            pool + "postgresql-18-pgvector_0.8.6-1.pgdg22.04%2B2_arm64.deb",
            "pgvector-0.8.6-pg18-aarch64-unknown-linux-gnu.deb",
        ),
    ]
    with pytest.raises(TdxError, match="no pgvector build is published"):
        binaries.pgvector_archive("0.8.6", "18", "x86_64-unknown-linux-musl")


# ---- into the system's own tree --------------------------------------------


def test_the_postgresql_archive_becomes_the_tree(tmp_path):
    archive = _tar(
        tmp_path / "pg.tar.gz",
        {"postgresql-18.6.0-x/bin/postgres": b"#", "postgresql-18.6.0-x/lib/a": b"#"},
    )
    tree = tmp_path / "sys" / "postgresql"
    binaries.expand_postgresql(archive, tree)
    assert (tree / "bin" / "postgres").is_file() and (tree / "lib" / "a").is_file()
    assert [p.name for p in tree.parent.iterdir()] == ["postgresql"]


def test_an_archive_that_is_not_one_tree_leaves_nothing_behind(tmp_path):
    archive = _tar(tmp_path / "pg.tar.gz", {"a/bin/x": b"#", "b/bin/y": b"#"})
    tree = tmp_path / "sys" / "postgresql"
    with pytest.raises(TdxError, match="not a PostgreSQL tree"):
        binaries.expand_postgresql(archive, tree)
    assert list(tree.parent.iterdir()) == []


def test_a_bottle_installs_the_build_for_the_servers_major(tmp_path):
    bottle = _tar(
        tmp_path / "pgvector-0.8.6-t.bottle.tar.gz",
        {
            "pgvector/0.8.6/lib/postgresql@17/vector.dylib": b"seventeen",
            "pgvector/0.8.6/lib/postgresql@18/vector.dylib": b"eighteen",
            "pgvector/0.8.6/share/postgresql@17/extension/vector.control": b"c17",
            "pgvector/0.8.6/share/postgresql@18/extension/vector.control": b"c18",
            "pgvector/0.8.6/share/postgresql@18/extension/vector--0.8.6.sql": b"s",
            "pgvector/0.8.6/include/postgresql@18/server/extension/vector/v.h": b"h",
            "pgvector/0.8.6/README.md": b"r",
        },
    )
    tree = tmp_path / "postgresql"
    binaries.install_pgvector(bottle, "18", tree)
    assert (tree / "lib" / "vector.dylib").read_bytes() == b"eighteen"
    ext = tree / "share" / "extension"
    assert sorted(p.name for p in ext.iterdir()) == [
        "vector--0.8.6.sql",
        "vector.control",
    ]
    assert (ext / "vector.control").read_bytes() == b"c18"
    assert sorted(p.name for p in tree.iterdir()) == ["lib", "share"]
    with pytest.raises(TdxError, match="no pgvector build for PostgreSQL 16"):
        binaries.install_pgvector(bottle, "16", tmp_path / "other")


def _deb(path, files: dict[str, bytes]):
    """A Debian package: an ar archive holding data.tar.xz among its members."""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:xz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    out = bytearray(b"!<arch>\n")
    for name, content in (
        ("debian-binary", b"2.0\n"),
        ("control.tar.xz", b"ctl"),
        ("data.tar.xz", data.getvalue()),
    ):
        out += f"{name:<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(content):<10}`\n".encode()
        out += content + (b"\n" if len(content) % 2 else b"")
    path.write_bytes(bytes(out))
    return path


def test_a_debian_package_installs_its_build_and_nothing_else(tmp_path):
    deb = _deb(
        tmp_path / "pgvector-0.8.6-pg18-x.deb",
        {
            "./usr/lib/postgresql/18/lib/vector.so": b"so",
            "./usr/lib/postgresql/18/lib/bitcode/vector/src/hnsw.bc": b"bc",
            "./usr/share/postgresql/18/extension/vector.control": b"c",
            "./usr/share/postgresql/18/extension/vector--0.8.6.sql": b"s",
            "./usr/include/postgresql/18/server/extension/vector/vector.h": b"h",
            "./usr/share/doc/postgresql-18-pgvector/copyright": b"d",
        },
    )
    tree = tmp_path / "postgresql"
    binaries.install_pgvector(deb, "18", tree)
    assert [p.name for p in (tree / "lib").iterdir()] == ["vector.so"]
    assert sorted(p.name for p in (tree / "share" / "extension").iterdir()) == [
        "vector--0.8.6.sql",
        "vector.control",
    ]
    with pytest.raises(TdxError, match="no ar signature"):
        binaries.deb_data(b"PK\x03\x04")


def test_a_windows_zip_installs_by_bare_name_whatever_its_paths_say(tmp_path):
    archive = _zip(
        tmp_path / "pgvector-0.8.6-pg18-w.zip",
        {
            "lib/vector.dll": b"dll",
            "share/extension/vector.control": b"c",
            "../../escape/vector--0.8.6.sql": b"s",
            "readme.txt": b"r",
        },
    )
    tree = tmp_path / "t" / "postgresql"
    binaries.install_pgvector(archive, "18", tree)
    assert (tree / "lib" / "vector.dll").read_bytes() == b"dll"
    assert (tree / "share" / "extension" / "vector--0.8.6.sql").read_bytes() == b"s"
    assert not (tmp_path / "escape").exists()


# ---- downloading ---------------------------------------------------------


class _Response(io.BytesIO):
    headers: ClassVar[dict] = {}


def test_a_missing_asset_fails_at_once_with_the_curl_that_reproduces_it(
    tmp_path, monkeypatch
):
    calls = []

    def missing(url, headers):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(download, "_open", missing)
    monkeypatch.setattr(download.time, "sleep", lambda s: pytest.fail("retried"))
    with pytest.raises(TdxError, match="404") as err:
        download.fetch("https://h/x.tar.gz", tmp_path / "x.tar.gz", what="x")
    assert calls == ["https://h/x.tar.gz"]
    assert (
        "curl --fail" in err.value.details and "https://h/x.tar.gz" in err.value.details
    )
    assert list(tmp_path.iterdir()) == []


def test_a_download_lands_only_when_its_checksum_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_open", lambda url, headers: _Response(b"bytes"))
    dest = tmp_path / "a.tar.gz"
    with pytest.raises(TdxError, match="does not match its checksum"):
        download.fetch("https://h/a", dest, what="a", sha256="00")
    assert list(tmp_path.iterdir()) == []
    good = hashlib.sha256(b"bytes").hexdigest()
    assert download.fetch("https://h/a", dest, what="a", sha256=good) == dest
    assert dest.read_bytes() == b"bytes" and [p.name for p in tmp_path.iterdir()] == [
        "a.tar.gz"
    ]


# ---- the system ------------------------------------------------------------


def test_a_system_lives_in_its_own_directory_on_its_types_port_slot(tdd_dir):
    b = systems.get(SLUG)
    meta = b.plan_system("pn1", {})
    assert meta["NATIVE_DIR"] == str(tdd_dir / "data" / "system-native" / "pn1")
    assert 23200 <= int(meta["PORT"]) <= 23299
    assert meta["EXTERNAL_HOST"] == meta["INTERNAL_HOST"] == "127.0.0.1"
    assert "PGVECTOR_VERSION" not in meta
    assert meta["DATABASE"] == "postgres" and meta["USER"] == "postgres"
    assert not b.listens_everywhere(meta)
    b.use_hostname("box.example")
    assert b.listens_everywhere(b.plan_system("pn2", {"PORT": "23250"}))


def test_a_pgvector_system_records_the_pgvector_its_tree_carries(tdd_dir):
    meta = systems.get(SLUG_PGVECTOR).plan_system("pv1", {})
    assert meta["NATIVE_DIR"] == str(tdd_dir / "data" / "system-native" / "pv1")
    assert 23400 <= int(meta["PORT"]) <= 23499
    assert meta["PGVECTOR_VERSION"] == binaries.PGVECTOR_VERSION


def test_only_a_pgvector_system_installs_it_in_its_tree(tdd_dir, monkeypatch):
    built = []
    monkeypatch.setattr(
        binaries,
        "build_tree",
        lambda version, target, tree, *, pgvector: built.append(pgvector),
    )
    for slug in (SLUG, SLUG_PGVECTOR):
        b = systems.get(slug)
        for step in ("_initdb", "_configure", "_start"):
            monkeypatch.setattr(b, step, lambda *args: None)
        monkeypatch.setattr(b, "_probe_version", lambda meta: "18.6")
        b.provision_system(b.plan_system(slug, {}))
    assert built == [False, True]


def test_its_capabilities_are_a_run_systems_without_a_container():
    cls = systems.get_class(SLUG)
    assert (cls.hosting, cls.nature) == ("native", "sql_database")
    assert cls.supports_restart and cls.fetches_binaries and cls.advertises_host
    assert not cls.is_container
    verbs = dispatch._system_verbs("system", SLUG)
    assert {"restart", "fetch-bin", "purge"} <= set(verbs)
    assert "connect" not in verbs
    # every container type still restarts; an attached one never did
    assert systems.get_class("postgres").supports_restart
    assert not systems.get_class("awspostgres").supports_restart


def test_sys_hostname_binds_on_a_native_system(monkeypatch):
    b = systems.get(SLUG)
    assert sys_create._bind_hostname(b, "box.example") == "box.example"
    assert b.hostname == "box.example"


@pytest.mark.parametrize("everywhere", [False, True])
def test_the_configuration_is_tdd_conf_included_and_a_pg_hba_of_its_own(
    tmp_path, everywhere
):
    b = systems.get(SLUG)
    root = tmp_path / "pn"
    (root / "data").mkdir(parents=True)
    (root / "data" / "postgresql.conf").write_text("# initdb's\n")
    host = "box.example" if everywhere else "127.0.0.1"
    b._configure(root, {"PORT": "23201", "EXTERNAL_HOST": host})
    conf = (root / "data" / "postgresql.conf").read_text()
    assert conf.startswith("# initdb's\n") and conf.endswith("include = 'tdd.conf'\n")
    tdd = (root / "data" / "tdd.conf").read_text()
    assert "port = 23201\n" in tdd and "unix_socket_directories = ''\n" in tdd
    assert "max_connections = 500\n" in tdd
    assert "max_locks_per_transaction = 1024\n" in tdd
    assert f"listen_addresses = '{'*' if everywhere else 'localhost'}'" in tdd
    hba = (root / "data" / "pg_hba.conf").read_text()
    assert "Copyright" not in hba + tdd
    lines = [line.split() for line in hba.splitlines() if not line.startswith("#")]
    assert ["host", "all", "all", "127.0.0.1/32", "scram-sha-256"] in lines
    assert (["host", "all", "all", "all", "scram-sha-256"] in lines) is everywhere
    assert all(line[-1] == "scram-sha-256" for line in lines if line)


def test_the_container_and_native_server_boot_with_the_same_settings():
    from tabsdata_dev.common.systems.systems.postgres.backend import (
        SERVER_SETTINGS,
        Postgres,
    )

    assert Postgres.cmd_args == [
        "-c",
        "max_connections=500",
        "-c",
        "max_locks_per_transaction=1024",
    ]
    assert SERVER_SETTINGS == {
        "max_connections": "500",
        "max_locks_per_transaction": "1024",
    }


def test_an_existing_directory_is_kept_unless_forced(tdd_dir, monkeypatch):
    b = systems.get(SLUG)
    meta = b.plan_system("pn", {"PORT": "23210"})
    root = tdd_dir / "data" / "system-native" / "pn"
    (root / "data").mkdir(parents=True)
    with pytest.raises(TdxError, match="already exists"):
        b.provision_system(meta)
    steps = []
    monkeypatch.setattr(b, "_stop", lambda r: steps.append(("stop", r)))
    monkeypatch.setattr(
        binaries,
        "build_tree",
        lambda v, t, tree, *, pgvector: steps.append(("tree", tree)),
    )
    monkeypatch.setattr(
        b, "_initdb", lambda r, m, major: steps.append(("initdb", major))
    )
    monkeypatch.setattr(b, "_configure", lambda r, m: steps.append(("configure", r)))
    monkeypatch.setattr(b, "_start", lambda r: steps.append(("start", r)))
    monkeypatch.setattr(b, "_probe_version", lambda m: "18.6")
    assert b.provision_system(meta, force=True) == {"VERSION": "18.6"}
    assert steps == [
        ("stop", root),
        ("tree", root / "postgresql"),
        ("initdb", "18"),
        ("configure", root),
        ("start", root),
    ]
    assert not (root / "data").exists()  # the old cluster went with --force


def test_destroy_stops_the_server_and_removes_its_directory(tdd_dir, monkeypatch):
    b = systems.get(SLUG)
    meta = b.plan_system("pn", {"PORT": "23211"})
    root = tdd_dir / "data" / "system-native" / "pn"
    with pytest.raises(TdxError, match="does not exist"):
        b.destroy_system(meta)
    (root / "postgresql" / "bin").mkdir(parents=True)
    ro = root / "postgresql" / "bin" / "postgres"
    ro.write_text("#")
    ro.chmod(0o444)
    stopped = []
    monkeypatch.setattr(b, "_stop", lambda r: stopped.append(r))
    b.destroy_system(meta)
    assert stopped == [root] and not root.exists()


def test_restart_starts_a_stopped_server_and_restarts_a_running_one(
    tdd_dir, monkeypatch
):
    b = systems.get(SLUG)
    meta = b.plan_system("pn", {"PORT": "23212"})
    root = tdd_dir / "data" / "system-native" / "pn"
    with pytest.raises(TdxError, match="holds no"):
        b.restart_system(meta)
    (root / "data").mkdir(parents=True)
    steps = []
    running = [False]
    monkeypatch.setattr(b, "_running", lambda r: running[0])
    monkeypatch.setattr(b, "_stop", lambda r: steps.append("stop"))
    monkeypatch.setattr(b, "_start", lambda r: steps.append("start"))
    assert b.restart_system(meta) == "started" and steps == ["start"]
    running[0] = True
    steps.clear()
    assert b.restart_system(meta) == "restarted" and steps == ["stop", "start"]


def test_libpq_variables_never_reach_the_servers_programs(monkeypatch):
    monkeypatch.setenv("PGDATA", "/elsewhere")
    monkeypatch.setenv("PGPORT", "5432")
    env = native.PostgresNative._environment()
    assert "PGDATA" not in env and "PGPORT" not in env and "PATH" in env


# ---- domains: --pgvector ----------------------------------------------------


def _sys_meta(b):
    return b.plan_system("pn", {"PORT": "23420", "PASSWORD": "pw"})


@pytest.mark.parametrize("slug", PGVECTOR_SLUGS)
def test_a_domain_records_its_pgvector_choice_off_by_default(tdd_dir, slug):
    """Installed on the server is all a pgvector system promises: a domain's
    database has the extension created only when its create asked."""
    b = systems.get(slug)
    dom = b.domain_meta(_sys_meta(b), "d1", "secret")
    assert dom["PGVECTOR"] == "off"
    assert "NATIVE_DIR" not in dom
    b.use_pgvector("on")
    assert b.domain_meta(_sys_meta(b), "d1", "secret")["PGVECTOR"] == "on"
    with pytest.raises(TdxError, match="on or off"):
        b.use_pgvector("yes")


def test_a_native_pgvector_domain_carries_its_systems_pgvector_version(tdd_dir):
    b = systems.get(SLUG_PGVECTOR)
    dom = b.domain_meta(_sys_meta(b), "d1", "secret")
    assert dom["PGVECTOR_VERSION"] == binaries.PGVECTOR_VERSION


@pytest.mark.parametrize("slug", PLAIN_SLUGS)
def test_a_plain_domain_says_nothing_of_pgvector(tdd_dir, slug):
    b = systems.get(slug)
    dom = b.domain_meta(_sys_meta(b), "d1", "secret")
    assert not {"PGVECTOR", "PGVECTOR_VERSION"} & set(dom)
    assert not hasattr(b, "use_pgvector")


@pytest.mark.parametrize("slug", PGVECTOR_SLUGS)
@pytest.mark.parametrize("choice", ["on", "off"])
def test_pgvector_on_creates_the_extension_in_the_domains_database(
    tdd_dir, monkeypatch, slug, choice
):
    b = systems.get(slug)
    ran = []
    monkeypatch.setattr(b, "_do_list", lambda admin: [])
    monkeypatch.setattr(b, "_run_admin", lambda admin, sql: ran.append((admin.db, sql)))
    b.use_pgvector(choice)
    sys_meta = _sys_meta(b)
    b.provision_domain(sys_meta, "d1", b.domain_meta(sys_meta, "d1", "secret"))
    created = [("d1", ["CREATE EXTENSION IF NOT EXISTS vector"])]
    assert (ran[-1:] == created) is (choice == "on")
    assert ran[0][0] == "postgres"  # the database itself, from the maintenance db


def _create_options(slug):
    parser = dispatch.ArgumentParser(prog="x")
    dispatch._command_module("domain", slug, "create").add_arguments(parser)
    return parser


@pytest.mark.parametrize("slug", PGVECTOR_SLUGS)
def test_domain_create_takes_pgvector_and_a_manifest_replays_it(slug):
    parser = _create_options(slug)
    assert parser.parse_args(["--sys", "s"]).pgvector == "off"
    assert parser.parse_args(["--sys", "s", "--pgvector", "on"]).pgvector == "on"
    with pytest.raises(UsageError, match="invalid choice: 'maybe'"):
        parser.parse_args(["--sys", "s", "--pgvector", "maybe"])

    def info(pgvector):
        return descriptor.DomainInfo(
            system=slug,
            name="d",
            started="2026-10-29T00:00:00Z",
            sys_name="pn",
            sys_uuid="u",
            external_name="d",
            meta={"PGVECTOR": pgvector},
        )

    assert manifest.domain_entry(info("on")) == {
        "name": "d",
        "sys": "pn",
        "pgvector": "on",
    }
    assert manifest.domain_entry(info("off")) == {"name": "d", "sys": "pn"}
    steps = dispatch._entry_steps(
        "domain", {"name": "d", "sys": "pn", "pgvector": "on"}, force=False
    )
    assert steps[0][-2:] == ["--pgvector", "on"]


@pytest.mark.parametrize("slug", PLAIN_SLUGS)
def test_a_server_without_pgvector_offers_no_pgvector_to_create(slug):
    """CREATE EXTENSION could only fail there: the files are not installed."""
    with pytest.raises(UsageError, match="unrecognized arguments: --pgvector"):
        _create_options(slug).parse_args(["--sys", "s", "--pgvector", "on"])


def test_help_names_the_options_of_the_targets_own_type(tdd_dir, monkeypatch):
    """`domain create --sys S -h` is S's type's create; help needs no key and no
    stored target, so without them it is the first type's, which has no
    --pgvector."""
    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-key-for-the-test-only")
    for name, slug in (("pn", SLUG_PGVECTOR), ("plain", SLUG)):
        info = descriptor.SystemInfo(system=slug, name=name, started="now", meta={})
        descriptor.save(info, store.system_path(name))

    def options(argv):
        parser = dispatch._help_parser("domain", "create", [*argv, "-h"])
        return {flag for a in parser._actions for flag in a.option_strings}

    assert "--pgvector" in options(["--sys", "pn"])
    assert "--pgvector" not in options(["--sys", "plain"])
    assert "--pgvector" not in options(["--sys", "missing"])
    assert "--pgvector" not in options(["--sys", "pn,missing"])
    monkeypatch.delenv("_TDD_CRYPTO_KEY")
    assert "--pgvector" not in options(["--sys", "pn"])
