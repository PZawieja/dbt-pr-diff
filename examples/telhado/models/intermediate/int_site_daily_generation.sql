WITH readings AS (
    SELECT *
    FROM {{ ref('stg_generation_readings') }}
    WHERE reading_quality IN ('ok', 'estimated')
)

, sites AS (
    SELECT *
    FROM {{ ref('stg_sites') }}
)

SELECT
    readings.site_id
    , readings.reading_date AS generation_date
    , readings.energy_kwh
    , readings.irradiance_kwh_m2
    , readings.reading_quality
    , sites.installed_kw
    , sites.peak_kw
FROM readings
INNER JOIN sites
    ON readings.site_id = sites.site_id
