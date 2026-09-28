-- Dodaje bezpieczne przekierowanie dla tematów scalonych przez AI.
-- Uruchom jednorazowo w Supabase SQL Editor przed pierwszym uruchomieniem
-- workflow z nowym etapem scalania.

alter table public.topics
    add column if not exists merged_into_topic_id text references public.topics(topic_id);

alter table public.topics
    add column if not exists merged_at timestamptz;

create index if not exists topics_merged_into_idx
    on public.topics(merged_into_topic_id);

create or replace view public.source_topic_coverage as
select
    a.source_id,
    max(a.source_name) as source_name,
    count(distinct t.topic_id) as total_topic_count,
    count(distinct t.topic_id) filter (where t.coverage_status = 'SINGLE_ARTICLE')
        as single_article_topic_count,
    count(distinct t.topic_id) filter (where t.coverage_status = 'SINGLE_SOURCE')
        as single_source_topic_count,
    count(distinct t.topic_id) filter (where t.coverage_status = 'MULTI_SOURCE')
        as multi_source_topic_count,
    count(distinct t.topic_id) filter (where ts.topic_id is not null)
        as summarized_topic_count
from public.topic_articles ta
join public.topics t on t.topic_id = ta.topic_id
join public.articles a on a.article_id = ta.article_id
left join public.topic_summaries ts on ts.topic_id = t.topic_id
where t.status = 'ACTIVE'
group by a.source_id;

-- Widok aplikacji pokazuje wyłącznie status ACTIVE, więc wątki z MERGED
-- znikają z listy bez usuwania ich historii.
