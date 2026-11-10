# Running a Culprit agent

An agent runs Culprit's read-only probes where your services are, and walks
a request path from a symptom when the control plane asks it to. It holds
its own grants (its configuration file), its own key, and its own audit log.
The control plane can withhold any of its grants for a task; nothing can add
one. See `docs/PERMISSIONS.md` for every grant and `docs/SECURITY.md` for
what a compromised agent or control plane can and cannot do.

Every recipe here runs the agent the same way:

- **Outbound only.** It opens no port and needs none. It reaches the control
  plane over **https**; plain http is refused except to a loopback address,
  and no recipe here allows it.
- **Non-root, read-only.** User 65532, a read-only root filesystem, no
  capabilities, no privilege escalation. It writes one thing: its audit log.
- **The key is a secret.** A file only the agent's user can read, mounted
  read-only. The key is the agent's identity: pairing again means a new key
  and a new agent id.
- **The audit log persists.** The control plane holds the same hash chain;
  an agent that lost its log could not extend it, and would be refused.
- **One agent, one key.** Never run two copies of one agent. For an agent per
  node or per host, pair one per node, each with its own id and key.

| Recipe | File | Checked in CI |
|---|---|---|
| Docker Compose | `compose.yaml` | run against the quickstart, end to end, from a pairing code made in the browser |
| Kubernetes | `kubernetes.yaml` | applied in a kind cluster, paired with the quickstart, Ready as non-root with a read-only root filesystem |
| systemd | `systemd/culprit-agent.service` | `systemd-analyze verify` |
| Plain Docker | `docker.sh` | the same container as Compose; the image is checked by `scripts/check_agent_image.sh` |

## 1. The configuration

Copy `agent.example.yaml` to `agent.yaml` and set `agent_id`, the control
plane's `url` (your dashboard's address, with `/api`), and the grants for each
environment. `manifest` names your system model (`culprit.yaml`), which goes
beside it. `docs/PERMISSIONS.md` lists the minimum grants for each kind of
investigation.

`key:` names where the recipe mounts the key: `/run/secrets/agent.key` for
Docker, Compose and Kubernetes; `/run/credentials/culprit-agent.service/agent.key`
for systemd.

## 2. The key

`culprit agent init` writes a new Ed25519 key to the path `key:` names, with
mode 0600, and never overwrites one. The private key never leaves that file;
pairing sends only its public half.

- **Docker or Compose:** `deploy/agent/docker.sh init`, from the directory
  holding `config/`. It writes `secrets/agent.key`, owned by 65532.
- **Kubernetes:** run `culprit agent init` anywhere with a configuration whose
  `key:` is a local path, then `kubectl -n culprit-agent create secret generic
  culprit-agent-key --from-file=agent.key` and delete the local copy.
- **systemd:** `culprit agent init` with `key: /etc/culprit/agent.key`, then
  set `key:` back to the credentials path above. The file stays root's, 0600;
  systemd hands the service its own copy.

## 3. Pairing

In the dashboard, **Settings → Agents → Create a pairing code**. It works once
and expires after 15 minutes. Where the agent is:

```sh
culprit agent pair --config agent.yaml --code -      # paste the code, then Ctrl-D
```

`--code -` reads it from standard input, so it is in neither your shell's
history nor the process list. Compose: `docker compose run --rm -T agent agent
pair --config /etc/culprit/agent.yaml --code - < code.txt`. Plain Docker:
`deploy/agent/docker.sh pair < code.txt`.

A newly paired agent is allowed **nothing**. Choose what it may use under
**Settings → Agents → Edit allowance**: only grants it reports holding are
offered.

## 4. Running it

- **Compose:** `CULPRIT_TARGET_NETWORK=<your services' network> docker compose
  up -d`, from this directory (or with `-f`), with `config/` and
  `secrets/agent.key` beside `compose.yaml`.
- **Plain Docker:** `CULPRIT_TARGET_NETWORK=... deploy/agent/docker.sh run`.
- **Kubernetes:** create the namespace, the Secret and the ConfigMap as the
  file's header says, then `kubectl apply -f kubernetes.yaml`.
- **systemd:** install the binary, the configuration and the unit as the
  unit's header says, then `systemctl enable --now culprit-agent`.

## Revoking

**Settings → Agents → Revoke.** The agent's very next request is refused, and
every one after; it exits, and a restart policy only repeats the refusal.
Remove the deployment, and the key with it.

## What the agent can see from where it runs

A walk tests what can be tested from the agent's vantage. Run it beside a
service (Compose and Docker on that service's network; Kubernetes in its
namespace) and the connections from that service, and its configuration,
can be read only if the agent runs *inside* it — see `docs/LIMITS.md`. An
investigation that could not test something says so, and names the grant or
the vantage it lacked.
