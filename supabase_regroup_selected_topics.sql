-- Usuwa wyłącznie warstwę AI sześciu wskazanych tematów.
-- Artykuły pozostają w public.articles i po usunięciu przypisań wracają do
-- kolejki trybu ai-only, o ile od ich pobrania nie minęło 55 godzin.

begin;

create temporary table gni_topics_to_regroup on commit drop as
select topic_id, headline_pl
from public.topics
where headline_pl = any(array[
    '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
    '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
    '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
    '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
    '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
    '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
]::text[]);

do $$
declare
    found_count integer;
begin
    select count(*) into found_count from gni_topics_to_regroup;
    if found_count <> 6 then
        raise exception 'Znaleziono % z 6 tematów. Niczego nie usunięto.', found_count;
    end if;
end $$;

-- Jeśli wpisy z X były przypięte do usuwanych tematów, wracają do kolejki X.
update public.x_posts xp
set ai_status = 'PENDING'
where exists (
    select 1
    from public.topic_x_posts txp
    join gni_topics_to_regroup g on g.topic_id = txp.topic_id
    where txp.post_id = xp.post_id
);

delete from public.topic_x_posts
where topic_id in (select topic_id from gni_topics_to_regroup);

delete from public.topic_summary_versions
where topic_id in (select topic_id from gni_topics_to_regroup);

delete from public.topic_summaries
where topic_id in (select topic_id from gni_topics_to_regroup);

delete from public.article_topic_assignments
where topic_id in (select topic_id from gni_topics_to_regroup);

delete from public.topic_articles
where topic_id in (select topic_id from gni_topics_to_regroup);

-- Ewentualne tematy wcześniej scalone do jednego z usuwanych tematów nie mogą
-- zachować odwołania do nieistniejącego rekordu.
update public.topics
set merged_into_topic_id = null,
    merged_at = null,
    status = 'ACTIVE',
    updated_at = now()
where merged_into_topic_id in (select topic_id from gni_topics_to_regroup);

delete from public.topics
where topic_id in (select topic_id from gni_topics_to_regroup);

commit;

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
