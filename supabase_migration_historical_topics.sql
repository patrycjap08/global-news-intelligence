-- Udostępnia aplikacji także niepołączone tematy starsze niż 30 godzin.
-- Status MERGED pozostaje ukryty; is_current jest wyliczane dynamicznie.

drop view if exists public.app_topics;

create view public.app_topics as
select
    topic_id,
    headline_pl,
    status,
    first_seen_at,
    last_seen_at,
    article_count,
    source_count,
    coverage_status,
    needs_review,
    merged_into_topic_id,
    merged_at,
    updated_at,
    (last_seen_at >= now() - interval '30 hours') as is_current
from public.topics
where status <> 'MERGED';

grant select on public.app_topics to anon, authenticated;
