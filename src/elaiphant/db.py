import psycopg
import logging
# Removed TypeAlias
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from elaiphant.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection() -> psycopg.Connection:
    """Provides a transactional database connection context."""
    if not settings.database_url:
        raise ConnectionError("Database URL is not configured.")

    # Ensure the DSN is a string for psycopg.connect
    dsn = str(settings.database_url)
    conn: Optional[psycopg.Connection] = None
    try:
        conn = psycopg.connect(dsn)
        yield conn
        # Commit only if connection is valid and no error occurred before yield returned
        if conn: # Check explicitly for None
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
    logger.info(f"Executing query: {sql}" + (f" with params: {params}" if params else ""))
    results: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            # Use server-side cursors for potentially large results if needed,
            # but start with standard cursors for simplicity.
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute(sql, params)
                # Check if the query returns rows
                if cur.description:
                    results = cur.fetchall()
                else:
                    logger.info(f"Query executed successfully, no rows returned (Status: {cur.statusmessage}).")
                    # Ensure empty list has the correct type annotation if needed by linter
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
    # Use JSON format for easier parsing
    explain_sql = f"EXPLAIN (ANALYZE, VERBOSE, BUFFERS, FORMAT JSON) {sql}"
    logger.info(f"Executing explain: {explain_sql}" + (f" with params: {params}" if params else ""))
    plan: List[Dict[str, List[Dict[str, Any]]]] = []
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
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