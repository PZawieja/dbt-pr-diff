import math
from dataclasses import dataclass, field

import duckdb

from dbt_pr_diff.manifest import ModelSpec

SAMPLE_SIZE = 5
NULL_RATE_PP = 1.0
DISTINCT_PCT = 5.0


@dataclass
class ColumnShift:
    column: str
    null_pct_base: float
    null_pct_head: float
    distinct_base: int
    distinct_head: int


@dataclass
class MetricShift:
    column: str
    sum_base: float | None
    sum_head: float | None
    avg_base: float | None
    avg_head: float | None

    @property
    def sum_pct(self) -> float | None:
        return pct(self.sum_base, self.sum_head)

    @property
    def avg_pct(self) -> float | None:
        return pct(self.avg_base, self.avg_head)


@dataclass
class ModelDiff:
    name: str
    status: str
    keys: list[str]
    rows_base: int | None = None
    rows_head: int | None = None
    added: int | None = None
    removed: int | None = None
    changed: int | None = None
    dup_keys_base: int | None = None
    dup_keys_head: int | None = None
    columns_added: dict[str, str] = field(default_factory=dict)
    columns_removed: dict[str, str] = field(default_factory=dict)
    columns_retyped: dict[str, list[str]] = field(default_factory=dict)
    column_shifts: list[ColumnShift] = field(default_factory=list)
    metrics: list[MetricShift] = field(default_factory=list)
    sample_changed: list[dict] = field(default_factory=list)
    sample_added: list[str] = field(default_factory=list)
    sample_removed: list[str] = field(default_factory=list)
    sample_dup_keys: list[str] = field(default_factory=list)

    @property
    def row_pct(self) -> float | None:
        return pct(self.rows_base, self.rows_head)

    @property
    def has_changes(self) -> bool:
        return self.status != "unchanged"


def same(base: float | None, head: float | None) -> bool:
    if base is None or head is None:
        return base is head
    # parallel float aggregation is not order-stable, so tiny drifts are noise
    return math.isclose(base, head, rel_tol=1e-9, abs_tol=1e-9)


def pct(base: float | None, head: float | None) -> float | None:
    if base is None or head is None:
        return None
    if same(base, head):
        return 0.0
    if base == 0:
        return 0.0 if head == 0 else None
    return (head - base) / abs(base) * 100


def q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def connect(base_db: str, head_db: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"ATTACH '{base_db}' AS b (READ_ONLY)")
    con.execute(f"ATTACH '{head_db}' AS h (READ_ONLY)")
    return con


def columns(con, catalog: str, schema: str, table: str) -> dict[str, str]:
    rows = con.execute(
        "SELECT column_name, data_type FROM duckdb_columns() "
        "WHERE database_name = ? AND schema_name = ? AND table_name = ? "
        "ORDER BY column_index",
        [catalog, schema, table],
    ).fetchall()
    return dict(rows)


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def _dup_keys(con, rel: str, keys: str) -> tuple[int, list[str]]:
    rows = con.execute(
        f"SELECT CONCAT_WS(' | ', {keys}) AS k FROM {rel} "
        f"GROUP BY ALL HAVING COUNT(*) > 1 ORDER BY k"
    ).fetchall()
    return len(rows), [r[0] for r in rows[:SAMPLE_SIZE]]


def _column_stats(con, rel: str, cols: list[str]) -> dict[str, tuple[float, int]]:
    if not cols:
        return {}
    parts = ["COUNT(*)"]
    for c in cols:
        parts += [f"COUNT({q(c)})", f"COUNT(DISTINCT {q(c)})"]
    row = con.execute(f"SELECT {', '.join(parts)} FROM {rel}").fetchone()
    total = row[0]
    stats = {}
    for i, c in enumerate(cols):
        non_null, distinct = row[1 + 2 * i], row[2 + 2 * i]
        null_pct = (total - non_null) / total * 100 if total else 0.0
        stats[c] = (round(null_pct, 2), distinct)
    return stats


def _metric_stats(con, rel: str, metrics: list[str]) -> dict[str, tuple]:
    if not metrics:
        return {}
    parts = [f"SUM({q(m)}), AVG({q(m)})" for m in metrics]
    row = con.execute(f"SELECT {', '.join(parts)} FROM {rel}").fetchone()
    return {m: (_num(row[2 * i]), _num(row[2 * i + 1])) for i, m in enumerate(metrics)}


def _num(value) -> float | None:
    return None if value is None else float(value)


def _shifted(base: tuple[float, int], head: tuple[float, int]) -> bool:
    if abs(head[0] - base[0]) > NULL_RATE_PP:
        return True
    distinct_pct = pct(base[1], head[1])
    return distinct_pct is None or abs(distinct_pct) > DISTINCT_PCT


def _key_expr(keys: list[str], alias: str) -> str:
    return "CONCAT_WS(' | ', " + ", ".join(f"{alias}.{q(k)}" for k in keys) + ")"


def _row_hash(cols: list[str], alias: str) -> str:
    parts = ", ".join(f"CAST({alias}.{q(c)} AS VARCHAR)" for c in cols)
    return f"MD5(CAST(ROW({parts}) AS VARCHAR))"


