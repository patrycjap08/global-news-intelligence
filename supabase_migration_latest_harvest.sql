-- Udostępnia aplikacji godzinę rozpoczęcia ostatniego pobierania danych.
-- Widok nie ujawnia ustawień ani kluczy używanych przez harvester.

create or replace view public.app_latest_harvest as
select
    run_id,
    started_at,
    finished_at,
    status
from public.harvest_runs
order by started_at desc
limit 1;

grant select on public.app_latest_harvest to anon, authenticated;
