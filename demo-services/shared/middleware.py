import asyncio
import time

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.context import attach, detach
from opentelemetry.propagate import extract
from opentelemetry.trace import Status, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from shared.faults import FaultState

# Faults never apply to admin/health traffic — otherwise an elevated error
# rate could make it impossible to clear the very fault that caused it.
FAULT_EXEMPT_PREFIXES = ("/admin", "/health")


class TelemetryFaultMiddleware(BaseHTTPMiddleware):
    """Traces every request and records request count / latency / error
    count per route, then applies whatever fault is currently active.

    Faults are applied here rather than in each handler so every route
    gets them uniformly and a handler can't forget to check.
    """

    def __init__(self, app: FastAPI, service_name: str, fault_state: FaultState) -> None:
        super().__init__(app)
        self._fault_state = fault_state
        self._tracer = trace.get_tracer(service_name)
        meter = metrics.get_meter(service_name)
        self._requests = meter.create_counter(
            "demo.http.server.requests", description="Total HTTP requests handled"
        )
        self._errors = meter.create_counter(
            "demo.http.server.errors", description="Total HTTP requests that errored"
        )
        self._duration = meter.create_histogram(
            "demo.http.server.duration", unit="ms", description="Request duration"
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        route = request.url.path
        method = request.method
        exempt = route.startswith(FAULT_EXEMPT_PREFIXES)

        # Extract trace context propagated by an upstream caller (e.g.
        # order-service) so this request's span nests under it instead of
        # starting a disconnected trace.
        token = attach(extract(request.headers))
        try:
            with self._tracer.start_as_current_span(f"{method} {route}") as span:
                span.set_attribute("http.method", method)
                span.set_attribute("http.route", route)
                start = time.perf_counter()

                if not exempt:
                    delay_ms = self._fault_state.latency_delay_ms()
                    if delay_ms:
                        span.set_attribute("fault.latency_delay_ms", delay_ms)
                        await asyncio.sleep(delay_ms / 1000)

                    if self._fault_state.should_error():
                        span.set_attribute("fault.injected", "error_rate")
                        span.set_status(Status(StatusCode.ERROR))
                        duration_ms = (time.perf_counter() - start) * 1000
                        self._record(route, method, 500, duration_ms)
                        return JSONResponse({"detail": "injected fault"}, status_code=500)

                response = await call_next(request)
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR))

                if not exempt:
                    self._record(route, method, response.status_code, duration_ms)

                return response
        finally:
            detach(token)

    def _record(self, route: str, method: str, status_code: int, duration_ms: float) -> None:
        attrs = {"route": route, "method": method, "status_code": status_code}
        self._requests.add(1, attrs)
        self._duration.record(duration_ms, attrs)
        if status_code >= 500:
            self._errors.add(1, attrs)
