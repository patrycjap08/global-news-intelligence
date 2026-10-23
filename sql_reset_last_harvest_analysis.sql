-- Supabase -> SQL Editor -> wklej CALY plik -> Run.
-- Uruchom przy zatrzymanym workflow, potem NOWE ai-only z main.
-- Zakres: aktywne watki podpiete do artykulow faktycznie pobranych
-- (run_articles.fetched_now = true) w OSTATNIM harvescie.
-- Reset obejmuje tylko watki odtwarzalne przez obecna kolejke ai-only.
-- Starszy format, watki poza 36 h i bez dwoch artykulow/zrodel sa pomijane;
-- ich opracowania pozostaja, a powod jest pokazany w wyniku SQL.
-- Usuwa cale opracowania i ich wersje: syntezy, fakty, perspektywy,
-- aktualizacje oraz cache ekstrakcji i checkpointy uzywane do wznowienia.
-- Artykuly, przypisania, watki, daty, tytuly i kategorie pozostaja.
-- Kopia wynikow trafia do prywatnego schematu gni_recovery.
-- Jedna atomowa instrukcja DO; bez tabel tymczasowych ani zaleznosci od sesji.

do $reset_harvest_analysis$
declare
    -- Opcjonalnie wpisz konkretny harvest_... zamiast null.
    requested_run_id constant text := null;
    selected_run_id text;
    fetched_article_ids text[];
    candidate_topic_ids text[];
    selected_topic_ids text[];
    skipped_topics jsonb;
    all_topic_article_ids text[];
    cache_ids text[];
    checkpoint_ids text[];
    backup jsonb;
    backup_id bigint;
    deleted_summaries integer;
    deleted_versions integer;
    deleted_cache integer;
    cleared_checkpoints integer;
