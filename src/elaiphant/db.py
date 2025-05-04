import psycopg
import logging
import importlib
from psycopg import rows
from psycopg.sql import SQL
from typing import Optional, List, Dict, Any, Tuple, Iterator, cast
from typing_extensions import LiteralString
from contextlib import contextmanager

import elaiphant.settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection() -> Iterator[psycopg.Connection]:
    """Provides a transactional database connection context."""
    try:
        current_settings = importlib.reload(elaiphant.settings).settings
    except Exception as e:
        logger.error(f"Failed to reload settings: {e}")
        current_settings = elaiphant.settings.settings

    if not current_settings.database_url:
        raise ConnectionError("Database URL is not configured.")

    dsn = str(current_settings.database_url)
    logger.debug(f"Attempting connection using DSN: {dsn}")
    conn: Optional[psycopg.Connection] = None
    try:
        conn = psycopg.connect(dsn)
        # Assert conn is not None to satisfy linter, though connect() would raise if failed
        assert conn is not None
        logger.debug(f"Connection successful to: {conn.info.dbname}")
        yield conn
        # Improved commit/rollback logic
        # Check conn is not None here because yield could raise before commit/rollback
        if conn and not conn.closed:
            if conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE:
                try:
                    logger.debug("Committing transaction.")
                    conn.commit()
                except psycopg.Error as e:
                    logger.error(f"Commit failed, attempting rollback: {e}")
                    try:
                        conn.rollback()
                    except psycopg.Error as rb_exc:
                        logger.error(
                            f"Rollback after failed commit also failed: {rb_exc}"
                        )
                    raise
            elif conn.info.transaction_status == psycopg.pq.TransactionStatus.INERROR:
                logger.warning(
                    "Connection in error state at end of context, rolling back."
                )
                try:
                    conn.rollback()
                except psycopg.Error as rb_exc:
                    logger.error(f"Rollback for INERROR state failed: {rb_exc}")
            else:
                logger.debug(
                    f"Connection ended with status: {conn.info.transaction_status}. No commit/rollback needed by context manager."
                )
    except psycopg.Error as e:
        logger.error(f"Database connection or operation failed: {e}")
        if conn and not conn.closed:
            try:
                logger.debug("Rolling back transaction due to error.")
                conn.rollback()
            except psycopg.Error as rb_exc:
                logger.error(f"Rollback following operation error failed: {rb_exc}")
        raise
    finally:
        if conn and not conn.closed:
            logger.debug("Closing connection.")
            conn.close()


def execute_query(
    sql: str, params: Optional[Tuple[Any, ...]] = None
) -> List[Dict[str, Any]]:
    """Executes a SQL query and returns results as a list of dicts."""
    logger.info(
        f"Executing query: {sql}" + (f" with params: {params}" if params else "")
    )
    results: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=rows.dict_row) as cur:
                cur.execute(SQL(cast(LiteralString, sql)), params)
                if cur.description:
                    results = cur.fetchall()
                else:
                    logger.info(
                        f"Query executed successfully, no rows returned (Status: {cur.statusmessage})."
                    )
                    results = []
    except psycopg.Error as e:
        logger.error(f"Failed to execute query: {sql}. Error: {e}")
        raise
    return results


def get_explain_analyze(
    sql: str, params: Optional[Tuple[Any, ...]] = None
) -> List[Dict[str, List[Dict[str, Any]]]]:
    """Executes EXPLAIN ANALYZE (FORMAT JSON) and returns the plan."""
    explain_template = SQL(
        cast(LiteralString, "EXPLAIN (ANALYZE, VERBOSE, BUFFERS, FORMAT JSON) {}")
    )
    explain_sql = explain_template.format(SQL(cast(LiteralString, sql)))

    logger.info(
        f"Getting EXPLAIN ANALYZE for: {sql}"
        + (f" with params: {params}" if params else "")
    )
    plan: List[Dict[str, List[Dict[str, Any]]]] = []

    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=rows.dict_row) as cur:
                cur.execute(explain_sql, params)

                fetched_plan = cur.fetchall()
                if not fetched_plan:
                    logger.error(f"EXPLAIN ANALYZE for query '{sql}' returned no plan.")
                    raise psycopg.Error("EXPLAIN ANALYZE did not return any plan.")

                plan = fetched_plan
    except psycopg.Error as e:
        logger.error(f"Failed to execute EXPLAIN ANALYZE for query: {sql}. Error: {e}")
        raise

    return plan


def list_tables(conn: Optional[psycopg.Connection] = None) -> List[str]:
    """Lists all tables in the public schema. Uses provided connection or creates a new one."""
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
    logger.info("Listing tables in public schema")
    table_names: List[str] = []

    def _fetch_tables(cursor: psycopg.Cursor):
        cursor.execute(sql)
        results = cursor.fetchall()
        return [row[0] for row in results]

    try:
        if conn:
            # Use the provided connection's cursor
            with conn.cursor() as cur:
                table_names = _fetch_tables(cur)
        else:
            # Create a new connection context
            with get_db_connection() as new_conn:
                with new_conn.cursor() as cur:
                    table_names = _fetch_tables(cur)
    except psycopg.Error as e:
        logger.error(f"Failed to list tables. Error: {e}")
        raise
    return table_names


def get_table_schema(
    table_name: str, conn: Optional[psycopg.Connection] = None
) -> Dict[str, str]:
    """Retrieves the schema for a table. Uses provided connection or creates a new one."""
    sql = "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public';"
    logger.info(f"Getting schema for table: {table_name}")
    schema: Dict[str, str] = {}

    def _fetch_schema(cursor: psycopg.Cursor):
        cursor.execute(sql, (table_name,))
        results = cursor.fetchall()
        if not results:
            logger.warning(f"Table '{table_name}' not found or has no columns.")
        return {row[0]: row[1] for row in results}

    try:
        if conn:
            with conn.cursor() as cur:
                schema = _fetch_schema(cur)
        else:
            with get_db_connection() as new_conn:
                with new_conn.cursor() as cur:
                    schema = _fetch_schema(cur)
    except psycopg.Error as e:
        logger.error(f"Failed to get schema for table {table_name}. Error: {e}")
        raise
    return schema


def get_table_indexes(
    table_name: str, conn: Optional[psycopg.Connection] = None
) -> List[str]:
    """Retrieves index names for a table. Uses provided connection or creates a new one."""
    sql = "SELECT indexname FROM pg_indexes WHERE tablename = %s AND schemaname = 'public';"
    logger.info(f"Getting indexes for table: {table_name}")
    index_names: List[str] = []

    def _fetch_indexes(cursor: psycopg.Cursor):
        cursor.execute(sql, (table_name,))
        results = cursor.fetchall()
        return [row[0] for row in results]

    try:
        if conn:
            with conn.cursor() as cur:
                index_names = _fetch_indexes(cur)
        else:
            with get_db_connection() as new_conn:
                with new_conn.cursor() as cur:
                    index_names = _fetch_indexes(cur)
    except psycopg.Error as e:
        logger.error(f"Failed to get indexes for table {table_name}. Error: {e}")
        raise
    return index_names
