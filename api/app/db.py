"""Database engine and session dependency.

Pool sizing is deliberately small: Render's free tier is 512 MB / 0.1 CPU and
Neon's free tier caps connections. A big pool here buys nothing and risks
exhausting both.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlmodel import Session

from .config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    echo=_settings.debug,
    pool_pre_ping=True,  # Neon scales to zero; stale connections must be detected
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
