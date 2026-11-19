# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

# Re-exported from shared/culprit_shared — see that package's docstring.
# Kept here so existing `from app.ingest_gateway.schemas import RawEventIn`
# call sites (otlp_decode.py, streams.py) don't need to change.
from culprit_shared.raw_event import RawEventIn
from culprit_shared.service_edge import ServiceEdgeObservation

__all__ = ["RawEventIn", "ServiceEdgeObservation"]
