import time
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Request, Response  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (  # noqa: E402
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (  # noqa: E402
    ExportMetricsServiceResponse,
)
from opentelemetry.trace import Status, StatusCode  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.middleware import SlowAPIMiddleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from app.ingest_gateway.auth import api_key_store, authenticated_service_name  # noqa: E402
from app.ingest_gateway.config import (  # noqa: E402
    INGEST_MAX_BODY_BYTES,
    INGEST_RATE_LIMIT,
    REDIS_URL,
)
from app.ingest_gateway.limiter import limiter  # noqa: E402
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
app.state.limiter = limiter


async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Same structure as app/main.py's own handler — replaces slowapi's
    default only to add the explicit structured log (Phase 10: no silent
    429s)."""
    access_logger.warning(
        "rate_limit_exceeded",
        path=request.url.path,
        method=request.method,
        detail=str(exc.detail),
    )
    response = JSONResponse({"error": f"Rate limit exceeded: {exc.detail}"}, status_code=429)
    return request.app.state.limiter._inject_headers(response, request.state.view_rate_limit)


app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,  # pyright: ignore[reportArgumentType]
)
app.add_middleware(SlowAPIMiddleware)


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
    """Caddy's own request_body max_size (frontend/Caddyfile) caps the
    raw body arriving from outside, but this gateway is also reachable
    directly on the compose network, bypassing Caddy entirely — and even
    behind Caddy, that cap applies to the *compressed* size, which tells
    you nothing about a gzip bomb. `gzip.decompress()` has no size bound
    of its own: it happily materializes the entire decompressed output
    before this function could ever check its length, so the bomb has
    already gone off by the time a naive check would run.

    zlib's incremental decompressobj sidesteps that: `max_length` bounds
    how much *output* a single decompress() call will produce, so a
    payload that would decompress to gigabytes never gets the chance —
    it stops at INGEST_MAX_BODY_BYTES + 1 and leaves the rest sitting in
    `unconsumed_tail`, which is exactly the signal that the real
    (uncapped) output would have exceeded the limit.
    """
    if content_encoding == "gzip":
        # wbits = MAX_WBITS | 16 selects gzip-container decoding (the
        # plain zlib wrapper decompressobj defaults to won't accept a
        # gzip header) without pulling in the separate `gzip` module's
        # unbounded decompress() path.
        decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)
        try:
            body = decompressor.decompress(body, INGEST_MAX_BODY_BYTES + 1)
        except zlib.error as exc:
            raise HTTPException(status_code=400, detail="invalid gzip payload") from exc
        if decompressor.unconsumed_tail:
            raise HTTPException(status_code=413, detail="payload too large")
        body += decompressor.flush()

    if len(body) > INGEST_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")
    return body


@app.get("/healthz")
async def healthz() -> dict:
    """No auth, no DB/Redis touch (per docs/SELF_HOSTED_PLAN.md Phase 15:
    "a health endpoint that fails when a dependency is slow tells you
    less, not more") — infra/deploy.sh polls this independently of the
    dashboard API's own /incidents-based health check."""
    return {"status": "ok"}


@app.post("/v1/metrics")
@limiter.limit(INGEST_RATE_LIMIT)
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
@limiter.limit(INGEST_RATE_LIMIT)
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