def _key_diff(con, b: str, h: str, spec: ModelSpec, common: list[str], d: ModelDiff):
    for name, rel in (("kb", b), ("kh", h)):
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE {name} AS "
            f"SELECT {_key_expr(spec.keys, 't')} AS k, COUNT(*) AS n, "
            f"MIN({_row_hash(common, 't')}) AS rh FROM {rel} AS t GROUP BY 1"
        )
    d.added = _scalar(con, "SELECT COUNT(*) FROM kh ANTI JOIN kb USING (k)")
    d.removed = _scalar(con, "SELECT COUNT(*) FROM kb ANTI JOIN kh USING (k)")
    con.execute(
        "CREATE OR REPLACE TEMP TABLE kc AS SELECT k FROM kb JOIN kh USING (k) "
        "WHERE kb.n = 1 AND kh.n = 1 AND kb.rh <> kh.rh"
    )
    d.changed = _scalar(con, "SELECT COUNT(*) FROM kc")
    d.sample_added = _keys(con, "SELECT k FROM kh ANTI JOIN kb USING (k)")
    d.sample_removed = _keys(con, "SELECT k FROM kb ANTI JOIN kh USING (k)")
    keys = ", ".join(q(k) for k in spec.keys)
    d.dup_keys_base, _ = _dup_keys(con, b, keys)
    d.dup_keys_head, d.sample_dup_keys = _dup_keys(con, h, keys)
    if d.changed:
        d.sample_changed = _sample_changed(con, b, h, spec, common)


def _keys(con, sql: str) -> list[str]:
    rows = con.execute(f"{sql} ORDER BY k LIMIT {SAMPLE_SIZE}").fetchall()
    return [r[0] for r in rows]


def _sample_changed(con, b, h, spec: ModelSpec, common: list[str]) -> list[dict]:
    order = "kc.k"
    metrics = [m for m in spec.metrics if m in common]
    if metrics:

        def num(alias: str, m: str) -> str:
            return f"TRY_CAST({alias}.{q(m)} AS DOUBLE)"

        deltas = ", ".join(
            f"COALESCE(ABS({num('hh', m)} - {num('bb', m)})"
            f" / NULLIF(ABS({num('bb', m)}), 0), 0)"
            for m in metrics
        )
        order = f"GREATEST({deltas}, 0) DESC, kc.k"
    select_cols = ", ".join(
        f"CAST(bb.{q(c)} AS VARCHAR), CAST(hh.{q(c)} AS VARCHAR)" for c in common
    )
    rows = con.execute(
        f"SELECT kc.k, {select_cols} FROM kc "
        f"JOIN {b} AS bb ON {_key_expr(spec.keys, 'bb')} = kc.k "
        f"JOIN {h} AS hh ON {_key_expr(spec.keys, 'hh')} = kc.k "
        f"ORDER BY {order} LIMIT {SAMPLE_SIZE}"
    ).fetchall()
    samples = []
    for row in rows:
        diffs = {}
        for i, c in enumerate(common):
            before, after = row[1 + 2 * i], row[2 + 2 * i]
            if before != after:
                diffs[c] = [before, after]
        samples.append({"key": row[0], "columns": diffs})
    return samples


def diff_model(con, spec: ModelSpec) -> ModelDiff:
    cols_b = columns(con, "b", spec.schema, spec.alias)
    cols_h = columns(con, "h", spec.schema, spec.alias)
    b = f"b.{q(spec.schema)}.{q(spec.alias)}"
    h = f"h.{q(spec.schema)}.{q(spec.alias)}"
    d = ModelDiff(name=spec.name, status="unchanged", keys=spec.keys)
    if not cols_h:
        d.status = "removed" if cols_b else "missing"
        return d
    d.rows_head = _scalar(con, f"SELECT COUNT(*) FROM {h}")
    if not cols_b:
        d.status = "new"
        return d
    d.rows_base = _scalar(con, f"SELECT COUNT(*) FROM {b}")

    d.columns_added = {c: t for c, t in cols_h.items() if c not in cols_b}
    d.columns_removed = {c: t for c, t in cols_b.items() if c not in cols_h}
    d.columns_retyped = {
        c: [cols_b[c], t] for c, t in cols_h.items() if c in cols_b and cols_b[c] != t
    }
    common = [c for c in cols_h if c in cols_b]

    stats_b = _column_stats(con, b, common)
    stats_h = _column_stats(con, h, common)
    d.column_shifts = [
        ColumnShift(c, stats_b[c][0], stats_h[c][0], stats_b[c][1], stats_h[c][1])
        for c in common
        if _shifted(stats_b[c], stats_h[c])
    ]

    metrics = [m for m in spec.metrics if m in common]
    mb, mh = _metric_stats(con, b, metrics), _metric_stats(con, h, metrics)
    d.metrics = [
        MetricShift(m, mb[m][0], mh[m][0], mb[m][1], mh[m][1]) for m in metrics
    ]

    if spec.keys and all(k in common for k in spec.keys):
        _key_diff(con, b, h, spec, common, d)

    changed = (
        d.rows_base != d.rows_head
        or d.added
        or d.removed
        or d.changed
        or (d.dup_keys_head or 0) > (d.dup_keys_base or 0)
        or d.columns_added
        or d.columns_removed
        or d.columns_retyped
        or d.column_shifts
        or not all(same(m.sum_base, m.sum_head) for m in d.metrics)
    )
    d.status = "changed" if changed else "unchanged"
    return d
