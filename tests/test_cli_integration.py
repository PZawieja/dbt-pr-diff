import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dbt_pr_diff.cli import main

TELHADO = Path(__file__).resolve().parent.parent / "examples" / "telhado"
FCT = "models/marts/fct_daily_generation.sql"


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    project = tmp_path / "telhado"
    shutil.copytree(
        TELHADO,
        project,
        ignore=shutil.ignore_patterns(
            "target", "logs", "*.duckdb", ".user.yml", "dbt_packages"
        ),
    )
    git("init", "-q", "-b", "main", cwd=tmp_path)
    git("-c", "user.name=t", "-c", "user.email=t@t", "add", ".", cwd=tmp_path)
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-qm",
        "base",
        cwd=tmp_path,
    )
    return tmp_path, project


def run(repo_root, project, *extra, monkeypatch):
    monkeypatch.chdir(repo_root)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["compare", "--project-dir", str(project), "--no-ai", *extra])
    report = json.loads((repo_root / ".pr-diff" / "pr-diff.json").read_text())
    return exc.value.code, {m["name"]: m for m in report["models"]}


def test_capacity_factor_change(repo, monkeypatch):
    root, project = repo
    sql = (project / FCT).read_text().replace("peak_kw * 24", "installed_kw * 24")
    (project / FCT).write_text(sql)
    code, models = run(
        root, project, "--fail-on", "pk_duplicates", monkeypatch=monkeypatch
    )
    fct = models["fct_daily_generation"]
    assert code == 0
    assert fct["added"] == 0 and fct["removed"] == 0 and fct["changed"] > 0
    assert fct["sample_changed"][0]["key"].startswith("PRT-027|")
    assert set(models) == {"fct_daily_generation", "fct_site_monthly"}


FAN_OUT_SQL = """WITH daily AS (
    SELECT *
    FROM {{ ref('int_site_daily_generation') }}
)

, inverters AS (
    SELECT *
    FROM {{ ref('stg_inverters') }}
)

SELECT
    daily.site_id || '|' || STRFTIME(daily.generation_date, '%Y-%m-%d')
        AS daily_generation_id
    , daily.site_id
    , daily.generation_date
    , inverters.inverter_model
    , daily.energy_kwh
    , daily.irradiance_kwh_m2
    , ROUND(daily.energy_kwh / (daily.peak_kw * 24), 4) AS capacity_factor
FROM daily
LEFT JOIN inverters
    ON daily.site_id = inverters.site_id
"""


def test_fan_out_fails(repo, monkeypatch):
    root, project = repo
    (project / FCT).write_text(FAN_OUT_SQL)
    code, models = run(
        root, project, "--fail-on", "pk_duplicates", monkeypatch=monkeypatch
    )
    fct = models["fct_daily_generation"]
    assert code == 1
    assert fct["dup_keys_head"] > 0 and fct["dup_keys_base"] == 0
    assert fct["columns_added"] == {"inverter_model": "VARCHAR"}


def test_no_changes(repo, monkeypatch):
    root, project = repo
    code, models = run(
        root, project, "--fail-on", "pk_duplicates", monkeypatch=monkeypatch
    )
    assert code == 0 and models == {}
