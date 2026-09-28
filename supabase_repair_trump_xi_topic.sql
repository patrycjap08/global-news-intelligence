-- Jednorazowa naprawa błędnie zgrupowanego wątku Trump–Xi.
-- Zachowuje w nim wyłącznie właściwy artykuł Parkietu. Pozostałych artykułów
-- nie usuwa z bazy: usuwa tylko błędne przypisania, dzięki czemu tryb ai-only
-- przetworzy je ponownie według nowych, bardziej rygorystycznych zasad.

do $$
declare
    target_topic_id text;
begin
    select topic_id
    into target_topic_id
    from public.topics
    where headline_pl ilike '%Trump i Xi%rozejm handlowy%'
    order by last_seen_at desc
    limit 1;

    if target_topic_id is null then
        raise exception 'Nie znaleziono wskazanego wątku Trump–Xi.';
    end if;

    delete from public.article_topic_assignments ata
    where ata.topic_id = target_topic_id
      and ata.article_id in (
          select ta.article_id
          from public.topic_articles ta
          join public.articles a on a.article_id = ta.article_id
          where ta.topic_id = target_topic_id
            and a.title <> 'Xi i Trump grają o czas. Rozejm supermocarstw został utrzymany'
      );

    delete from public.topic_articles ta
    where ta.topic_id = target_topic_id
      and ta.article_id in (
          select a.article_id
          from public.articles a
          where a.title <> 'Xi i Trump grają o czas. Rozejm supermocarstw został utrzymany'
      );

    update public.topics t
    set article_count = stats.article_count,
        source_count = stats.source_count,
        coverage_status = case
            when stats.article_count <= 1 then 'SINGLE_ARTICLE'
            when stats.source_count <= 1 then 'SINGLE_SOURCE'
            else 'MULTI_SOURCE'
        end,
        needs_review = true,
        updated_at = now()
    from (
        select
            count(*)::integer as article_count,
            count(distinct a.source_id)::integer as source_count
        from public.topic_articles ta
        join public.articles a on a.article_id = ta.article_id
        where ta.topic_id = target_topic_id
    ) stats
    where t.topic_id = target_topic_id;
end $$;

select
    t.topic_id,
    t.headline_pl,
    t.article_count,
    t.source_count,
    t.coverage_status,
    a.source_name,
    a.title
from public.topics t
left join public.topic_articles ta on ta.topic_id = t.topic_id
left join public.articles a on a.article_id = ta.article_id
where t.headline_pl ilike '%Trump i Xi%rozejm handlowy%';
