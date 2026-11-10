#!/usr/bin/env bash
# The agent's Kubernetes and systemd recipes, checked for real (Phase 33
# part 3), against a running quickstart. CI's e2e job runs it after the
# browser journeys, which ran the Compose recipe (frontend/e2e/agents.spec.ts).
#
#   1. systemd: `systemd-analyze verify` on deploy/agent/systemd/, with the
#      binary installed where the unit's ExecStart says. Any complaint about
#      the unit fails it.
#   2. Kubernetes: deploy/agent/kubernetes.yaml applied as it is to a kind
#      cluster (KIND_CLUSTER, already running), its agent paired with the
#      quickstart, then Ready — as a non-root user, with a read-only root
#      filesystem, not restarted — and the control plane has recorded a
#      signed request from it.
#
# CI's patch to the applied Deployment is two things a CI runner needs and a
# real cluster does not: the image this commit built, loaded into kind, and
# a host alias for the quickstart on the host. Its agent configuration sets
# allow_plain_http, because the quickstart is plain http; no recipe does.
#
# Needs: a running `just quickstart` (QUICKSTART_HTTP_PORT), the image
# culprit-quickstart-cli it built, kind, kubectl, sudo.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
port="${QUICKSTART_HTTP_PORT:-80}"
cluster="${KIND_CLUSTER:?the kind cluster to use}"
base="http://localhost:$port/api"
work="$(mktemp -d)"

# On the way out: if anything failed, say why the cluster thinks so — the
# pod's state, its events, and what the agent itself printed (it exits on
# any refusal, so its last lines are the reason). Then clean up; the key
# directory is the agent user's, so it takes sudo.
finish() {
    local status=$?
    if [ "$status" -ne 0 ] && command -v kubectl >/dev/null && kubectl get namespace culprit-agent >/dev/null 2>&1; then
        echo "==> diagnostics (exit $status)"
        kubectl -n culprit-agent get pods,pvc -o wide || true
        kubectl -n culprit-agent describe pods || true
        kubectl -n culprit-agent logs deployment/culprit-agent --all-containers --tail=50 || true
        kubectl -n culprit-agent logs deployment/culprit-agent --all-containers --previous --tail=50 || true
        kubectl -n culprit-agent get events --sort-by=.lastTimestamp || true
    fi
    sudo rm -rf "$work" 2>/dev/null || rm -rf "$work" 2>/dev/null || true
    exit "$status"
}
trap finish EXIT

read_env() { grep -E "^$1=" "$repo/infra/.env.prod" | cut -d= -f2- | sed 's/\$\$/$/g'; }

# ---- 1. systemd ------------------------------------------------------------------
echo "==> systemd-analyze verify deploy/agent/systemd/culprit-agent.service"
binary="$(mktemp)"
cid="$(docker create culprit-quickstart-cli)"
docker cp "$cid:/culprit" "$binary" >/dev/null
docker rm "$cid" >/dev/null
sudo install -m 0755 "$binary" /usr/local/bin/culprit
unit="$work/culprit-agent.service"
install -m 0644 "$repo/deploy/agent/systemd/culprit-agent.service" "$unit"
verify="$(systemd-analyze verify "$unit" 2>&1)" || { echo "$verify"; echo "FAIL: systemd-analyze verify" >&2; exit 1; }
echo "$verify"
if echo "$verify" | grep -F "culprit-agent.service"; then
    echo "FAIL: systemd-analyze has something to say about the unit" >&2
    exit 1
fi
echo "systemd unit: verified"

# ---- 2. Kubernetes, in kind ------------------------------------------------------
echo "==> deploy/agent/kubernetes.yaml in kind cluster $cluster"
docker tag culprit-quickstart-cli culprit-agent:ci
# Through an archive: `kind load docker-image` reports success and leaves
# nothing on the node when Docker keeps images in its containerd store
# (CI run 42804120023: ImagePullBackOff on docker.io/library/culprit-agent:ci).
docker save culprit-agent:ci -o "$work/agent-image.tar"
kind load image-archive "$work/agent-image.tar" --name "$cluster"
docker exec "$cluster-control-plane" crictl images | grep -F culprit-agent     || { echo "FAIL: the agent image is not on the kind node" >&2; exit 1; }

token="$(curl -fsS -X POST "$base/auth/login" -H 'Content-Type: application/json' \
    --data-binary @- <<JSON | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
{"username": "$(read_env QUICKSTART_ADMIN_USERNAME)", "password": "$(read_env QUICKSTART_ADMIN_PASSWORD)"}
JSON
)"
code="$(curl -fsS -X POST "$base/agents/pairing-codes" -H "Authorization: Bearer $token" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["code"])')"
agent_id="kind-agent-$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')"

