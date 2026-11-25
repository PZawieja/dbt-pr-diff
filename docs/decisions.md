# Decisions

## 1. Build both sides in full instead of `--defer`

**Choice:** run `dbt seed` and `dbt run` for the base branch and the PR into two DuckDB files.

**Why:** defer reads unchanged parents from production, and with DuckDB there is no shared production schema, only files. Two full builds are simple, deterministic and take seconds on a demo-sized project. `--base-db` and `--base-state` let a team skip the base build when it already keeps a production DuckDB file and manifest.

**Cost:** the wrong choice for a project that takes minutes to build. There the diff SQL in `diff.py` stays useful, and the build step should be replaced.

## 2. `seed` + `run`, not `build`

**Choice:** don't run tests while building for the diff.

**Why:** with `dbt build`, a failing `unique` test skips everything downstream, so the fan-out PR would show no numbers for the downstream models, which is the PR that needs them most. Tests belong to the regular CI job (`ci.yml` runs `dbt build`), and both checks go red on that PR.

## 3. Match rows on the key, compare by hash

**Choice:** group each side by key, keep a row count and an MD5 of the shared columns cast to text, and compare those.

**Why:** it's one pass per side, it works on any column types, and it separates the three cases a reviewer cares about: rows added, rows removed, and same key with different values. Keys duplicated on either side are left out of "changed" and counted as duplicates instead, so a fan-out isn't double-reported.

**Cost:** a column whose type changes (DECIMAL to DOUBLE) can make every row look changed. The schema section flags the retype, so the cause is visible.

## 4. Key discovery: `meta.diff_key`, then the `unique` test

**Why:** most dbt projects already declare their grain with a `unique` test. `diff_key` covers composite keys without needing `dbt_utils`. A model with neither still gets row counts, column shifts and metrics, plus a note asking for a key.

## 5. Metrics are opt-in

**Choice:** sums and averages only for columns tagged `meta: {diff_metric: true}`.

**Why:** summing every numeric column produces noise like "sum of site_id changed". Tagging metrics also documents which columns matter.

## 6. Averages and sums together

**Why:** a fan-out duplicates rows roughly evenly, so the average stays put while the sum inflates. In the demo, energy is up 65% while the average moves 0.9%. A comment with only averages would call that PR safe.

## 7. The LLM sees numbers only

**Choice:** the AI summary gets the JSON report with every `sample_*` field removed. The model is Claude Haiku 5.5 at low effort, and the summary is labeled as AI-written.

**Why:** row samples are customer data and add little to a summary of aggregates. Model and column names still go in, so the prompt tells the model to treat them as data. With no key the section is skipped silently, which keeps CI and fork PRs working.

## 8. Fork PRs get a step summary, not a comment

**Why:** `pull_request` workflows from forks get a read-only `GITHUB_TOKEN` and no secrets. `pull_request_target` would allow a comment but runs with write access on untrusted code, and a dbt build executes that code. The safer default is the job summary.

## 9. Not a wrapper around Recce

**Why:** Recce is an interactive review tool with a server and a UI. This project is about the smallest thing that puts numbers in front of a reviewer without anyone opening a new tool. Rebuilding the core in plain SQL also keeps the implementation readable as a reference.
