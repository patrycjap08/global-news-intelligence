-- Tylko odczyt: 8 konkretnych wątków ze zrzutów = 28 niepowtarzających się par.
-- Wyniki historyczne, nie nowe wywołanie embeddingów. Nie zmienia progów ani danych.
-- Diagnostyka zapisuje próbki. NULL oznacza brak zapisanej próbki, nie wynik 0.
-- Każda para dostaje najnowszy DOSTĘPNY wynik; daty/teksty mogą się między parami różnić.
with settings as (
    -- Zostaw NULL, aby przeszukać wszystkie przebiegi, albo wpisz konkretny run_id.
    select null::text as run_id, 0.78::numeric as obecny_prog
), wanted(topic_id, tytul_ze_zrzutu) as (
    values
    ('topic_perspectives_d47c451ef7a0c2a4a8327596', '[Francja] Minister rezygnuje, Macron odmawia jej przyjęcia'),
    ('topic_perspectives_e76e6853f89111c7a22d8d61', '[Francja] Częściowa godzina policyjna w reakcji na zamieszki'),
    ('topic_perspectives_449f14cebf8083ee911b91dc', '[Francja] Zniszczenia podczas protestów'),
    ('topic_perspectives_f63c6bcbe03aa9b33e8b63d9', '[Francja] Macron o protestach - apel do społeczeństwa'),
    ('topic_perspectives_802d78b36ab2940d59552746', '[Francja] Aresztowania podczas protestów'),
    ('topic_perspectives_bfe87060175e86a633d35bee', '[Francja] Szkody po protestach społecznych'),
    ('topic_perspectives_5897d4f7a483837ce7c52e4f', '[Francja] Protesty przeciwko kosztom życia w Paryżu'),
    ('topic_perspectives_0bb17b14683705e57fd24b02', '[Francja] Protesty w Luwrze wspierające licealistów')
), targets as (
    select w.topic_id, coalesce(t.headline_pl, w.tytul_ze_zrzutu) as title,
           coalesce(t.status, 'BRAK W BAZIE') as status,
           t.merged_into_topic_id
    from wanted w
    left join public.topics t using (topic_id)
), pairs as (
    select a.topic_id as id_a, b.topic_id as id_b,
           a.title as tytul_a, b.title as tytul_b,
           a.status as status_a, b.status as status_b,
           a.merged_into_topic_id as scalony_do_a,
           b.merged_into_topic_id as scalony_do_b
    from targets a
    join targets b on a.topic_id < b.topic_id
), observations as (
    select p.id_a, p.id_b, r.created_at, r.run_id, r.topic_run_id,
           r.model, r.raw_output, sample.value as s, sample.ordinality,
           (sample.value ->> 'topic_id_a' = p.id_a) as zgodna_kolejnosc
    from public.topic_runs r
    cross join settings cfg
    cross join lateral jsonb_array_elements(
        coalesce(r.raw_output -> 'samples', '[]'::jsonb)
        || coalesce(r.raw_output -> 'score_band_samples', '[]'::jsonb)
    ) with ordinality as sample(value, ordinality)
    join pairs p
      on p.id_a = least(sample.value ->> 'topic_id_a', sample.value ->> 'topic_id_b')
     and p.id_b = greatest(sample.value ->> 'topic_id_a', sample.value ->> 'topic_id_b')
    where r.stage = 'EMBEDDING_DIAGNOSTICS' and r.status = 'COMPLETED'
      and (cfg.run_id is null or r.run_id = cfg.run_id)
), latest as (
    select distinct on (id_a, id_b) *
    from observations
    order by id_a, id_b, created_at desc, topic_run_id desc, ordinality
)
select
    p.tytul_a, p.tytul_b,
    case when l.topic_run_id is null then 'BRAK ZAPISANEGO WYNIKU'
         else 'ZAPISANA PRÓBKA' end as dostepnosc,
    round((l.s ->> 'similarity')::numeric, 6) as podobienstwo,
    cfg.obecny_prog,
    (l.s ->> 'similarity')::numeric >= cfg.obecny_prog as spelnia_obecny_prog,
    (l.s ->> 'similarity')::numeric >= 0.80 as spelnia_0_80,
    (l.s ->> 'similarity')::numeric >= 0.78 as spelnia_0_78,
    (l.s ->> 'similarity')::numeric >= 0.75 as spelnia_0_75,
    timezone('Europe/Warsaw', l.created_at) as data_porownania,
    l.run_id, l.model,
    coalesce((l.s ->> 'threshold')::numeric,
             (l.raw_output ->> 'threshold')::numeric) as prog_wtedy,
    (l.s ->> 'selected_for_merge')::boolean as wybrane_do_scalenia_wtedy,
    p.status_a, p.status_b, p.scalony_do_a, p.scalony_do_b,
    case when l.zgodna_kolejnosc then l.s ->> 'embedding_text_a'
         else l.s ->> 'embedding_text_b' end as porownywany_tekst_a,
    case when l.zgodna_kolejnosc then l.s ->> 'embedding_text_b'
         else l.s ->> 'embedding_text_a' end as porownywany_tekst_b,
    p.id_a, p.id_b,
    count(l.topic_run_id) over () as par_z_zapisanym_wynikiem,
    count(*) over () as par_lacznie
from pairs p
cross join settings cfg
left join latest l using (id_a, id_b)
order by podobienstwo desc nulls last, p.tytul_a, p.tytul_b;
