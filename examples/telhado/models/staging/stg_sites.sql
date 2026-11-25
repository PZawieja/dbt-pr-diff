SELECT
    site_id
    , site_name
    , region
    , CAST(installed_kw AS DECIMAL(8, 2)) AS installed_kw
    , CAST(peak_kw AS DECIMAL(8, 2)) AS peak_kw
    , CAST(commissioned_on AS DATE) AS commissioned_on
FROM {{ ref('raw_sites') }}
