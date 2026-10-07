-- Tylko odczyt. Uruchom po nowym full lub ai-only na aktualnym main.
-- Historyczne przebiegi sprzed EMBEDDING_DIAGNOSTICS nie mają tych danych.
-- Embedding wybiera kandydatów; selected_for_ai nie oznacza scalenia przez AI.
-- Próbki są celowo wybierane blisko progu i z różnych par; nie są reprezentatywne.

with latest as (
    select topic_run_id, run_id, created_at, raw_output
    from public.topic_runs
    where stage = 'EMBEDDING_DIAGNOSTICS' and status = 'COMPLETED'
    order by created_at desc, topic_run_id desc
    limit 1
), samples as (
    select l.*, s.value as sample,
        row_number() over (
            partition by s.value ->> 'bucket'
            order by abs((s.value ->> 'similarity')::numeric
                       - (l.raw_output ->> 'threshold')::numeric),
                     s.value ->> 'topic_id_a', s.value ->> 'topic_id_b'
        ) as example_number
    from latest l
    cross join lateral jsonb_array_elements(l.raw_output -> 'samples') s
)
select
    timezone('Europe/Warsaw', created_at) as data_porownania,
    run_id,
    case sample ->> 'bucket'
        when 'SELECTED_NEAR_THRESHOLD' then 'Wybrane: tuż nad progiem'
        when 'SELECTED_HIGH_SCORE' then 'Wybrane: wyższe podobieństwo'
        when 'BELOW_THRESHOLD' then 'Pominięte: tuż pod progiem'
        when 'ABOVE_THRESHOLD_OUTSIDE_TOP_K' then 'Pominięte: poza limitem sąsiadów'
    end as grupa_przykladu,
    round((sample ->> 'similarity')::numeric, 6) as podobienstwo_embeddingow,
    (raw_output ->> 'threshold')::numeric as prog,
    round((sample ->> 'similarity')::numeric
          - (raw_output ->> 'threshold')::numeric, 6) as odleglosc_od_progu,
    (sample ->> 'selected_for_ai')::boolean as wybrane_do_oceny_ai,
    (sample ->> 'rank_a_to_b')::integer as pozycja_b_wsrod_sasiadow_a,
    (sample ->> 'rank_b_to_a')::integer as pozycja_a_wsrod_sasiadow_b,
    (raw_output ->> 'top_k')::integer as limit_sasiadow,
    sample ->> 'title_a' as tytul_a,
    sample ->> 'title_b' as tytul_b,
    sample ->> 'embedding_text_a' as tekst_porownany_a,
    sample ->> 'embedding_text_b' as tekst_porownany_b
from samples
where example_number <= 5 -- Zmień na 20, aby zobaczyć wszystkie zapisane próbki.
order by grupa_przykladu, example_number;

-- Podsumowanie ostatniego raportu: są to liczniki par, a nie liczby próbek.
select
    timezone('Europe/Warsaw', created_at) as data_porownania,
    run_id,
    raw_output ->> 'embedding_model' as model,
    (raw_output ->> 'dimensions')::integer as wymiary,
    (raw_output ->> 'threshold')::numeric as prog,
    (raw_output ->> 'top_k')::integer as limit_sasiadow,
    (raw_output ->> 'topic_count')::integer as porownane_tematy,
    (raw_output ->> 'compared_pairs')::bigint as wszystkie_porownane_pary,
    (raw_output ->> 'selected_pair_count')::integer as pary_wybrane_do_ai,
    coalesce((raw_output #>> '{bucket_pair_counts,BELOW_THRESHOLD}')::integer, 0)
        as pary_tuz_pod_progiem,
    coalesce((raw_output #>> '{bucket_pair_counts,ABOVE_THRESHOLD_OUTSIDE_TOP_K}')::integer, 0)
        as pary_nad_progiem_pominiete_przez_limit_sasiadow,
    jsonb_array_length(raw_output -> 'samples') as zapisane_probki
from public.topic_runs
where stage = 'EMBEDDING_DIAGNOSTICS' and status = 'COMPLETED'
order by created_at desc, topic_run_id desc
limit 1;
