-- Jednorazowo: pierwsze syntezy opublikowane w ostatnich 30 godzinach
-- przywracają aktywne, niescalone wątki do Aktualnych. Bez zmiany treści.
-- Historyczny backfill wersji jest wykluczony.
update public.topics t
set last_seen_at = v.generated_at, updated_at = now()
from public.topic_summary_versions v
where v.topic_id = t.topic_id
  and v.version = 1
  and v.run_id is not null
  and v.prompt_version <> 'BACKFILL_BEFORE_UPDATE_HISTORY'
  and v.generated_at >= now() - interval '30 hours'
  and t.status = 'ACTIVE'
  and (t.last_seen_at is null or t.last_seen_at < v.generated_at)
  and exists (select 1 from public.topic_summaries s where s.topic_id = t.topic_id)
returning t.headline_pl as przywrocony_watek, t.last_seen_at;
