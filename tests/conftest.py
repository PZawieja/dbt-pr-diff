import duckdb
import pytest

from dbt_pr_diff.diff import connect

BASE_ROWS = """
    SELECT * FROM (VALUES
        ('a', 1, 10.0, 'x'),
        ('b', 2, 20.0, 'y'),
        ('c', 3, 30.0, NULL),
        ('d', 4, 40.0, 'z')
    ) AS t(id, n, amount, label)
"""


def make_db(path, sql: str, table: str = "orders") -> None:
    con = duckdb.connect(str(path))
    con.execute(f"CREATE TABLE {table} AS {sql}")
    con.close()


@pytest.fixture
def pair(tmp_path):
    def build(head_sql: str, base_sql: str = BASE_ROWS, table: str = "orders"):
        make_db(tmp_path / "base.duckdb", base_sql, table)
        make_db(tmp_path / "head.duckdb", head_sql, table)
        return connect(str(tmp_path / "base.duckdb"), str(tmp_path / "head.duckdb"))

    return build
