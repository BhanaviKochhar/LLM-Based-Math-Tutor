-- TinyThinker progress storage. Run once in the Supabase SQL editor
-- (Dashboard -> SQL Editor -> New query -> paste -> Run). Safe to re-run.
--
-- A parent or teacher signs up through Supabase Auth (auth.users). Each
-- child they add is one row in students; each graded answer is one row in
-- attempts. Row Level Security limits every account to its own children,
-- enforced by the database rather than only by the app.

create table if not exists public.students (
    id                uuid primary key default gen_random_uuid(),
    parent_account_id uuid not null default auth.uid()
                      references auth.users (id) on delete cascade,
    display_name      text not null check (char_length(display_name) between 1 and 40),
    grade             smallint not null check (grade between 1 and 5),
    created_at        timestamptz not null default now()
);

create table if not exists public.attempts (
    id          bigint generated always as identity primary key,
    student_id  uuid not null references public.students (id) on delete cascade,
    topic       text not null,
    correct     boolean not null,
    created_at  timestamptz not null default now()
);

create index if not exists students_parent_idx on public.students (parent_account_id);
create index if not exists attempts_student_idx on public.attempts (student_id, id desc);

-- The project does not expose new tables automatically, so access is
-- granted here on purpose: logged-in accounts only (the policies below then
-- narrow that to their own rows), nothing for logged-out visitors.
revoke all on public.students, public.attempts from anon;
grant select, insert, update, delete on public.students to authenticated;
grant select, insert, delete on public.attempts to authenticated;

alter table public.students enable row level security;
alter table public.attempts enable row level security;

drop policy if exists "own students" on public.students;
create policy "own students" on public.students
    for all to authenticated
    using (parent_account_id = (select auth.uid()))
    with check (parent_account_id = (select auth.uid()));

drop policy if exists "own attempts" on public.attempts;
create policy "own attempts" on public.attempts
    for all to authenticated
    using (exists (select 1 from public.students s
                   where s.id = student_id and s.parent_account_id = (select auth.uid())))
    with check (exists (select 1 from public.students s
                        where s.id = student_id and s.parent_account_id = (select auth.uid())));

-- One round trip for scripts/llm/student_tracker.stats(): lifetime totals,
-- wrong answers per topic (first-missed first, the order the JSON store
-- keeps), and the last p_window outcomes oldest first. Runs as the caller,
-- so the policies above still apply.
create or replace function public.student_summary(p_student_id uuid, p_window int)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select jsonb_build_object(
        'attempts', (select count(*) from public.attempts a
                     where a.student_id = p_student_id),
        'correct', (select count(*) from public.attempts a
                    where a.student_id = p_student_id and a.correct),
        'weak_topics', coalesce((
            select jsonb_agg(jsonb_build_array(w.topic, w.n) order by w.first_id)
            from (select a.topic, count(*) as n, min(a.id) as first_id
                  from public.attempts a
                  where a.student_id = p_student_id and not a.correct
                  group by a.topic) w), '[]'::jsonb),
        'recent', coalesce((
            select jsonb_agg(r.outcome order by r.id)
            from (select a.id, case when a.correct then 1 else 0 end as outcome
                  from public.attempts a
                  where a.student_id = p_student_id
                  order by a.id desc
                  limit p_window) r), '[]'::jsonb)
    );
$$;

revoke execute on function public.student_summary(uuid, int) from public, anon;
grant execute on function public.student_summary(uuid, int) to authenticated;

