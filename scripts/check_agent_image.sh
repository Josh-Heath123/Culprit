#!/usr/bin/env bash
# The agent image's three promises (docs/DIAGNOSTIC_PLAN.md Phase 33,
# field 14 and part 1's criteria), checked against a built image:
#
#   1. it is under 30 MB (30,000,000 bytes, as the daemon reports it);
#   2. it runs as a non-root user;
#   3. `culprit agent` runs with a read-only root filesystem — it writes
#      only to the task directory and audit log mounted for it — and
#      answers a task, refusing one it holds no grant for and running one
#      it does, with an audit log whose chain verifies.
#
# Usage: scripts/check_agent_image.sh <image>      (CI: local/cli:ci)
set -euo pipefail

image="${1:?usage: check_agent_image.sh <image>}"
limit=30000000

size=$(docker image inspect "$image" --format '{{.Size}}')
if [ "$size" -ge "$limit" ]; then
    echo "FAIL: $image is $size bytes; the agent image must be under $limit" >&2
    exit 1
fi
echo "size: $size bytes (< $limit)"

user=$(docker image inspect "$image" --format '{{.Config.User}}')
case "$user" in
    "" | 0 | root | 0:* | root:*)
        echo "FAIL: $image runs as '${user:-root}'; it must run as a non-root user" >&2
        exit 1
        ;;
esac
echo "user: $user (not root)"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/etc" "$work/var/tasks/inbox" "$work/var/tasks/outbox" "$work/var/tasks/done"

cat > "$work/etc/culprit.yaml" <<'YAML'
version: 1
components:
  - name: orders
    kind: service
    connections:
      - to: payments
        kind: http
        criticality: on_request_path
  - name: payments
    kind: service
environments:
  production:
    adapter: process
    components:
      orders: {}
    endpoints:
      payments: { host: localhost, port: 9, health_path: /health }
YAML
cat > "$work/etc/agent.yaml" <<'YAML'
version: 1
agent_id: image-check
manifest: ./culprit.yaml
environments:
  production:
    grants:
      net.dns.resolve: true
YAML
# Granted: resolve a name. Not granted: open a connection.
cat > "$work/var/tasks/inbox/resolve.json" <<'JSON'
{"id": "resolve", "environment": "production", "kind": "probe",
 "probe": {"probe_id": "probe.net.dns_resolve", "target": "connection:orders->payments",
           "inputs": {"host": "localhost"}}}
JSON
cat > "$work/var/tasks/inbox/connect.json" <<'JSON'
{"id": "connect", "environment": "production", "kind": "probe",
 "probe": {"probe_id": "probe.net.tcp_connect", "target": "connection:orders->payments",
           "inputs": {"host": "localhost", "port": 9}}}
JSON
chmod -R a+rwX "$work/var"

# Run as this host user, not the image's own (65532): the agent writes its
# results 0600, and on a Linux host the runner must be able to read them
# back. Still non-root (the image's default user is checked above) and
# still with a read-only root filesystem, which is what this run proves.
docker run --rm --read-only --network none --user "$(id -u):$(id -g)" \
    -v "$work/etc:/etc/culprit:ro" -v "$work/var:/var/culprit" \
    "$image" agent --once \
    --config /etc/culprit/agent.yaml --tasks /var/culprit/tasks --audit /var/culprit/audit.log

for id in resolve connect; do
    if [ ! -s "$work/var/tasks/outbox/$id.json" ]; then
        echo "FAIL: no result for task $id" >&2
        exit 1
    fi
done
grep -q '"outcome": "refused"' "$work/var/tasks/outbox/connect.json" || {
    echo "FAIL: the ungranted connect task was not refused" >&2
    cat "$work/var/tasks/outbox/connect.json" >&2
    exit 1
}
grep -q '"outcome": "completed"' "$work/var/tasks/outbox/resolve.json" || {
    echo "FAIL: the granted resolve task did not complete" >&2
    cat "$work/var/tasks/outbox/resolve.json" >&2
    exit 1
}

docker run --rm --read-only --network none --user "$(id -u):$(id -g)" -v "$work/var:/var/culprit:ro" \
    "$image" agent verify /var/culprit/audit.log
echo "OK: $image — under 30 MB, non-root, runs read-only, refuses what it was not granted"
