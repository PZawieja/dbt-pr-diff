SELECT
    reading_id
    , site_id
    , reading_date
    , CAST(energy_kwh AS DOUBLE) AS energy_kwh
    , CAST(irradiance_kwh_m2 AS DOUBLE) AS irradiance_kwh_m2
    , reading_quality
FROM {{ ref('raw_generation_readings') }}
