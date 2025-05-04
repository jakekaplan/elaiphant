import psycopg
import logging
from psycopg import rows
from psycopg.sql import SQL
from typing import Optional, List, Dict, Any, Tuple, Iterator, cast
from typing_extensions import LiteralString
from contextlib import contextmanager

from elaiphant.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection() -> Iterator[psycopg.Connection]:
    """Provides a transactional database connection context."""
    if not settings.database_url:
        raise ConnectionError("Database URL is not configured.")

    dsn = str(settings.database_url)
    conn: Optional[psycopg.Connection] = None
    try:
        conn = psycopg.connect(dsn)
        yield conn
        if conn:
            conn.commit()
    except psycopg.Error as e:
        logger.error(f"Database operation failed: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
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
        # Error is logged in get_db_connection context manager, re-raise it
        logger.error(f"Failed to execute query: {sql}. Error: {e}")
        raise
    return results


# Keep more specific type hint for EXPLAIN ANALYZE result
def get_explain_analyze(
    sql: str, params: Optional[Tuple[Any, ...]] = None
) -> List[Dict[str, List[Dict[str, Any]]]]:
    """Executes EXPLAIN ANALYZE (FORMAT JSON) and returns the plan."""
    explain_template = SQL(
        cast(LiteralString, "EXPLAIN (ANALYZE, VERBOSE, BUFFERS, FORMAT JSON) {}")
    )
    explain_sql = explain_template.format(SQL(cast(LiteralString, sql)))
    # Simplified logging: Log the original SQL query being explained
    logger.info(
        f"Getting EXPLAIN ANALYZE for: {sql}"
        + (f" with params: {params}" if params else "")
    )
    plan: List[Dict[str, List[Dict[str, Any]]]] = []
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=rows.dict_row) as cur:
                cur.execute(explain_sql, params)
                # EXPLAIN ANALYZE should always return rows if successful
                fetched_plan = cur.fetchall()
                if not fetched_plan:
                    # This case might indicate an issue with the query itself
                    # before execution plan generation, or an unexpected PG response.
                    logger.error(f"EXPLAIN ANALYZE for query '{sql}' returned no plan.")
                    raise psycopg.Error("EXPLAIN ANALYZE did not return any plan.")
                # Assign fetched plan; type checker should see it matches ExplainAnalyzeResult
                plan = fetched_plan
    except psycopg.Error as e:
        logger.error(f"Failed to execute EXPLAIN ANALYZE for query: {sql}. Error: {e}")
        raise
    # The result is typically a list containing one dictionary: [{'QUERY PLAN': [...]}]
    return plan
