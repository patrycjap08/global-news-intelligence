-- Rozdziela okno widoczności w aplikacji od okna dopasowywania tematów.
--
-- Backend nadal może przypisać nowy artykuł do nieaktualizowanego tematu przez
-- 48 godzin. Widok aplikacji oznacza go jako aktualny tylko przez 24 godzin.
-- Po przypisaniu nowego artykułu last_seen_at zostaje odświeżone, więc temat
-- wraca do zakładki „Aktualne”.

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
    coalesce(
        (
            select array_agg(tc.category order by tc.category)
            from public.topic_categories tc
            where tc.topic_id = public.topics.topic_id
        ),
        '{}'::text[]
    ) as categories,
    (last_seen_at >= now() - interval '24 hours') as is_current
from public.topics
where status <> 'MERGED';

grant select on public.app_topics to anon, authenticated;
