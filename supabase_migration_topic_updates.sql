-- Zachowuje poprzednie wersje opracowań tematów i pozwala aplikacji pokazać
-- blok „nowe od ostatniej aktualizacji”. Uruchom jednorazowo po wdrożeniu.

create table if not exists public.topic_summary_versions (
    topic_id text not null references public.topics(topic_id),
    version integer not null,
    run_id text references public.harvest_runs(run_id),
    model text not null,
    prompt_version text not null,
    summary jsonb not null,
    new_article_ids jsonb not null default '[]'::jsonb,
    generated_at timestamptz not null default now(),
    primary key (topic_id, version)
);

create index if not exists topic_summary_versions_topic_idx
    on public.topic_summary_versions(topic_id, version desc);

-- Zachowaj aktualną wersję istniejących opracowań jako wersję początkową.
insert into public.topic_summary_versions (
    topic_id, version, run_id, model, prompt_version, summary,
    new_article_ids, generated_at
)
select
    ts.topic_id,
    ts.version,
    null,
    ts.model,
    'BACKFILL_BEFORE_UPDATE_HISTORY',
    ts.summary,
    '[]'::jsonb,
    ts.generated_at
from public.topic_summaries ts
on conflict (topic_id, version) do nothing;
