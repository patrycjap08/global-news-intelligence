-- Źródła bez żadnego poprawnie pobranego artykułu zostały wyłączone
-- w konfiguracji harvestera. To zapytanie synchronizuje flagę w Supabase.

update public.sources
set enabled = false,
    updated_at = now()
where source_id in (
    'ap',
    'bloomberg',
    'die_zeit',
    'economist',
    'liberation',
    'new_york_times',
    'politico',
    'wall_street_journal'
);
