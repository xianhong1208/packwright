#!/bin/sh
# Prepare the /data volume, then run the service (exec, so tini signals reach it).
set -e

if ! touch /data/.write-test 2>/dev/null; then
    echo "Packwright: /data is not writable by uid $(id -u)." >&2
    echo "Give the volume to uid 1000, e.g.  sudo chown -R 1000:1000 <host dir>" >&2
    exit 1
fi
rm -f /data/.write-test
mkdir -p /data/workspace /data/docker_images /data/nuitka-cache /data/uv-cache

exec "$@"
