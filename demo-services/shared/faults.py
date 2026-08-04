import random
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field


class LatencyFaultRequest(BaseModel):
    delay_ms: float = Field(gt=0)
    duration_s: float = Field(gt=0)


class ErrorRateFaultRequest(BaseModel):
    rate: float = Field(gt=0, le=1)
    duration_s: float = Field(gt=0)


class FaultState:
    """In-memory, per-process, per-service fault configuration.

    Deliberately not persisted or shared across processes — this models
    "something is currently wrong with this service instance," which is a
    demo concern, not real infrastructure state.
    """

    def __init__(self) -> None:
        self._latency_delay_ms = 0.0
        self._latency_expires_at = 0.0
        self._error_rate = 0.0
        self._error_expires_at = 0.0

    def set_latency(self, delay_ms: float, duration_s: float) -> None:
        self._latency_delay_ms = delay_ms
        self._latency_expires_at = time.time() + duration_s

    def set_error_rate(self, rate: float, duration_s: float) -> None:
        self._error_rate = rate
        self._error_expires_at = time.time() + duration_s

    def clear(self) -> None:
        self._latency_delay_ms = 0.0
        self._latency_expires_at = 0.0
        self._error_rate = 0.0
        self._error_expires_at = 0.0

    def latency_delay_ms(self) -> float:
        return self._latency_delay_ms if time.time() < self._latency_expires_at else 0.0

    def should_error(self) -> bool:
        if time.time() >= self._error_expires_at or self._error_rate <= 0:
            return False
        return random.random() < self._error_rate

    def snapshot(self) -> dict:
        now = time.time()
        return {
            "latency_delay_ms": self._latency_delay_ms if now < self._latency_expires_at else 0.0,
            "latency_remaining_s": max(0.0, self._latency_expires_at - now),
            "error_rate": self._error_rate if now < self._error_expires_at else 0.0,
            "error_remaining_s": max(0.0, self._error_expires_at - now),
        }


def build_fault_router(fault_state: FaultState) -> APIRouter:
    # No auth on these endpoints — deliberate, not an oversight. This
    # router only exists on the three demo services (order/inventory/
    # payments), and none of them are part of infra/docker-compose.prod.yml
    # — they never run anywhere but a developer's own machine, where the
    # thing being modeled is "inject a fault into my own local demo," not
    # a real production control plane. If a demo service is ever deployed
    # somewhere reachable by anyone but its own operator, this needs auth
    # first.
    router = APIRouter()

    @router.get("")
    def get_fault_state() -> dict:
        return fault_state.snapshot()

    @router.post("/latency")
    def inject_latency(req: LatencyFaultRequest) -> dict:
        fault_state.set_latency(req.delay_ms, req.duration_s)
        return fault_state.snapshot()

    @router.post("/error-rate")
    def inject_error_rate(req: ErrorRateFaultRequest) -> dict:
        fault_state.set_error_rate(req.rate, req.duration_s)
        return fault_state.snapshot()

    @router.delete("")
    def clear_fault() -> dict:
        fault_state.clear()
        return fault_state.snapshot()

    return router
