#
# Copyright 2026 Tabsdata Inc.
#

"""azurebloblocal: the local twin of azureblob, served by Azurite -- container
hosting with the Azure store, and a descriptor that reaches the store on its
own."""

import base64
import json

from tabsdata_dev.common.systems import systems


def _planned():
    backend = systems.get("azurebloblocal")
    backend.use_ports([29010])
    password = backend.generate_password()
    return backend, backend.plan_system("k1", {"PORT": "", "PASSWORD": password})


def test_azurebloblocal_is_a_single_container_azure_store():
    backend = systems.get("azurebloblocal")
    assert (backend.hosting, backend.nature) == ("container", "object_store")
    assert backend.volume_path == "/data"
    assert "--skipApiVersionCheck" in backend.cmd_args
    assert backend.image.startswith("mcr.microsoft.com/azure-storage/azurite:3.37.0@")


def test_its_account_key_is_base64_as_azure_keys_are():
    key = systems.get("azurebloblocal").generate_password()
    assert len(base64.b64decode(key, validate=True)) == 32


def test_azurebloblocal_plans_its_azure_config_from_the_container():
    _, meta = _planned()
    assert meta["ENDPOINT"] == "http://127.0.0.1:29010/tdd"
    assert meta["ACCOUNT_NAME"] == meta["USER"] == "tdd"
    assert meta["ACCOUNT_KEY"] == meta["PASSWORD"]
    assert meta["CONTAINER"] == "tdd"
    assert meta["LOCATION"] == "az://tdd/"
    assert json.loads(meta["STORAGE_OPTIONS"]) == {
        "azure_storage_account_name": "tdd",
        "azure_storage_account_key": meta["PASSWORD"],
        "azure_endpoint": "http://127.0.0.1:29010/tdd",
        "allow_http": "true",
    }


def test_an_azurebloblocal_domain_descriptor_reaches_the_store_on_its_own():
    backend, meta = _planned()
    domain = backend.domain_meta(meta, "dom", "")
    assert domain["URI"] == "az://tdd/dom"
    for key in ("ENDPOINT", "CONTAINER", "ACCOUNT_NAME", "ACCOUNT_KEY"):
        assert domain[key] == meta[key]
    assert domain["STORAGE_OPTIONS"] == meta["STORAGE_OPTIONS"]


def test_the_azure_cloud_store_has_no_endpoint_options():
    options = systems.get("azureblob").storage_options(
        {"ACCOUNT_NAME": "acct", "ACCOUNT_KEY": "k"}
    )
    assert options == {
        "azure_storage_account_name": "acct",
        "azure_storage_account_key": "k",
    }
