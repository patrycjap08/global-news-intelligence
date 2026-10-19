-- Reset opracowan do ponownego testu ai-only; NIE cofa scalania ani grupowania.
-- Supabase -> SQL Editor -> New query -> wklej CALY plik -> Run.
-- Uruchom po zakonczeniu/zatrzymaniu workflow, przed NOWYM ai-only z main.
--
-- Zakres: aktywne watki topic_perspectives_ w oknie 36 godzin, analizowane
-- w dwoch ostatnich roznych harvest_runs. Aby wybrac jeden run, zmien 2 na 1.
-- Powtorki ai-only tego samego pobrania maja wspolny run_id.
-- Usuwa CALE opracowanie wskazanego watku: pierwotna synteze, fakty,
-- perspektywy, kontekst, aktualizacje i wszystkie jego wersje historii.
-- Dotyczy tez starszej syntezy, jesli ostatnio byla tylko aktualizowana.
-- Dzieki temu ai-only tworzy synteze od nowa ze wszystkich podpietych artykulow.
-- Pozostawia artykuly, przypisania, watki, scalenia, kategorie i logi AI.
-- Stary format opracowan oraz watki poza oknem 36 godzin pozostaja nietkniete.
-- Kopia usuwanych rekordow trafia do prywatnego gni_recovery.summary_resets.
-- SQL nie zmienia juz opublikowanego pliku Pages: odswiezy go eksport po AI.

do $reset_summaries$
declare
    liczba_przebiegow constant integer := 2;
    wybrane_runy text[];
    wybrane_watki text[];
    kopia jsonb;
    id_kopii bigint;
    usuniete_opracowania integer;
    usuniete_wersje integer;
begin
    set local lock_timeout = '5s';
    lock table public.harvest_runs, public.topics, public.topic_articles,
        public.topic_summaries, public.topic_summary_versions
        in share row exclusive mode;

    -- Wybor nie zalezy od tabel usuwanych ponizej: ponowne wykonanie
    -- bez nowego harvestu NIE przesuwa zakresu na coraz starsze przebiegi.
    select array_agg(r.run_id order by r.started_at desc, r.run_id desc)
    into wybrane_runy
    from (
        select run_id, started_at
        from public.harvest_runs
        order by started_at desc, run_id desc
        limit liczba_przebiegow
    ) r;

    if wybrane_runy is null then
        raise exception 'Brak harvest_runs. Nic nie usunieto.';
    end if;

    select coalesce(array_agg(t.topic_id order by t.topic_id), '{}'::text[])
    into wybrane_watki
    from public.topics t
    join public.topic_summaries s on s.topic_id = t.topic_id
    where t.status = 'ACTIVE'
      and t.last_seen_at >= now() - interval '36 hours'
      -- Po usunieciu syntezy kod rozpoznaje nowy format po prefiksie ID.
      and starts_with(t.topic_id, 'topic_perspectives_')
      and (
          s.summary->'last_analysis'->>'run_id' = any(wybrane_runy)
          or exists (
              select 1 from public.topic_summary_versions v
              where v.topic_id = t.topic_id and v.run_id = any(wybrane_runy)
          )
      );

    select jsonb_build_object(
        'topic_summaries', (
            select coalesce(jsonb_agg(to_jsonb(s) order by s.topic_id), '[]'::jsonb)
            from public.topic_summaries s where s.topic_id = any(wybrane_watki)
        ),
        'topic_summary_versions', (
            select coalesce(jsonb_agg(to_jsonb(v) order by v.topic_id, v.version), '[]'::jsonb)
            from public.topic_summary_versions v where v.topic_id = any(wybrane_watki)
        )
    ) into kopia;

    create schema if not exists gni_recovery;
    revoke all on schema gni_recovery from public, anon, authenticated;
    create table if not exists gni_recovery.summary_resets (
        reset_id bigint generated always as identity primary key,
        created_at timestamptz not null default now(),
        run_ids text[] not null,
        topic_ids text[] not null,
        deleted_summaries integer not null default 0,
        deleted_versions integer not null default 0,
        payload jsonb not null
    );
    revoke all on gni_recovery.summary_resets from public, anon, authenticated;
    insert into gni_recovery.summary_resets(run_ids, topic_ids, payload)
    values (wybrane_runy, wybrane_watki, kopia)
    returning reset_id into id_kopii;

    delete from public.topic_summary_versions where topic_id = any(wybrane_watki);
    get diagnostics usuniete_wersje = row_count;
    delete from public.topic_summaries where topic_id = any(wybrane_watki);
    get diagnostics usuniete_opracowania = row_count;

    if usuniete_opracowania <> jsonb_array_length(kopia->'topic_summaries')
       or usuniete_wersje <> jsonb_array_length(kopia->'topic_summary_versions') then
        raise exception 'Liczby rekordow nie zgadzaja sie z kopia. Cala operacja wycofana.';
    end if;

    update gni_recovery.summary_resets set
        deleted_summaries = usuniete_opracowania, deleted_versions = usuniete_wersje
    where reset_id = id_kopii;
end
$reset_summaries$;

select reset_id as id_kopii,
       run_ids as wybrane_przebiegi,
       deleted_summaries as opracowania_do_wygenerowania_od_nowa,
       deleted_versions as usuniete_wersje_historii,
       created_at as czas_resetowania
from gni_recovery.summary_resets
order by reset_id desc
limit 1;
