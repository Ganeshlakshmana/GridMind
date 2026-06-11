select
    system_id,
    cast(reading_at as date) as health_date,
    count(case when status = 'healthy' then 1 end) * 100.0 / count(*) as health_score_pct,
    avg(solar_output_kw) as avg_solar_output_kw,
    avg(expected_output_kw) as avg_expected_output_kw
from {{ ref('stg_telemetry') }}
group by system_id, cast(reading_at as date)
