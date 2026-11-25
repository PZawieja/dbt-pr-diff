import json
from dataclasses import asdict

from dbt_pr_diff.diff import ModelDiff, pct
from dbt_pr_diff.thresholds import Breach

MARKER = "<!-- dbt-pr-diff -->"


def _n(value) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:,.4g}" if abs(value) < 1000 else f"{value:,.1f}"
    return f"{value:,}"


def _cell(value) -> str:
    return "–" if value is None else str(value).replace("|", "\\|")


def _pct(value: float | None) -> str:
    if value is None:
        return "–"
    if value == 0:
        return "0%"
    if abs(value) < 0.05:
        return "±0.0%"
    return f"{value:+.1f}%"


def verdict(diffs: list[ModelDiff], breaches: list[Breach]) -> tuple[str, str]:
    if breaches:
        n = len(breaches)
        return "❌", f"{n} check{'s' if n > 1 else ''} failed"
    changed = [d for d in diffs if d.has_changes]
    if changed:
        n = len(changed)
        return "⚠️", f"data changed in {n} model{'s' if n > 1 else ''}"
    return "✅", "no data changes"


def _status(d: ModelDiff, failed: set[str]) -> str:
    if d.name in failed:
        return "❌ failed"
    return {
        "unchanged": "✅ same",
        "changed": "⚠️ changed",
        "new": "🆕 new",
        "removed": "🗑️ removed",
        "missing": "– not built",
    }[d.status]


def _summary_table(diffs: list[ModelDiff], failed: set[str]) -> list[str]:
    lines = [
        "| Model | Rows base → head | Δ rows | Added | Removed | Changed "
        "| Dup keys | Status |",
        "|---|--:|--:|--:|--:|--:|--:|---|",
    ]
    for d in diffs:
        dups = "–" if d.dup_keys_head is None else _n(d.dup_keys_head)
        lines.append(
            f"| `{d.name}` | {_n(d.rows_base)} → {_n(d.rows_head)} "
            f"| {_pct(d.row_pct)} | {_n(d.added)} | {_n(d.removed)} "
            f"| {_n(d.changed)} | {dups} | {_status(d, failed)} |"
        )
    return lines


def _details(d: ModelDiff) -> list[str]:
    key = ", ".join(f"`{k}`" for k in d.keys) or "none found"
    out = ["<details>", f"<summary><b>{d.name}</b> · key {key}</summary>", ""]
    if not d.keys:
        out += [
            "No primary key found, so rows were not matched one to one. Add a "
            "`unique` test or `meta: {diff_key: ...}` to the model.",
            "",
        ]
    if d.columns_added or d.columns_removed or d.columns_retyped:
        out.append("**Schema**")
        out += [f"- added `{c}` {t}" for c, t in d.columns_added.items()]
        out += [f"- removed `{c}` {t}" for c, t in d.columns_removed.items()]
        out += [f"- `{c}` {a} → {b}" for c, (a, b) in d.columns_retyped.items()]
        out.append("")
    if d.metrics:
        out += [
            "**Metrics**",
            "",
            "| Column | Sum base | Sum head | Δ | Avg base | Avg head | Δ |",
            "|---|--:|--:|--:|--:|--:|--:|",
        ]
        for m in d.metrics:
            out.append(
                f"| `{m.column}` | {_n(m.sum_base)} | {_n(m.sum_head)} "
                f"| {_pct(m.sum_pct)} | {_n(m.avg_base)} | {_n(m.avg_head)} "
                f"| {_pct(m.avg_pct)} |"
            )
        out.append("")
    if d.column_shifts:
        out += [
            "**Column shifts**",
            "",
            "| Column | Null % base → head | Distinct base → head | Δ distinct |",
            "|---|--:|--:|--:|",
        ]
        for s in d.column_shifts:
            out.append(
                f"| `{s.column}` | {s.null_pct_base:g}% → {s.null_pct_head:g}% "
                f"| {_n(s.distinct_base)} → {_n(s.distinct_head)} "
                f"| {_pct(pct(s.distinct_base, s.distinct_head))} |"
            )
        out.append("")
    if d.sample_dup_keys:
        keys = ", ".join(f"`{k}`" for k in d.sample_dup_keys)
        out += [
            f"**Duplicate keys in head** (first {len(d.sample_dup_keys)}): {keys}",
            "",
        ]
    if d.sample_changed:
        out += [
            "**Changed rows** (sample)",
            "",
            "| Key | Column | Base | Head |",
            "|---|---|--:|--:|",
        ]
        for row in d.sample_changed:
            for i, (col, (before, after)) in enumerate(row["columns"].items()):
                key = f"`{_cell(row['key'])}`" if i == 0 else ""
                out.append(
                    f"| {key} | `{_cell(col)}` | {_cell(before)} | {_cell(after)} |"
                )
        out.append("")
    for label, keys in (("Added", d.sample_added), ("Removed", d.sample_removed)):
        if keys:
            joined = ", ".join(f"`{k}`" for k in keys)
            out += [f"**{label} keys** (first {len(keys)}): {joined}", ""]
    out.append("</details>")
    return out


def markdown(
    diffs: list[ModelDiff],
    breaches: list[Breach],
    base_label: str,
    head_label: str,
    ai_summary: str | None = None,
) -> str:
    icon, text = verdict(diffs, breaches)
    failed = {b.model for b in breaches}
    lines = [
        MARKER,
        f"## {icon} dbt-pr-diff: {text}",
        "",
        f"Compared **{head_label}** against **{base_label}** · "
        f"{len(diffs)} model{'s' if len(diffs) != 1 else ''} in "
        "`state:modified+`",
        "",
    ]
    if not diffs:
        lines.append("No models changed in this pull request.")
        return "\n".join(lines) + "\n"
    lines += _summary_table(diffs, failed)
    lines.append("")
    if breaches:
        lines.append("**Failed checks**")
        lines += [f"- `{b.model}` · `{b.rule}`: {b.detail}" for b in breaches]
        lines.append("")
    if ai_summary:
        lines += [
            "**AI summary** (written from the numbers above only, verify before "
            "trusting)",
            "",
            ai_summary.strip(),
            "",
        ]
    for d in diffs:
        if d.has_changes and d.status not in {"removed", "missing"}:
            lines += _details(d)
            lines.append("")
    lines.append(
        "<sub>Generated by [dbt-pr-diff](https://github.com/PZawieja/dbt-pr-diff) "
        "from full builds of both refs in DuckDB.</sub>"
    )
    return "\n".join(lines) + "\n"


def to_json(diffs: list[ModelDiff], breaches: list[Breach], samples=True) -> str:
    models = []
    for d in diffs:
        item = asdict(d)
        item["row_pct"] = d.row_pct
        for m, raw in zip(item["metrics"], d.metrics, strict=True):
            m["sum_pct"], m["avg_pct"] = raw.sum_pct, raw.avg_pct
        if not samples:
            for k in [k for k in item if k.startswith("sample_")]:
                del item[k]
        models.append(item)
    return json.dumps(
        {"models": models, "breaches": [asdict(b) for b in breaches]},
        indent=2,
        default=str,
    )
