WITH sites AS (
    SELECT *
    FROM {{ ref('stg_sites') }}
)

, inverter_counts AS (
    SELECT
        site_id
        , COUNT(*) AS inverter_count
    FROM {{ ref('stg_inverters') }}
    GROUP BY site_id
)

SELECT
    sites.site_id
    , sites.site_name
    , sites.region
    , sites.installed_kw
    , sites.peak_kw
    , sites.commissioned_on
    , COALESCE(inverter_counts.inverter_count, 0) AS inverter_count
FROM sites
LEFT JOIN inverter_counts
    ON sites.site_id = inverter_counts.site_id
