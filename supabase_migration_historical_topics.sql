-- Udostępnia aplikacji także niepołączone tematy starsze niż 55 godzin.
-- Status MERGED pozostaje ukryty; is_current jest wyliczane dynamicznie.

create or replace view public.app_topics as
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
    (last_seen_at >= now() - interval '55 hours') as is_current
from public.topics
where status <> 'MERGED';

grant select on public.app_topics to anon, authenticated;
