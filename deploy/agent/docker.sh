#!/usr/bin/env bash
# Culprit agent — plain Docker recipe (Phase 33 part 3).
#
# The same container compose.yaml describes, as `docker run` commands, for
# a machine without Compose. Non-root (65532), read-only root filesystem, no
# capabilities, no new privileges, no published port; the key mounted
# read-only from a file owned by 65532 with mode 0600; the audit log in a
# named volume. It reaches the control plane only outbound, over https.
#
# Usage, from a directory holding config/agent.yaml (key:
# /run/secrets/agent.key) and config/culprit.yaml:
#
#   deploy/agent/docker.sh init                  # writes secrets/agent.key, once
#   deploy/agent/docker.sh pair < code.txt       # spends the pairing code
#   deploy/agent/docker.sh run                   # starts the agent
#
# Environment: CULPRIT_TARGET_NETWORK (required for run: the network your
# services are on), CULPRIT_AGENT_IMAGE (default the published image).
set -euo pipefail

image="${CULPRIT_AGENT_IMAGE:-ghcr.io/josh-heath123/culprit/cli:latest}"
here="$(pwd)"
config="$here/config"
secrets="$here/secrets"

# Every container this recipe starts runs under these.
hardened=(--user 65532:65532 --read-only --cap-drop ALL --security-opt no-new-privileges:true)

case "${1:-}" in
    init)
        # The key is written by the agent's own user into a directory only
        # that user can enter, so it is never readable by anyone else.
        mkdir -p "$secrets"
        if [ "$(id -u)" = 0 ]; then
            chown 65532:65532 "$secrets"
        else
            sudo chown 65532:65532 "$secrets"
        fi
        chmod 0700 "$secrets" 2>/dev/null || sudo chmod 0700 "$secrets"
        docker run --rm "${hardened[@]}" \
            -v "$config:/etc/culprit:ro" -v "$secrets:/run/secrets" \
            "$image" agent init --config /etc/culprit/agent.yaml
        ;;
    pair)
        docker run --rm -i "${hardened[@]}" \
            -v "$config:/etc/culprit:ro" -v "$secrets/agent.key:/run/secrets/agent.key:ro" \
            "$image" agent pair --config /etc/culprit/agent.yaml --code -
        ;;
    run)
        : "${CULPRIT_TARGET_NETWORK:?name the Docker network your services are on}"
        docker run -d --name culprit-agent --restart unless-stopped "${hardened[@]}" \
            --network "$CULPRIT_TARGET_NETWORK" \
            -v "$config:/etc/culprit:ro" -v "$secrets/agent.key:/run/secrets/agent.key:ro" \
            -v culprit-agent-state:/var/lib/culprit \
            "$image" agent --config /etc/culprit/agent.yaml --audit /var/lib/culprit/audit.log
        ;;
    *)
        echo "usage: $0 init | pair < code.txt | run" >&2
        exit 2
        ;;
esac
