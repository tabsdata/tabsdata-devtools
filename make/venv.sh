#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#
# Print the python of the cargo-make tasks' own env, <tdd dir>/tdd-venvs/make,
# building it first when it is missing or was built from another PYTHON or
# requirements.txt. Every task that runs Python runs it from here:
#
#   PY="$("${MAKE_SCRIPTS}/venv.sh")"
#
# Built on exactly the repo's PYTHON, uv-managed only -- `uv venv` never takes
# an active venv, conda env or ./.venv for its interpreter, which `uv run` does.
# The check is two small files read and compared, nothing asked of uv: the env
# keeps a copy of what it was built from, and a rebuild is what a change costs.
#
# tdd itself is not installed here: it is the standard library only, so a task
# puts this checkout's tdd on PYTHONPATH -- an env shared by several checkouts
# must not hold any one of them.

set -euo pipefail

make_folder="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$make_folder")"
env="${TDD_DIR:-$HOME/.tdd}/tdd-venvs/make"
built_from="$env/built-from"
wanted="$(cat "$root/PYTHON" "$make_folder/requirements.txt")"

if [ -x "$env/bin/python" ] && [ -f "$built_from" ] &&
    [ "$(cat "$built_from")" = "$wanted" ]; then
    echo "$env/bin/python"
    exit 0
fi

python="$(cat "$root/PYTHON")"
echo "building the cargo-make tasks' env $env (python $python)" >&2
# Relocatable and copied from the cache, as every env in a tdd dir is.
export UV_LINK_MODE=copy
uv venv --quiet --clear --relocatable --managed-python --python "$python" "$env" >&2
uv pip install --quiet --python "$env" -r "$make_folder/requirements.txt" >&2
printf '%s' "$wanted" > "$built_from"
echo "$env/bin/python"
