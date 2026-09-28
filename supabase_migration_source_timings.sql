alter table public.source_run_results
    add column if not exists discovery_duration_ms integer not null default 0,
    add column if not exists fetch_duration_ms integer not null default 0,
    add column if not exists total_duration_ms integer not null default 0,
    add column if not exists average_article_fetch_ms integer not null default 0;

-- Najwolniejsze źródła z ostatnich 14 dni.
select
    srr.source_id,
    s.name as source_name,
    count(*) as runs,
    round(avg(srr.total_duration_ms) / 1000.0, 1) as avg_total_seconds,
    round(avg(srr.discovery_duration_ms) / 1000.0, 1) as avg_discovery_seconds,
    round(avg(srr.fetch_duration_ms) / 1000.0, 1) as avg_fetch_seconds,
    round(avg(srr.average_article_fetch_ms) / 1000.0, 2) as avg_seconds_per_article,
    max(srr.total_duration_ms) / 1000.0 as slowest_run_seconds
from public.source_run_results srr
join public.sources s on s.source_id = srr.source_id
join public.harvest_runs hr on hr.run_id = srr.run_id
where hr.started_at >= now() - interval '14 days'
group by srr.source_id, s.name
order by avg(srr.total_duration_ms) desc;
