-- Tylko odczyt. Wynik wyeksportuj jako CSV lub JSON (nie kopiuj komórek ręcznie).
-- Zawiera wyłącznie dane publicznego interfejsu, bez body artykułów i kluczy.
with visible as materialized (
  select * from public.app_topics where source_count >= 2
), latest as (
  select started_at from public.app_latest_harvest limit 1
)
select jsonb_build_object(
  'schema', 1, 'expected_topics', (select count(*) from visible),
  'exported_at', now(), 'latest_harvest_started_at', (select started_at from latest),
  'topic', to_jsonb(t),
  'links', coalesce((select jsonb_agg(to_jsonb(l)) from public.app_topic_articles l where l.topic_id=t.topic_id), '[]'::jsonb),
  'articles', coalesce((select jsonb_agg(jsonb_build_object(
    'article_id',a.article_id,'source_id',a.source_id,'source_name',a.source_name,
    'source_profile',a.source_profile,'source_type',a.source_type,'title',a.title,
    'original_url',a.original_url,'published_at',a.published_at,'fetched_at',a.fetched_at,'word_count',a.word_count
  )) from public.app_articles a where exists (
    select 1 from public.app_topic_articles l where l.topic_id=t.topic_id and l.article_id=a.article_id
  )), '[]'::jsonb),
  'summary', (select to_jsonb(s) from public.app_topic_summaries s where s.topic_id=t.topic_id),
  'history', case when exists (
    select 1 from public.app_topic_summaries s where s.topic_id=t.topic_id and jsonb_typeof(s.summary->'updates')='array'
  ) then '[]'::jsonb else coalesce((select jsonb_agg(jsonb_build_object(
    'topic_id',v.topic_id,'version',v.version,'generated_at',v.generated_at,
    'summary',jsonb_build_object('updates',v.summary->'updates','latest_update',v.summary->'latest_update','update',v.summary->'update')
  ) order by v.version) from public.app_topic_summary_versions v where v.topic_id=t.topic_id), '[]'::jsonb) end
) as payload
from visible t order by t.topic_id;
