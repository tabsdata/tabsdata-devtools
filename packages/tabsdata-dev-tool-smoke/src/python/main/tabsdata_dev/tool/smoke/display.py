#
# Copyright 2026 Tabsdata Inc.
#

"""A command line as text with every credential masked, for the stage lines
and the log of a smoke run.

Masked: the value after --password/-p/--token/--secret/--pat/--*-key/
--*-token/--*-secret/--*-password (space or = form), the user:password of a
URL, and a NAME=value whose NAME says PASSWORD/SECRET/TOKEN/KEY/_PAT. Patterns
are shell-case globs, case-sensitive, as the engine has always matched them.
"""

from __future__ import annotations

import fnmatch
import re

MASK = "***"

#: An option whose next argument is its value.
VALUE_OPTIONS = (
    "--password",
    "-p",
    "--token",
    "--secret",
    "--pat",
    "--*-key",
    "--*-token",
    "--*-secret",
    "--*-password",
)

#: The words a NAME=value names a credential by.
SECRET_WORDS = ("PASSWORD", "SECRET", "TOKEN", "KEY")

_URL_CREDENTIALS = re.compile(r"(://)[^/@]*@")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][^=]*=")


def _matches(arg: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(arg, pattern) for pattern in patterns)


def _secret_name(name: str) -> bool:
    return (
        any(word in name for word in SECRET_WORDS)
        or name.endswith("_PAT")
        or "_PAT_" in name
    )


def display(args: list[str]) -> str:
    out = []
    mask_next = False
    for arg in args:
        if mask_next:
            out.append(MASK)
            mask_next = False
        elif _matches(arg, VALUE_OPTIONS):
            out.append(arg)
            mask_next = True
        elif _matches(
            arg, tuple(f"{option}=*" for option in VALUE_OPTIONS if option != "-p")
        ):
            out.append(f"{arg.split('=', 1)[0]}={MASK}")
        elif fnmatch.fnmatchcase(arg, "*://*:*@*"):
            out.append(_URL_CREDENTIALS.sub(rf"\1{MASK}@", arg, count=1))
        elif _ASSIGNMENT.match(arg) and _secret_name(arg.split("=", 1)[0]):
            out.append(f"{arg.split('=', 1)[0]}={MASK}")
        else:
            out.append(arg)
    return " ".join(out)
