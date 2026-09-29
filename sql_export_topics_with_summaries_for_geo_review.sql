-- Eksport wszystkich niepołączonych wątków, dla których istnieje synteza,
-- do ręcznej kontroli geograficznych prefiksów tytułów.
-- Zapytanie jest tylko do odczytu i nie pobiera pełnych treści artykułów.

select
    t.topic_id,
    t.headline_pl,
    t.status,
    t.first_seen_at,
    t.last_seen_at,
    t.article_count,
    t.source_count,
    t.coverage_status,
    coalesce(
        (
            select jsonb_agg(tc.category order by tc.category)
            from public.topic_categories tc
            where tc.topic_id = t.topic_id
        ),
        '[]'::jsonb
    ) as categories,
    coalesce(
        ts.summary #>> '{base_summary,topic,headline_pl}',
        ts.summary #>> '{topic,headline_pl}',
        ''
    ) as synthesis_headline_pl,
    coalesce(
        ts.summary #>> '{base_summary,topic,what_happened_one_sentence_pl}',
        ts.summary #>> '{topic,what_happened_one_sentence_pl}',
        ''
    ) as one_sentence_summary,
    coalesce(
        ts.summary #>> '{base_summary,summary_pl}',
        ts.summary #>> '{summary_pl}',
        ''
    ) as synthesis,
    coalesce(
        (
            select jsonb_agg(
                jsonb_build_object(
                    'article_id', a.article_id,
                    'source_name', a.source_name,
                    'title', a.title,
                    'published_at', a.published_at
                )
                order by a.published_at desc nulls last, a.article_id
            )
            from public.topic_articles ta
            join public.articles a on a.article_id = ta.article_id
            where ta.topic_id = t.topic_id
        ),
        '[]'::jsonb
    ) as articles
from public.topics t
join public.topic_summaries ts on ts.topic_id = t.topic_id
where t.status <> 'MERGED'
order by t.last_seen_at desc, t.topic_id;
