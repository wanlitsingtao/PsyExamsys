-- ============================================================================
--  exmsys · 云端 PostgreSQL 巡检 SQL      文件：03_verify.sql
-- ----------------------------------------------------------------------------
--  用途：导入完成后跑一遍；以后线上出问题也先跑这个定位。
--  执行：控制台 SQL Editor -> 【整段一次性】粘贴 -> Run
--
--  ⚠️ 目标 schema：psych_exm（不是 public —— public 被另一个应用占用）。
--     下面第一节的 set search_path 让本文件里的裸表名解析到 psych_exm。
--     因此和 01_schema.sql 一样【必须整段执行】，逐条选中执行会丢失 search_path，
--     后续语句会报 "relation does not exist"（报错，不会静默查错库 —— 这是刻意的）。
--     要换 schema 名：只改下面 set search_path 这一行。
-- ============================================================================

set search_path to psych_exm;


-- ---------------------------------------------------------------------------
-- 1. 各表行数总览。对照本地库的基准值（2026-10-08 快照）：
--      users 6 / user_devices 6 / app_config 1 / user_config 121
--      questions 5118 / case_studies 6 / question_stats 5109 / wrong_questions 23
--      answer_records 18538 / exam_records 142 / mock_exam_records 31
--      study_records 21 / drafts 4
--    注意：上线后 answer_records / question_stats 只增不减，比基准多属正常。
-- ---------------------------------------------------------------------------
select 'users'              as table_name, count(*) from users
union all select 'user_devices',       count(*) from user_devices
union all select 'app_config',         count(*) from app_config
union all select 'user_config',        count(*) from user_config
union all select 'questions',          count(*) from questions
union all select 'case_studies',       count(*) from case_studies
union all select 'question_stats',     count(*) from question_stats
union all select 'wrong_questions',    count(*) from wrong_questions
union all select 'answer_records',     count(*) from answer_records
union all select 'exam_records',       count(*) from exam_records
union all select 'mock_exam_records',  count(*) from mock_exam_records
union all select 'study_records',      count(*) from study_records
union all select 'drafts',             count(*) from drafts
order by table_name;


-- ---------------------------------------------------------------------------
-- 2. 题库分布：3 类题库 / owner 归属。
--    期望 owner_id 全部为 '__public__'，exam_type 为：
--      心理协会咨询师初级 444 / 心理学会咨询师三级 2559 / 心理学会咨询师四级 2115
-- ---------------------------------------------------------------------------
select owner_id, exam_type, count(*) as cnt
  from questions
 group by owner_id, exam_type
 order by owner_id, exam_type;


-- ---------------------------------------------------------------------------
-- 3. 题型分布（含案例题）。案例题期望：三级 2 个案例 / 四级 2 个案例 / 初级 0 个。
-- ---------------------------------------------------------------------------
select exam_type, type, count(*) as cnt
  from questions
 group by exam_type, type
 order by exam_type, type;

-- 案例「个数」（按 case_study_id 归组，与本系统 get_case_group_count() 口径一致）
select exam_type, count(distinct case_study_id) as case_group_count
  from questions
 where type = '案例题' and coalesce(case_study_id, '') <> ''
 group by exam_type;


-- ---------------------------------------------------------------------------
-- 4. 完整性红线 1：主键 / 唯一约束是否生效
--    questions(owner_id, md5) 必须唯一，否则公共题库去重会坏掉。
-- ---------------------------------------------------------------------------
select owner_id, md5, count(*) as cnt
  from questions
 group by owner_id, md5
having count(*) > 1;

select question_id, user_id, count(*) as cnt
  from question_stats
 group by question_id, user_id
having count(*) > 1;


-- ---------------------------------------------------------------------------
-- 5. 完整性红线 2：断链检查（统计 / 错题 指向了不存在的题 = 数据错乱）
--    三条查询都应返回 0 行。
-- ---------------------------------------------------------------------------
select count(*) as orphan_stats
  from question_stats s
  left join questions q on q.id = s.question_id
 where q.id is null and s.question_id is not null;

select count(*) as orphan_wrong
  from wrong_questions w
  left join questions q on q.id = w.question_id
 where q.id is null;

select count(*) as orphan_answer
  from answer_records a
  left join questions q on q.id = a.question_id
 where q.id is null;


-- ---------------------------------------------------------------------------
-- 6. 完整性红线 3：NULL 与空串是否被混淆（导入最容易出的事故）
--    下面这些计数应与本地库一致：case_study_id 空串 5078、user_answer 空串 158、
--    username NULL 4、explanation 空串 111、source_file NULL 99、index_num NULL 37。
-- ---------------------------------------------------------------------------
select
    count(*) filter (where case_study_id = '')  as case_study_id_empty,
    count(*) filter (where case_study_id is null) as case_study_id_null,
    count(*) filter (where explanation = '')   as explanation_empty,
    count(*) filter (where source_file is null) as source_file_null,
    count(*) filter (where index_num is null)  as index_num_null
  from questions;

select
    count(*) filter (where user_answer = '')  as user_answer_empty,
    count(*) filter (where user_answer is null) as user_answer_null
  from answer_records;

select count(*) filter (where username is null) as username_null,
       count(*) filter (where role = 'admin')   as admin_cnt
  from users;


-- ---------------------------------------------------------------------------
-- 7. 自增序列是否已对齐（导入后必须检查！）
--    期望 last_value >= 表内 max(id)，否则应用下一条 INSERT 会主键冲突。
-- ---------------------------------------------------------------------------
select 'answer_records' as t,
       (select max(id) from answer_records) as max_id,
       last_value
  from answer_records_id_seq
union all
select 'exam_records',
       (select max(id) from exam_records), last_value
  from exam_records_id_seq
union all
select 'mock_exam_records',
       (select max(id) from mock_exam_records), last_value
  from mock_exam_records_id_seq;

-- 序列名若与上面不同（Supabase 有时会带后缀），用这条查真实名字：
select sequencename, last_value
  from pg_sequences
 where schemaname = current_schema()
 order by sequencename;


-- ---------------------------------------------------------------------------
-- 8. 安全自检：这些表必须全部 has_rls = true，且没有任何策略。
--    预期 13 行 has_rls = true、policy_count = 0。
-- ---------------------------------------------------------------------------
select c.relname as table_name,
       c.relrowsecurity as has_rls,
       (select count(*) from pg_policies p
         where p.schemaname = current_schema() and p.tablename = c.relname) as policy_count
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = current_schema() and c.relkind = 'r'
   and c.relname in ('users','user_devices','app_config','user_config',
                     'questions','case_studies','question_stats','wrong_questions',
                     'answer_records','exam_records','mock_exam_records',
                     'study_records','drafts')
 order by c.relname;


-- ---------------------------------------------------------------------------
-- 9. 表体积（判断是否接近免费额度）
-- ---------------------------------------------------------------------------
select relname as table_name,
       pg_size_pretty(pg_total_relation_size(c.oid)) as total_size,
       pg_total_relation_size(c.oid) as bytes
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = current_schema() and c.relkind = 'r'
 order by pg_total_relation_size(c.oid) desc;

select pg_size_pretty(pg_database_size(current_database())) as database_size;
