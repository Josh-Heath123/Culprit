"""Culprit's dashboard API (Phase 7, minimal — see api/app/incidents/).

Distinct from app/ingest_gateway (Phase 3, a separate uvicorn process on
its own port): this is the read-mostly API Phase 8's frontend talks to.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import os  # noqa: E402
import time  # noqa: E402

import structlog  # noqa: E402
from arq.connections import RedisSettings, create_pool  # noqa: E402
from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.trace import Status, StatusCode  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.middleware import SlowAPIMiddleware  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from starlette.responses import JSONResponse, Response  # noqa: E402

from app.auth.dependencies import require_auth  # noqa: E402
from app.auth.router import router as auth_router  # noqa: E402
from app.incidents.config import API_READER_DATABASE_URL, REDIS_URL  # noqa: E402
from app.incidents.limiter import limiter  # noqa: E402
from app.incidents.router import router as incidents_router  # noqa: E402
from app.observability import configure_observability  # noqa: E402

configure_observability("culprit-api")

tracer = trace.get_tracer("culprit.api")
access_logger = structlog.get_logger("api.access")

#: Comma-separated list of origins allowed to call this API — the Vite
#: dev server's default port locally, overridable for any other frontend
#: origin (a deployed dashboard, a different local port).
CORS_ALLOW_ORIGINS = os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_async_engine(API_READER_DATABASE_URL)
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    # For POST /incidents/{id}/regenerate-root-cause to enqueue Phase 6's
    # arq job by name — this API process never runs arq jobs itself.
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    yield
    await app.state.arq_pool.aclose()
    await engine.dispose()


app = FastAPI(title="Culprit API", lifespan=lifespan)
app.state.limiter = limiter


async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Replaces slowapi's default handler only to add the explicit
    structured log (Phase 10: no silent 429s) — the response it builds
    is otherwise identical to slowapi's own _rate_limit_exceeded_handler."""
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """One span + one structured access-log line per request. Added
    last, so it's the outermost middleware and wraps CORS/rate-limiting
    too — every request gets a trace, including ones short-circuited
    before reaching a route. Specific failure reasons (auth, rate limit)
    are logged at their own raise sites (app/auth/, the handler above),
    not reconstructed here from the response — the response itself here
    is generic on purpose for auth (see app/auth/router.py)."""
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


app.include_router(auth_router)
app.include_router(incidents_router, dependencies=[Depends(require_auth)])
