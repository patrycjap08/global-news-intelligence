-- Run once in Supabase SQL Editor before enabling the evening X import.
create table if not exists public.x_accounts (
    username text primary key,
    display_name text not null,
    category text not null,
    editorial_profile text not null default 'UNCLASSIFIED',
    x_user_id text unique,
    enabled boolean not null default true,
    last_checked_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.x_posts (
    post_id text primary key,
    username text not null references public.x_accounts(username),
    display_name text not null,
    category text not null,
    editorial_profile text not null default 'UNCLASSIFIED',
    text text not null,
    lang text,
    posted_at timestamptz,
    url text not null,
    fetched_at timestamptz not null default now(),
    harvest_run_id text references public.harvest_runs(run_id),
    ai_status text not null default 'PENDING',
    exclusion_reason text,
    raw_json jsonb
);
create index if not exists x_posts_run_idx on public.x_posts(harvest_run_id);
create index if not exists x_posts_status_idx on public.x_posts(ai_status);

create table if not exists public.topic_x_posts (
    topic_id text not null references public.topics(topic_id) on delete cascade,
    post_id text not null references public.x_posts(post_id) on delete cascade,
    confidence numeric,
    assigned_at timestamptz not null default now(),
    primary key (topic_id, post_id)
);

alter table public.x_accounts enable row level security;
alter table public.x_posts enable row level security;
alter table public.topic_x_posts enable row level security;

drop policy if exists "public can read x accounts" on public.x_accounts;
create policy "public can read x accounts" on public.x_accounts for select to anon, authenticated using (true);
drop policy if exists "public can read x posts" on public.x_posts;
create policy "public can read x posts" on public.x_posts for select to anon, authenticated using (true);
drop policy if exists "public can read topic x posts" on public.topic_x_posts;
create policy "public can read topic x posts" on public.topic_x_posts for select to anon, authenticated using (true);

create or replace view public.app_x_posts as
select post_id, username, display_name, category, editorial_profile, text,
       posted_at, url, ai_status
from public.x_posts where ai_status = 'MATCHED';

create or replace view public.app_topic_x_posts as
select topic_id, post_id, confidence, assigned_at from public.topic_x_posts;

grant select on public.app_x_posts, public.app_topic_x_posts to anon, authenticated;
