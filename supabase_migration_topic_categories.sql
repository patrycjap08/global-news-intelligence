-- Kategorie redakcyjne tematów w relacji wiele–wiele.
-- Temat może mieć od jednej do trzech kategorii z zamkniętej listy.

create table if not exists public.topic_categories (
    topic_id text not null references public.topics(topic_id) on delete cascade,
    category text not null check (category in (
        'POLITYKA', 'SWIAT', 'GOSPODARKA', 'SPOLECZENSTWO',
        'TECHNOLOGIA', 'ZDROWIE', 'KULTURA_SPORT'
    )),
    primary key (topic_id, category)
);

create index if not exists topic_categories_category_idx
    on public.topic_categories(category, topic_id);

alter table public.topic_categories enable row level security;

drop policy if exists "authenticated users can read topic categories" on public.topic_categories;
create policy "authenticated users can read topic categories"
    on public.topic_categories for select to authenticated using (true);

-- Podgląd tematów oczekujących na ręczne przypisanie:
-- select t.topic_id, t.headline_pl, ts.summary
-- from public.topics t
-- left join public.topic_summaries ts on ts.topic_id = t.topic_id
-- where t.status <> 'MERGED'
-- order by t.last_seen_at desc;
