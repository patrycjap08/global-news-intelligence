-- Uruchom jednorazowo w Supabase SQL Editor.
-- Oznacza, czy temat pojawił się w jednym artykule, jednym źródle czy wielu źródłach.

alter table public.topics
    add column if not exists coverage_status text not null default 'SINGLE_ARTICLE';

with coverage as (
    select
        ta.topic_id,
        count(distinct ta.article_id)::integer as article_count,
        count(distinct a.source_id)::integer as source_count
    from public.topic_articles ta
    join public.articles a on a.article_id = ta.article_id
    group by ta.topic_id
)
update public.topics t
set article_count = coverage.article_count,
    source_count = coverage.source_count,
    coverage_status = case
        when coverage.article_count = 1 then 'SINGLE_ARTICLE'
        when coverage.source_count = 1 then 'SINGLE_SOURCE'
        else 'MULTI_SOURCE'
    end,
    updated_at = now()
from coverage
where t.topic_id = coverage.topic_id;

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
group by a.source_id;

-- Przykład kontroli źródeł, które mają dużo tematów wyłącznie u siebie:
-- select * from public.source_topic_coverage
-- order by (single_article_topic_count + single_source_topic_count) desc;
