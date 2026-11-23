-- Run after the core documents schema exists. The existing Gemini column and
-- match_documents function remain usable on all previously indexed documents.
begin;
set local lock_timeout = '5s';
set local search_path = pg_catalog, extensions, public;

alter table public.documents
    add column if not exists embedding_cloudflare vector(1024),
    alter column embedding drop not null;

create or replace function public.match_documents_cloudflare(
    query_embedding vector(1024),
    match_threshold double precision,
    match_count integer
)
returns table (
    id bigint,
    content text,
    source text,
    category text,
    similarity double precision
)
language sql
stable
security invoker
set search_path = pg_catalog, extensions, public
as $$
    select d.id, d.content, d.source, d.category,
           1 - (d.embedding_cloudflare <=> query_embedding) as similarity
    from public.documents as d
    where d.embedding_cloudflare is not null
      and 1 - (d.embedding_cloudflare <=> query_embedding) >= match_threshold
    order by d.embedding_cloudflare <=> query_embedding, d.id
    limit least(greatest(match_count, 0), 50);
$$;

revoke all on function public.match_documents_cloudflare(vector, double precision, integer)
    from public, anon, authenticated;
grant execute on function public.match_documents_cloudflare(vector, double precision, integer)
    to service_role;
commit;
