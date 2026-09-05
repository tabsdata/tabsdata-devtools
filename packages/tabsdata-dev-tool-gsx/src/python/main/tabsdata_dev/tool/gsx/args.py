#
# Copyright 2026 Tabsdata Inc.
#

"""The two option shapes argparse cannot express, split off argv before it runs.

gsx speaks two grammars of its own on top of the ordinary options:

* **passthrough** -- ``--<char>:<flag> [VALUE]`` forwards a flag to one of the
  native ``gh`` commands the subcommand drives; the char names the operation,
  so the same letter can mean different things in different subcommands.
* **label/reviewer ops** -- ``--label:<scope>[:<mode>] LIST`` (and
  ``--reviewer:``), repeatable, applied in the order given.

Both are pulled out of argv by :func:`split` before the shared runner parses
what is left, so ``--help``/``--format``/``--verbose`` and every plain option
stay argparse's and these stay gsx's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tabsdata_dev.common.core.errors import ToolError

LR_KINDS = {"label": "label", "l": "label", "reviewer": "reviewer", "r": "reviewer"}
LR_SCOPES = {
    "new": "new",
    "n": "new",
    "top": "top",
    "t": "top",
    "all": "all",
    "a": "all",
    "mine": "mine",
    "m": "mine",
}
LR_MODES = {"replace": "replace", "r": "replace", "add": "add", "a": "add"}

_LR_TOKEN = re.compile(r"--?([A-Za-z]+)(?::([A-Za-z]+))?(?::([A-Za-z]+))?")
_PASSTHROUGH = re.compile(r"--([A-Za-z]):(.*)")


@dataclass(frozen=True)
class Native:
    """One native command a subcommand drives, and its ``--<char>:`` prefix.

    ``owned`` names the flags gsx derives itself; a passthrough naming one is
    refused unless ``--override``, because the two would fight.
    """

    char: str
    target: str
    owned: dict[str, str] = field(default_factory=dict)


@dataclass
class LrOp:
    """One ``--label:scope:mode VALUE`` (or reviewer) instruction."""

    kind: str  # label | reviewer
    scope: str  # new | top | all | mine
    mode: str  # replace | add
    values: list[str]
    token: str  # as typed, for error messages


@dataclass
class Extras:
    """What :func:`split` took out of argv."""

    lr_ops: list[LrOp] = field(default_factory=list)
    passthrough: dict[str, list[str]] = field(default_factory=dict)
    names: dict[str, list[str]] = field(default_factory=dict)


def csv(value: str | None) -> list[str]:
    """``"a, b"`` -> ``["a", "b"]``; ``""`` -> ``[]``, which means "remove all"."""
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_lr_token(token: str) -> tuple[str, str, str] | None:
    """``--label:top:add`` -> ``("label", "top", "add")``; None when not one."""
    matched = _LR_TOKEN.fullmatch(token)
    if not matched:
        return None
    kind_word, scope_word, mode_word = matched.groups()
    kind = LR_KINDS.get(kind_word.lower())
    if kind is None:
        return None
    scope = LR_SCOPES.get((scope_word or "new").lower())
    if scope is None:
        raise ToolError(
            f"unknown scope in {token}: {scope_word!r}; use new|top|all|mine (n|t|a|m)"
        )
    mode = LR_MODES.get((mode_word or "replace").lower())
    if mode is None:
        raise ToolError(
            f"unknown mode in {token}: {mode_word!r}; use replace|add (r|a)"
        )
    return kind, scope, mode


def _as_flag(name: str) -> str:
    return f"-{name}" if len(name) == 1 else f"--{name}"


def split(
    argv: list[str], natives: list[Native], takes_lr: bool
) -> tuple[list[str], Extras]:
    """Take gsx's own two grammars out of `argv`, returning (rest, extras).

    Arity is inferred the way the native tools do it: a following token that
    does not start with ``-`` is the value, otherwise the flag is a boolean.
    ``--<char>:name=value`` is unambiguous. Everything after a ``--`` is left
    for argparse (they are paths), and so is every token gsx does not claim.
    """
    prefixes = {native.char: native for native in natives}
    rest: list[str] = []
    extras = Extras()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":  # paths from here on; argparse owns them
            rest.extend(argv[index:])
            break

        if takes_lr and token.startswith("-"):
            head, sep, inline = token.partition("=")
            lr = parse_lr_token(head)
            if lr is not None:
                kind, scope, mode = lr
                if sep:
                    raw = inline
                elif index + 1 < len(argv):
                    raw = argv[index + 1]
                    index += 1
                else:
                    raise ToolError(f'{token} needs a value (use "" to remove all)')
                extras.lr_ops.append(LrOp(kind, scope, mode, csv(raw), token))
                index += 1
                continue

        matched = _PASSTHROUGH.fullmatch(token)
        if matched:
            char, body = matched.group(1), matched.group(2)
            if char not in prefixes:
                known = (
                    ", ".join(f"--{n.char}: ({n.target})" for n in natives) or "none"
                )
                raise ToolError(
                    f"unknown passthrough prefix --{char}: here; this subcommand "
                    f"accepts: {known}"
                )
            if "=" in body:
                name, value = body.split("=", 1)
                pieces = [_as_flag(name), value]
                index += 1
            else:
                name = body
                following = argv[index + 1] if index + 1 < len(argv) else None
                if following is not None and (
                    not following.startswith("-") or following == "-"
                ):
                    pieces = [_as_flag(name), following]
                    index += 2
                else:
                    pieces = [_as_flag(name)]
                    index += 1
            if not name:
                raise ToolError(f"empty passthrough option: {token}")
            extras.passthrough.setdefault(char, []).extend(pieces)
            extras.names.setdefault(char, []).append(name)
            continue

        rest.append(token)
        index += 1
    return rest, extras


def check_overlaps(extras: Extras, natives: list[Native], override: bool, out) -> None:
    """Refuse passthrough that would fight a value gsx derives, unless
    ``--override``, which appends yours last so gh's last-wins applies."""
    clashes = [
        f"--{native.char}:{name} collides with {native.owned[name]} ({native.target})"
        for native in natives
        for name in extras.names.get(native.char, [])
        if name in native.owned
    ]
    if not clashes:
        return
    if override:
        out.warn(
            "overriding gsx's own options, yours are passed last and win: "
            + "; ".join(clashes)
        )
        return
    raise ToolError(
        "these passthrough options collide with values gsx sets itself: "
        + "; ".join(clashes)
        + " -- re-run with --override/-o to let yours win, or drop them"
    )


