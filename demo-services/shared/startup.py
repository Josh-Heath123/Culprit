"""The demo services' startup, in one place (Phase 39 part 2, Q39).

Every demo service is created with `FastAPI(lifespan=startup(...))`. Its
startup runs the service's own warm-up, if it has one, then a full garbage
collection followed by `gc.freeze()`, before the server answers anything.

Why (Q39, attributed by the architecture session on the image's Python
3.12): a just-started process is slow twice over. Its first request is
cold (78 to 129 ms), and Python's first full collection after startup
walks the whole startup heap, a pause of about 36 ms that fell on one
request about 7 s in, every time. Both landed inside the fault library's
latency runs, against budgets of a few milliseconds' headroom. Warming the
read paths takes the first; collecting once and freezing what survived
means no later full collection walks the startup heap.
"""

import gc
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI


def startup(
    warm: Callable[[], None] | None = None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """A lifespan that warms, then collects and freezes the startup heap."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if warm is not None:
            warm()
        gc.collect()
        gc.freeze()
        yield

    return lifespan
