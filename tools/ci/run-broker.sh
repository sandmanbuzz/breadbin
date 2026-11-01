#!/bin/sh
# Start the lease broker in its own container, published on localhost only.
#   tools/ci/run-broker.sh [start|stop|status]      (default start)
#   BREADBIN_BROKER=127.0.0.1:7077 tools/ci/lease -r vice -- cmd...
# Plain on the host, no container:  python3 tools/ci/broker.py --listen 127.0.0.1:7077
# State is in memory: restarting the broker drops all leases; clients must re-request.
# Containers reach it at host.containers.internal:7077 (run.sh rewrites that for you).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
port=${BREADBIN_BROKER_PORT:-7077}
img=${BREADBIN_BROKER_IMAGE:-mirror.gcr.io/library/python:3.14-slim}
name=breadbin-ci-broker
case ${1:-start} in
    start)
        podman rm -f "$name" >/dev/null 2>&1 || true
        podman run -d --rm --init --name "$name" -p "127.0.0.1:$port:$port" \
            -v "$here:/ci:ro" "$img" python3 -u /ci/broker.py --listen "0.0.0.0:$port" >/dev/null
        echo "broker up on 127.0.0.1:$port (export BREADBIN_BROKER=127.0.0.1:$port)" ;;
    stop) podman rm -f "$name" ;;
    status) BREADBIN_BROKER=127.0.0.1:$port python3 "$here/broker.py" status ;;
    *) echo "usage: run-broker.sh [start|stop|status]" >&2; exit 2 ;;
esac
