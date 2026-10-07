-- Jednorazowy reset świeżych tematów jednoartykułowych.
--
-- Skrypt NIE usuwa artykułów. Usuwa wyłącznie aktywne tematy, które:
--   1) mają dokładnie jeden rekord w topic_articles;
--   2) były ostatnio aktualizowane w ciągu ostatnich 48 godzin.
--
-- Artykuły pozostają w bazie i przy kolejnym pełnym runie mogą zostać
-- ponownie przypisane od AI 1.
--
-- Nie używamy tabeli tymczasowej, ponieważ Supabase SQL Editor może wykonywać
-- kolejne instrukcje w różnych transakcjach/sesjach. Całe usuwanie odbywa się
-- atomowo w jednym bloku DO.
--
-- Uruchom w Supabase Dashboard -> SQL Editor.

-- 1. Podgląd zakresu. To zapytanie jest tylko do odczytu.
with singleton_topics as (
    select
        t.topic_id,
        min(ta.article_id) as article_id,
        t.headline_pl,
        t.first_seen_at,
        t.last_seen_at
    from public.topics t
    join public.topic_articles ta on ta.topic_id = t.topic_id
    where t.status = 'ACTIVE'
      and t.last_seen_at >= now() - interval '48 hours'
    group by
        t.topic_id,
        t.headline_pl,
        t.first_seen_at,
        t.last_seen_at
    having count(*) = 1
)
select
    st.topic_id,
    st.article_id,
    st.headline_pl,
    st.first_seen_at,
    st.last_seen_at,
    a.title as article_title,
    a.source_name,
    a.original_url
from singleton_topics st
join public.articles a on a.article_id = st.article_id
order by st.last_seen_at desc, st.topic_id;

-- 2. Usunięcie. DO jest jedną atomową operacją; przy błędzie PostgreSQL
-- wycofa wszystkie poniższe zmiany.
do $$
declare
    target_topic_ids text[];
    target_count integer;
    changed_count integer;
begin
    select
        coalesce(array_agg(topic_id), '{}'::text[]),
        count(*)::integer
    into target_topic_ids, target_count
    from (
        select t.topic_id
        from public.topics t
        join public.topic_articles ta on ta.topic_id = t.topic_id
        where t.status = 'ACTIVE'
          and t.last_seen_at >= now() - interval '48 hours'
        group by t.topic_id
        having count(*) = 1
    ) candidates;

    raise notice 'Singleton topics selected for reset: %', target_count;

    if target_count = 0 then
        return;
    end if;

    -- Usuń ewentualne referencje historycznych tematów MERGED.
    update public.topics t
    set merged_into_topic_id = null,
        merged_at = null,
        updated_at = now()
    where t.merged_into_topic_id = any(target_topic_ids);

    -- Najpierw rekordy zależne od topics, potem same tematy.
    delete from public.topic_summary_versions tsv
    where tsv.topic_id = any(target_topic_ids);

    delete from public.topic_summaries ts
    where ts.topic_id = any(target_topic_ids);

    delete from public.article_topic_assignments ata
    where ata.topic_id = any(target_topic_ids);

    delete from public.topic_articles ta
    where ta.topic_id = any(target_topic_ids);

    delete from public.topics t
    where t.topic_id = any(target_topic_ids);

    get diagnostics changed_count = row_count;
    raise notice 'Singleton topics deleted: %', changed_count;
end $$;

-- 3. Kontrola po operacji. Powinno zwrócić 0.
with singleton_topics as (
    select t.topic_id
    from public.topics t
    join public.topic_articles ta on ta.topic_id = t.topic_id
    where t.status = 'ACTIVE'
      and t.last_seen_at >= now() - interval '48 hours'
    group by t.topic_id
    having count(*) = 1
)
select count(*) as remaining_recent_singletons
from singleton_topics;
