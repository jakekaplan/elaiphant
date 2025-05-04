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
    # urlsplit port can be None, provide default
    return urlsplit(base_postgres_url).port or 5432

@pytest.fixture(scope="session")
def pg_user(base_postgres_url: str) -> str:
    return urlsplit(base_postgres_url).username

@pytest.fixture(scope="session")
def pg_password(base_postgres_url: str) -> str:
    return urlsplit(base_postgres_url).password

@pytest_asyncio.fixture(scope="session")
async def _postgres_service(pg_host: str, pg_port: int, pg_user: str, pg_password: str) -> None:
    """Check if the postgres service is available."""
    # Connect to the default 'postgres' database to check availability
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
    _postgres_service: None, # Depends on the service check
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
    postgres_db_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/postgres"

    conn = None
    try:
        # Connect to the default 'postgres' database to manage test DBs
        conn = await asyncpg.connect(dsn=postgres_db_url)
        logger.info(f"Attempting to create test database: {db_name}")
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)') # Use FORCE if needed and available
        await conn.execute(f'CREATE DATABASE "{db_name}"' )
        logger.info(f"Successfully created test database: {db_name}")
    except Exception as e:
        pytest.fail(f"Failed to create test database '{db_name}'. Error: {e}")
    finally:
        if conn:
            await conn.close()

    # --- Test Session Runs ---
    yield test_db_url
    # --- Test Session Runs ---

    # Teardown: Drop the test database
    conn = None
    try:
        conn = await asyncpg.connect(dsn=postgres_db_url)
        logger.info(f"Attempting to drop test database: {db_name}")
        # Terminate connections before dropping - important!
        # Use IF EXISTS for robustness in termination query
        await conn.execute(f"""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid();
            """, db_name)
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"' )
        logger.info(f"Successfully dropped test database: {db_name}")
    except Exception as e:
        # Log error but don't fail the entire test suite run if cleanup fails
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

    # Force reload of the settings module AFTER the env var is set.
    try:
        import importlib
        import elaiphant.settings
        importlib.reload(elaiphant.settings)
        logger.info("Reloaded elaiphant.settings module.")
        # Verify the reloaded settings picked up the change
        from elaiphant.settings import settings
        reloaded_url_str = str(settings.database_url)
        if reloaded_url_str != session_test_db_url:
             logger.warning(
                 f"Reloaded settings URL ({reloaded_url_str}) does not match "
                 f"session DB URL ({session_test_db_url}). Check import timing."
             )

    except ImportError:
        logger.error("Failed to reload elaiphant.settings.")
        pass # Module probably not loaded yet, which is fine.

    yield # Run tests

    # Restore original environment variable
    logger.info("Restoring original DATABASE_URL.")
    if original_url is None:
        if "DATABASE_URL" in os.environ:
             del os.environ["DATABASE_URL"]
    else:
        os.environ["DATABASE_URL"] = original_url
    # Optionally reload settings again if needed
    # try:
    #     import importlib
    #     import elaiphant.settings
    #     importlib.reload(elaiphant.settings)
    # except ImportError:
    #     pass 