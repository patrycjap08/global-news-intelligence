-- Global News Intelligence: Supabase schema.
-- Run once in Supabase Dashboard -> SQL Editor.
-- The GitHub Action uses SUPABASE_SECRET_KEY for server-side writes.

create table if not exists public.sources (
    source_id text primary key,
    name text not null,
    homepage text not null,
    region text not null default '',
    editorial_profile text not null default 'UNCLASSIFIED',
    source_type text not null default 'UNCLASSIFIED',
    enabled boolean not null default true,
    updated_at timestamptz not null default now()
);

create table if not exists public.harvest_runs (
    run_id text primary key,
    started_at timestamptz not null,
    finished_at timestamptz,
    status text not null,
    source_count integer not null default 0,
    discovered_count integer not null default 0,
    fetched_count integer not null default 0,
    skipped_existing_count integer not null default 0,
    valid_article_count integer not null default 0,
    failed_count integer not null default 0,
    created_at timestamptz not null default now()
);

create table if not exists public.articles (
    article_id text primary key,
    source_id text not null references public.sources(source_id),
    source_name text not null,
    source_profile text not null default 'UNCLASSIFIED',
    source_type text not null default 'UNCLASSIFIED',
    original_language text not null default 'en/original',
    title text not null,
    body text not null default '',
    description text not null default '',
    author text not null default '',
    original_url text not null,
    canonical_url text not null,
    published_at text,
    updated_at text,
    section text,
    item_kind text not null,
    content_status text not null,
    word_count integer not null default 0,
    content_hash text not null default '',
    title_key text not null default '',
    opening_text text not null default '',
    opening_fingerprint text not null default '',
    sentiment text,
    tone_hint text not null default 'NOT_ANALYZED',
    topic_hint text,
    fetch_method text not null,
    http_status integer,
    error text,
    first_seen_at timestamptz not null,
    fetched_at timestamptz not null,
    last_seen_on_homepage_at timestamptz not null,
    created_at timestamptz not null default now(),
    unique(source_id, canonical_url)
);

create table if not exists public.article_url_aliases (
    source_id text not null references public.sources(source_id),
    candidate_url text not null,
    duplicate_of_article_id text not null references public.articles(article_id),
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    reason text not null,
    primary key (source_id, candidate_url)
);

create table if not exists public.rejected_candidates (
    source_id text not null references public.sources(source_id),
    canonical_url text not null,
    title text not null default '',
    word_count integer not null default 0,
    opening_fingerprint text not null default '',
    reason text not null,
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    primary key (source_id, canonical_url)
);

create table if not exists public.run_articles (
    run_id text not null references public.harvest_runs(run_id),
    article_id text not null references public.articles(article_id),
    discovered_on_homepage boolean not null default true,
    fetched_now boolean not null default false,
    primary key (run_id, article_id)
);

create table if not exists public.source_run_results (
    run_id text not null references public.harvest_runs(run_id),
    source_id text not null references public.sources(source_id),
    homepage_status integer,
    discovered_count integer not null default 0,
    fetched_count integer not null default 0,
    skipped_existing_count integer not null default 0,
    valid_article_count integer not null default 0,
    failed_count integer not null default 0,
    duplicate_count integer not null default 0,
    rejected_short_count integer not null default 0,
    discovery_duration_ms integer not null default 0,
    fetch_duration_ms integer not null default 0,
    total_duration_ms integer not null default 0,
    average_article_fetch_ms integer not null default 0,
    notes text not null default '',
    primary key (run_id, source_id)
);

create table if not exists public.article_homepage_sightings (
    run_id text not null references public.harvest_runs(run_id),
    article_id text not null references public.articles(article_id),
    source_id text not null references public.sources(source_id),
    seen_at timestamptz not null default now(),
    position integer,
    primary key (run_id, article_id)
);

create table if not exists public.topics (
    topic_id text primary key,
    headline_pl text not null,
    status text not null default 'ACTIVE',
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    article_count integer not null default 0,
    source_count integer not null default 0,
    coverage_status text not null default 'SINGLE_ARTICLE',
    needs_review boolean not null default false,
    merged_into_topic_id text references public.topics(topic_id),
    merged_at timestamptz,
    updated_at timestamptz not null default now()
);

alter table public.topics
    add column if not exists coverage_status text not null default 'SINGLE_ARTICLE';
alter table public.topics
    add column if not exists merged_into_topic_id text references public.topics(topic_id);
alter table public.topics
    add column if not exists merged_at timestamptz;

