-- Uruchom po nowym full/ai-only, który zapisał próbki aż do 0,60.
-- Przedziały mają szerokość 0,02: [0,84; 0,86), [0,82; 0,84), ... [0,60; 0,62).
-- Do pięciu unikalnych par najbliższych dolnej granicy każdego przedziału.
-- To nie jest reprezentatywna próba. NULL w tytułach oznacza pusty przedział.
with latest as (
    select created_at, run_id, raw_output
    from public.topic_runs
    where stage = 'EMBEDDING_DIAGNOSTICS' and status = 'COMPLETED'
      and raw_output ? 'score_band_samples'
    order by created_at desc, topic_run_id desc
    limit 1
), bands as (
    select n::numeric / 50 as lower_score, (n + 1)::numeric / 50 as upper_score
    from generate_series(42, 30, -1) n
)
select
    timezone('Europe/Warsaw', l.created_at) as data_porownania,
    l.run_id,
    b.lower_score as od_score,
    b.upper_score as do_score_bez_tej_wartosci,
    (l.raw_output ->> 'threshold')::numeric as aktualny_prog_scalania,
    coalesce((l.raw_output -> 'score_band_pair_counts' ->> trim_scale(b.lower_score)::text)::bigint, 0)
        as wszystkie_pary_w_przedziale,
    round((s.value ->> 'similarity')::numeric, 6) as score,
    s.value ->> 'title_a' as temat_a,
    s.value ->> 'title_b' as temat_b,
    s.value ->> 'embedding_text_a' as tekst_porownany_a,
    s.value ->> 'embedding_text_b' as tekst_porownany_b,
    coalesce(s.value ->> 'selected_for_merge', s.value ->> 'selected_for_ai')::boolean
        as wybrane_do_scalania
from latest l
cross join bands b
left join lateral (
    select value
    from jsonb_array_elements(l.raw_output -> 'score_band_samples')
    where (value ->> 'band_lower')::numeric = b.lower_score
    order by (value ->> 'similarity')::numeric, value ->> 'topic_id_a', value ->> 'topic_id_b'
    limit 5
) s on true
order by b.lower_score desc, score;
