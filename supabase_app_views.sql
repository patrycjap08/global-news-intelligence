-- Bezpieczny, tylko-do-odczytu interfejs aplikacji.
--
-- Aplikacja mobilna korzysta wyłącznie z klucza publishable/anon. Nie wolno
-- umieszczać w niej SUPABASE_SECRET_KEY. Widok app_articles celowo nie
-- udostępnia pełnego body artykułu — aplikacja pokazuje opracowanie AI i link
-- do oryginalnego materiału.

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

create or replace view public.app_topic_articles as
select
    topic_id,
    article_id,
    confidence,
    assigned_at
from public.topic_articles;

create or replace view public.app_topic_summaries as
select
    topic_id,
    version,
    summary,
    generated_at,
    updated_at
from public.topic_summaries;

create or replace view public.app_topic_summary_versions as
select
    topic_id,
    version,
    summary,
    new_article_ids,
    generated_at
from public.topic_summary_versions;

create or replace view public.app_articles as
select
    article_id,
    source_id,
    source_name,
    source_profile,
    source_type,
    original_language,
    title,
    description,
    author,
    original_url,
    canonical_url,
    published_at,
    updated_at,
    section,
    item_kind,
    content_status,
    word_count,
    sentiment,
    tone_hint,
    fetched_at
from public.articles;

-- Widoki zawierają wyłącznie dane przeznaczone do prezentacji w aplikacji.
grant select on public.app_topics to anon, authenticated;
grant select on public.app_topic_articles to anon, authenticated;
grant select on public.app_topic_summaries to anon, authenticated;
grant select on public.app_topic_summary_versions to anon, authenticated;
grant select on public.app_articles to anon, authenticated;
