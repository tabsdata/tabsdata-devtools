#
# Copyright 2026 Tabsdata Inc.
#
"""What the shells env tells the processes that cannot import this package:
tdd-install, whose own env does not hold it, and the two loaders, which are
shell. Plumbing, not a tdd command: it prints a bare answer for a program to
read.

    python -m tabsdata_dev.shell loaders                  {family: [installed name, template]}
    python -m tabsdata_dev.shell scripts-folder FAMILY    the family's command files
"""

import argparse
import json

from tabsdata_dev import shell


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tabsdata_dev.shell")
    words = parser.add_subparsers(dest="word", required=True)
    words.add_parser("loaders", help="each family's loader name and template, as JSON")
    folder = words.add_parser("scripts-folder", help="where a family's commands are")
    folder.add_argument("family", choices=shell.FAMILIES)
    args = parser.parse_args(argv)
    if args.word == "loaders":
        loaders = {
            family: [shell.INSTALLED[family], shell.source_template(family)]
            for family in shell.FAMILIES
        }
        print(json.dumps(loaders))
    else:
        print(shell.scripts_dir(args.family))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
