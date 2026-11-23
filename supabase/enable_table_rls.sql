-- The FastAPI server uses the service-role key. Browser clients need no
-- direct table access, so no anon or authenticated policy is added.
begin;
set local lock_timeout = '5s';

alter table public.chat_analytics enable row level security;
alter table public.chat_messages enable row level security;
alter table public.chat_sessions enable row level security;
alter table public.chat_summaries enable row level security;
alter table public.documents enable row level security;

commit;
