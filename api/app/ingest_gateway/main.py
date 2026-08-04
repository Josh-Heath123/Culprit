import gzip
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402
from fastapi import Depends, FastAPI, Request, Response  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (  # noqa: E402
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (  # noqa: E402
    ExportMetricsServiceResponse,
)
from opentelemetry.trace import Status, StatusCode  # noqa: E402

from app.ingest_gateway.auth import api_key_store, authenticated_service_name  # noqa: E402
from app.ingest_gateway.config import REDIS_URL  # noqa: E402
from app.ingest_gateway.otlp_decode import decode_logs_request, decode_metrics_request  # noqa: E402
from app.ingest_gateway.streams import LOGS_STREAM, METRICS_STREAM, push_events  # noqa: E402
from app.observability import configure_observability  # noqa: E402

configure_observability("culprit-ingest-gateway")

tracer = trace.get_tracer("culprit.ingest_gateway")
access_logger = structlog.get_logger("ingest_gateway.access")

_state: dict[str, redis.Redis] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _state["redis"] = redis.from_url(REDIS_URL)
    await api_key_store.load()
    yield
    await _state["redis"].aclose()


app = FastAPI(title="ingest-gateway", lifespan=lifespan)


@app.middleware("http")
async def observability_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """A span + structured access-log line per request — this ingest-
    gateway's own request handling (auth, decompression, dispatch to the
    decode step), distinct from otlp_decode.py's payload parsing, which
    isn't separately traced (it's a pure function call within the
    request span, not its own request boundary)."""
    start = time.perf_counter()
    with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.route", request.url.path)
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        span.set_attribute("http.status_code", response.status_code)
        if response.status_code >= 400:
            span.set_status(Status(StatusCode.ERROR))
        access_logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response


def _maybe_decompress(body: bytes, content_encoding: str | None) -> bytes:
    if content_encoding == "gzip":
        return gzip.decompress(body)
    return body


@app.post("/v1/metrics")
async def export_metrics(
    request: Request,
    service_name: str = Depends(authenticated_service_name),
) -> Response:
    body = _maybe_decompress(await request.body(), request.headers.get("content-encoding"))
    events = decode_metrics_request(body, service_name)
    await push_events(_state["redis"], METRICS_STREAM, events)
    return Response(
        content=ExportMetricsServiceResponse().SerializeToString(),
        media_type="application/x-protobuf",
    )


@app.post("/v1/logs")
async def export_logs(
    request: Request,
    service_name: str = Depends(authenticated_service_name),
) -> Response:
    body = _maybe_decompress(await request.body(), request.headers.get("content-encoding"))
    events = decode_logs_request(body, service_name)
    await push_events(_state["redis"], LOGS_STREAM, events)
    return Response(
        content=ExportLogsServiceResponse().SerializeToString(),
        media_type="application/x-protobuf",
    )
