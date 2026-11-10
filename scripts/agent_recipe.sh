#!/usr/bin/env bash
# Drives the shipped agent recipes against a running quickstart (Phase 33
# part 3). Used by the browser journeys (frontend/e2e/agents.spec.ts) and by
# `just agent-recipes` in CI. Nothing here is a recipe: it writes CI's own
# agent configuration and runs deploy/agent/ as an operator would.
#
#   agent_recipe.sh compose-prepare <work> <agent-id>   config + key, via deploy/agent/docker.sh init
#   agent_recipe.sh compose-pair <work>                 the pairing code on stdin
#   agent_recipe.sh compose-up <work> | compose-down <work> | compose-logs <work>
#
# CI's configuration differs from a deployment's in one way, said where it
# is written: the quickstart is plain http on the host, so it sets
# allow_plain_http, which the agent reports at every start. No file under
# deploy/agent/ sets it (scripts/tests/test_agent_recipes.py).
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
port="${QUICKSTART_HTTP_PORT:-80}"
image="${CULPRIT_AGENT_IMAGE:-culprit-quickstart-cli}"
network="${CULPRIT_TARGET_NETWORK:-culprit-quickstart_default}"
export MSYS_NO_PATHCONV=1

work="${2:?usage: agent_recipe.sh <command> <work-dir> [agent-id]}"

compose() {
    local id
    id="$(cat "$work/agent-id")"
    CULPRIT_AGENT_IMAGE="$image" CULPRIT_TARGET_NETWORK="$network" \
    CULPRIT_AGENT_CONFIG="$work/config" CULPRIT_AGENT_KEY="$work/secrets/agent.key" \
        docker compose -p "culprit-agent-$id" \
        -f "$repo/deploy/agent/compose.yaml" -f "$repo/cli/testdata/agent-recipes/compose.ci.yaml" "$@"
}

case "$1" in
    compose-prepare)
        id="${3:?an agent id}"
        mkdir -p "$work/config"
        echo "$id" > "$work/agent-id"
        cp "$repo/demo-services/culprit.yaml" "$work/config/culprit.yaml"
        cat > "$work/config/agent.yaml" <<YAML
version: 1
agent_id: $id
manifest: ./culprit.yaml
key: /run/secrets/agent.key
control_plane:
  url: http://host.docker.internal:$port/api
  # CI's own configuration, not a recipe's: the quickstart serves plain http.
  allow_plain_http: true
environments:
  quickstart:
    grants:
      net.dns.resolve: true
      net.tcp.connect: true
      net.http.outbound: true
      config.read.names: true
YAML
        chmod -R a+rX "$work/config"
        (cd "$work" && CULPRIT_AGENT_IMAGE="$image" bash "$repo/deploy/agent/docker.sh" init)
        ;;
    compose-pair)
        compose run --rm -T agent agent pair --config /etc/culprit/agent.yaml --code -
        ;;
    compose-up)
        compose up -d
        ;;
    compose-down)
        compose down -v --remove-orphans
        ;;
    compose-logs)
        compose logs --no-color agent
        ;;
    *)
        echo "unknown command: $1" >&2
        exit 2
        ;;
esac
