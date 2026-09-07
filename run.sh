#!/bin/sh
set -eu

script=$0
while [ -L "$script" ]; do
    directory=$(CDPATH= cd -- "$(dirname -- "$script")" && pwd)
    target=$(readlink "$script")
    case "$target" in
        /*) script=$target ;;
        *) script=$directory/$target ;;
    esac
done
root=$(CDPATH= cd -- "$(dirname -- "$script")" && pwd)

for candidate in "${HERDR_TASKS_PYTHON:-}" /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    [ -n "$candidate" ] || continue
    if "$candidate" -c 'import curses, sqlite3; raise SystemExit(0 if __import__("sys").version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        exec "$candidate" "$root/herdr_tasks.py" "$@"
    fi
done

echo "herdr-tasks requires Python 3.10+ with curses and sqlite3" >&2
exit 1
