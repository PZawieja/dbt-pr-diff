SELECT
    inverter_id
    , site_id
    , inverter_model
    , CAST(rated_kw AS DECIMAL(8, 2)) AS rated_kw
FROM {{ ref('raw_inverters') }}
