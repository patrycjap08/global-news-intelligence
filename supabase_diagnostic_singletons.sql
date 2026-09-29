-- Tylko odczyt. Nie zmienia żadnych danych.
-- Ten plik służy do audytu singletonów pozostałych po AI-REPAIR.

-- ZAPYTANIE 1: pełna lista widocznych singletonów.
-- Wynik można wyeksportować z Supabase SQL Editor do CSV.
with singleton_links as (
    select
        ta.topic_id,
        min(ta.article_id) as article_id,
        count(*) as linked_article_count
    from public.topic_articles ta
    group by ta.topic_id
    having count(*) = 1
), assignment_evidence as (
    select
        ata.topic_id,
        ata.article_id,
        array_agg(distinct nullif(trim(ata.grouping_reason), ''))
            filter (where nullif(trim(ata.grouping_reason), '') is not null)
            as grouping_reasons,
        max(ata.confidence) as max_assignment_confidence,
        bool_or(ata.needs_review) as any_needs_review
    from public.article_topic_assignments ata
    group by ata.topic_id, ata.article_id
), summary_evidence as (
    select
        ts.topic_id,
        coalesce(
            nullif(ts.summary #>> '{base_summary,topic,what_happened_one_sentence_pl}', ''),
            nullif(ts.summary #>> '{topic,what_happened_one_sentence_pl}', ''),
            ''
        ) as one_sentence,
        coalesce(
            nullif(ts.summary #>> '{base_summary,summary_pl}', ''),
            nullif(ts.summary #>> '{summary_pl}', ''),
            ''
        ) as summary_pl
    from public.topic_summaries ts
)
select
    t.topic_id,
    t.status,
    t.headline_pl,
    t.first_seen_at,
    t.last_seen_at,
    t.article_count as topic_article_count,
    t.source_count as topic_source_count,
    t.coverage_status,
    t.needs_review,
    sl.article_id,
    a.title as article_title,
    a.description as article_description,
    a.source_name,
    a.published_at,
    a.original_url,
    ae.grouping_reasons,
    ae.max_assignment_confidence,
    ae.any_needs_review as assignment_needs_review,
    se.one_sentence as summary_one_sentence,
    se.summary_pl,
    case
        when exists (
            select 1
            from unnest(coalesce(ae.grouping_reasons, '{}'::text[])) as reason
            where reason ilike 'Artykuł zachowany osobno:%'
        ) then 'FALLBACK_SINGLETON'
        else 'OTHER_SINGLETON'
    end as singleton_origin
from public.topics t
join singleton_links sl on sl.topic_id = t.topic_id
join public.articles a on a.article_id = sl.article_id
left join assignment_evidence ae
    on ae.topic_id = sl.topic_id
   and ae.article_id = sl.article_id
left join summary_evidence se on se.topic_id = t.topic_id
where t.status <> 'MERGED'
order by t.last_seen_at desc, t.topic_id;


-- ZAPYTANIE 2: pary singletonów, które mają co najmniej dwa wspólne
-- niebanalne słowa w tytule tematu lub artykułu.
-- To jest heurystyka do ręcznej/AI weryfikacji, nie automatyczne scalanie.
with singleton_topics as (
    select
        t.topic_id,
        t.headline_pl,
        t.last_seen_at,
        ta.article_id,
        a.title as article_title,
        a.source_name,
        coalesce(
            nullif(ts.summary #>> '{base_summary,topic,what_happened_one_sentence_pl}', ''),
            nullif(ts.summary #>> '{topic,what_happened_one_sentence_pl}', ''),
            ''
        ) as summary_one_sentence
    from public.topics t
    join (
        select topic_id, min(article_id) as article_id
        from public.topic_articles
        group by topic_id
        having count(*) = 1
    ) ta on ta.topic_id = t.topic_id
    join public.articles a on a.article_id = ta.article_id
    left join public.topic_summaries ts on ts.topic_id = t.topic_id
    where t.status <> 'MERGED'
), topic_tokens as (
    select distinct
        st.topic_id,
        token
    from singleton_topics st
    cross join lateral regexp_split_to_table(
        lower(
            regexp_replace(
                coalesce(st.headline_pl, '') || ' ' || coalesce(st.article_title, ''),
                '[^[:alnum:]]+',
                ' ',
                'g'
            )
        ),
        '\s+'
    ) as token
    where length(token) >= 4
      and token not in (
          'artykuł', 'artykuły', 'artykułów', 'temat', 'tematy',
          'sprawa', 'sprawy', 'wydarzenie', 'wydarzenia',
          'świat', 'polska', 'polskie', 'polski', 'światowy',
          'pierwszy', 'pierwsza', 'pierwsze', 'nowy', 'nowa', 'nowe',
          'ważny', 'ważne', 'aktualizacja', 'aktualizacje',
          'informacje', 'wiadomości', 'sytuacja', 'komentarze',
          'historyczny', 'historyczne', 'kontekst', 'wyniki',
          'during', 'first', 'latest', 'news', 'update', 'world'
      )
), pair_tokens as (
    select
        left_tokens.topic_id as left_topic_id,
        right_tokens.topic_id as right_topic_id,
        left_tokens.token
    from topic_tokens left_tokens
    join topic_tokens right_tokens
      on right_tokens.token = left_tokens.token
     and right_tokens.topic_id > left_tokens.topic_id
), pair_scores as (
    select
        left_topic_id,
        right_topic_id,
        count(distinct token) as shared_token_count,
        array_agg(distinct token order by token) as shared_tokens
    from pair_tokens
    group by left_topic_id, right_topic_id
    having count(distinct token) >= 2
)
select
    ps.shared_token_count,
    ps.shared_tokens,
    left_topic.topic_id as left_topic_id,
    left_topic.headline_pl as left_headline,
    left_topic.article_title as left_article_title,
    left_topic.source_name as left_source,
    left_topic.summary_one_sentence as left_summary,
    right_topic.topic_id as right_topic_id,
    right_topic.headline_pl as right_headline,
    right_topic.article_title as right_article_title,
    right_topic.source_name as right_source,
    right_topic.summary_one_sentence as right_summary,
    case
        when ps.shared_token_count >= 3 then 'WYSOKI_KANDYDAT_DO_WERYFIKACJI'
        else 'KANDYDAT_DO_WERYFIKACJI'
    end as heuristic_label
from pair_scores ps
join singleton_topics left_topic on left_topic.topic_id = ps.left_topic_id
join singleton_topics right_topic on right_topic.topic_id = ps.right_topic_id
order by ps.shared_token_count desc, left_topic.last_seen_at desc;
