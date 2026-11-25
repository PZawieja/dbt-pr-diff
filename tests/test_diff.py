from conftest import BASE_ROWS

from dbt_pr_diff.diff import diff_model, pct
from dbt_pr_diff.manifest import ModelSpec


def spec(keys=("id",), metrics=("amount",)):
    return ModelSpec(
        "model.x.orders", "orders", "main", "orders", list(keys), list(metrics)
    )


def test_identical_tables_are_unchanged(pair):
    d = diff_model(pair(BASE_ROWS), spec())
    assert d.status == "unchanged"
    assert (d.added, d.removed, d.changed) == (0, 0, 0)
    assert d.dup_keys_head == 0


def test_added_removed_changed(pair):
    head = """
        SELECT * FROM (VALUES
            ('a', 1, 10.0, 'x'),
            ('b', 2, 25.0, 'y'),
            ('c', 3, 30.0, NULL),
            ('e', 5, 50.0, 'w')
        ) AS t(id, n, amount, label)
    """
    d = diff_model(pair(head), spec())
    assert d.status == "changed"
    assert (d.added, d.removed, d.changed) == (1, 1, 1)
    assert d.sample_added == ["e"]
    assert d.sample_removed == ["d"]
    assert d.sample_changed == [{"key": "b", "columns": {"amount": ["20.0", "25.0"]}}]


def test_fan_out_counts_duplicate_keys(pair):
    head = (
        BASE_ROWS + " UNION ALL SELECT 'a', 1, 10.0, 'x' UNION ALL "
        "SELECT 'b', 2, 20.0, 'y'"
    )
    d = diff_model(pair(head), spec())
    assert d.rows_base == 4 and d.rows_head == 6
    assert d.dup_keys_base == 0 and d.dup_keys_head == 2
    assert d.sample_dup_keys == ["a", "b"]
    assert d.changed == 0
    amount = d.metrics[0]
    assert amount.sum_base == 100.0 and amount.sum_head == 130.0
    assert round(amount.sum_pct, 1) == 30.0


def test_schema_change(pair):
    head = (
        f"SELECT id, CAST(n AS VARCHAR) AS n, amount, 'new' AS extra FROM ({BASE_ROWS})"
    )
    d = diff_model(pair(head), spec())
    assert d.columns_added == {"extra": "VARCHAR"}
    assert d.columns_removed == {"label": "VARCHAR"}
    assert d.columns_retyped == {"n": ["INTEGER", "VARCHAR"]}
    assert d.status == "changed"


def test_null_rate_shift_is_flagged(pair):
    head = f"SELECT id, n, amount, NULL::VARCHAR AS label FROM ({BASE_ROWS})"
    d = diff_model(pair(head), spec())
    shifts = {s.column: s for s in d.column_shifts}
    assert shifts["label"].null_pct_base == 25.0
    assert shifts["label"].null_pct_head == 100.0


def test_composite_key(pair):
    head = BASE_ROWS.replace("('d', 4, 40.0, 'z')", "('d', 5, 40.0, 'z')")
    d = diff_model(pair(head), spec(keys=("id", "n")))
    assert (d.added, d.removed, d.changed) == (1, 1, 0)
    assert d.sample_added == ["d | 5"]


def test_without_key_compares_aggregates_only(pair):
    head = BASE_ROWS.replace("40.0", "41.0")
    d = diff_model(pair(head), spec(keys=()))
    assert d.added is None and d.changed is None
    assert d.status == "changed"
    assert d.metrics[0].sum_head == 101.0


def test_new_removed_and_missing_models(tmp_path):
    import duckdb

    from dbt_pr_diff.diff import connect

    base = duckdb.connect(str(tmp_path / "b.duckdb"))
    base.execute("CREATE TABLE gone AS SELECT 1 AS id")
    base.close()
    head = duckdb.connect(str(tmp_path / "h.duckdb"))
    head.execute("CREATE TABLE fresh AS SELECT 1 AS id UNION ALL SELECT 2")
    head.close()
    con = connect(str(tmp_path / "b.duckdb"), str(tmp_path / "h.duckdb"))
    fresh = diff_model(con, ModelSpec("m1", "fresh", "main", "fresh", ["id"], []))
    assert fresh.status == "new" and fresh.rows_head == 2
    gone = diff_model(con, ModelSpec("m2", "gone", "main", "gone", ["id"], []))
    assert gone.status == "removed"
    ghost = diff_model(con, ModelSpec("m3", "ghost", "main", "ghost", ["id"], []))
    assert ghost.status == "missing"


def test_float_noise_is_not_a_change():
    from dbt_pr_diff.diff import same

    assert same(82393.70000000001, 82393.7)
    assert not same(82393.7, 82393.8)
    assert pct(82393.70000000001, 82393.7) == 0.0


def test_pct_edges():
    assert pct(None, 1) is None
    assert pct(0, 0) == 0.0
    assert pct(0, 5) is None
    assert pct(50, 75) == 50.0
