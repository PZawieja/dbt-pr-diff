import re
from dataclasses import dataclass

from dbt_pr_diff.diff import ModelDiff

FLAG_RULES = {
    "pk_duplicates",
    "removed_rows",
    "added_rows",
    "changed_rows",
    "schema_change",
}
NUMERIC_RULES = {"row_count_pct", "metric_pct"}
PATTERN = re.compile(r"^(?P<rule>[a-z_]+)\s*(?:>\s*(?P<limit>\d+(?:\.\d+)?))?$")


@dataclass
class Rule:
    name: str
    limit: float | None = None


@dataclass
class Breach:
    model: str
    rule: str
    detail: str


def parse(spec: str) -> list[Rule]:
    rules = []
    for raw in filter(None, (part.strip() for part in spec.split(","))):
        match = PATTERN.match(raw)
        if not match:
            raise ValueError(f"cannot parse fail_on rule: {raw!r}")
        name, limit = match["rule"], match["limit"]
        if name in FLAG_RULES and limit is None:
            rules.append(Rule(name))
        elif name in NUMERIC_RULES and limit is not None:
            rules.append(Rule(name, float(limit)))
        else:
            known = sorted(FLAG_RULES) + [f"{r}>N" for r in sorted(NUMERIC_RULES)]
            raise ValueError(f"unknown fail_on rule {raw!r}; use one of {known}")
    return rules


def _check(rule: Rule, d: ModelDiff) -> str | None:
    match rule.name:
        case "pk_duplicates":
            new = (d.dup_keys_head or 0) - (d.dup_keys_base or 0)
            if new > 0:
                return (
                    f"{d.dup_keys_head:,} keys appear more than once "
                    f"(base: {d.dup_keys_base or 0:,})"
                )
        case "removed_rows" if d.removed:
            return f"{d.removed:,} rows removed"
        case "added_rows" if d.added:
            return f"{d.added:,} rows added"
        case "changed_rows" if d.changed:
            return f"{d.changed:,} rows changed"
        case "schema_change" if (
            d.columns_added or d.columns_removed or d.columns_retyped
        ):
            return "columns added, removed or retyped"
        case "row_count_pct":
            if d.row_pct is not None and abs(d.row_pct) > rule.limit:
                return f"row count moved {d.row_pct:+.1f}% (limit {rule.limit:g}%)"
        case "metric_pct":
            for m in d.metrics:
                if m.sum_pct is not None and abs(m.sum_pct) > rule.limit:
                    return (
                        f"sum of {m.column} moved {m.sum_pct:+.1f}% "
                        f"(limit {rule.limit:g}%)"
                    )
    return None


def evaluate(rules: list[Rule], diffs: list[ModelDiff]) -> list[Breach]:
    breaches = []
    for d in diffs:
        for rule in rules:
            detail = _check(rule, d)
            if detail:
                breaches.append(Breach(d.name, rule.name, detail))
    return breaches