-- Saved chat history. One row per chat (a child's conversation thread) and
-- one per message, in order. thread_notes are the tutor's short notes on
-- earlier problems in the chat (scripts/llm/memory.py), kept so a reopened
-- chat continues with the same context. Deleting a chat removes its
-- messages; deleting a child removes its chats.

create table if not exists public.chats (
    id            uuid primary key default gen_random_uuid(),
    student_id    uuid not null references public.students (id) on delete cascade,
    title         text not null default '' check (char_length(title) <= 200),
    thread_notes  jsonb not null default '[]'::jsonb,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create table if not exists public.messages (
    id          bigint generated always as identity primary key,
    chat_id     uuid not null references public.chats (id) on delete cascade,
    position    int not null,
    role        text not null check (role in ('user', 'assistant')),
    content     text not null default '',
    metadata    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now(),
    unique (chat_id, position)
);

create index if not exists chats_student_idx on public.chats (student_id, updated_at desc);

revoke all on public.chats, public.messages from anon;
grant select, insert, update, delete on public.chats to authenticated;
grant select, insert, delete on public.messages to authenticated;

alter table public.chats enable row level security;
alter table public.messages enable row level security;

drop policy if exists "own chats" on public.chats;
create policy "own chats" on public.chats
    for all to authenticated
    using (exists (select 1 from public.students s
                   where s.id = student_id and s.parent_account_id = (select auth.uid())))
    with check (exists (select 1 from public.students s
                        where s.id = student_id and s.parent_account_id = (select auth.uid())));

drop policy if exists "own messages" on public.messages;
create policy "own messages" on public.messages
    for all to authenticated
    using (exists (select 1 from public.chats c
                   join public.students s on s.id = c.student_id
                   where c.id = chat_id and s.parent_account_id = (select auth.uid())))
    with check (exists (select 1 from public.chats c
                        join public.students s on s.id = c.student_id
                        where c.id = chat_id and s.parent_account_id = (select auth.uid())));

-- Textbook search: the meaning-based half of scripts/retrieval.py. One row per
-- chunk of data/extracted_json/ncert_chunks.json (id = its position there,
-- the same number as Chroma's chunk_<id>), with its all-MiniLM-L6-v2 vector.
-- The text itself stays in the JSON file the app already ships. Textbook
-- content, not personal data: everyone can read it, including guests; nobody
-- can change it through the app (scripts/upload_chunks.py writes it with the
-- secret key).

create extension if not exists vector with schema extensions;

create table if not exists public.chunks (
    id         int primary key,
    grade      smallint not null,
    page       int not null,
    embedding  extensions.vector(384) not null
);

revoke all on public.chunks from anon, authenticated;
grant select on public.chunks to anon, authenticated;
-- scripts/upload_chunks.py writes with the secret key (role service_role),
-- which also gets no access to new tables in this project unless granted.
grant select, insert, update, delete on public.chunks to service_role;

alter table public.chunks enable row level security;

drop policy if exists "textbook is public" on public.chunks;
create policy "textbook is public" on public.chunks
    for select to anon, authenticated
    using (true);

-- The same search Chroma does: chunks in the given grades, past the front
-- matter, nearest first by L2 distance (Chroma's "l2" space). Exact search:
-- at a few thousand rows a full scan takes milliseconds.
create or replace function public.match_chunks(
    query_embedding extensions.vector(384), grades int[], min_page int, match_count int)
returns table (id int, distance float8)
language sql
stable
security invoker
set search_path = ''
as $$
    select c.id, (c.embedding operator(extensions.<->) query_embedding)::float8 as distance
    from public.chunks c
    where c.grade = any(grades) and c.page > min_page
    order by c.embedding operator(extensions.<->) query_embedding, c.id
    limit match_count;
$$;

revoke execute on function public.match_chunks(extensions.vector, int[], int, int) from public;
grant execute on function public.match_chunks(extensions.vector, int[], int, int) to anon, authenticated;

-- Admin dashboard (frontend/views/admin_page.py). Admins are listed here by
-- email; add yourself in the SQL editor:
--     insert into public.admins (email) values ('you@example.com');
-- Nothing in the app can read or change this table. admin_dashboard()
-- returns the numbers of supabase/admin_queries.sql in one bundle, totals
-- only, and refuses anyone whose login email isn't listed. Accounts flagged
-- test_account are left out, as in admin_queries.sql.

create table if not exists public.admins (email text primary key);
alter table public.admins enable row level security;
revoke all on public.admins from anon, authenticated;

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (select 1 from public.admins a
                   where lower(a.email) = lower(coalesce(auth.jwt() ->> 'email', '')));
$$;

revoke execute on function public.is_admin() from public, anon;
grant execute on function public.is_admin() to authenticated;

create or replace function public.admin_dashboard()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if not public.is_admin() then
        raise exception 'not an admin' using errcode = '42501';
    end if;
    return (
        with real_accounts as (
            select id, created_at from auth.users
            where coalesce((raw_user_meta_data ->> 'test_account')::boolean, false) = false
        ), real_students as (
            select s.id, s.grade from public.students s
            join real_accounts a on a.id = s.parent_account_id
        ), msgs as (
            select m.id, m.chat_id, m.role, m.metadata, m.created_at, c.student_id
            from public.messages m
            join public.chats c on c.id = m.chat_id
            join real_students s on s.id = c.student_id
        ), answers as (
            select a.* from public.attempts a join real_students s on s.id = a.student_id
        ), recent as (
            select student_id, correct,
                   row_number() over (partition by student_id order by id desc) as n
            from answers
        ), per_child as (
            select s.id, count(r.correct) as answers,
                   avg(case when r.correct then 1.0 else 0.0 end) as accuracy
            from real_students s left join recent r on r.student_id = s.id and r.n <= 5
            group by s.id
        ), per_chat as (
            select c.id, count(m.id) filter (where m.role = 'user') as typed
            from public.chats c
            join real_students s on s.id = c.student_id
            left join public.messages m on m.chat_id = c.id
            group by c.id
        )
        select jsonb_build_object(
            'totals', jsonb_build_object(
                'accounts', (select count(*) from real_accounts),
                'children', (select count(*) from real_students),
                'active_7_days', (select count(distinct student_id) from msgs
                                  where role = 'user' and created_at > now() - interval '7 days'),
                'active_30_days', (select count(distinct student_id) from msgs
                                   where role = 'user' and created_at > now() - interval '30 days')),
            'new_accounts_per_week', coalesce((
                select jsonb_agg(jsonb_build_object('week', w, 'accounts', n) order by w)
                from (select date_trunc('week', created_at)::date as w, count(*) as n
                      from real_accounts group by 1) t), '[]'::jsonb),
            'active_children_per_day', coalesce((
                select jsonb_agg(jsonb_build_object('day', d, 'children', n) order by d)
                from (select created_at::date as d, count(distinct student_id) as n from msgs
                      where role = 'user' and created_at > now() - interval '30 days'
                      group by 1) t), '[]'::jsonb),
            'accuracy_per_class', coalesce((
                select jsonb_agg(jsonb_build_object('class', g, 'children', c, 'answers', n,
                                                    'percent_correct', p) order by g)
                from (select s.grade as g, count(distinct s.id) as c, count(*) as n,
                             round(100.0 * avg(case when a.correct then 1 else 0 end), 1) as p
                      from answers a join real_students s on s.id = a.student_id
                      group by 1) t), '[]'::jsonb),
            'most_missed_topics', coalesce((
                select jsonb_agg(jsonb_build_object('topic', topic, 'answers', n, 'wrong', w,
                                                    'percent_wrong', p, 'children', c)
                                 order by w desc, p desc)
                from (select topic, count(*) as n, count(*) filter (where not correct) as w,
                             round(100.0 * count(*) filter (where not correct) / count(*), 1) as p,
                             count(distinct student_id) as c
                      from answers group by 1
                      order by 3 desc, 4 desc limit 15) t), '[]'::jsonb),
            'tutor_levels', coalesce((
                select jsonb_agg(jsonb_build_object('level', l, 'children', n) order by l)
                from (select case when answers < 3 then 'not enough answers yet'
                                  when accuracy < 0.4 then 'beginner'
                                  when accuracy < 0.75 then 'intermediate'
                                  else 'advanced' end as l, count(*) as n
                      from per_child group by 1) t), '[]'::jsonb),
            'chats_per_day', coalesce((
                select jsonb_agg(jsonb_build_object('day', d, 'chats', c, 'typed', n) order by d)
                from (select created_at::date as d, count(distinct chat_id) as c, count(*) as n
                      from msgs where role = 'user' and created_at > now() - interval '30 days'
                      group by 1) t), '[]'::jsonb),
            'typed_per_chat', (
                select jsonb_build_object('chats', count(*), 'average', round(avg(typed), 1),
                                          'median', percentile_cont(0.5) within group (order by typed),
                                          'most', max(typed))
                from per_chat),
            'problem_outcomes', coalesce((
                select jsonb_agg(jsonb_build_object('ended', o, 'problems', n) order by n desc)
                from (select metadata ->> 'outcome' as o, count(*) as n from msgs
                      where role = 'assistant' and metadata ->> 'outcome' is not null
                      group by 1) t), '[]'::jsonb),
            'safety_and_scope_per_day', coalesce((
                select jsonb_agg(jsonb_build_object('day', d, 'safety_blocked', b,
                                                    'scope_declined', s, 'replies', n) order by d)
                from (select created_at::date as d,
                             count(*) filter (where metadata ->> 'mode' = 'safety_blocked') as b,
                             count(*) filter (where metadata ->> 'mode' = 'scope_refused') as s,
                             count(*) as n
                      from msgs where role = 'assistant' and created_at > now() - interval '30 days'
                      group by 1) t), '[]'::jsonb)
        )
    );
end;
$$;

revoke execute on function public.admin_dashboard() from public, anon;
grant execute on function public.admin_dashboard() to authenticated;

-- An unfinished problem in a saved chat (the tutor's state, retrieved
-- chunks, hints shown), so a reopened chat carries on where it stopped.
alter table public.chats add column if not exists episode jsonb;
