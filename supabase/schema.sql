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
