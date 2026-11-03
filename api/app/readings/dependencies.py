"""The session for the probe writer.

Its own session factory, like `app/divergences/dependencies.py`'s and for
the same reason: an upload is an independent transaction, and sharing a
factory across endpoints makes one's in-flight state visible to another
that was not written to expect it.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_probe_writer_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.probe_writer_session_factory
    )
    async with session_factory() as session:
        yield session
