# dbt-pr-diff

**When someone changes a data model, this shows the reviewer what happens to the actual numbers, not just the code, before the change goes live.**

## At a glance

### The problem

Data teams review changes the way software teams do. Someone proposes an edit (a *pull request*), a colleague reads the code and approves it. But a change can look harmless in code and still break the numbers. One extra join can quietly double every row in a table, and every report built on it doubles too. Nobody notices until a dashboard looks wrong in a meeting.

### How it works, simply

1. Someone proposes a change to the data models.
2. The tool builds the data twice, before and after the change, and compares the two.
3. It posts one short report on the proposal: how many rows changed, whether anything got duplicated, which totals moved.
4. If a rule is broken, for example rows were duplicated, the check turns red so the change can't be merged by accident.

### What you get

- **Reviewers see the effect on the data in seconds**, without running anything themselves.
- **Duplicated rows are caught before they reach a dashboard.** In the demo, a new join raised total energy by 65% while the average moved less than 1%: exactly the kind of change that passes a code review.
- **Intended changes come with evidence.** "The metric changes for these sites, row counts don't" is easier to approve than a wall of SQL.
- **Nothing to run or pay for**: a GitHub Action with no server and no account. An AI summary of the numbers is optional.

### Analytics engineering tasks it covers

- Reviewing dbt pull requests
- Testing model changes for regressions before they reach production
- Catching grain breaks and fan-out joins
- Checking that a metric change moved the numbers it was meant to, and only those
- dbt CI on GitHub Actions
- Writing the "what changes in the data" part of a PR description

### Can I use it at work?

