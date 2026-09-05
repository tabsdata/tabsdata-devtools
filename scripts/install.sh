#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#

# install.sh -- build a tdd dir and give every command its config file.
#
#     scripts/install.sh [--dir PATH] [--editable] [--force] [--no-config]
#
# `cargo make install` builds the envs; this adds the second half of a fresh
# setup: `tdd <command> config --create` for every command that has options, so
# the files are there to read and edit instead of having to be asked for one at
# a time. An existing file is left alone unless --force, and a command that
# owns no options (the launchers: every argument is the program's) is skipped.
#
# Safe to re-run: it is `cargo make install` plus a create that refuses to
# clobber, which is what makes it the way to pick up a new command's config too.

set -u

DIR_OPT="${TDD_DIR:-$HOME/.tdd}"
EDITABLE=0
FORCE=0
CONFIGS=1
RED=""; GREEN=""; YELLOW=""; DIM=""; RESET=""
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RESET=$'\033[0m'
fi

usage() {
    cat <<'USAGE'
usage: scripts/install.sh [--dir PATH] [--editable] [--force] [--no-config]

Build a tdd dir with `cargo make install`, then create the config file of every
command that has options (`tdd <command> config --create`).

options:
  --dir PATH    the tdd dir to build (default: $TDD_DIR, else ~/.tdd)
  --editable    link the envs to this checkout (`cargo make dev`) instead of
                installing from built wheels
  --force       recreate a config file that already exists, keeping what it set
  --no-config   only build the tdd dir

example: scripts/install.sh --dir /tmp/t2 --editable
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dir) DIR_OPT="$2"; shift 2 ;;
        --dir=*) DIR_OPT="${1#--dir=}"; shift ;;
        --editable) EDITABLE=1; shift ;;
        --force | -f) FORCE=1; shift ;;
        --no-config) CONFIGS=0; shift ;;
        --help | -h) usage; exit 0 ;;
        *) echo "install.sh: unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
done

say() { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$DIM" "$RESET" "$*"; }
fail() { printf '%sinstall.sh: %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }

for binary in cargo-make uv jq; do
    command -v "$binary" >/dev/null 2>&1 || fail "$binary is not on PATH"
done

# ---------------------------------------------------------------- the envs
TASK="install"
[ "$EDITABLE" = 1 ] && TASK="dev"
step "cargo make $TASK -- --dir $DIR_OPT"
cargo make "$TASK" -- --dir "$DIR_OPT" || fail "cargo make $TASK failed"

[ "$CONFIGS" = 1 ] || { say ""; say "${GREEN}installed${RESET} $DIR_OPT   (no config files: --no-config)"; exit 0; }

# ------------------------------------------------------------- the configs
# The `tdd` function is what dispatches to both halves, so the configs are
# created through it -- a shell command has no other entry point.
# shellcheck disable=SC1090
. "$DIR_OPT/tdd-source.sh" >/dev/null 2>&1 || fail "could not source $DIR_OPT/tdd-source.sh"

CATALOG="$DIR_OPT/catalog.json"
[ -r "$CATALOG" ] || fail "no catalog at $CATALOG"
# A launcher owns no options: `tdd tdk config` is the program's own `config`.
SKIP=" $(jq -r '.tools | to_entries[] | select(.value.launcher == true) | .key' "$CATALOG" | tr '\n' ' ')"
# `tdd help` lists tdd-exe's own builtins (doctor, info) beside the commands;
# only a catalog tool or a shell command has options of its own to configure.
# Demo tools are samples of the shape, not the user's work: `tdd help` leaves
# them out without --demo, and so does this.
KNOWN=" $(jq -r '.tools | to_entries[] | select(.value.demo != true) | .key' "$CATALOG" | tr '\n' ' ')"
COMMANDS="$(tdd help --format json 2>/dev/null |
    jq -r '.commands[] | select(.shell == true) | .name'; printf '%s' "${KNOWN# }")"
COMMANDS="$(printf '%s\n' $COMMANDS | sort -u)"
[ -n "$COMMANDS" ] || fail "could not list the commands of $DIR_OPT"

step "config files in $DIR_OPT"
CREATED=0; KEPT=0; SKIPPED=0; FAILED=0
for command in $COMMANDS; do
    case "$SKIP" in
        *" $command "*)
            say "  ${DIM}$command  skipped (a launcher: every argument is the program's)${RESET}"
            SKIPPED=$((SKIPPED + 1))
            continue
            ;;
    esac
    file="$DIR_OPT/$command.toml"
    if [ -e "$file" ] && [ "$FORCE" != 1 ]; then
        say "  ${DIM}$command  kept${RESET}   $file"
        KEPT=$((KEPT + 1))
        continue
    fi
    if [ "$FORCE" = 1 ] && [ -e "$file" ]; then
        out="$(tdd "$command" config --create --force 2>&1)"
    else
        out="$(tdd "$command" config --create 2>&1)"
    fi
    if [ $? -eq 0 ]; then
        say "  ${GREEN}$command  created${RESET} $file"
        CREATED=$((CREATED + 1))
    else
        say "  ${YELLOW}$command  failed${RESET}  $(printf '%s' "$out" | grep -v '^details:' | tail -1)"
        FAILED=$((FAILED + 1))
    fi
done

say ""
say "${GREEN}installed${RESET} $DIR_OPT"
say "  configs   $CREATED created, $KEPT kept, $SKIPPED skipped$([ "$FAILED" -gt 0 ] && printf ', %s failed' "$FAILED")"
say "  source it  source $DIR_OPT/tdd-source.sh"
[ "$FAILED" -eq 0 ] || exit 1
