from dbt_pr_diff.manifest import model_ids, spec


def manifest(model_meta=None, column_meta=None):
    return {
        "nodes": {
            "model.p.fct": {
                "unique_id": "model.p.fct",
                "resource_type": "model",
                "name": "fct",
                "schema": "main",
                "alias": "fct",
                "config": {"materialized": "table", "meta": model_meta or {}},
                "columns": {
                    "id": {"name": "id"},
                    "amount": {"name": "amount", "config": {"meta": column_meta or {}}},
                    "legacy": {"name": "legacy", "meta": {"diff_metric": True}},
                },
            },
            "model.p.eph": {
                "unique_id": "model.p.eph",
                "resource_type": "model",
                "name": "eph",
                "schema": "main",
                "config": {"materialized": "ephemeral"},
            },
            "test.p.unique_fct_id": {
                "resource_type": "test",
                "attached_node": "model.p.fct",
                "test_metadata": {"name": "unique"},
                "column_name": "id",
            },
        }
    }


def test_key_from_unique_test_and_metrics_from_meta():
    s = spec(manifest(column_meta={"diff_metric": True}), "model.p.fct")
    assert s.keys == ["id"]
    assert s.metrics == ["amount", "legacy"]


def test_diff_key_meta_overrides_tests():
    m = manifest(model_meta={"diff_key": ["site_id", "day"]})
    assert spec(m, "model.p.fct").keys == ["site_id", "day"]
    m = manifest(model_meta={"diff_key": "other"})
    assert spec(m, "model.p.fct").keys == ["other"]


def test_ephemeral_models_are_skipped():
    assert model_ids(manifest()) == {"model.p.fct"}
