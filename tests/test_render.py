import json
import os
from pathlib import Path

from dbt_pr_diff.diff import ColumnShift, MetricShift, ModelDiff
from dbt_pr_diff.render import MARKER, markdown, to_json, verdict
from dbt_pr_diff.thresholds import Breach

GOLDEN = Path(__file__).parent / "golden" / "fan_out.md"


def fan_out() -> list[ModelDiff]:
    return [
        ModelDiff(
            name="fct_daily_generation",
            status="changed",
            keys=["daily_generation_id"],
            rows_base=2441,
            rows_head=4056,
            added=0,
            removed=0,
            changed=0,
            dup_keys_base=0,
            dup_keys_head=1133,
            columns_added={"inverter_model": "VARCHAR"},
            metrics=[MetricShift("energy_kwh", 82393.7, 135708.7, 33.75, 33.46)],
            sample_dup_keys=["PRT-003|2026-08-17"],
        ),
        ModelDiff(
            name="fct_site_monthly",
            status="changed",
            keys=["site_month_id"],
            rows_base=120,
            rows_head=120,
            added=0,
            removed=0,
            changed=56,
            dup_keys_base=0,
            dup_keys_head=0,
            column_shifts=[ColumnShift("days_reported", 0.0, 0.0, 15, 33)],
            sample_changed=[
                {"key": "PRT-023|2026-09", "columns": {"days_reported": ["29", "87"]}}
            ],
        ),
        ModelDiff(
            name="dim_sites",
            status="unchanged",
            keys=["site_id"],
            rows_base=30,
            rows_head=30,
            added=0,
            removed=0,
            changed=0,
            dup_keys_base=0,
            dup_keys_head=0,
        ),
    ]


def breaches():
    return [
        Breach(
            "fct_daily_generation",
            "pk_duplicates",
            "1,133 keys appear more than once (base: 0)",
        )
    ]


def test_markdown_matches_golden():
    out = markdown(fan_out(), breaches(), "main (abc1234)", "HEAD (def5678)")
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(out)
    assert out == GOLDEN.read_text()


def test_markdown_basics():
    out = markdown(fan_out(), breaches(), "main", "HEAD", ai_summary="- one")
    assert out.startswith(MARKER)
    assert "## ❌ dbt-pr-diff: 1 check failed" in out
    assert "`PRT-023\\|2026-09`" in out
    assert "**AI summary**" in out
    assert "<b>dim_sites</b>" not in out


def test_verdicts():
    assert verdict([], [])[1] == "no data changes"
    assert verdict(fan_out()[2:], [])[0] == "✅"
    assert verdict(fan_out()[1:], [])[1] == "data changed in 1 model"


def test_json_without_samples_drops_row_values():
    payload = json.loads(to_json(fan_out(), breaches(), samples=False))
    assert "sample_changed" not in payload["models"][1]
    assert round(payload["models"][0]["metrics"][0]["sum_pct"], 1) == 64.7
    assert payload["breaches"][0]["rule"] == "pk_duplicates"


def test_no_models():
    assert "No models changed" in markdown([], [], "main", "HEAD")
