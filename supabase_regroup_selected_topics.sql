-- Usuwa wyłącznie warstwę AI sześciu wskazanych tematów.
-- Artykuły pozostają w public.articles i po usunięciu przypisań wracają do
-- kolejki trybu ai-only, o ile od ich pobrania nie minęło 55 godzin.

begin;

-- Jeżeli nie znaleziono dokładnie sześciu tematów, dzielenie przez zero
-- zatrzyma transakcję przed jakimkolwiek usuwaniem.
select 1 / case when count(*) = 6 then 1 else 0 end as all_six_topics_found
from public.topics
where headline_pl = any(array[
    '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
    '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
    '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
    '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
    '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
    '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
]::text[]);

-- Jeśli wpisy z X były przypięte do usuwanych tematów, wracają do kolejki X.
update public.x_posts xp
set ai_status = 'PENDING'
where exists (
    select 1
    from public.topic_x_posts txp
    join public.topics t on t.topic_id = txp.topic_id
    where txp.post_id = xp.post_id
      and t.headline_pl = any(array[
          '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
          '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
          '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
          '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
          '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
          '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
      ]::text[])
);

delete from public.topic_x_posts txp
using public.topics t
where txp.topic_id = t.topic_id
  and t.headline_pl = any(array[
      '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
      '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
      '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
      '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
      '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
      '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
  ]::text[]);

delete from public.topic_summary_versions v using public.topics t
where v.topic_id = t.topic_id and t.headline_pl = any(array[
    '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
    '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
    '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
    '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
    '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
    '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
]::text[]);

delete from public.topic_summaries s using public.topics t
where s.topic_id = t.topic_id and t.headline_pl = any(array[
    '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
    '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
    '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
    '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
    '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
    '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
]::text[]);

delete from public.article_topic_assignments a using public.topics t
where a.topic_id = t.topic_id and t.headline_pl = any(array[
    '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
    '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
    '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
    '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
    '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
    '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
]::text[]);

delete from public.topic_articles a using public.topics t
where a.topic_id = t.topic_id and t.headline_pl = any(array[
    '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
    '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
    '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
    '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
    '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
    '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
]::text[]);

update public.topics child
set merged_into_topic_id = null, merged_at = null, status = 'ACTIVE', updated_at = now()
from public.topics target
where child.merged_into_topic_id = target.topic_id
  and target.headline_pl = any(array[
      '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
      '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
      '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
      '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
      '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
      '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
  ]::text[]);

delete from public.topics
where headline_pl = any(array[
    '[Polska] Kraków 2026: I tura i druga tura wyborów na prezydenta miasta',
    '[Świat] Codzienne ataki Rosji na Ukrainę i bilans września 2026',
    '[USA i Chiny] Trump i Xi przedłużyli rozejm handlowy i zapowiedzieli dialog o AI',
    '[Świat] AI: apokalipsa to złudzenie, mówi Le Monde',
    '[Polska] 13-latek planował atak w szkole; policja zatrzymała go w domu',
    '[Świat] Międzynarodowe i gospodarcze aktualności 27-28 września 2026'
]::text[]);

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
