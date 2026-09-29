-- Dodaje POLSKA do zamkniętej listy kategorii tematów.
-- Uruchom jednorazowo w Supabase SQL Editor przed użyciem nowych kategorii.

alter table public.topic_categories
    drop constraint if exists topic_categories_category_check;

alter table public.topic_categories
    add constraint topic_categories_category_check check (category in (
        'POLSKA', 'POLITYKA', 'SWIAT', 'GOSPODARKA', 'SPOLECZENSTWO',
        'TECHNOLOGIA', 'ZDROWIE', 'KULTURA_SPORT'
    ));
