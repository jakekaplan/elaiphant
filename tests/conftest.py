import os
import pytest
import pytest_asyncio
import asyncpg
import uuid
import logging
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def base_postgres_url() -> str:
    """Gets the base DB connection URL from environment (set by pyproject.toml)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail(
            "DATABASE_URL environment variable not set."
            " Ensure it's configured in pyproject.toml [tool.pytest.ini_options].env"
        )
    return url


@pytest.fixture(scope="session")
def pg_host(base_postgres_url: str) -> str:
    return urlsplit(base_postgres_url).hostname


@pytest.fixture(scope="session")
def pg_port(base_postgres_url: str) -> int:
    return urlsplit(base_postgres_url).port or 5432


@pytest.fixture(scope="session")
def pg_user(base_postgres_url: str) -> str:
    return urlsplit(base_postgres_url).username


@pytest.fixture(scope="session")
def pg_password(base_postgres_url: str) -> str:
    return urlsplit(base_postgres_url).password


@pytest_asyncio.fixture(scope="session")
async def _postgres_service(
    pg_host: str, pg_port: int, pg_user: str, pg_password: str
) -> None:
    """Check if the postgres service is available."""
    dsn = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/postgres"
    try:
        conn = await asyncpg.connect(dsn=dsn, timeout=5)
        await conn.close()
        logger.info("PostgreSQL service is available.")
    except (asyncpg.PostgresError, OSError, ConnectionRefusedError) as e:
        pytest.fail(
            f"PostgreSQL service is unavailable at {pg_host}:{pg_port}. "
            f"Ensure the Docker container is running and healthy. Error: {e}"
        )


@pytest_asyncio.fixture(scope="session")
async def session_test_db_url(
    _postgres_service: None,
    pg_host: str,
    pg_port: int,
    pg_user: str,
    pg_password: str,
) -> str:
    """
    Creates a temporary database for the test session and yields its URL.
    Drops the database after the session.
    """
    db_name = f"test_db_{uuid.uuid4().hex[:8]}"
    test_db_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"
    postgres_db_url = (
        f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/postgres"
    )

    conn = None
    try:
        conn = await asyncpg.connect(dsn=postgres_db_url)
        logger.info(f"Attempting to create test database: {db_name}")
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{db_name}"')
        logger.info(f"Successfully created test database: {db_name}")
    except Exception as e:
        pytest.fail(f"Failed to create test database '{db_name}'. Error: {e}")
    finally:
        if conn:
            await conn.close()

    yield test_db_url

    conn = None
    try:
        conn = await asyncpg.connect(dsn=postgres_db_url)
        logger.info(f"Attempting to drop test database: {db_name}")
        await conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid();
            """,
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        logger.info(f"Successfully dropped test database: {db_name}")
    except Exception as e:
        logger.error(f"Failed to drop test database '{db_name}'. Error: {e}")
    finally:
        if conn:
            await conn.close()


@pytest.fixture(scope="session", autouse=True)
def override_database_url(session_test_db_url: str) -> None:
    """
    Overrides the DATABASE_URL environment variable for the entire test session
    to point to the temporary database created by session_test_db_url.
    """
    original_url = os.environ.get("DATABASE_URL")
    logger.info(f"Overriding DATABASE_URL for session: {session_test_db_url}")
    os.environ["DATABASE_URL"] = session_test_db_url

    try:
        import importlib
        import elaiphant.settings

        importlib.reload(elaiphant.settings)
        logger.info("Reloaded elaiphant.settings module.")
        from elaiphant.settings import settings

        reloaded_url_str = str(settings.database_url)
        if reloaded_url_str != session_test_db_url:
            logger.warning(
                f"Reloaded settings URL ({reloaded_url_str}) does not match "
                f"session DB URL ({session_test_db_url}). Check import timing."
            )

    except ImportError:
        logger.error("Failed to reload elaiphant.settings.")
        pass

    yield

    logger.info("Restoring original DATABASE_URL.")
    if original_url is None:
        if "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
    else:
        os.environ["DATABASE_URL"] = original_url


# --- Fixture for Per-Test Cleanup (Optional but Recommended) ---
# @pytest_asyncio.fixture(scope="function", autouse=True)
# async def cleanup_db_tables(session_test_db_url: str):
#     """Truncates all user tables in the test database before each test."""
#     # ... implementation remains commented out ...