create index if not exists topics_merged_into_idx
    on public.topics(merged_into_topic_id);

create table if not exists public.topic_articles (
    topic_id text not null references public.topics(topic_id),
    article_id text not null references public.articles(article_id),
    assigned_at timestamptz not null default now(),
    confidence numeric,
    primary key (topic_id, article_id)
);

create table if not exists public.article_topic_assignments (
    assignment_id bigint generated by default as identity primary key,
    run_id text not null references public.harvest_runs(run_id),
    article_id text not null references public.articles(article_id),
    topic_id text not null references public.topics(topic_id),
    confidence numeric,
    needs_review boolean not null default false,
    grouping_reason text not null default '',
    prompt_version text not null,
    created_at timestamptz not null default now(),
    unique(run_id, article_id)
);

create table if not exists public.topic_runs (
    topic_run_id text primary key,
    run_id text not null references public.harvest_runs(run_id),
    stage text not null,
    prompt_version text not null,
    model text not null,
    input_hash text not null,
    status text not null,
    raw_output jsonb,
    error text,
    created_at timestamptz not null default now()
);

create table if not exists public.topic_summaries (
    topic_id text primary key references public.topics(topic_id),
    version integer not null default 1,
    input_hash text not null,
    model text not null,
    summary jsonb not null,
    generated_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

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

create index if not exists articles_source_published_idx on public.articles(source_id, published_at);
create index if not exists articles_content_hash_idx on public.articles(content_hash);
create index if not exists topics_last_seen_idx on public.topics(status, last_seen_at desc);
create index if not exists topic_articles_article_idx on public.topic_articles(article_id);
create index if not exists topic_summary_versions_topic_idx on public.topic_summary_versions(topic_id, version desc);

-- Recalculate coverage for topics created before coverage_status was added.
with coverage as (
    select
        ta.topic_id,
        count(distinct ta.article_id)::integer as article_count,
        count(distinct a.source_id)::integer as source_count
    from public.topic_articles ta
    join public.articles a on a.article_id = ta.article_id
    group by ta.topic_id
)
update public.topics t
set article_count = coverage.article_count,
    source_count = coverage.source_count,
    coverage_status = case
        when coverage.article_count = 1 then 'SINGLE_ARTICLE'
        when coverage.source_count = 1 then 'SINGLE_SOURCE'
        else 'MULTI_SOURCE'
    end,
    updated_at = now()
from coverage
where t.topic_id = coverage.topic_id
  and t.status = 'ACTIVE';

create or replace view public.source_topic_coverage as
select
    a.source_id,
    max(a.source_name) as source_name,
    count(distinct t.topic_id) as total_topic_count,
    count(distinct t.topic_id) filter (where t.coverage_status = 'SINGLE_ARTICLE')
        as single_article_topic_count,
    count(distinct t.topic_id) filter (where t.coverage_status = 'SINGLE_SOURCE')
        as single_source_topic_count,
    count(distinct t.topic_id) filter (where t.coverage_status = 'MULTI_SOURCE')
        as multi_source_topic_count,
    count(distinct t.topic_id) filter (where ts.topic_id is not null)
        as summarized_topic_count
from public.topic_articles ta
join public.topics t on t.topic_id = ta.topic_id
join public.articles a on a.article_id = ta.article_id
left join public.topic_summaries ts on ts.topic_id = t.topic_id
where t.status = 'ACTIVE'
group by a.source_id;

-- The publishable key is safe to use from a frontend only together with RLS.
alter table public.sources enable row level security;
alter table public.articles enable row level security;
alter table public.topics enable row level security;
alter table public.topic_articles enable row level security;
alter table public.topic_summaries enable row level security;

drop policy if exists "authenticated users can read sources" on public.sources;
create policy "authenticated users can read sources" on public.sources
    for select to authenticated using (true);
drop policy if exists "authenticated users can read articles" on public.articles;
create policy "authenticated users can read articles" on public.articles
    for select to authenticated using (true);
drop policy if exists "authenticated users can read topics" on public.topics;
create policy "authenticated users can read topics" on public.topics
    for select to authenticated using (true);
drop policy if exists "authenticated users can read topic articles" on public.topic_articles;
create policy "authenticated users can read topic articles" on public.topic_articles
    for select to authenticated using (true);
drop policy if exists "authenticated users can read summaries" on public.topic_summaries;
create policy "authenticated users can read summaries" on public.topic_summaries
    for select to authenticated using (true);
