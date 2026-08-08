from pydantic import BaseModel


class ServiceEdgeObservation(BaseModel):
    """One observed (from_service, to_service) call, decoded from a
    single CLIENT-kind trace span (Phase 19 — see
    api/app/ingest_gateway/otlp_decode.py's decode_traces_request).

    Written by api/app/ingest_gateway (onto the traces Redis Stream) and
    read by worker/app/consumer.py (validates incoming stream entries
    against this same model before upserting into
    observed_service_edges) — same one-definition-not-two pattern as
    RawEventIn in this package's raw_event.py.
    """

    from_service: str
    to_service: str