begin
    set local lock_timeout = '5s';
    lock table public.harvest_runs, public.run_articles, public.topics,
        public.topic_articles, public.topic_summaries,
        public.topic_summary_versions, public.topic_runs
        in share row exclusive mode;

    select h.run_id into selected_run_id
    from public.harvest_runs h
    where requested_run_id is null or h.run_id = requested_run_id
    order by h.started_at desc, h.run_id desc
    limit 1;
    if selected_run_id is null then
        raise exception 'Brak wskazanego harvestu. Nic nie zmieniono.';
    end if;

    -- Wybor nie zalezy od usuwanych wynikow: powtorka nie siega starszego runu.
    select coalesce(array_agg(ra.article_id order by ra.article_id), '{}'::text[])
    into fetched_article_ids
    from public.run_articles ra
    where ra.run_id = selected_run_id and ra.fetched_now;
    if cardinality(fetched_article_ids) = 0 then
        raise exception 'Harvest % nie ma faktycznie pobranych artykulow. Nic nie zmieniono.', selected_run_id;
    end if;

    select coalesce(array_agg(t.topic_id order by t.topic_id), '{}'::text[])
    into candidate_topic_ids
    from public.topics t
    where t.status = 'ACTIVE' and exists (
        select 1 from public.topic_articles ta
        where ta.topic_id = t.topic_id and ta.article_id = any(fetched_article_ids)
    );
    if cardinality(candidate_topic_ids) = 0 then
        raise exception 'Brak aktywnych watkow powiazanych z artykulami harvestu %. Nic nie zmieniono.', selected_run_id;
    end if;

    -- Jeden nieodtwarzalny watek nie blokuje resetu pozostalych.
    -- Zachowaj jego wyniki i pokaz powod, zamiast zmieniac daty albo format ID.
    with coverage as (
        select ta.topic_id, count(distinct ta.article_id) as linked_articles,
            count(distinct a.article_id) as available_articles,
            count(distinct nullif(btrim(coalesce(nullif(a.source_id, ''), a.source_name, '')), '')) as sources
        from public.topic_articles ta
        left join public.articles a on a.article_id = ta.article_id
        where ta.topic_id = any(candidate_topic_ids)
        group by ta.topic_id
    ), eligibility as (
        select t.topic_id, t.headline_pl, t.last_seen_at,
            case
                when not starts_with(t.topic_id, 'topic_perspectives_') then 'stary format watku'
                when t.last_seen_at is null then 'brak daty ostatniej aktywnosci'
                when t.last_seen_at < now() - interval '36 hours' then 'poza oknem 36 godzin'
                when c.linked_articles < 2 then 'mniej niz dwa podpiete artykuly'
                when c.available_articles < 2 then 'mniej niz dwa dostepne artykuly'
                when c.sources < 2 then 'artykuly pochodza tylko z jednego zrodla'
                else null
            end as skip_reason
        from public.topics t join coverage c on c.topic_id = t.topic_id
    )
    select
        coalesce(array_agg(e.topic_id order by e.topic_id)
                 filter (where e.skip_reason is null), '{}'::text[]),
        coalesce(jsonb_agg(jsonb_build_object(
            'topic_id', e.topic_id, 'tytul', e.headline_pl,
            'ostatnia_aktywnosc', e.last_seen_at, 'powod', e.skip_reason
        ) order by e.topic_id) filter (where e.skip_reason is not null), '[]'::jsonb)
    into selected_topic_ids, skipped_topics
    from eligibility e;

    -- Nowa ekstrakcja obejmie WSZYSTKIE artykuly wybranych watkow, takze starsze.
    select coalesce(array_agg(distinct ta.article_id order by ta.article_id), '{}'::text[])
    into all_topic_article_ids
    from public.topic_articles ta where ta.topic_id = any(selected_topic_ids);

    select coalesce(array_agg(r.topic_run_id), '{}'::text[]) into cache_ids
    from public.topic_runs r
    where r.stage = 'ARTICLE_EXTRACTION_CACHE'
      and r.raw_output->>'article_id' = any(all_topic_article_ids);

    select coalesce(array_agg(r.topic_run_id), '{}'::text[]) into checkpoint_ids
    from public.topic_runs r
    where r.stage = 'SUMMARY' and r.raw_output ? 'extraction_checkpoint'
      and (
          r.input_hash in (
              select s.input_hash from public.topic_summaries s
              where s.topic_id = any(selected_topic_ids)
          )
          or exists (
              -- Ten sam identyfikator co load_extraction_checkpoint w Pythonie.
              -- Dziala tez dla nieudanej pierwszej syntezy z pustymi faktami.
              select 1 from unnest(selected_topic_ids) as target(topic_id)
              where r.topic_run_id = 'topicrun_' || left(encode(sha256(convert_to(
                  '{"input":' || to_json(r.input_hash)::text ||
                  ',"stage":"SUMMARY","topic":' || to_json(target.topic_id)::text || '}',
                  'UTF8')), 'hex'), 24)
          )
      );

    select jsonb_build_object(
        'fetched_article_ids', to_jsonb(fetched_article_ids),
        'candidate_topic_ids', to_jsonb(candidate_topic_ids),
        'topic_ids', to_jsonb(selected_topic_ids),
        'skipped_topics', skipped_topics,
        'all_topic_article_ids', to_jsonb(all_topic_article_ids),
        'topic_summaries', (select coalesce(jsonb_agg(to_jsonb(s)), '[]'::jsonb)
            from public.topic_summaries s where s.topic_id = any(selected_topic_ids)),
        'topic_summary_versions', (select coalesce(jsonb_agg(to_jsonb(v)), '[]'::jsonb)
            from public.topic_summary_versions v where v.topic_id = any(selected_topic_ids)),
        'topic_runs', (select coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb)
            from public.topic_runs r where r.topic_run_id = any(cache_ids)
               or r.topic_run_id = any(checkpoint_ids))
    ) into backup;

    create schema if not exists gni_recovery;
    revoke all on schema gni_recovery from public, anon, authenticated;
    create table if not exists gni_recovery.harvest_analysis_resets (
        reset_id bigint generated always as identity primary key,
        created_at timestamptz not null default now(),
        run_id text not null,
        payload jsonb not null
    );
    revoke all on gni_recovery.harvest_analysis_resets from public, anon, authenticated;
    insert into gni_recovery.harvest_analysis_resets(run_id, payload)
    values (selected_run_id, backup) returning reset_id into backup_id;

    delete from public.topic_summary_versions where topic_id = any(selected_topic_ids);
    get diagnostics deleted_versions = row_count;
    delete from public.topic_summaries where topic_id = any(selected_topic_ids);
    get diagnostics deleted_summaries = row_count;
    delete from public.topic_runs where topic_run_id = any(cache_ids);
    get diagnostics deleted_cache = row_count;
    update public.topic_runs set raw_output = raw_output - 'extraction_checkpoint'
    where topic_run_id = any(checkpoint_ids);
    get diagnostics cleared_checkpoints = row_count;

    if deleted_summaries <> jsonb_array_length(backup->'topic_summaries')
       or deleted_versions <> jsonb_array_length(backup->'topic_summary_versions')
       or deleted_cache + cleared_checkpoints <> jsonb_array_length(backup->'topic_runs') then
        raise exception 'Niezgodnosc z kopia wynikow. Caly reset wycofano.';
    end if;

    update gni_recovery.harvest_analysis_resets
    set payload = payload || jsonb_build_object('result', jsonb_build_object(
        'summaries', deleted_summaries, 'versions', deleted_versions,
        'cache', deleted_cache, 'checkpoints', cleared_checkpoints))
    where reset_id = backup_id;
end
$reset_harvest_analysis$;

-- Wynik pozostaje dostepny takze po zmianie polaczenia SQL Editora.
select reset_id as id_kopii, run_id,
    jsonb_array_length(payload->'fetched_article_ids') as pobrane_artykuly,
    jsonb_array_length(payload->'candidate_topic_ids') as powiazane_aktywne_watki,
    jsonb_array_length(payload->'topic_ids') as wybrane_watki,
    jsonb_array_length(payload->'skipped_topics') as pominiete_watki_bez_kasowania,
    jsonb_array_length(payload->'all_topic_article_ids') as artykuly_do_ponownej_ekstrakcji,
    (payload->'result'->>'summaries')::integer as usuniete_syntezy_z_faktami,
    (payload->'result'->>'versions')::integer as usuniete_wersje,
    (payload->'result'->>'cache')::integer as usuniety_cache_ekstrakcji,
    (payload->'result'->>'checkpoints')::integer as wyczyszczone_checkpointy,
    payload->'skipped_topics' as pominiete_watki_i_powody
from gni_recovery.harvest_analysis_resets
order by reset_id desc limit 1;
