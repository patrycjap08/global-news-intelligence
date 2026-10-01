-- Opcjonalne usunięcie dawnych tabel i widoków integracji X.
-- Nowy worker i aplikacja nie korzystają z nich nawet bez tej migracji.
-- Uruchom w Supabase SQL Editor, jeśli historyczne surowe wpisy mają zostać
-- usunięte. Istniejące syntezy i ich historia pozostają zachowane.

begin;

drop view if exists public.app_topic_x_posts;
drop view if exists public.app_x_posts;
drop table if exists public.topic_x_posts;
drop table if exists public.x_posts;
drop table if exists public.x_accounts;

commit;
