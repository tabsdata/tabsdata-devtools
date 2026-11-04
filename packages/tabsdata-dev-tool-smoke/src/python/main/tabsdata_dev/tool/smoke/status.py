#
# Copyright 2026 Tabsdata Inc.
#

"""What a `tdkserver status` listing says about an instance.

tdkserver exits 0 whether the instance runs or not, so the state is read from
its text. kminus says `Instance 'NAME' is not running.` when stopped and lists
the workloads otherwise; eks always draws the Deployments/Pods/CronJobs/Jobs
tables and says nothing -- stopped is the tables being empty, drawn as an
empty box or, by later builds, as `No rows found.` under the title. So a
sentence decides when there is one, else the Deployments and Pods rows do.
"""

from __future__ import annotations

import dataclasses
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

RUNNING = "running"
STOPPED = "stopped"
MISSING = "missing"
STATES = (RUNNING, STOPPED)

_MISSING_SAYS = ("does not exist",)
_STOPPED_SAYS = ("is not running", "is stopped", "was already stopped")

#: The section titles that end the Pods table.
_AFTER_PODS = re.compile(r"^(Deployments|CronJobs|Jobs|Services|StatefulSets)")


@dataclasses.dataclass(frozen=True)
class Pod:
    name: str
    status: str
    ready: str

    @property
    def is_ready(self) -> bool:
        # `n/m`: ready when both halves agree
        done, _, wanted = self.ready.partition("/")
        return self.status == "Running" and bool(wanted) and done == wanted

    def __str__(self) -> str:
        return f"{self.name} ({self.status} {self.ready})"


def _lines(text: str) -> list[str]:
    return ANSI.sub("", text).splitlines()


def pods(text: str) -> list[Pod]:
    """The rows of the Pods table, `│ srv-apiserver-58cc-pfkch │ Running │ 1/1
    │ 2s │`, up to the next table's title."""
    found, inside = [], False
    for line in _lines(text):
        if line.startswith("Pods"):
            inside = True
            continue
        if _AFTER_PODS.match(line):
            inside = False
        if not inside or not line.startswith("│"):
            continue
        cells = line.replace("│", " ").split()
        if len(cells) >= 3 and cells[0] != "Name":
            found.append(Pod(*cells[:3]))
    return found


def unready(listed: list[Pod], services: list[str]) -> tuple[list[str], list[Pod]]:
    """The SERVICES with no Running, Ready pod named `<service>-...`, and every
    pod of the instance in another state."""
    missing = [
        service
        for service in services
        if not any(p.name.startswith(f"{service}-") and p.is_ready for p in listed)
    ]
    return missing, [p for p in listed if not p.is_ready]


def workload_rows(text: str) -> int:
    """How many data rows the Deployments and Pods tables hold, between a
    table's header rule (`├`, or `┡` under a heavy header) and its `└`
    bottom. Jobs and CronJobs are left out: a completed init job can outlive a
    stop, a deployment or pod cannot."""
    rows, keep, body = 0, False, False
    for line in _lines(text):
        if re.match(r"^(Deployments|Pods)\s*$", line):
            keep = True
        elif re.match(r"^(CronJobs|Jobs)\s*$", line):
            keep = False
        elif line.startswith(("├", "┡")):
            body = True
        elif line.startswith("└"):
            body = False
        elif keep and body and line.startswith("│"):
            rows += 1
    return rows


def state(text: str) -> str:
    if any(says in text for says in _MISSING_SAYS):
        return MISSING
    if any(says in text for says in _STOPPED_SAYS):
        return STOPPED
    if "Deployments" in text:
        return RUNNING if workload_rows(text) > 0 else STOPPED
    return RUNNING