# Flags gsx derives itself, per native command, mapped to the gsx option that
# produces them.
TEXT_OWNED = {
    "title": "-s/--summary",
    "t": "-s/--summary",
    "body": "-m/--message",
    "b": "-m/--message",
    "body-file": "-m/--message",
    "F": "-m/--message",
}
STACK_ADD_OWNED = {
    "message": "the commit message gsx builds",
    "m": "the commit message gsx builds",
    "all": "the staging gsx does (git add)",
    "A": "the staging gsx does (git add)",
    "update": "the staging gsx does (git add)",
    "u": "the staging gsx does (git add)",
}
PR_EDIT_OWNED = {
    "add-label": "--label:...",
    "add-reviewer": "--reviewer:...",
    "remove-label": "--label:...",
    "remove-reviewer": "--reviewer:...",
}

CREATE_NATIVES = [
    Native("i", "gh issue create", TEXT_OWNED),
    Native("s", "gh stack init / gh stack add", STACK_ADD_OWNED),
]
UPDATE_NATIVES = [
    Native("i", "gh issue edit", TEXT_OWNED),
    Native("e", "gh pr edit", TEXT_OWNED),
]
CHECKOUT_NATIVES = [Native("c", "gh stack checkout")]
SUBMIT_NATIVES = [
    Native("p", "gh stack submit", {"auto": "gsx always runs non-interactively"}),
    Native("s", "gh stack sync"),
    Native("e", "gh pr edit", PR_EDIT_OWNED),
]
APPLY_NATIVES = [Native("e", "gh pr edit", PR_EDIT_OWNED)]
NATIVES = {
    "create": CREATE_NATIVES,
    "update": UPDATE_NATIVES,
    "checkout": CHECKOUT_NATIVES,
    "submit": SUBMIT_NATIVES,
    "apply": APPLY_NATIVES,
    "auto-config": [],
}
TAKES_LR = {"submit", "apply"}
