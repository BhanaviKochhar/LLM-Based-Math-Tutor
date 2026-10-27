-- TinyThinker admin numbers. Run one query at a time in the Supabase SQL
-- editor (Dashboard -> SQL Editor; select a query and Run, or save each as
-- a snippet). They run as the project owner, so they see every account.
--
-- Totals only: no emails, no child names, no message text, so the results
-- are safe to screenshot. Accounts flagged as test accounts
-- (raw_user_meta_data.test_account = true) are left out everywhere; each
-- query starts from the same "real_students" list for that reason.
--
-- Times are UTC.


-- 1. Usage: totals ----------------------------------------------------------
with real_accounts as (
    select id, created_at from auth.users
    where coalesce((raw_user_meta_data ->> 'test_account')::boolean, false) = false
), real_students as (
    select s.id from public.students s join real_accounts a on a.id = s.parent_account_id
), activity as (
    select c.student_id, m.created_at
    from public.messages m join public.chats c on c.id = m.chat_id
    where m.role = 'user'
)
select
    (select count(*) from real_accounts)                                 as accounts,
    (select count(*) from real_students)                                 as children,
    (select count(distinct a.student_id) from activity a join real_students s on s.id = a.student_id
     where a.created_at > now() - interval '7 days')                     as children_active_last_7_days,
    (select count(distinct a.student_id) from activity a join real_students s on s.id = a.student_id
     where a.created_at > now() - interval '30 days')                    as children_active_last_30_days;


-- 2. Usage: new accounts per week -------------------------------------------
select date_trunc('week', created_at)::date as week_starting, count(*) as new_accounts
from auth.users
where coalesce((raw_user_meta_data ->> 'test_account')::boolean, false) = false
group by 1
order by 1 desc;


-- 3. Usage: active children per day, last 30 days ---------------------------
with real_students as (
    select s.id from public.students s join auth.users u on u.id = s.parent_account_id
    where coalesce((u.raw_user_meta_data ->> 'test_account')::boolean, false) = false
)
select m.created_at::date as day, count(distinct c.student_id) as active_children
from public.messages m
join public.chats c on c.id = m.chat_id
join real_students s on s.id = c.student_id
where m.role = 'user' and m.created_at > now() - interval '30 days'
group by 1
order by 1 desc;


-- 4. Learning: accuracy per class -------------------------------------------
-- By each child's class today; graded answers only (what the level uses).
with real_students as (
    select s.id, s.grade from public.students s join auth.users u on u.id = s.parent_account_id
    where coalesce((u.raw_user_meta_data ->> 'test_account')::boolean, false) = false
)
select s.grade as class,
       count(distinct s.id)                                      as children_with_answers,
       count(*)                                                  as graded_answers,
       round(100.0 * avg(case when a.correct then 1 else 0 end), 1) as percent_correct
from public.attempts a join real_students s on s.id = a.student_id
group by 1
order by 1;


-- 5. Learning: most-missed topics -------------------------------------------
with real_students as (
    select s.id from public.students s join auth.users u on u.id = s.parent_account_id
    where coalesce((u.raw_user_meta_data ->> 'test_account')::boolean, false) = false
)
select a.topic,
       count(*)                                                       as graded_answers,
       count(*) filter (where not a.correct)                          as wrong,
       round(100.0 * count(*) filter (where not a.correct) / count(*), 1) as percent_wrong,
       count(distinct a.student_id)                                   as children
from public.attempts a join real_students s on s.id = a.student_id
group by 1
order by wrong desc, percent_wrong desc
limit 15;


-- 6. Learning: children at each tutor level ---------------------------------
-- The same rule as scripts/llm/student_tracker.classify(): the last 5 graded
-- answers decide; with fewer than 3 there isn't enough to go on yet (the
-- tutor then uses the level set in the app).
with real_students as (
    select s.id from public.students s join auth.users u on u.id = s.parent_account_id
    where coalesce((u.raw_user_meta_data ->> 'test_account')::boolean, false) = false
), recent as (
    select a.student_id, a.correct,
           row_number() over (partition by a.student_id order by a.id desc) as n
    from public.attempts a join real_students s on s.id = a.student_id
), per_child as (
    select s.id, count(r.correct) as answers,
           avg(case when r.correct then 1.0 else 0.0 end) as accuracy
    from real_students s left join recent r on r.student_id = s.id and r.n <= 5
    group by s.id
)
select case when answers < 3 then 'not enough answers yet'
            when accuracy < 0.4 then 'beginner'
            when accuracy < 0.75 then 'intermediate'
            else 'advanced' end as level,
       count(*) as children
from per_child
group by 1
order by 1;


-- 7. Conversations: chats and questions per day, last 30 days ---------------
with real_students as (
    select s.id from public.students s join auth.users u on u.id = s.parent_account_id
    where coalesce((u.raw_user_meta_data ->> 'test_account')::boolean, false) = false
), msgs as (
    select m.created_at::date as day, m.chat_id
    from public.messages m
    join public.chats c on c.id = m.chat_id
    join real_students s on s.id = c.student_id
    where m.role = 'user' and m.created_at > now() - interval '30 days'
)
select day, count(distinct chat_id) as chats_used, count(*) as questions_and_answers_typed
from msgs
group by 1
order by 1 desc;


-- 8. Conversations: messages typed per chat ---------------------------------
with real_students as (
    select s.id from public.students s join auth.users u on u.id = s.parent_account_id
    where coalesce((u.raw_user_meta_data ->> 'test_account')::boolean, false) = false
), per_chat as (
    select c.id, count(m.id) filter (where m.role = 'user') as typed
    from public.chats c
    join real_students s on s.id = c.student_id
    left join public.messages m on m.chat_id = c.id
    group by c.id
)
select count(*)                                                as chats,
       round(avg(typed), 1)                                    as average_typed_per_chat,
       percentile_cont(0.5) within group (order by typed)      as median_typed_per_chat,
       max(typed)                                              as most_in_one_chat
from per_chat;


-- 9. Conversations: how problems ended --------------------------------------
-- solved = the child got it; shown = the answer was revealed; gave_up and
-- moved_on = the child stopped or switched to something else.
with real_students as (
    select s.id from public.students s join auth.users u on u.id = s.parent_account_id
    where coalesce((u.raw_user_meta_data ->> 'test_account')::boolean, false) = false
)
select m.metadata ->> 'outcome' as ended,
       count(*) as problems,
       round(100.0 * count(*) / sum(count(*)) over (), 1) as percent
from public.messages m
join public.chats c on c.id = m.chat_id
join real_students s on s.id = c.student_id
where m.role = 'assistant' and m.metadata ->> 'outcome' is not null
group by 1
order by problems desc;


-- 10. Safety and scope: blocked and declined messages per day, last 30 days -
-- safety_blocked = the child's message was stopped by the safety filter;
-- scope_refused = the question was declined as beyond Class 1-5 maths.
with real_students as (
    select s.id from public.students s join auth.users u on u.id = s.parent_account_id
    where coalesce((u.raw_user_meta_data ->> 'test_account')::boolean, false) = false
)
select m.created_at::date as day,
       count(*) filter (where m.metadata ->> 'mode' = 'safety_blocked') as safety_blocked,
       count(*) filter (where m.metadata ->> 'mode' = 'scope_refused')  as scope_declined,
       count(*)                                                       as tutor_replies
from public.messages m
join public.chats c on c.id = m.chat_id
join real_students s on s.id = c.student_id
where m.role = 'assistant' and m.created_at > now() - interval '30 days'
group by 1
order by 1 desc;
