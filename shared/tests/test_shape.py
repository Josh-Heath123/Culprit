"""`ValueShape` cannot carry a literal — proved by attempting it.

Phase 28 acceptance criterion 3: "A `Fact` about a config key **cannot be
constructed carrying a literal value** — not through the API, not by
serialising a bundle that never touches the database. Proved by
attempting it in a test, not by inspection."

So this file attempts it, six ways, including the exact payload the Phase
27 invariant audit demonstrated against the free-JSONB version of
`configured_facts.value_shape`.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from culprit_model import build
from culprit_model.facts import Fact, Provenance
from culprit_model.planes import ConfidenceRank, Plane, SourceKind
from culprit_model.protocol import CaptureBundle, Predicate
from culprit_model.shape import (
    LengthClass,
    ValueFormat,
    ValueShape,
    ValueType,
    classify_format,
)
from pydantic import ValidationError

#: The value from docs/HANDOFF.md §3 Q5 — the one that "inserts happily
#: with no grant_ref" against a free-form JSONB shape column.
LEAKED_DSN = "postgresql://u:hunter2@db/orders"


def _provenance() -> Provenance:
    return Provenance(
        source_kind=SourceKind.STATIC,
        extractor="culprit-extract-python@0.1.0",
        artefact=".env.example",
        locator="L3",
        confidence_rank=ConfidenceRank.STATIC_FRAMEWORK_CODE,
    )


def _config_fact(**overrides: object) -> Fact:
    payload: dict[str, object] = {
        "plane": Plane.CONFIGURED,
        "subject": build("config", component="orders-svc", key="DATABASE_URL"),
        "predicate": Predicate.VALUE_SHAPE,
        "value_shape": ValueShape.of(LEAKED_DSN),
        "environment": "staging",
        "provenance": _provenance(),
        "captured_at": datetime.now(UTC),
        "capture_id": uuid4(),
    }
    payload.update(overrides)
    return Fact(**payload)  # pyright: ignore[reportArgumentType]


# --- the shape itself has nowhere to put a literal ---------------------


def test_extra_field_on_value_shape_is_refused() -> None:
    """The exact Q5 payload, rejected by the type rather than by review."""
    with pytest.raises(ValidationError):
        ValueShape(**{"type": "string", "sample": LEAKED_DSN})  # type: ignore[arg-type]


def test_value_shape_fields_are_all_closed() -> None:
    """No field of a ValueShape accepts free text.

    Asserted over the model's own fields rather than by naming them, so
    adding a fifth field that *is* free text fails here instead of
    quietly reopening the hole this type exists to close.
    """
    for name, field in ValueShape.model_fields.items():
        annotation = field.annotation
        assert annotation in (ValueType, LengthClass, ValueFormat, bool), (
            f"ValueShape.{name} is annotated {annotation!r} — every field must be a "
            "closed enum or a bool, or a literal config value can be carried in it"
        )


def test_of_classifies_without_retaining() -> None:
    shape = ValueShape.of(LEAKED_DSN)
    assert shape.type is ValueType.STRING
    assert shape.format is ValueFormat.DSN
    assert shape.length_class is LengthClass.MEDIUM
    assert LEAKED_DSN not in shape.model_dump_json()
    assert "hunter2" not in shape.model_dump_json()


def test_absent_and_unknown_are_different_claims() -> None:
    assert ValueShape.absent().present is False
    assert ValueShape.unknown().present is True
    assert ValueShape.unknown().type is ValueType.UNKNOWN
    assert ValueShape.absent() != ValueShape.unknown()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("postgresql://u:p@db/orders", ValueFormat.DSN),
        ("https://api.example.com/v1", ValueFormat.URL),
        ("-----BEGIN RSA PRIVATE KEY-----\nMII", ValueFormat.SECRET),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig", ValueFormat.SECRET),
        ("AKIAIOSFODNN7EXAMPLE", ValueFormat.SECRET),
        ("ghp_abcdefghijklmnopqrstuvwxyz0123", ValueFormat.SECRET),
        ("ops@example.com", ValueFormat.EMAIL),
        ("8bd0e2e1-2b0a-4a1e-9c0f-0d1a2b3c4d5e", ValueFormat.UUID),
        ("true", ValueFormat.BOOLEANISH),
        ("5432", ValueFormat.PORT),
        ("30s", ValueFormat.DURATION),
        ("-12.5", ValueFormat.NUMERIC),
        ("10.0.0.7", ValueFormat.IP_ADDRESS),
        ("/var/run/app.sock", ValueFormat.PATH),
        ('{"a": 1}', ValueFormat.JSON),
        ("db.internal.example.com", ValueFormat.HOSTNAME),
        ("some-opaque-token-value-here", ValueFormat.OPAQUE),
        ("", ValueFormat.NOT_APPLICABLE),
    ],
)
def test_classify_format(value: str, expected: ValueFormat) -> None:
    assert classify_format(value) is expected


def test_classify_format_never_echoes_its_input() -> None:
    """A classification is a member of a closed enum, always."""
    assert classify_format(LEAKED_DSN) in set(ValueFormat)


# --- a Fact about a config key refuses an ungranted literal ------------


def test_config_fact_with_a_literal_value_and_no_grant_is_refused() -> None:
    with pytest.raises(ValidationError, match="grant_ref"):
        _config_fact(value=LEAKED_DSN)


def test_config_fact_with_an_empty_grant_ref_is_refused() -> None:
    """`grant_ref=""` is not a grant.

    The database CHECK (`value IS NULL OR grant_ref IS NOT NULL`) accepts
    an empty string, which docs/HANDOFF.md §3 Q5 called out as "related
    and cheaper". The type does not.
    """
    with pytest.raises(ValidationError, match="grant_ref"):
        _config_fact(value=LEAKED_DSN, grant_ref="   ")


def test_config_fact_with_a_real_grant_is_allowed() -> None:
    """The opt-in path still works — this is a guard, not a prohibition."""
    fact = _config_fact(value=LEAKED_DSN, grant_ref="config.read.values:DATABASE_URL")
    assert fact.value == LEAKED_DSN


def test_value_shape_is_refused_on_a_non_config_subject() -> None:
    with pytest.raises(ValidationError, match="value_shape"):
        Fact(
            plane=Plane.INTENT,
            subject=build("http", component="orders-svc", method="POST", path="/orders"),
            predicate="exists",
            value_shape=ValueShape.unknown(),
            provenance=_provenance(),
            captured_at=datetime.now(UTC),
            capture_id=uuid4(),
        )


def test_fact_forbids_unknown_fields() -> None:
    """An open model is a second door into the same room."""
    with pytest.raises(ValidationError):
        _config_fact(sample=LEAKED_DSN)


# --- and the bundle that never touches Postgres is safe too ------------


def test_serialised_bundle_cannot_contain_a_config_value() -> None:
    """The artefact the promise is actually about (§5).

    Built the way the CLI builds one, dumped the way `culprit intent`
    dumps one, and searched for the literal.
    """
    bundle = CaptureBundle(
        # CONFIGURED, matching the fact inside it. A bundle's plane and
        # its facts' planes must agree — `intent_facts` has no
        # `environment` column, so an INTENT bundle carrying a CONFIGURED
        # fact would store a reading of an environment as a claim about
        # intent. Enforced on CaptureBundle since the Phase 28 audit.
        plane=Plane.CONFIGURED,
        environment="staging",
        extractor="culprit@0.1.0",
        capture_id=uuid4(),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        facts=(_config_fact(),),
        meta={"root": "/repo"},
    )
    serialised = bundle.model_dump_json()
    assert LEAKED_DSN not in serialised
    assert "hunter2" not in serialised
    # And the shape survived, so this is not passing by emitting nothing.
    assert json.loads(serialised)["facts"][0]["value_shape"]["format"] == "dsn"


def test_bundle_round_trips() -> None:
    bundle = CaptureBundle(
        plane=Plane.CONFIGURED,
        environment="staging",
        extractor="culprit@0.1.0",
        capture_id=uuid4(),
        started_at=datetime.now(UTC),
        facts=(_config_fact(),),
    )
    assert CaptureBundle.model_validate_json(bundle.model_dump_json()) == bundle


# --- an error message is an artefact too --------------------------------


def test_str_of_a_validation_error_would_leak_and_safe_message_does_not() -> None:
    """`str(ValidationError)` renders the input it rejected.

    That is the right default for pydantic and the wrong one here: the
    input to a rejected `ValueShape` field can be the config value the
    type exists to keep out of reach. Both halves are asserted — the leak
    *and* the fix — because a test that only checked `safe_message` would
    pass just as well if pydantic stopped echoing inputs, and would then
    be pinning nothing.
    """
    from culprit_model.errors import safe_message

    with pytest.raises(ValidationError) as caught:
        ValueShape(
            type=LEAKED_DSN,  # type: ignore[arg-type]
            length_class=LengthClass.MEDIUM,
            format=ValueFormat.DSN,
            present=True,
        )

    assert LEAKED_DSN in str(caught.value), (
        "pydantic no longer echoes rejected inputs; safe_message may be unnecessary, "
        "but check before removing it"
    )
    message = safe_message(caught.value)
    assert LEAKED_DSN not in message
    assert "hunter2" not in message
    # Still useful: it names the field and the rule.
    assert "type" in message


def test_safe_message_passes_other_exceptions_through() -> None:
    """This codebase's own exceptions are written not to carry values, so
    they are reported as-is rather than flattened to a type name."""
    from culprit_model.errors import safe_message
    from culprit_model.subjects import SubjectError

    message = safe_message(SubjectError("expected 'component/KEY'"))
    assert "SubjectError" in message
    assert "expected" in message


def test_an_extractor_skip_reason_cannot_carry_a_value() -> None:
    """The path that actually matters.

    `culprit-extract-python` turns any failure into a `skipped` reason,
    and a skip travels inside the capture bundle — the artefact §5
    promises is safe to attach to a bug report. A credential arriving
    there through an error message defeats the promise as thoroughly as
    one arriving in a fact.
    """
    from culprit_model.errors import safe_message
    from culprit_model.protocol import Skip

    with pytest.raises(ValidationError) as caught:
        ValueShape(**{"type": "string", "length_class": "medium", "format": "dsn",
                      "present": True, "sample": LEAKED_DSN})  # type: ignore[arg-type]

    skip = Skip(want="config_keys", reason=safe_message(caught.value))
    assert LEAKED_DSN not in skip.model_dump_json()
