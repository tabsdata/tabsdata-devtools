#
# Copyright 2026 Tabsdata Inc.
#

"""gcslocal: the local twin of gcs, served by cloudburrow built here -- an image
named after its inputs, an upstream watch that only warns, and a descriptor that
reaches the store on its own."""

import json

from tabsdata_dev.common.systems import systems
from tabsdata_dev.common.systems.systems.gcslocal import backend as gcslocal


def _planned():
    backend = systems.get("gcslocal")
    backend.use_ports([29020])
    return backend, backend.plan_system("k1", {"PORT": "", "PASSWORD": "unused"})


def test_gcslocal_is_a_single_container_gcs_store():
    backend = systems.get("gcslocal")
    assert (backend.hosting, backend.nature) == ("container", "object_store")
    assert backend.volume_path == "/data"
    assert backend.image == gcslocal.image_tag()


def test_the_image_tag_names_the_commit_and_changes_with_any_input(
    tmp_path, monkeypatch
):
    for name in ("Dockerfile", "cloudburrow.patch"):
        (tmp_path / name).write_bytes((gcslocal.IMAGE_DIR / name).read_bytes())
    monkeypatch.setattr(gcslocal, "IMAGE_DIR", tmp_path)
    tag = gcslocal.image_tag()
    assert tag.startswith(f"tdd/gcslocal:{gcslocal.COMMIT[:12]}-")
    assert gcslocal.image_tag() == tag
    (tmp_path / "cloudburrow.patch").write_text("changed")
    assert gcslocal.image_tag() != tag


def test_the_image_inputs_keep_the_line_ends_they_are_committed_with():
    for name in ("Dockerfile", "cloudburrow.patch"):
        assert b"\r" not in (gcslocal.IMAGE_DIR / name).read_bytes(), name


def test_the_upstream_watch_warns_only_when_the_pin_is_behind(monkeypatch):
    said: list[str] = []
    monkeypatch.setattr(gcslocal.console, "warn", said.append)
    for head in ("", gcslocal.COMMIT, "f" * 40):
        monkeypatch.setattr(gcslocal, "upstream_head", lambda head=head: head)
        gcslocal.watch_upstream()
    assert len(said) == 1 and "ffffffffffff" in said[0]


def test_gcslocal_plans_its_gcs_config_from_the_container():
    _, meta = _planned()
    assert meta["ENDPOINT"] == "http://127.0.0.1:29020"
    assert meta["BUCKET"] == meta["PROJECT"] == "tdd"
    assert meta["USER"] == ""
    assert meta["LOCATION"] == "gs://tdd/"
    options = json.loads(meta["STORAGE_OPTIONS"])
    assert options["allow_http"] == "true"
    account = json.loads(options["google_service_account_key"])
    assert account["gcs_base_url"] == "http://127.0.0.1:29020"
    assert account["disable_oauth"] is True


def test_a_gcslocal_domain_descriptor_reaches_the_store_on_its_own():
    backend, meta = _planned()
    domain = backend.domain_meta(meta, "dom", "")
    assert domain["URI"] == "gs://tdd/dom"
    for key in ("ENDPOINT", "BUCKET", "PROJECT", "STORAGE_OPTIONS"):
        assert domain[key] == meta[key]


def test_the_gcs_cloud_store_passes_its_service_account():
    gcs = systems.get("gcs")
    assert gcs.storage_options({"SERVICE_ACCOUNT_KEY": '{"type": "x"}'}) == {
        "google_service_account_key": '{"type": "x"}'
    }
    assert gcs.storage_options({"SERVICE_ACCOUNT_KEY": "/keys/sa.json"}) == {
        "google_service_account": "/keys/sa.json"
    }
