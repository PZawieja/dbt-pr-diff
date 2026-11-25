WITH daily AS (
    SELECT *
    FROM {{ ref('fct_daily_generation') }}
)

SELECT
    site_id || '|' || STRFTIME(DATE_TRUNC('month', generation_date), '%Y-%m')
        AS site_month_id
    , site_id
    , DATE_TRUNC('month', generation_date) AS generation_month
    , COUNT(*) AS days_reported
    , ROUND(SUM(energy_kwh), 2) AS energy_kwh
    , ROUND(AVG(capacity_factor), 4) AS avg_capacity_factor
FROM daily
GROUP BY site_id, DATE_TRUNC('month', generation_date)
