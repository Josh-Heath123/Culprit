"""Sessions for the investigation routes: the writer for POST, api-reader
for every read. Separate factories, as for readings and divergences: an
upload is its own transaction."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_investigation_writer_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.investigation_writer_session_factory
    )
    async with session_factory() as session:
        yield session


async def get_read_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session
