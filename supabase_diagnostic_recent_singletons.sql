-- Tylko odczyt. Ten plik nie zmienia żadnych danych.
-- Pokazuje stan przed ponownym uruchomieniem resetu singletonów.

with singleton_topics as (
    select
        t.topic_id,
        min(ta.article_id) as article_id,
        count(*) as linked_article_count,
        t.status,
        t.headline_pl,
        t.first_seen_at,
        t.last_seen_at,
        t.article_count,
        t.coverage_status
    from public.topics t
    join public.topic_articles ta on ta.topic_id = t.topic_id
    group by
        t.topic_id,
        t.status,
        t.headline_pl,
        t.first_seen_at,
        t.last_seen_at,
        t.article_count,
        t.coverage_status
    having count(*) = 1
)
select
    st.topic_id,
    st.article_id,
    st.status,
    st.headline_pl,
    st.first_seen_at,
    st.last_seen_at,
    st.article_count as stored_article_count,
    st.coverage_status,
    a.title as article_title,
    a.source_name,
    a.published_at,
    a.original_url,
    (st.last_seen_at >= now() - interval '55 hours') as within_reset_window,
    (
        select count(*)
        from public.article_topic_assignments ata
        where ata.topic_id = st.topic_id
    ) as assignment_rows,
    exists (
        select 1
        from public.topic_summaries ts
        where ts.topic_id = st.topic_id
    ) as has_summary,
    exists (
        select 1
        from public.topic_summary_versions tsv
        where tsv.topic_id = st.topic_id
    ) as has_summary_versions
from singleton_topics st
join public.articles a on a.article_id = st.article_id
order by st.last_seen_at desc, st.topic_id;

-- Zbiorcze podsumowanie singletonów, które obejmie migracja.
with singleton_topics as (
    select t.topic_id, t.last_seen_at
    from public.topics t
    join public.topic_articles ta on ta.topic_id = t.topic_id
    where t.status = 'ACTIVE'
    group by t.topic_id, t.last_seen_at
    having count(*) = 1
)
select
    count(*) as recent_active_singleton_count,
    min(last_seen_at) as oldest_selected_last_seen_at,
    max(last_seen_at) as newest_selected_last_seen_at
from singleton_topics
where last_seen_at >= now() - interval '55 hours';
