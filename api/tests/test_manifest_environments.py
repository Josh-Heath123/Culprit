"""`culprit.yaml`'s `environments:` section on the control-plane side
(Phase 30 field 10).

The control plane never acts on the section — capture runs in the CLI —
but `apply-model` has to *accept* a manifest that carries it and
`--export` has to give it back, or the documented
`apply-model --export > culprit.yaml` workflow deletes a user's grants.
The same defect Phase 27's audit found in `declared_by` and Phase 28
guarded against for `extract:`. Pure: no database.
"""

from pathlib import Path

import pytest
from app.model.manifest import ManifestError, dump_manifest, load_manifest

DEMO = Path(__file__).parents[2] / "cli" / "testdata" / "demo" / "culprit.yaml"


def test_the_demo_manifest_loads_and_round_trips() -> None:
    manifest = load_manifest(DEMO.read_text(encoding="utf-8"))
    assert manifest.environments is not None
    assert set(manifest.environments) == {"staging", "production"}

    exported = dump_manifest(manifest)
    again = load_manifest(exported)
    assert again == manifest, "the export must parse to the manifest that was applied"
    assert dump_manifest(again) == exported, "export must be a fixed point"


BASE = """
version: 1
components:
  - name: orders-api
environments:
  production:
    adapter: compose
    components:
      {component}:
        database: {{dsn_env: {dsn_env}}}
"""


def test_an_undeclared_component_is_refused() -> None:
    with pytest.raises(ManifestError, match="not declared"):
        load_manifest(BASE.format(component="payments-api", dsn_env="DB_URL"))


def test_a_connection_string_where_a_variable_name_belongs_is_refused_without_echo() -> None:
    dsn = "postgresql://orders:hunter2-manifest@db:5432/orders"
    with pytest.raises(ManifestError) as caught:
        load_manifest(BASE.format(component="orders-api", dsn_env=f'"{dsn}"'))
    assert "hunter2" not in str(caught.value)


def test_an_unknown_adapter_is_refused() -> None:
    with pytest.raises(ManifestError):
        load_manifest(
            "version: 1\ncomponents: [{name: a}]\n"
            "environments: {x: {adapter: ssh, components: {a: {}}}}\n"
        )


_ECHO_HEADER = """
version: 1
components: [{name: orders-api}]
environments:
  production:
    adapter: process
    components:
      orders-api:
"""

ECHO_CASES = {
    # The invariant audit's two reproductions. Neither is the `user:pass@`
    # form `_reject_credentials` matches, so both reach pydantic — whose
    # default error message appends `input_value=` for every error.
    "dsn": _ECHO_HEADER
    + """        database:
          dsn_env: 'postgresql://app@db.internal/orders?password=hunter2-q'
""",
    "host": _ECHO_HEADER
    + """        endpoint: {host: 'admin:hunter2-q@db', port: 5432}
""",
}


@pytest.mark.parametrize("case", sorted(ECHO_CASES))
def test_a_refused_field_is_never_echoed(case: str) -> None:
    with pytest.raises(ManifestError, match=r"does not match the culprit\.yaml schema") as caught:
        load_manifest(ECHO_CASES[case])
    assert "hunter2" not in str(caught.value)


@pytest.mark.parametrize(
    "grants",
    [
        pytest.param("{db.schema.write: true}", id="a write capability"),
        pytest.param("{config.read.values: true}", id="a blanket value grant"),
        pytest.param("{config.read.name: true}", id="a typo"),
        pytest.param("{db.metadata.read: [orders]}", id="a list where a bool belongs"),
    ],
)
def test_grants_outside_the_closed_set_are_refused(grants: str) -> None:
    """docs/PERMISSIONS.md says these are validation errors. Until the
    Phase 30 audit that was true of the Go loader only."""
    with pytest.raises(ManifestError):
        load_manifest(
            "version: 1\ncomponents: [{name: a}]\n"
            f"environments: {{x: {{adapter: process, grants: {grants}, "
            "components: {a: {}}}}\n"
        )


QUICKSTART_MODEL = Path(__file__).parents[2] / "demo-services" / "culprit.yaml"


def test_the_quickstart_model_loads() -> None:
    """`just quickstart` applies demo-services/culprit.yaml with this
    loader. Phase 32 part 1 gave it `tokens:` maps, which the credential
    check refused — and the bootstrap's `| tee` hid the exit status, so a
    fresh quickstart started demo services with no ingest keys. Nothing
    loaded this file in a test until then; this does."""
    manifest = load_manifest(QUICKSTART_MODEL.read_text(encoding="utf-8"))
    assert manifest.environments is not None
    assert {"faults-order", "quickstart"} <= set(manifest.environments)
    exported = dump_manifest(manifest)
    assert load_manifest(exported) == manifest, "export must keep endpoints and tokens"


TOKENS = """
version: 1
components:
  - name: orders-api
  - name: stock-api
environments:
  production:
    adapter: process
    components:
      orders-api:
        tokens: {{stock-api: {variable}}}
"""


def test_a_token_reference_names_a_variable() -> None:
    load_manifest(TOKENS.format(variable="STOCK_TOKEN"))


def test_a_token_where_its_variable_name_belongs_is_refused_without_echo() -> None:
    token = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJzdG9jayJ9.c2lnbmF0dXJl"
    with pytest.raises(ManifestError) as refused:
        load_manifest(TOKENS.format(variable=f'"{token}"'))
    assert token not in str(refused.value)
    assert "name" in str(refused.value)


def test_tokens_anywhere_else_is_still_a_credential() -> None:
    with pytest.raises(ManifestError, match="looks like a credential"):
        load_manifest("version: 1\ncomponents:\n  - name: a\n    labels: {tokens: abc}\n")


@pytest.mark.parametrize(
    "token", ["ghp_abcdefghijklmnopqrstuvwxyz0123456789", "AKIAIOSFODNN7EXAMPLE"]
)
def test_a_credential_shaped_like_a_variable_name_is_still_refused(token: str) -> None:
    with pytest.raises(ManifestError) as refused:
        load_manifest(TOKENS.format(variable=token))
    assert token not in str(refused.value)
