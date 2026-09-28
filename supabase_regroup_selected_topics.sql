-- Usuwa wyłącznie warstwę AI sześciu wskazanych tematów.
-- Artykuły pozostają w public.articles i po usunięciu przypisań wracają do
-- kolejki trybu ai-only, o ile od ich pobrania nie minęło 55 godzin.

do $$
declare
    target_headlines text[] := array[
        '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
        '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
        '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
        '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
        '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
        '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
    ]::text[];
    target_ids text[];
    found_count integer;
begin
    select array_agg(topic_id), count(*)
    into target_ids, found_count
    from public.topics
    where headline_pl = any(target_headlines);

    if found_count <> 6 then
        raise exception 'Znaleziono % z 6 tematów. Niczego nie usunięto.', found_count;
    end if;

    -- Jeśli wpisy z X były przypięte do usuwanych tematów, wracają do kolejki X.
    update public.x_posts xp
    set ai_status = 'PENDING'
    where exists (
        select 1
        from public.topic_x_posts txp
        where txp.topic_id = any(target_ids)
          and txp.post_id = xp.post_id
    );

    delete from public.topic_x_posts where topic_id = any(target_ids);
    delete from public.topic_summary_versions where topic_id = any(target_ids);
    delete from public.topic_summaries where topic_id = any(target_ids);
    delete from public.article_topic_assignments where topic_id = any(target_ids);
    delete from public.topic_articles where topic_id = any(target_ids);

    -- Ewentualne tematy wcześniej scalone do jednego z usuwanych tematów nie
    -- mogą zachować odwołania do nieistniejącego rekordu.
    update public.topics
    set merged_into_topic_id = null,
        merged_at = null,
        status = 'ACTIVE',
        updated_at = now()
    where merged_into_topic_id = any(target_ids);

    delete from public.topics where topic_id = any(target_ids);
end $$;

-- Kontrola: wynik powinien wynosić 0.
select count(*) as selected_topics_still_present
from public.topics
where headline_pl = any(array[
    '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
    '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
    '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
    '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
    '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
    '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
]::text[]);
