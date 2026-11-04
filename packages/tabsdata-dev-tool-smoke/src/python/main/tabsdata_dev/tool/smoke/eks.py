#
# Copyright 2026 Tabsdata Inc.
#

"""What the EKS smoke needs to give its instance the apiserver role that reads
worker logs back from CloudWatch: the cluster and region a kubeconfig context
reaches (`tdd _smoke eks-cluster`), and the role's IAM documents (`tdd _smoke
eks-role-documents`) -- trusted by the instance's `aut-apiserver` service
account, allowed to read only the instance's `/tabsdata/<namespace>` log group,
the layout the cluster's Fluent Bit writes.
"""

from __future__ import annotations

import json
import re

SERVICE_ACCOUNT = "aut-apiserver"
AUDIENCE = "sts.amazonaws.com"
LOG_GROUP_PREFIX = "/tabsdata/"

#: Where a context's `aws eks get-token` (or `aws-iam-authenticator token`)
#: names the cluster.
_CLUSTER_FLAGS = ("--cluster-name", "--cluster-id", "-i")
_REGION_ENV = ("AWS_REGION", "AWS_DEFAULT_REGION")
_SERVER_REGION = re.compile(r"\.([a-z]{2}(?:-[a-z]+)+-\d+)\.eks\.amazonaws\.com")


def _first(config: dict, key: str, inner: str) -> dict:
    return ((config.get(key) or [{}])[0].get(inner)) or {}


def _flag(args: list[str], names: tuple[str, ...]) -> str | None:
    for i, arg in enumerate(args):
        for name in names:
            if arg == name and i + 1 < len(args):
                return args[i + 1]
            if arg.startswith(f"{name}="):
                return arg.split("=", 1)[1]
    return None


def cluster(view: str) -> tuple[str, str]:
    """The EKS cluster name and region of `kubectl config view --minify -o json`:
    from the user's exec plugin arguments, the region falling back to the
    plugin's environment and then to the API server's host name."""
    config = json.loads(view)
    plugin = _first(config, "users", "user").get("exec") or {}
    args = [str(a) for a in plugin.get("args") or []]
    name = _flag(args, _CLUSTER_FLAGS)
    if not name:
        raise ValueError(
            "the context's user runs no `aws eks get-token --cluster-name NAME`: "
            "not an EKS context, or one this run cannot read the cluster from"
        )
    region = _flag(args, ("--region",))
    if not region:
        env = {e.get("name"): e.get("value") for e in plugin.get("env") or []}
        region = next((env[k] for k in _REGION_ENV if env.get(k)), None)
    if not region:
        found = _SERVER_REGION.search(
            _first(config, "clusters", "cluster").get("server", "")
        )
        region = found.group(1) if found else None
    if not region:
        raise ValueError(
            f"no region for cluster {name}: not in the exec arguments, its environment or the server"
        )
    return name, region


def role_documents(
    caller_arn: str, issuer: str, namespace: str, region: str
) -> tuple[dict, dict]:
    """The trust and permission policies of the apiserver role of the instance
    in NAMESPACE, in the account and partition of the caller."""
    parts = caller_arn.split(":")
    if len(parts) < 6 or parts[0] != "arn" or not parts[4]:
        raise ValueError(f"not an AWS ARN: {caller_arn}")
    partition, account = parts[1], parts[4]
    provider = issuer.removeprefix("https://").rstrip("/")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": f"arn:{partition}:iam::{account}:oidc-provider/{provider}"
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"{provider}:sub": f"system:serviceaccount:{namespace}:{SERVICE_ACCOUNT}",
                        f"{provider}:aud": AUDIENCE,
                    }
                },
            }
        ],
    }
    permissions = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["logs:GetLogEvents"],
                "Resource": f"arn:{partition}:logs:{region}:{account}:log-group:"
                f"{LOG_GROUP_PREFIX}{namespace}:*",
            }
        ],
    }
    return trust, permissions
