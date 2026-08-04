# Re-exported from shared/culprit_shared — see that package's docstring.
# Kept here so existing `from app.ingest_gateway.schemas import RawEventIn`
# call sites (otlp_decode.py, streams.py) don't need to change.
from culprit_shared.raw_event import RawEventIn

__all__ = ["RawEventIn"]
