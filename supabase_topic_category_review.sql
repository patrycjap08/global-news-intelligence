-- Lista tematów i syntez do ręcznego przypisania kategorii.
-- Wynik można wyeksportować z panelu Supabase do CSV.

select
    t.topic_id,
    t.headline_pl,
    t.last_seen_at,
    coalesce(
        ts.summary -> 'base_summary' ->> 'summary_pl',
        ts.summary ->> 'summary_pl',
        ''
    ) as summary_pl,
    coalesce(
        ts.summary -> 'base_summary' -> 'topic' -> 'categories',
        ts.summary -> 'topic' -> 'categories',
        '[]'::jsonb
    ) as ai_categories,
    coalesce(
        (
            select jsonb_agg(tc.category order by tc.category)
            from public.topic_categories tc
            where tc.topic_id = t.topic_id
        ),
        '[]'::jsonb
    ) as assigned_categories,
    coalesce(
        (
            select jsonb_agg(
                jsonb_build_object(
                    'source_name', a.source_name,
                    'title', a.title
                ) order by a.published_at desc nulls last
            )
            from public.topic_articles ta
            join public.articles a on a.article_id = ta.article_id
            where ta.topic_id = t.topic_id
        ),
        '[]'::jsonb
    ) as articles
from public.topics t
left join public.topic_summaries ts on ts.topic_id = t.topic_id
where t.status <> 'MERGED'
order by t.last_seen_at desc;

-- Przykład ręcznego przypisania jednego tematu do kilku kategorii:
-- insert into public.topic_categories (topic_id, category)
-- values
--     ('topic_id tutaj', 'POLITYKA'),
--     ('topic_id tutaj', 'ZDROWIE')
-- on conflict (topic_id, category) do nothing;