- **Your dbt project runs on DuckDB:** yes, as is. Add one workflow file ([Quickstart](#quickstart)) and every PR gets the comment. About 15 minutes.
- **Your project runs on Snowflake, BigQuery or Databricks:** not directly, because it builds both sides in DuckDB. Use the comment as the template for what a data PR should show, run the same comparison by hand with the SQL in [the post](https://goldlayer.dev/writing/data-pull-requests-show-the-numbers.html), or use [Recce](https://github.com/DataRecce/recce) or dbt Cloud's "compare changes", which work against those warehouses.
- **Any team, starting with your next PR:** add a short "what changes in the data" table to the description (row counts before and after, duplicate keys, the totals you expected to move). No tool needed.

### Try it in two minutes

```bash
git clone https://github.com/PZawieja/dbt-pr-diff && cd dbt-pr-diff && uv sync
git switch demo/fan-out && uv run dbt-pr-diff compare --project-dir examples/telhado
```

Or just read the comments on the [four open demo PRs](#the-demo).

## What it does

A reviewer can read your SQL. Without help, they can't see that the join you added doubled the rows in `fct_daily_generation`.

dbt-pr-diff builds both sides of a dbt pull request in DuckDB, compares every model in `state:modified+`, and posts the numbers as one comment on the PR. That covers row counts, keys added, removed and changed, duplicate keys, schema changes, column null-rate and distinct-count shifts, and sums and averages of the columns you mark as metrics. A `fail_on` rule turns a grain break into a red check.

It is a GitHub Action and a CLI of about 1,000 lines with no server and no account. It pairs with the post [Reviewers can read your SQL. Show them the numbers.](https://goldlayer.dev/writing/data-pull-requests-show-the-numbers.html)

## What the comment looks like

This is the real comment on the [fan-out demo PR](https://github.com/PZawieja/dbt-pr-diff/pull/2), where a join to `stg_inverters` duplicates every site that has more than one inverter:

<img src="docs/images/pr-comment-fan-out.png" width="820" alt="A dbt-pr-diff pull request comment titled 2 checks failed. fct_daily_generation went from 2,441 to 4,056 rows, plus 66.2 percent, with 1,133 duplicate keys. Two failed checks are listed: pk_duplicates and row_count_pct. An AI summary notes that average energy barely moved while the sum rose 64.7 percent, which points to repeated rows, and suggests inspecting the duplicated keys and the new inverter_model join.">

The average barely moves while the sum goes up 65%, which is why the comment shows both:

<img src="docs/images/average-hides-fan-out.svg" width="820" alt="Two bar charts for demo PR 2. Average energy per row goes from 33.75 to 33.46 kWh, minus 0.9 percent, which looks fine. Total energy goes from 82,394 to 135,709 kWh, plus 64.7 percent, inflated by duplicate rows.">

## How it works

```mermaid
flowchart LR
    PR[pull request] --> W[git worktree<br/>base branch]
    PR --> H[working tree<br/>head]
    W --> B[(base.duckdb)]
    H --> D[(head.duckdb)]
    H --> S["dbt ls<br/>state:modified+"]
    B --> X[diff in one DuckDB<br/>ATTACH base, head]
    D --> X
    S --> X
    X --> T{fail_on}
    X --> AI[optional AI summary<br/>numbers only]
    T --> C[sticky PR comment<br/>+ step summary + JSON]
    AI --> C
```

1. **Build both sides.** It checks out the base branch in a `git worktree` and runs `dbt seed` and `dbt run` into `base.duckdb`, then does the same for the PR into `head.duckdb`. Tests are left to your normal CI, so a failing test can't hide the diff that explains it.
2. **Pick the models.** `dbt ls --select state:modified+` runs against the base manifest, so only changed models and everything downstream get compared.
3. **Find keys and metrics in your YAML.** The key is the column with a `unique` test, or `meta: {diff_key: [a, b]}` for composite keys. Metrics are columns with `meta: {diff_metric: true}`.
4. **Diff in SQL.** One DuckDB connection attaches both files. Rows are matched on the key and compared by a hash of their shared columns. Duplicate keys are counted on each side, so a grain break the PR introduces is separated from one that was already there.
5. **Post.** It writes one comment and updates it on every push instead of adding new ones. The same markdown goes to the job summary, and the full report is uploaded as `pr-diff.json`.

## Quickstart

### In GitHub Actions

```yaml
# .github/workflows/pr-diff.yml
name: pr-diff
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: PZawieja/dbt-pr-diff@v0
        with:
          project-dir: .
          fail-on: pk_duplicates,removed_rows,row_count_pct>10
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}  # optional
```

| Input | Default | |
|---|---|---|
| `project-dir` | `.` | dbt project path |
| `base-ref` | the PR's base branch | branch to compare against |
| `select` | `state:modified+` | any dbt selector |
| `fail-on` | none | `pk_duplicates`, `removed_rows`, `added_rows`, `changed_rows`, `schema_change`, `row_count_pct>N`, `metric_pct>N` |
| `comment` | `true` | post the sticky comment |
| `dbt-duckdb-version` | latest | pin to match your project |

### Locally, before you open the PR

```bash
uvx --from git+https://github.com/PZawieja/dbt-pr-diff dbt-pr-diff compare \
  --base-ref main --project-dir path/to/dbt_project
```

It prints the same markdown, ready to paste under "What changes in the data" in your PR description.

### Try it on the demo project

```bash
git clone https://github.com/PZawieja/dbt-pr-diff && cd dbt-pr-diff
uv sync && uv run pytest -q
git switch demo/fan-out && uv run dbt-pr-diff compare --project-dir examples/telhado
```

## The demo

`examples/telhado` is a small dbt project for Telhado, a fictional rooftop-solar co-op in Portugal: 30 sites, their inverters, and 90 days of meter readings, generated by a seeded script. Four PRs stay open so you can read real comments:

| PR | What it does | Verdict |
|---|---|---|
| [#1 Safe refactor](https://github.com/PZawieja/dbt-pr-diff/pull/1) | Renames CTEs and reformats SQL | ✅ no data changes |
| [#2 Silent fan-out](https://github.com/PZawieja/dbt-pr-diff/pull/2) | Adds `inverter_model` by joining inverters without aggregating | ❌ duplicate keys, rows +66% |
| [#3 Filter drift](https://github.com/PZawieja/dbt-pr-diff/pull/3) | Lets `estimated` readings into the trusted daily table | ⚠️ rows added, null rate shifts |
| [#4 Capacity-factor fix](https://github.com/PZawieja/dbt-pr-diff/pull/4) | Divides by installed kW instead of peak kW | ⚠️ values change, rows don't |

## AI summary

If `ANTHROPIC_API_KEY` is set, Claude Haiku 5.5 reads the aggregates (never row samples) and writes three bullets: what changed, the biggest risk, and what to check by hand. The section is labeled as AI-written. Without a key, or on PRs from forks, which don't get secrets, the comment is the same minus that section.

## Limits

- DuckDB only. The diff SQL is portable, but the build step assumes DuckDB files. For a warehouse, point `--base-db` at an existing production copy, or use the tools below.
- It builds both sides in full. That takes seconds at demo scale and is the wrong choice for a large project (see [decisions](docs/decisions.md)).
- PRs from forks get a read-only token, so they get the job summary instead of a comment.

## Prior art

- [Recce](https://github.com/DataRecce/recce) is the most complete open-source option: an interactive server with lineage diff, profile diff, query diff and checklists. If your team wants a review UI, use it.
- [datafold/data-diff](https://github.com/datafold/data-diff) did fast cross-database diffs. It was archived in May 2024; forks such as reladiff continue it.
- dbt Cloud's "compare changes" does this inside dbt Cloud CI.
- [dbt-audit-helper](https://github.com/dbt-labs/dbt-audit-helper) has macros for comparing two relations by hand.

dbt-pr-diff takes a narrower position: comment first, no infrastructure, opinionated failure rules, and code short enough to read in one sitting.

## Development

```bash
uv sync --all-extras
uv run pytest -q                       # unit tests + two end-to-end runs
uvx ruff check . && uv run sqlfluff lint examples/telhado/models
python examples/telhado/scripts/generate.py   # regenerate seeds
```

Design notes are in [docs/decisions.md](docs/decisions.md). MIT licensed.
