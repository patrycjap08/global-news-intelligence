-- Jednorazowa korekta trzech tematów widocznych na zrzucie ekranu.
-- Uruchom w Supabase Dashboard -> SQL Editor.
-- Skrypt zmienia wyłącznie topics.headline_pl.

begin;

with summary_rows as (
    select
        ts.topic_id,
        coalesce(
            nullif(
                ts.summary #>> '{base_summary,topic,what_happened_one_sentence_pl}',
                ''
            ),
            nullif(
                ts.summary #>> '{topic,what_happened_one_sentence_pl}',
                ''
            ),
            ''
        ) as description
    from public.topic_summaries ts
), replacements as (
    select
        topic_id,
        case
            when description ilike
                'Podczas szczytu w Waszyngtonie Prezydent USA Donald Trump%'
                then '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI'
            when description ilike
                'W Kujawsko-Pomorskiem 13-latek planował zamach w szkole%'
                then '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu'
            when description ilike
                'W dniu 28 września 2026 r. Chiny odnotowały szereg istotnych wydarzeń:%'
                then '[Chiny] Głębinowe odwierty, egzoszkielety i przekazanie pand do Zoo Atlanta'
        end as headline_pl
    from summary_rows
    where description ilike
        'Podczas szczytu w Waszyngtonie Prezydent USA Donald Trump%'
       or description ilike
        'W Kujawsko-Pomorskiem 13-latek planował zamach w szkole%'
       or description ilike
        'W dniu 28 września 2026 r. Chiny odnotowały szereg istotnych wydarzeń:%'
)
update public.topics t
set headline_pl = replacements.headline_pl,
    updated_at = now()
from replacements
where t.topic_id = replacements.topic_id
  and t.status <> 'MERGED'
  and t.headline_pl ilike '%neutralna nazwa wydarzenia%'
  and replacements.headline_pl is not null
returning t.topic_id, t.headline_pl;

commit;
