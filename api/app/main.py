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

from app.auth.config import AUTH_SERVICE_DATABASE_URL  # noqa: E402
from app.auth.dependencies import require_admin, require_auth  # noqa: E402
from app.auth.router import router as auth_router  # noqa: E402
from app.auth.users_router import router as users_router  # noqa: E402
from app.divergences.config import DIVERGENCE_WRITER_DATABASE_URL  # noqa: E402
from app.divergences.router import router as divergences_router  # noqa: E402
from app.errors import install as install_error_handlers  # noqa: E402
from app.facts.config import FACT_WRITER_DATABASE_URL  # noqa: E402
from app.facts.router import router as facts_router  # noqa: E402
from app.incidents.config import API_READER_DATABASE_URL, REDIS_URL  # noqa: E402
from app.incidents.limiter import limiter  # noqa: E402
from app.incidents.router import router as incidents_router  # noqa: E402
from app.memory.router import router as memory_router  # noqa: E402
from app.model.router import router as model_router  # noqa: E402
from app.observability import configure_observability  # noqa: E402
from app.postmortems.config import POSTMORTEM_WRITER_DATABASE_URL  # noqa: E402
from app.postmortems.router import router as postmortems_router  # noqa: E402
from app.registry.config import REGISTRY_ADMIN_DATABASE_URL  # noqa: E402
from app.registry.router import router as registry_router  # noqa: E402

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
    # Phase 14: a second engine, under registry-admin, only for the
    # registry router's writes (POST/PATCH/DELETE /services and its keys
    # sub-routes). api-reader (above) stays read-only and is what
    # GET /services still uses — see app/registry/router.py.
    registry_engine = create_async_engine(REGISTRY_ADMIN_DATABASE_URL)
    app.state.registry_session_factory = async_sessionmaker(registry_engine, expire_on_commit=False)
    # Phase 16: a third engine, under auth-service, for /auth/login,
    # /auth/change-password, and every /users write. app.state.session_factory
    # (api-reader, above) stays read-only and is what require_auth's own
    # disabled-user check uses (app/auth/dependencies.py) — only writes
    # need this one.
    auth_engine = create_async_engine(AUTH_SERVICE_DATABASE_URL)
    app.state.auth_session_factory = async_sessionmaker(auth_engine, expire_on_commit=False)
    # Phase 18: a fourth engine, under postmortem-writer, for every
    # /postmortems write. GET /postmortems stays on api-reader (above),
    # which already has SELECT on postmortems. Explicitly capped (unlike
    # the three engines above, which predate this being called out) —
    # docs/SELF_HOSTED_PLAN.md Phase 18 Known Trap 4: this VM is an
    # Always Free shape and Postgres's default max_connections isn't
    # generous, and this is now the fourth connection pool in one
    # process, not the third the plan was written against.
    postmortem_engine = create_async_engine(
        POSTMORTEM_WRITER_DATABASE_URL, pool_size=5, max_overflow=5
    )
    app.state.postmortem_session_factory = async_sessionmaker(
        postmortem_engine, expire_on_commit=False
    )
    # Phase 28: a fifth engine, under fact-writer, for POST
    # /facts/captures. INSERT-only on captures/intent_facts and nothing
    # on configured_facts/readings -- a new role rather than a widened
    # one, see app/facts/config.py. Capped like postmortem_engine above,
    # and smaller: capture uploads are occasional CI events, not
    # interactive traffic, so a large pool would only consume
    # max_connections on an Always Free VM to sit idle.
    fact_engine = create_async_engine(FACT_WRITER_DATABASE_URL, pool_size=2, max_overflow=3)
    app.state.fact_session_factory = async_sessionmaker(fact_engine, expire_on_commit=False)
    # Phase 29: POST /divergences/captures, under the same fact-writer
    # role (see app/divergences/config.py for why that reuse is
    # sanctioned rather than a rule broken). Its own engine and its own
    # session factory, so a transaction in one upload is never visible to
    # the other.
    divergence_engine = create_async_engine(
        DIVERGENCE_WRITER_DATABASE_URL, pool_size=2, max_overflow=3
    )
    app.state.divergence_session_factory = async_sessionmaker(
        divergence_engine, expire_on_commit=False
    )
    # For POST /incidents/{id}/regenerate-root-cause and POST/PATCH
    # /postmortems to enqueue arq jobs by name — this API process never
    # runs arq jobs itself.
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    yield
    await app.state.arq_pool.aclose()
    await engine.dispose()
    await registry_engine.dispose()
    await auth_engine.dispose()
    await postmortem_engine.dispose()
    await fact_engine.dispose()


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
# A 422 must not echo the request body: a rejected capture bundle
# would otherwise write the credential it was refused for into this
# API's access log and the caller's CI log. See app/errors.py.
install_error_handlers(app)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    # Phase 14: the registry router (app/registry/router.py) is the
    # first thing in this API to use PATCH/DELETE at all — every route
    # before it was GET/POST only, so this list was never exercised
    # against them. Without this, the frontend's Settings > Services
    # page would 405 on every disable/enable, revoke, or update, purely
    # from the browser's own CORS preflight, not from FastAPI routing.
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
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
# Phase 16: registry and user-management writes now require the admin
# role, not just any authenticated session — require_admin is a thin
# wrapper over require_auth (app/auth/dependencies.py), so this is the
# only line either router needed to change.
# Phase 27: the system model (/model/components, /model/connections,
# /model/graph, /model/apply). Same admin gate and the same two engines
# the registry router uses -- app/model/router.py is the real surface,
# and registry_router below is now a thin /services alias over it,
# retained for one release and removed in Phase 30 (that phase field 9).
app.include_router(model_router, dependencies=[Depends(require_admin)])
app.include_router(registry_router, dependencies=[Depends(require_admin)])
app.include_router(users_router, dependencies=[Depends(require_admin)])
# Phase 18: not admin-only, unlike registry/users above — any
# authenticated team member may read and write postmortems.
app.include_router(postmortems_router, dependencies=[Depends(require_auth)])
# Phase 21 (docs/AI_NATIVE_PLAN.md): no router-level dependency here,
# unlike every router above — app/memory/router.py gates each endpoint
# individually, since POST /ai-change-records needs require_auth_or_agent
# instead of require_auth and a router-level dependency can't be opted
# out of per-route. See that module's own docstring.
app.include_router(memory_router)
# Phase 28 (docs/DIAGNOSTIC_PLAN.md): POST /facts/captures. No
# router-level dependency, and for a different reason than memory_router
# above -- this one is not authenticated by a user session at all. It
# takes a project token (app/facts/dependencies.py), declared per-route,
# so that adding an endpoint here later cannot inherit a credential
# nobody chose for it.
app.include_router(facts_router)
# Phase 29: POST /divergences/captures. Same reasoning as facts_router
# immediately above -- a project token, declared per route.
app.include_router(divergences_router)
