begin;

create table if not exists public.municipal_usage_daily (
    usage_date date primary key,
    questions bigint not null default 0 check (questions >= 0),
    tokens bigint not null default 0 check (tokens >= 0)
);
alter table public.municipal_usage_daily enable row level security;
revoke all on public.municipal_usage_daily from anon, authenticated;

create or replace function public.record_municipal_usage(question_delta integer, token_delta bigint)
returns void
language sql
security invoker
set search_path = ''
as $$
    insert into public.municipal_usage_daily (usage_date, questions, tokens)
    values ((now() at time zone 'Asia/Bangkok')::date, question_delta, token_delta)
    on conflict (usage_date) do update
        set questions = municipal_usage_daily.questions + excluded.questions,
            tokens = municipal_usage_daily.tokens + excluded.tokens;
$$;

create or replace function public.municipal_usage_snapshot(pdf_bucket text)
returns table (questions bigint, tokens bigint, used_bytes bigint)
language sql
stable
security definer
set search_path = ''
as $$
    select
        coalesce((select u.questions from public.municipal_usage_daily u
            where u.usage_date = (now() at time zone 'Asia/Bangkok')::date), 0),
        coalesce((select u.tokens from public.municipal_usage_daily u
            where u.usage_date = (now() at time zone 'Asia/Bangkok')::date), 0),
        case when exists (select 1 from storage.buckets b where b.id = pdf_bucket)
            then coalesce((select sum((o.metadata->>'size')::bigint) from storage.objects o
                where o.bucket_id = pdf_bucket and o.metadata->>'size' ~ '^[0-9]+$'), 0)::bigint
            else null end;
$$;

revoke all on function public.record_municipal_usage(integer, bigint) from public, anon, authenticated;
revoke all on function public.municipal_usage_snapshot(text) from public, anon, authenticated;
grant select, insert, update on public.municipal_usage_daily to service_role;
grant execute on function public.record_municipal_usage(integer, bigint) to service_role;
grant execute on function public.municipal_usage_snapshot(text) to service_role;
commit;
