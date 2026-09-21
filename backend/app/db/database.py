"""SQLAlchemy async database engine and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings


def _make_engine():
    """Create an async engine with settings appropriate for the configured database.

    SQLite does not support pool_size/max_overflow — use NullPool instead.
    PostgreSQL uses the default pool with explicit sizing.
    """
    url = settings.DATABASE_URL
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        return create_async_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        return create_async_engine(
            url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )


engine = _make_engine()

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables (used in development; use Alembic in production)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
