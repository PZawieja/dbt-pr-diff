WITH trusted_daily_readings AS (
    SELECT
        site_id
        , generation_date
        , energy_kwh
        , irradiance_kwh_m2
        , peak_kw
    FROM {{ ref('int_site_daily_generation') }}
)

SELECT
    site_id || '|' || STRFTIME(generation_date, '%Y-%m-%d') AS daily_generation_id
    , site_id
    , generation_date
    , energy_kwh
    , irradiance_kwh_m2
    , ROUND(energy_kwh / (peak_kw * 24), 4) AS capacity_factor
FROM trusted_daily_readings
