import pytest
import psycopg


from elaiphant.db import execute_query, get_explain_analyze, get_db_connection


def test_execute_query_select_1():
    """should execute a simple SELECT query correctly."""
    results = execute_query("SELECT 1 AS number;")
    assert len(results) == 1
    assert results[0]["number"] == 1


def test_execute_query_no_results():
    """should handle queries that return no rows."""
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute("DROP TABLE IF EXISTS test_empty_query;")
                cur.execute("CREATE TEMP TABLE test_empty_query (id INT);")
                cur.execute("SELECT * FROM test_empty_query;")
                results = cur.fetchall()
                assert results == []
    except (psycopg.Error, ConnectionError) as e:
        pytest.fail(
            f"Database operation failed during test_execute_query_no_results: {e}"
        )


def test_execute_query_with_params():
    """should execute a query with parameters correctly."""
    results = execute_query("SELECT %s AS value;", ("hello",))
    assert len(results) == 1
    assert results[0]["value"] == "hello"


def test_get_explain_analyze_basic():
    """should retrieve an EXPLAIN ANALYZE plan in JSON format."""
    plan_result = get_explain_analyze("SELECT 1;")
    assert isinstance(plan_result, list)
    assert len(plan_result) == 1
    assert isinstance(plan_result[0], dict)
    assert "QUERY PLAN" in plan_result[0]
    assert isinstance(plan_result[0]["QUERY PLAN"], list)
    assert len(plan_result[0]["QUERY PLAN"]) > 0


def test_get_explain_analyze_with_params():
    """should retrieve an EXPLAIN ANALYZE plan for a query with parameters."""
    plan_result = get_explain_analyze("SELECT %s::int;", (42,))
    assert isinstance(plan_result, list)
    assert len(plan_result) == 1
    assert "QUERY PLAN" in plan_result[0]
    assert isinstance(plan_result[0]["QUERY PLAN"], list)
