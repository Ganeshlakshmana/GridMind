select
    system_id,
    cast(timestamp as timestamp) as reading_at,
    cast(solar_output_kw as double) as solar_output_kw,
    cast(expected_output_kw as double) as expected_output_kw,
    cast(battery_soc_pct as double) as battery_soc_pct,
    cast(grid_feed_in_kw as double) as grid_feed_in_kw,
    status
from {{ source('raw_data', 'telemetry') }}
