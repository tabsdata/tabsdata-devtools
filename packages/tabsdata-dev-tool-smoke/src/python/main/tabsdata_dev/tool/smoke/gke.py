#
# Copyright 2026 Tabsdata Inc.
#

"""What the GKE smoke needs to let its apiserver read worker logs back from
Cloud Logging: the project, location and cluster a kubeconfig context reaches
(`tdd _smoke gke-cluster`), the bucket the Tabsdata logs land in (`tdd _smoke
gke-log-bucket`), the apiserver's Google service account (`tdd _smoke
gke-service-account`), and whether an IAM policy already holds a binding
(`tdd _smoke gke-has-binding`) -- so a setup an admin made once is reused
without writing to IAM again.
"""

from __future__ import annotations

import hashlib
import json
import re

DEFAULT_BUCKET = "_Default"
DEFAULT_LOCATION = "global"
VIEW_PREFIX = "tabsdata-"

#: `gcloud container clusters get-credentials` names the context and the cluster
#: entry gke_<project>_<location>_<cluster>; none of the three holds a `_`.
_CONTEXT = re.compile(r"^gke_([a-z][a-z0-9-]+)_([a-z0-9-]+)_([a-z][a-z0-9-]*)$")
_DESTINATION = re.compile(
    r"^logging\.googleapis\.com/projects/[^/]+/locations/([^/]+)/buckets/([^/]+)$"
)
_BUCKET_NAME = re.compile(r"^projects/[^/]+/locations/([^/]+)/buckets/([^/]+)$")
#: What the dguide's own sink filters on: the pods' `app.kubernetes.io/part-of`.
_TABSDATA_FILTER = ("app_kubernetes_io/part-of", "tabsdata")
_SYSTEM_SINKS = frozenset({"_Default", "_Required"})

_SERVICE_ACCOUNT_MAX = 30
_HASH_LEN = 6


def cluster(view: str) -> tuple[str, str, str]:
    """The project, location and cluster of `kubectl config view --minify -o json`:
    from the context's name, else the name of the cluster entry it uses."""
    config = json.loads(view)
    context = (config.get("contexts") or [{}])[0]
    names = [
        context.get("name") or "",
        (context.get("context") or {}).get("cluster") or "",
    ]
    for name in names:
        found = _CONTEXT.match(name)
        if found:
            return found.group(1), found.group(2), found.group(3)
    raise ValueError(
        f"neither the context nor its cluster is named gke_<project>_<location>_<cluster> "
        f"({' / '.join(n for n in names if n) or 'no names'}): not a context "
        "`gcloud container clusters get-credentials` made"
    )


def log_bucket(sinks: str, buckets: str) -> tuple[str, str]:
    """Where the Tabsdata container logs land: the bucket of an enabled sink
    that routes the pods labelled part of tabsdata, else `_Default` where that
    bucket is."""
    for sink in json.loads(sinks or "[]"):
        if sink.get("name") in _SYSTEM_SINKS or sink.get("disabled"):
            continue
        text = sink.get("filter") or ""
        if not all(part in text for part in _TABSDATA_FILTER):
            continue
        found = _DESTINATION.match(sink.get("destination") or "")
        if found:
            return found.group(2), found.group(1)
    for bucket in json.loads(buckets or "[]"):
        found = _BUCKET_NAME.match(bucket.get("name") or "")
        if found and found.group(2) == DEFAULT_BUCKET:
            return DEFAULT_BUCKET, found.group(1)
    return DEFAULT_BUCKET, DEFAULT_LOCATION


def service_account(namespace: str) -> str:
    """The apiserver's Google service account id: `td-<namespace>-apiserver`,
    or, past the 30 characters an id may have, the namespace cut short and a
    hash of it that keeps two long namespaces apart."""
    plain = f"td-{namespace}-apiserver"
    if len(plain) <= _SERVICE_ACCOUNT_MAX:
        return plain
    digest = hashlib.sha256(namespace.encode()).hexdigest()[:_HASH_LEN]
    room = _SERVICE_ACCOUNT_MAX - len("td--") - _HASH_LEN
    return f"td-{namespace[:room].rstrip('-')}-{digest}"


def has_binding(
    policy: str, role: str, member: str, expression: str | None = None
) -> bool:
    """Whether the IAM policy (`get-iam-policy --format json`) grants ROLE to
    MEMBER -- under exactly EXPRESSION when one is given, unconditionally
    otherwise."""
    for binding in json.loads(policy or "{}").get("bindings") or []:
        if binding.get("role") != role or member not in (binding.get("members") or []):
            continue
        condition = (binding.get("condition") or {}).get("expression")
        if condition == expression:
            return True
    return False
