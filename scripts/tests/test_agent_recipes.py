"""The agent's deployment recipes keep their promises (Phase 33 part 3).

Read as files, not run: CI runs them too (the Compose recipe against the
quickstart, the Kubernetes one in kind, the systemd unit through
`systemd-analyze verify` — `just agent-recipes`), but the promises below
must hold for whoever copies a recipe, before anything runs it:

- no recipe allows plain http, and every control-plane URL in one is https;
- the agent runs as a non-root user, with a read-only root filesystem and no
  capabilities;
- its key is mounted as a secret, read-only, mode 0600;
- it publishes no port, and one recipe is one agent.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
RECIPES = ROOT / "deploy" / "agent"


def _files() -> list[Path]:
    files = [p for p in RECIPES.rglob("*") if p.is_file()]
    assert len(files) >= 5, f"deploy/agent/ holds only {files}"
    return files


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.relative_to(RECIPES).as_posix())
def test_no_recipe_allows_plain_http(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # The setting may be *named* in prose that forbids it; it is never set.
    assert not re.search(r"^\s*allow_plain_http\s*:", text, re.MULTILINE), (
        f"{path.name} sets allow_plain_http"
    )
    for match in re.finditer(r"^\s*url\s*:\s*(\S+)", text, re.MULTILINE):
        assert match.group(1).startswith("https://"), f"{path.name}: control_plane url {match.group(1)}"


def test_the_example_configuration_is_https_and_names_the_mounted_key() -> None:
    config = yaml.safe_load((RECIPES / "agent.example.yaml").read_text(encoding="utf-8"))
    assert config["control_plane"]["url"].startswith("https://")
    assert "allow_plain_http" not in config["control_plane"]
    assert config["key"] == "/run/secrets/agent.key"
    for grants in config["environments"].values():
        for name in grants["grants"]:
            assert "*" not in name and name != "all" and not name.endswith(".write")


def test_the_compose_recipe() -> None:
    recipe = yaml.safe_load((RECIPES / "compose.yaml").read_text(encoding="utf-8"))
    assert list(recipe["services"]) == ["agent"], "one recipe, one agent"
    agent = recipe["services"]["agent"]
    user = str(agent["user"]).split(":")[0]
    assert user not in ("0", "root") and int(user) > 0
    assert agent["read_only"] is True
    assert agent["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in agent["security_opt"]
    assert "ports" not in agent and "expose" not in agent
    assert "deploy" not in agent or agent["deploy"].get("replicas", 1) == 1
    assert agent["secrets"] == [{"source": "agent-key", "target": "agent.key"}]
    assert "file" in recipe["secrets"]["agent-key"]
    assert any(str(v).endswith(":/etc/culprit:ro") for v in agent["volumes"]), "the config is read-only"


def test_the_kubernetes_recipe() -> None:
    documents = [
        d for d in yaml.safe_load_all((RECIPES / "kubernetes.yaml").read_text(encoding="utf-8")) if d
    ]
    kinds = [d["kind"] for d in documents]
    assert "Service" not in kinds and "DaemonSet" not in kinds, kinds
    (deployment,) = [d for d in documents if d["kind"] == "Deployment"]
    spec = deployment["spec"]
    assert spec["replicas"] == 1 and spec["strategy"]["type"] == "Recreate", "one agent, never two at once"
    pod = spec["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] != 0
    (container,) = pod["containers"]
    assert "ports" not in container
    security = container["securityContext"]
    assert security["readOnlyRootFilesystem"] is True
    assert security["allowPrivilegeEscalation"] is False
    assert security["capabilities"]["drop"] == ["ALL"]
    (key,) = [v for v in pod["volumes"] if v["name"] == "key"]
    assert key["secret"]["defaultMode"] == 0o600
    mounts = {m["name"]: m for m in container["volumeMounts"]}
    assert mounts["key"]["readOnly"] is True and mounts["config"]["readOnly"] is True
    assert any(v.get("persistentVolumeClaim") for v in pod["volumes"]), "the audit log must persist"


def test_the_systemd_unit() -> None:
    unit = (RECIPES / "systemd" / "culprit-agent.service").read_text(encoding="utf-8")
    settings = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in unit.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert settings["DynamicUser"] == "yes", "a transient unprivileged user"
    assert settings["NoNewPrivileges"] == "yes"
    assert settings["ProtectSystem"] == "strict", "the filesystem read-only but for StateDirectory"
    assert settings["CapabilityBoundingSet"] == ""
    assert settings["LoadCredential"].startswith("agent.key:"), "the key is a credential"
    assert "StateDirectory" in settings, "the audit log persists"
    assert "--audit /var/lib/culprit-agent/" in settings["ExecStart"]
