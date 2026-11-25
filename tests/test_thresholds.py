import pytest

from dbt_pr_diff.diff import MetricShift, ModelDiff
from dbt_pr_diff.thresholds import evaluate, parse


def test_parse_flags_and_limits():
    rules = parse("pk_duplicates, row_count_pct>5,metric_pct > 10.5")
    assert [(r.name, r.limit) for r in rules] == [
        ("pk_duplicates", None),
        ("row_count_pct", 5.0),
        ("metric_pct", 10.5),
    ]
    assert parse("") == []


@pytest.mark.parametrize("bad", ["row_count_pct", "pk_duplicates>1", "nope", "a>b"])
def test_parse_rejects_bad_rules(bad):
    with pytest.raises(ValueError):
        parse(bad)


def test_evaluate():
    d = ModelDiff(
        name="fct",
        status="changed",
        keys=["id"],
        rows_base=100,
        rows_head=150,
        added=0,
        removed=2,
        changed=0,
        dup_keys_base=0,
        dup_keys_head=50,
        metrics=[MetricShift("amount", 100.0, 108.0, 1.0, 1.08)],
    )
    rules = parse("pk_duplicates,removed_rows,row_count_pct>10,metric_pct>10")
    breaches = evaluate(rules, [d])
    assert [b.rule for b in breaches] == [
        "pk_duplicates",
        "removed_rows",
        "row_count_pct",
    ]


def test_existing_duplicates_do_not_fail():
    d = ModelDiff(
        name="fct", status="unchanged", keys=["id"], dup_keys_base=3, dup_keys_head=3
    )
    assert evaluate(parse("pk_duplicates"), [d]) == []