# The key and the pairing, outside the cluster, as the recipe's header says;
# then the key goes into a Secret.
mkdir -p "$work/config" "$work/secrets"
cp "$repo/demo-services/culprit.yaml" "$work/config/culprit.yaml"
cat > "$work/config/agent.yaml" <<YAML
version: 1
agent_id: $agent_id
manifest: ./culprit.yaml
key: /run/secrets/agent.key
control_plane:
  url: http://host.docker.internal:$port/api
  # CI's own configuration, not a recipe's: the quickstart serves plain http.
  allow_plain_http: true
environments:
  quickstart:
    grants:
      net.tcp.connect: true
      net.http.outbound: true
YAML
chmod -R a+rX "$work/config"
(cd "$work" && CULPRIT_AGENT_IMAGE=culprit-agent:ci bash "$repo/deploy/agent/docker.sh" init)
printf '%s\n' "$code" | (cd "$work" && docker run --rm -i --add-host host.docker.internal:host-gateway \
    --user 65532:65532 --read-only --cap-drop ALL \
    -v "$work/config:/etc/culprit:ro" -v "$work/secrets/agent.key:/run/secrets/agent.key:ro" \
    culprit-agent:ci agent pair --config /etc/culprit/agent.yaml --code -)

kubectl create namespace culprit-agent
sudo cat "$work/secrets/agent.key" | kubectl -n culprit-agent create secret generic culprit-agent-key \
    --from-file=agent.key=/dev/stdin
kubectl -n culprit-agent create configmap culprit-agent-config \
    --from-file=agent.yaml="$work/config/agent.yaml" --from-file=culprit.yaml="$work/config/culprit.yaml"
kubectl apply -f "$repo/deploy/agent/kubernetes.yaml"

gateway="$(docker network inspect kind -f '{{range .IPAM.Config}}{{.Gateway}} {{end}}' | tr ' ' '\n' | grep -E '^[0-9.]+$' | head -1)"
[ -n "$gateway" ] || { echo "FAIL: no IPv4 gateway on the kind network to reach the host" >&2; exit 1; }
echo "host.docker.internal -> $gateway (the kind network's gateway)"
kubectl -n culprit-agent set image deployment/culprit-agent agent=culprit-agent:ci
kubectl -n culprit-agent patch deployment culprit-agent --type=json -p "[
  {\"op\": \"add\", \"path\": \"/spec/template/spec/containers/0/imagePullPolicy\", \"value\": \"Never\"},
  {\"op\": \"add\", \"path\": \"/spec/template/spec/hostAliases\",
   \"value\": [{\"ip\": \"$gateway\", \"hostnames\": [\"host.docker.internal\"]}]}
]"
kubectl -n culprit-agent rollout status deployment/culprit-agent --timeout=180s
kubectl -n culprit-agent wait pod -l app.kubernetes.io/name=culprit-agent --for=condition=Ready --timeout=120s

# Ready, and staying up: the agent exits on any refusal or audit failure, so
# a pod that is still Ready, unrestarted, after several polls is one that is
# talking to its control plane.
sleep 20
pod="$(kubectl -n culprit-agent get pod -l app.kubernetes.io/name=culprit-agent -o jsonpath='{.items[0].metadata.name}')"
kubectl -n culprit-agent logs "$pod" || true
restarts="$(kubectl -n culprit-agent get pod "$pod" -o jsonpath='{.status.containerStatuses[0].restartCount}')"
ready="$(kubectl -n culprit-agent get pod "$pod" -o jsonpath='{.status.containerStatuses[0].ready}')"
uid="$(kubectl -n culprit-agent get pod "$pod" -o jsonpath='{.spec.securityContext.runAsUser}')"
readonly_root="$(kubectl -n culprit-agent get pod "$pod" -o jsonpath='{.spec.containers[0].securityContext.readOnlyRootFilesystem}')"
echo "pod $pod: ready=$ready restarts=$restarts runAsUser=$uid readOnlyRootFilesystem=$readonly_root"
[ "$ready" = "true" ] || { echo "FAIL: the agent pod is not Ready" >&2; exit 1; }
[ "$restarts" = "0" ] || { echo "FAIL: the agent restarted $restarts time(s)" >&2; exit 1; }
[ "$uid" != "0" ] && [ -n "$uid" ] || { echo "FAIL: the agent runs as root" >&2; exit 1; }
[ "$readonly_root" = "true" ] || { echo "FAIL: the root filesystem is writable" >&2; exit 1; }

last="$(curl -fsS "$base/agents" -H "Authorization: Bearer $token" | python3 -c "
import json, sys
for item in json.load(sys.stdin)['items']:
    if item['id'] == '$agent_id':
        print(item['last_request_at'] or '')
")"
[ -n "$last" ] || { echo "FAIL: the control plane has no signed request from $agent_id" >&2; exit 1; }
echo "Kubernetes recipe: $agent_id Ready, non-root, read-only root, last signed request $last"
