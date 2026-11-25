WITH daily AS (
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
