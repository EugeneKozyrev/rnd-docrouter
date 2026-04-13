#!/bin/sh
set -e

info() { printf '%s [INFO] %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${0##*/}" "$*"; }
warn() { printf '%s [WARN] %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${0##*/}" "$*"; }
err()  { printf '%s [ERROR] %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${0##*/}" "$*"; exit 1; }

cmd="uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --log-level debug --workers 1"

if [ "$#" -gt 0 ]; then
    info "Starting container with command: $@"
    exec "$@"
else
    info "Starting container with command: $cmd"
    exec $cmd
fi