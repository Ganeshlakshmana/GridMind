select
    system_id,
    count(case when status != 'healthy' and status is not null then 1 end) as anomaly_count,
    count(case when status = 'healthy' then 1 end) as healthy_count,
    count(*) as total_readings
from {{ ref('stg_telemetry') }}
group by system_id
