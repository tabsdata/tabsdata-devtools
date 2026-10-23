#
# Copyright 2026 Tabsdata Inc.
#

"""s3local: the local twin of s3, served by RustFS -- container hosting with the S3 store, and a
descriptor that reaches the store on its own."""

import json

from tabsdata_dev.common.systems import systems


def _planned():
    backend = systems.get("s3local")
    backend.use_ports([29000])
    return backend, backend.plan_system("k1", {"PORT": "", "PASSWORD": "secret-pw"})


def test_s3local_is_a_single_container_s3_store():
    backend = systems.get("s3local")
    assert (backend.hosting, backend.nature) == ("container", "object_store")
    assert backend.volume_path == "/data"
    assert "--memory" in backend.extra_run_flags
    assert backend.image.startswith("rustfs/rustfs:1.0.2@sha256:")


def test_s3local_plans_its_s3_config_from_the_container():
    _, meta = _planned()
    assert meta["ENDPOINT"] == "http://127.0.0.1:29000"
    assert meta["ACCESS_KEY"] == meta["USER"] == "tdd"
    assert meta["SECRET_KEY"] == meta["PASSWORD"] == "secret-pw"
    assert meta["BUCKET"] == "tdd"
    assert meta["LOCATION"] == "s3://tdd/"
    assert json.loads(meta["STORAGE_OPTIONS"]) == {
        "aws_access_key_id": "tdd",
        "aws_secret_access_key": "secret-pw",
        "aws_region": "us-east-1",
        "aws_endpoint_url": "http://127.0.0.1:29000",
        "aws_allow_http": "true",
    }


def test_an_s3local_domain_descriptor_reaches_the_store_on_its_own():
    backend, meta = _planned()
    domain = backend.domain_meta(meta, "dom", "")
    assert domain["URI"] == "s3://tdd/dom"
    for key in ("ENDPOINT", "BUCKET", "REGION", "ACCESS_KEY", "SECRET_KEY"):
        assert domain[key] == meta[key]
    assert domain["STORAGE_OPTIONS"] == meta["STORAGE_OPTIONS"]


def test_the_s3_cloud_store_has_no_endpoint_options():
    s3 = systems.get("s3")
    options = s3.storage_options(
        {"ACCESS_KEY": "a", "SECRET_KEY": "s", "REGION": "eu-west-1"}
    )
    assert options == {
        "aws_access_key_id": "a",
        "aws_secret_access_key": "s",
        "aws_region": "eu-west-1",
    }
