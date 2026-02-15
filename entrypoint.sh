#!/bin/sh
set -e

# Fix ownership of the persistent data volume.
# Previous deployments ran as root, so /app/data/* may be owned by root:root.
# The non-root 'rot' user (uid 1000) needs write access for SQLite WAL mode.
if [ "$(id -u)" = "0" ]; then
    chown -R rot:rot /app/data 2>/dev/null || true
    exec gosu rot "$@"
else
    # Already running as non-root (Railway may set the user)
    exec "$@"
fi
