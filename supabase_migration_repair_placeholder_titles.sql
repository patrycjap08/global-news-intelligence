-- Jednorazowa naprawa tematów zapisanych z placeholderem zamiast tytułu.
-- Uruchom w Supabase Dashboard -> SQL Editor.
-- Migracja nie zmienia przypisań artykułów ani treści syntez.

begin;

with candidates as (
    select
        t.topic_id,
        coalesce(
            substring(t.headline_pl from '^\[[^]]+\]'),
            '[Świat]'
        ) as prefix,
        nullif(
            btrim(
                regexp_replace(
                    coalesce(
                        nullif(
                            btrim(
                                coalesce(
                                    ts.summary #>> '{base_summary,topic,what_happened_one_sentence_pl}',
                                    ts.summary #>> '{topic,what_happened_one_sentence_pl}',
                                    ''
                                )
                            ),
                            ''
                        ),
                        (
                            select a.title
                            from public.topic_articles ta
                            join public.articles a on a.article_id = ta.article_id
                            where ta.topic_id = t.topic_id
                              and nullif(btrim(a.title), '') is not null
                            order by a.published_at desc nulls last, ta.assigned_at desc
                            limit 1
                        ),
                        ''
                    ),
                    '\s+',
                    ' ',
                    'g'
                )
            ),
            ''
        ) as candidate_title
    from public.topics t
    left join public.topic_summaries ts on ts.topic_id = t.topic_id
    where t.status <> 'MERGED'
      and lower(
          btrim(
              regexp_replace(
                  regexp_replace(t.headline_pl, '^\[[^]]+\]\s*', ''),
                  '\s+',
                  ' ',
                  'g'
              )
          )
      ) in (
          'neutralna nazwa wydarzenia',
          'neutralny wspólny tytuł',
          'temat bez tytułu',
          'połączony temat',
          'konkretny tytuł',
          'konkretny tytuł wydarzenia'
      )
), prepared as (
    select
        topic_id,
        left(
            prefix || ' ' || regexp_replace(candidate_title, '^\[[^]]+\]\s*', ''),
            300
        ) as headline_pl
    from candidates
    where lower(candidate_title) not in (
        'neutralna nazwa wydarzenia',
        'neutralny wspólny tytuł',
        'temat bez tytułu',
        'połączony temat',
        'konkretny tytuł',
        'konkretny tytuł wydarzenia'
    )
      and nullif(btrim(candidate_title), '') is not null
)
update public.topics t
set headline_pl = prepared.headline_pl,
    updated_at = now()
from prepared
where t.topic_id = prepared.topic_id
returning t.topic_id, t.headline_pl;

do $$
declare
    remaining integer;
begin
    select count(*)
    into remaining
    from public.topics t
    where t.status <> 'MERGED'
      and lower(
          btrim(
              regexp_replace(
                  regexp_replace(t.headline_pl, '^\[[^]]+\]\s*', ''),
                  '\s+',
                  ' ',
                  'g'
              )
          )
      ) in (
          'neutralna nazwa wydarzenia',
          'neutralny wspólny tytuł',
          'temat bez tytułu',
          'połączony temat',
          'konkretny tytuł',
          'konkretny tytuł wydarzenia'
      );

    if remaining > 0 then
        raise exception
            'Nie naprawiono % tematów: brak syntezy i tytułu artykułu do użycia jako źródło.',
            remaining;
    end if;
end $$;

commit;
