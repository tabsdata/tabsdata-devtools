#
# Copyright 2026 Tabsdata Inc.
#

"""What `gsx prune` does to a stack full of landed PRs, and why it costs a
number.

A stack keeps its merged PRs for good: `gh stack checkout` imports every branch
it ever had, `gh stack view` lists them all, and `sync --prune` deletes the
local branches while keeping the metadata. A long-lived stack therefore grows
without bound -- one in tabsdata-os is 93 PRs of which 90 have landed -- and
every command that reads it pays for the history.

There is no API for removing a PR from a stack (`gh stack unstack` takes no
body), so the only way to shrink one is to **dissolve it and relink what is
left**. That is what prune is: one `gh stack unstack <n>` on GitHub, then one
`gh stack link` over the PRs that are still open. The cost is fixed and worth
saying out loud: **the stack number changes.** The PR numbers do not, and
neither does any branch -- prune rewrites no commits at all.

Two facts shape the steps:

* **`gh stack link` takes PR numbers or branch names, and branch names are
  pushed.** "Branch arguments are automatically pushed to the remote before
  creating or looking up PRs. For branches without PRs, new PRs are created
  automatically." So prune passes numbers only: nothing is pushed and no PR can
  be opened by accident.
* **A stack needs two PRs.** With fewer than two still open there is no stack
  to make, so prune dissolves and stops there, which is the honest end for a
  stack with one open PR left.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tabsdata_dev.common.core.errors import ToolError

#: What GitHub calls a PR that is done with; `OPEN` is the only other state.
LANDED = ("MERGED", "CLOSED")

#: `gh stack link` needs this many PRs to make a stack.
NEEDS = 2


def _ends(pairs: list[tuple[str, int]], most: int = 6) -> str:
    """`branch (#pr)` for each, or just the ends of a long list: ninety of them
    tell the operator less than the first, the last and the count do."""
    named = [f"{branch} (#{pr})" for branch, pr in pairs]
    if len(named) <= most:
        return " ".join(named)
    return f"{named[0]} .. {named[-1]}   [{len(named)}]"


@dataclass
class Plan:
    """The stack as it is, and what it would be left as."""

    number: int
    trunk: str
    keep: list[tuple[str, int]] = field(default_factory=list)  # (branch, pr), bottom-up
    drop: list[tuple[str, int]] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)  # branches with no PR

    @property
    def branches(self) -> list[str]:
        """What the stack is re-tracked as locally: the open PRs' branches, and
        the branches that have no PR at all.

        A branch with no PR is not history and not a landed thing -- it is work
        that has not been submitted yet, and dropping it from the local stack
        would lose the arrangement it is part of. It cannot be linked on
        GitHub, because there is nothing there to link.
        """
        return [branch for branch, _ in self.keep] + self.untracked

    @property
    def prs(self) -> list[int]:
        return [pr for _, pr in self.keep]

    @property
    def links(self) -> bool:
        return len(self.keep) >= NEEDS

    def text(self) -> str:
        """The plan as the operator reads it before confirming."""
        lines = [
            "Plan",
            f"  stack #{self.number} on {self.trunk}: "
            f"{len(self.keep) + len(self.drop)} PR(s), {len(self.drop)} of them "
            "merged or closed",
            f"  drop  {_ends(self.drop)}",
            f"  keep  {_ends(self.keep) or '(none)'}",
        ]
        if self.untracked:
            lines.append(f"  keep  {' '.join(self.untracked)}   # no PR yet")
        lines.append("")
        lines.append(f"  1. gh stack unstack {self.number}   # on GitHub, irreversible")
        if self.links:
            lines.append(
                "  2. gh stack link "
                + " ".join(str(pr) for pr in self.prs)
                + "   # a new stack of the open PRs"
            )
        else:
            lines.append(
                f"  2. (nothing to link: a stack needs {NEEDS} PRs and "
                f"{len(self.keep)} would be left)"
            )
        lines.append(
            f"  3. gh stack init --base {self.trunk} {' '.join(self.branches)}"
            "   # track it here"
            if self.branches
            else "  3. (nothing left to track here)"
        )
        lines.append("")
        lines.append(
            f"  #{self.number} is lost -- a relinked stack is a new one. No PR "
            "number changes and no branch is rewritten."
        )
        return "\n".join(lines)


def build(stack: dict, states: dict) -> Plan:
    """The plan for one tracked stack, given its PRs' states.

    `states` is what `gh.pull_requests` answered. A PR the API did not answer
    for is kept: prune's whole purpose is to drop what is certainly finished,
    and a missing answer is not certainty.
    """
    number = stack.get("number")
    if not number:
        raise ToolError(
            "this stack is not on GitHub yet, so there is nothing to unstack "
            "there; `tdd gsx submit` makes it a stack first"
        )
    plan = Plan(
        number=int(number), trunk=((stack.get("trunk") or {}).get("branch")) or ""
    )
    for item in stack.get("branches") or []:
        branch = item.get("branch")
        if not branch:
            continue
        pr = (item.get("pullRequest") or {}).get("number")
        if not pr:
            plan.untracked.append(branch)
            continue
        state = ((states.get(int(pr)) or {}).get("state") or "").upper()
        if state in LANDED:
            plan.drop.append((branch, int(pr)))
        else:
            plan.keep.append((branch, int(pr)))
    if not plan.drop:
        raise ToolError(
            f"nothing to prune: every PR of stack #{plan.number} is still open, so "
            "dissolving it would cost its number for nothing"
        )
    return plan
