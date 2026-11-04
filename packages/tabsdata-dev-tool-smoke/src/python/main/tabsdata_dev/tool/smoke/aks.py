#
# Copyright 2026 Tabsdata Inc.
#

"""What the AKS smoke needs to let its apiserver read worker logs back from Log
Analytics: the cluster a kubeconfig context reaches and what it says of
Workload Identity and Container Insights (`tdd _smoke aks-cluster`), the role
condition that limits the apiserver's identity to its namespace's rows (`tdd
_smoke aks-condition`), and whether the identity already has that assignment
(`tdd _smoke aks-has-assignment`) -- so a setup an admin made once is reused
without writing to Azure RBAC again.
"""

from __future__ import annotations

import json
import re
import urllib.parse

#: The built-in Log Analytics Data Reader role.
DATA_READER = "3b03c2da-16b3-4a49-8834-0f8130efdd3b"

PRESENT = "present"
ABSENT = "absent"
DIFFERENT = "different"

_CLUSTER_ID = re.compile(
    r"^/subscriptions/([^/]+)/resourcegroups/([^/]+)/providers/"
    r"microsoft\.containerservice/managedclusters/([^/]+)$",
    re.IGNORECASE,
)


def _host(view: str) -> str:
    config = json.loads(view)
    entry = (config.get("clusters") or [{}])[0].get("cluster") or {}
    return urllib.parse.urlsplit(entry.get("server") or "").hostname or ""


def _get(mapping: dict, key: str):
    """A key of an `az` object in any casing: the addon is `omsagent` or
    `omsAgent`, its workspace `...ResourceID` or `...ResourceId`."""
    for name, value in (mapping or {}).items():
        if name.lower() == key.lower():
            return value
    return None


def cluster(view: str, clusters: str) -> list[str] | None:
    """The cluster of `az aks list --output json` that the API server of
    `kubectl config view --minify --output json` belongs to, as subscription,
    resource group, name, OIDC issuer, Workload Identity on (`true`/`false`)
    and the Container Insights workspace's resource id (`-` for none); none
    when no cluster there answers at that host."""
    host = _host(view).lower()
    if not host:
        raise ValueError("the context's cluster names no server")
    for found in json.loads(clusters or "[]"):
        names = {(found.get(k) or "").lower() for k in ("fqdn", "privateFqdn")}
        if host not in names:
            continue
        parts = _CLUSTER_ID.match(found.get("id") or "")
        if not parts:
            raise ValueError(f"not an AKS cluster id: {found.get('id')}")
        issuer = (found.get("oidcIssuerProfile") or {}).get("issuerUrl") or "-"
        identity = ((found.get("securityProfile") or {}).get("workloadIdentity")) or {}
        addon = _get(found.get("addonProfiles"), "omsagent") or {}
        workspace = "-"
        if addon.get("enabled"):
            config = addon.get("config") or {}
            workspace = _get(config, "logAnalyticsWorkspaceResourceID") or "-"
        return [
            *parts.groups(),
            issuer,
            "true" if identity.get("enabled") else "false",
            workspace,
        ]
    return None


def condition(namespace: str) -> str:
    """The dguide's condition: the assignment reads only `ContainerLogV2` rows
    whose `PodNamespace` is the instance's."""
    return (
        "((!(ActionMatches{'Microsoft.OperationalInsights/workspaces/tables/data/read'})) "
        "OR (@Resource[Microsoft.OperationalInsights/workspaces/tables:name] "
        "StringEquals 'ContainerLogV2' AND "
        "@Resource[Microsoft.OperationalInsights/workspaces/tables/record:"
        "PodNamespace<$key_case_sensitive$>] StringEquals "
        f"'{namespace}'))"
    )


def _squeezed(text: str) -> str:
    return " ".join(text.split())


def assignment(listing: str, principal: str, namespace: str) -> tuple[str, str]:
    """Whether the principal's Data Reader assignments in `az role assignment
    list --output json` hold this namespace's condition (present, with its
    id), none at all (absent), or only another (different): that one is not
    added to, since Azure grants the sum of every assignment."""
    wanted = _squeezed(condition(namespace))
    found = ABSENT
    for item in json.loads(listing or "[]"):
        if item.get("principalId") != principal:
            continue
        if not (item.get("roleDefinitionId") or "").lower().endswith(DATA_READER):
            continue
        if _squeezed(item.get("condition") or "") == wanted:
            return PRESENT, item.get("id") or ""
        found = DIFFERENT
    return found, ""
