import os
import pytest
import pytest_asyncio
import asyncpg
import uuid
import logging
from urllib.parse import urlsplit
import psycopg
from elaiphant.db import get_db_connection
from typing import Iterator, AsyncIterator
from contextlib import contextmanager
from elaiphant.settings import settings as global_settings, Settings


logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def base_postgres_url() -> str:
    """Gets the base DB connection URL from environment (set by pyproject.toml)."""
    url = os.environ.get("ELAIPHANT_DATABASE_URL")
    if not url:
        pytest.fail(
            "ELAIPHANT_DATABASE_URL environment variable not set."
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


@contextmanager
def temporary_settings(**kwargs):
    """Temporarily override elaiphant setting values by mutating the global object."""
    old_env = os.environ.copy()
    old_settings_state = global_settings.model_copy(deep=True)

    try:
        for setting_key, value in kwargs.items():
            if value is not None:
                os.environ[setting_key] = str(value)
            else:
                os.environ.pop(setting_key, None)

        try:
            new_settings_instance = Settings()
        except Exception as e:
            logger.error(
                f"Error creating new Settings instance during temporary_settings: {e}"
            )
            raise

        for field in Settings.model_fields:
            try:
                object.__setattr__(
                    global_settings, field, getattr(new_settings_instance, field)
                )
            except AttributeError:
                logger.warning(f"Could not sync field '{field}' in temporary_settings")
                pass

        logger.debug(f"temporary_settings applied: {kwargs}")
        yield global_settings

    finally:
        logger.debug("Restoring settings after temporary_settings")

        for key in kwargs:
            original_value = old_env.get(key)
            if original_value is not None:
                os.environ[key] = original_value
            elif key in os.environ:
                del os.environ[key]

        for field in Settings.model_fields:
            try:
                object.__setattr__(
                    global_settings, field, getattr(old_settings_state, field)
                )
            except AttributeError:
                logger.warning(
                    f"Could not restore field '{field}' in temporary_settings"
                )
                pass
        logger.debug("Settings restoration complete.")


@pytest_asyncio.fixture(scope="function")
async def function_test_db_url(
    pg_host: str,
    pg_port: int,
    pg_user: str,
    pg_password: str,
) -> AsyncIterator[str]:
    """
    Creates a temporary database for EACH test function and yields its URL.
    Drops the database after the function finishes.
    """
    db_name = f"test_db_{uuid.uuid4().hex[:8]}"
    test_db_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"
    postgres_db_url = (
        f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/postgres"
    )

    conn = None
    try:
        conn = await asyncpg.connect(dsn=postgres_db_url)
        logger.info(f"[Function Scope] Creating test database: {db_name}")
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{db_name}"')
        logger.info(f"[Function Scope] Successfully created test database: {db_name}")
    except Exception as e:
        pytest.fail(f"Failed to create test database '{db_name}'. Error: {e}")
    finally:
        if conn:
            await conn.close()

    yield test_db_url

    # Cleanup: Runs after the test function finishes
    conn = None
    try:
        conn = await asyncpg.connect(dsn=postgres_db_url)
        logger.info(f"[Function Scope] Dropping test database: {db_name}")
        await conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid();
            """,
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        logger.info(f"[Function Scope] Successfully dropped test database: {db_name}")
    except Exception as e:
        logger.error(f"Failed to drop test database '{db_name}'. Error: {e}")
    finally:
        if conn:
            await conn.close()


@pytest.fixture(scope="function")
def override_database_url_for_function(function_test_db_url: str) -> Iterator[None]:
    """
    Overrides the ELAIPHANT_DATABASE_URL for a single test function using temporary_settings.
    """
    settings_override = {"ELAIPHANT_DATABASE_URL": function_test_db_url}
    logger.info(f"[Function Scope] Applying temporary settings: {settings_override}")
    with temporary_settings(**settings_override):
        yield
    logger.info("[Function Scope] Restored settings after override.")


@pytest.fixture(scope="function")
def db_connection(
    override_database_url_for_function: None,
) -> Iterator[psycopg.Connection]:
    """Provides a database connection for a test function using the function-scoped DB."""
    with get_db_connection() as conn:
        try:
            yield conn
        finally:
            if (
                conn
                and not conn.closed
                and conn.pgconn.transaction_status
                != psycopg.pq.TransactionStatus.UNKNOWN
            ):
                try:
                    conn.rollback()
                except psycopg.Error as e:
                    logger.warning(
                        f"Error during final rollback in db_connection fixture: {e}"
                    )


# --- Fixture for Per-Test Cleanup (Optional but Recommended) ---
# @pytest_asyncio.fixture(scope="function", autouse=True)
# async def cleanup_db_tables(session_test_db_url: str):
#     """Truncates all user tables in the test database before each test."""
#     # ... implementation remains commented out ...
