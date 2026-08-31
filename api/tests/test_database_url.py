"""A managed provider's connection string must reach the driver we install.

This is the bug that broke the first cloud deploy: Render hands out
`postgresql://...`, SQLAlchemy reads that as psycopg2, psycopg2 is not
installed, and the container dies on ModuleNotFoundError during `alembic
upgrade head` — an error that names a package nobody chose and points nowhere
near the connection string.
"""

from app.config import Settings


class TestDatabaseUrlDriver:
    def test_a_plain_postgresql_url_gets_psycopg3(self):
        s = Settings(database_url="postgresql://u:p@h:5432/db")
        assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"

    def test_the_older_postgres_scheme_is_handled_too(self):
        # Heroku-style, and still what some providers print in their UI.
        s = Settings(database_url="postgres://u:p@h:5432/db")
        assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"

    def test_an_explicit_driver_is_left_alone(self):
        # Someone who wrote +asyncpg meant it; do not overwrite the choice.
        s = Settings(database_url="postgresql+asyncpg://u:p@h/db")
        assert s.database_url == "postgresql+asyncpg://u:p@h/db"

    def test_psycopg3_urls_pass_through_unchanged(self):
        url = "postgresql+psycopg://u:p@h/db"
        assert Settings(database_url=url).database_url == url

    def test_query_parameters_survive(self):
        # Managed providers append sslmode; losing it would break TLS.
        s = Settings(database_url="postgresql://u:p@h/db?sslmode=require")
        assert s.database_url == "postgresql+psycopg://u:p@h/db?sslmode=require"
