-- Run once in Supabase SQL Editor before rebuild_topic_updates.py --apply.
-- Only the server service_role may invoke this function. No public write RPC.
-- A topic's current summary and ALL its snapshots are replaced atomically.
-- No articles, links, dates, run IDs or version numbers are deleted/changed.

begin;

create or replace function public.rebuild_topic_updates_atomic(
    p_topic_id text,
    p_expected_current jsonb,
    p_expected_history jsonb,
    p_new_current jsonb,
    p_new_history jsonb,
    p_check_only boolean default false
) returns text
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
    actual_current jsonb;
    actual_history jsonb;
    item jsonb;
    previous_item jsonb;
begin
    if p_check_only then
        return 'ready';
    end if;

    select jsonb_build_object(
        'version', s.version, 'input_hash', s.input_hash,
        'model', s.model, 'summary', s.summary
    ) into actual_current
    from public.topic_summaries s where s.topic_id = p_topic_id
    for update;
    if not found then
        raise exception 'Missing topic summary: %', p_topic_id;
    end if;

    perform 1 from public.topic_summary_versions v
    where v.topic_id = p_topic_id order by v.version for update;
    select coalesce(jsonb_agg(jsonb_build_object(
        'version', v.version, 'run_id', v.run_id, 'model', v.model,
        'prompt_version', v.prompt_version, 'summary', v.summary,
        'new_article_ids', v.new_article_ids
    ) order by v.version), '[]'::jsonb) into actual_history
    from public.topic_summary_versions v where v.topic_id = p_topic_id;

    -- A lost network response can safely retry the same transaction.
    if actual_current = p_new_current and actual_history = p_new_history then
        return 'already_applied';
    end if;
    if actual_current is distinct from p_expected_current
       or actual_history is distinct from p_expected_history then
        raise exception 'Topic changed since backup; refusing overwrite: %', p_topic_id;
    end if;
    if p_new_current->'version' is distinct from p_expected_current->'version'
       or jsonb_array_length(p_new_history) <> jsonb_array_length(p_expected_history) then
        raise exception 'Replacement must preserve versions: %', p_topic_id;
    end if;

    -- Protect snapshot identities and article batches even from caller errors.
    for item in select value from jsonb_array_elements(p_new_history) loop
        select value into previous_item
        from jsonb_array_elements(p_expected_history)
        where value->'version' = item->'version';
        if not found
           or previous_item->'run_id' is distinct from item->'run_id'
           or previous_item->'new_article_ids' is distinct from item->'new_article_ids' then
            raise exception 'Replacement changed snapshot identity or articles: %', p_topic_id;
        end if;
    end loop;
    if (select count(distinct value->>'version') from jsonb_array_elements(p_new_history))
       <> jsonb_array_length(p_expected_history) then
        raise exception 'Duplicate replacement versions: %', p_topic_id;
    end if;

    update public.topic_summaries set
        summary = p_new_current->'summary',
        model = p_new_current->>'model',
        input_hash = p_new_current->>'input_hash'
    where topic_id = p_topic_id;
    -- Keep updated_at unchanged: advancing it would incorrectly consume
    -- articles that arrived after the last original summary/update.
    for item in select value from jsonb_array_elements(p_new_history) loop
        update public.topic_summary_versions set
            summary = item->'summary', model = item->>'model',
            prompt_version = item->>'prompt_version'
        where topic_id = p_topic_id and version = (item->>'version')::integer;
    end loop;
    return 'applied';
end;
$$;

revoke all on function public.rebuild_topic_updates_atomic(text,jsonb,jsonb,jsonb,jsonb,boolean)
    from public, anon, authenticated;
grant execute on function public.rebuild_topic_updates_atomic(text,jsonb,jsonb,jsonb,jsonb,boolean)
    to service_role;

notify pgrst, 'reload schema';
commit;
