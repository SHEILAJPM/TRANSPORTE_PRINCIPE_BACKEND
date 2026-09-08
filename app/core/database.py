from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# statement_cache_size=0: Neon (como PgBouncer en modo transacción) enruta cada
# consulta a conexiones físicas de Postgres compartidas entre clientes, así que el
# caché de "prepared statements" de asyncpg puede quedar con planes obsoletos tras
# cualquier cambio de esquema (ALTER TABLE), causando InvalidCachedStatementError.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args={"statement_cache_size": 0},
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
