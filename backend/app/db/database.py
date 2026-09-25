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


def _migrate_sqlite_columns(sync_conn):
    """Ensure newly added columns exist in existing SQLite databases."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    tables = inspector.get_table_names()

    if "emergency_events" in tables:
        existing_cols = {col["name"] for col in inspector.get_columns("emergency_events")}
        new_cols = [
            ("owner_id", "VARCHAR(36)"),
            ("trigger_source", "VARCHAR(20) DEFAULT 'MANUAL'"),
            ("place_name", "VARCHAR(200)"),
            ("microsleep_count", "INTEGER DEFAULT 0"),
            ("drowsiness_percentage", "FLOAT DEFAULT 0.0"),
            ("triggered_at", "DATETIME"),
            ("response_source", "VARCHAR(20)"),
            ("assistance_response_status", "VARCHAR(30)"),
            ("response_message", "TEXT"),
            ("responded_at", "DATETIME"),
            ("cancelled_at", "DATETIME"),
            ("cancelled_reason", "TEXT"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                sync_conn.execute(text(f"ALTER TABLE emergency_events ADD COLUMN {col_name} {col_type}"))

    if "highway_assistances" in tables:
        existing_cols = {col["name"] for col in inspector.get_columns("highway_assistances")}
        new_cols = [
            ("emergency_id", "VARCHAR(36)"),
            ("assistance_name", "VARCHAR(200)"),
            ("distance_km", "FLOAT"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                sync_conn.execute(text(f"ALTER TABLE highway_assistances ADD COLUMN {col_name} {col_type}"))


async def init_db():
    """Create all tables (used in development; use Alembic in production)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.DATABASE_URL.startswith("sqlite"):
            await conn.run_sync(_migrate_sqlite_columns)

