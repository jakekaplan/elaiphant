import pytest
import psycopg


from elaiphant.db import (
    execute_query,
    get_explain_analyze,
    get_db_connection,
    list_tables,
    get_table_schema,
    get_table_indexes,
)


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


def test_list_tables(db_connection: psycopg.Connection):
    """Should list tables created in the public schema."""
    table_name = "test_list_table"
    with db_connection.cursor() as cur:
        cur.execute(f"CREATE TABLE {table_name} (id serial primary key);")

    tables = list_tables(conn=db_connection)
    assert table_name in tables


def test_get_table_schema(db_connection: psycopg.Connection):
    """Should retrieve the correct schema for a given table."""
    table_name = "test_schema_table"
    with db_connection.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {table_name} (id serial primary key, name text, value integer);"
        )

    schema = get_table_schema(table_name, conn=db_connection)
    assert schema == {"id": "integer", "name": "text", "value": "integer"}


def test_get_table_indexes(db_connection: psycopg.Connection):
    """Should retrieve the correct indexes for a given table."""
    table_name = "test_index_table"
    index_name = "idx_test_index_table_name"
    with db_connection.cursor() as cur:
        cur.execute(f"CREATE TABLE {table_name} (id serial primary key, name text);")
        cur.execute(f"CREATE INDEX {index_name} ON {table_name} (name);")

    indexes = get_table_indexes(table_name, conn=db_connection)

    # Check for both the primary key index (name might vary) and the explicit index
    assert index_name in indexes
    assert any(idx.endswith("_pkey") for idx in indexes)  # Check for pk index
    assert len(indexes) >= 2  # Ensure at least the PK and the created index are found
