# exmsys 上云迁移包 · 云端 PostgreSQL + Streamlit

把**心理咨询师考试背题系统**从本机 SQLite 迁到**云端 PostgreSQL**，
本机能直接跑、也能部署到 **Streamlit Community Cloud**。

支持三家托管商。**数据库结构、导入脚本、自检脚本完全通用，只有连接串不同**：

| 平台 | 免费额度 | 项目数 | 闲置行为 | 信用卡 |
|---|---|---|---|---|
| Supabase | 500 MB / 项目 | **2 个活跃** | 1 周不活动 → 暂停，**要手动 Restore** | 免 |
| **Neon** ⭐ | **1 GB / 项目** | **100 个** | 5 分钟无活动 → 挂起计算，**下次连接自动唤醒（<1 秒）** | **免，无时间限制，可商用** |
| Aiven | 1 GB，1 CPU / 1 GB RAM 专用单节点 | 1 个 / 服务类型 | 长期闲置 → **关机，要手动开机** | 免 |

> ⚠️ **Supabase 的「2 个项目」限制是跟着人走的** —— 跨你所有 Owner/Admin 的组织**合计**只有 2 个
> 活跃名额，所以「再建一个免费组织」并不能多拿名额。但**已暂停的项目不计入配额**。
>
> 名额不够时有两条路：
> **A. 复用现有实例、用独立 schema 隔离** ← 最省事，见 [2C](#2c-同一实例跑两个应用schema-隔离)；
> **B. 换平台**（Neon 免费版 100 个项目），见 [2B](#2b-备选平台neon--aiven)。

按本文件从第 1 步做到第 6 步，中间不需要写任何代码。

---

## 目录

| 章节 | 内容 |
|---|---|
| [0](#0-这个包里有什么) | 文件清单 |
| [1](#1-总览要做什么) | 总览与时间预估 |
| [2](#2-第-1-步建-supabase-项目) | 建 Supabase 项目 |
| [2B](#2b-备选平台neon--aiven) | **备选平台：Neon / Aiven**（Supabase 名额不够时走这节） |
| [2C](#2c-同一实例跑两个应用schema-隔离) | **同一实例跑两个应用（schema 隔离）** ← 名额不够又不换平台时走这节 |
| [3](#3-第-2-步写配置文件) | 写配置文件（**只写一次，全场景通用**） |
| [4](#4-第-3-步建表) | 建表 |
| [5](#5-第-4-步导入数据) | 导入数据 |
| [6](#6-第-5-步本机验证) | 本机验证并启动 |
| [7](#7-第-6-步部署到-streamlit-cloud) | 部署到 Streamlit Cloud |
| [8](#8-日常运维) | 日常运维 |
| [9](#9-出问题了怎么查) | 排错速查 |
| [10](#10-程序是怎么支持云端的) | 架构说明（程序侧改了什么） |

---

## 0. 这个包里有什么

| 文件 | 作用 | 什么时候用 |
|---|---|---|
| `01_schema.sql` | 建表脚本：`create schema` + 13 张表 + 索引 + 唯一约束 + RLS 安全加固 + 序列对齐 + 自检 | 第 4 步 |
| `02_import_sqlite_to_supabase.py` | 数据搬运 + **逐行校验**（自动按配置的 schema 操作） | 第 5 步 |
| `preflight.py` | 连接与结构自检（配错、schema 没建、表没建、序列没对齐都会在这里被挡住） | 第 6 步 / 随时 |
| `03_verify.sql` | 纯 SQL 巡检（行数/分布/断链/NULL/序列/RLS/体积） | 第 5 步复核、线上排查 |
| `secrets.toml.example` | 配置文件模板（实际位置在 `.streamlit/secrets.toml`），**含 Supabase / Neon / Aiven 三家样例 + schema 项** | 第 3 步 |

> 本包与平台无关：**Supabase / Neon / Aiven 全部通用**，命令一字不差，只有连接串不同
> （见 [2B](#2b-备选平台neon--aiven)）。
> 同一个实例上要跑多个应用时，用 schema 隔离（见 [2C](#2c-同一实例跑两个应用schema-隔离)）。
> ⚠️ 目录名 `deploy/supabase` 和文件名 `02_import_sqlite_to_supabase.py` 是历史命名，
> 别被名字误导 —— 它们跟具体平台无关。

配套的应用侧文件（已在项目里，不用你动）：

| 文件 | 作用 |
|---|---|
| `utils/data_access_pg.py` | PostgreSQL 实现（方言翻译层 + 连接池） |
| `启动Supabase模式.bat` | 双击即启动云端模式（端口 8512） |
| `start.bat` | 启动本机 SQLite 模式（端口 8511），两种模式可同时开 |
| `scripts/test_pg_dialect.py` | 方言翻译 + schema 隔离回归测试（44 项） |
| `scripts/test_cloud_schema_platform.py` | 建库脚本跨平台 + schema 隔离回归测试（24 项） |

---

## 1. 总览：要做什么

```
[第1步] 建数据库项目（Supabase 或 Neon）   3~5 分钟
            ↓  复制连接串（Neon 要拿两条：直连 + 连接池）
[第2步] 写 .streamlit/secrets.toml        1 分钟
            ↓  （复用现有实例时多写一行 schema = "psych_exm"）
[第3步] 跑 01_schema.sql 建表              2 分钟   ← 必须整段一次性执行
            ↓
[第4步] 跑 02_import…py 导数据             2 分钟（含逐行校验）
            ↓
[第5步] 跑 preflight.py 自检                10 秒
       双击 启动Supabase模式.bat            ← 本机就能用了
            ↓
[第6步] 推到 GitHub → Streamlit Cloud 部署（可选）
```

**关键点：每一步都跑到「校验全部通过」才进下一步，不会有半成品状态。**
导入脚本是事务性的（要么全进要么全不进），自检脚本会把问题定位到具体哪一项。

> ⚠️ 迁移期间**先别停本机的 SQLite 模式**。两种模式端口不同、互不干扰，
> 云端跑顺了再停本机。本机库 `data/exmsys.db` 全程只读，不会被迁移动作改动。

---

## 2. 第 1 步：建 Supabase 项目

1. 打开 https://supabase.com/dashboard → `New project`
2. 填：
   - **Name**：`exmsys`
   - **Database Password**：点 `Generate a password` 或自己设一个。
     ⚠️ **用纯字母数字**（别用 `@ : / ? #`）—— 否则写连接串时要 URL 编码，最容易出错。
     **这个密码只显示一次，立刻存到密码管理器或记事本。**
   - **Region**：`Southeast Asia (Singapore)` 或 `Northeast Asia (Tokyo)`
3. 点 `Create new project`，等 1~2 分钟初始化
4. 左侧点 **Connect**（有些界面是 `Project Settings → Database → Connection string`）
5. 复制 **Session pooler** 那一行，形如：

```
postgresql://postgres.abcdefghijklmn:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
```

**必须用 Session pooler，不要用 Direct connection。** 原因：

| 连接方式 | 主机:端口 | 用户名 | 网络 | 用不用 |
|---|---|---|---|---|
| Direct 直连 | `db.<ref>.supabase.co:5432` | `postgres` | **只解析 IPv6** | ❌ 家用宽带连不上 |
| **Session pooler** | `aws-0-<region>.pooler.supabase.com:5432` | **`postgres.<ref>`** | IPv4 | ✅ **用这个** |
| Transaction pooler | `…pooler.supabase.com:6543` | `postgres.<ref>` | IPv4 | ❌ 无状态 serverless 专用 |

> 🔴 **最容易错的一处**：pooler 的用户名是 `postgres.<项目ref>`，**带项目后缀**，
> 不是裸 `postgres`。抄错这里报的是 `password authentication failed`，很容易误判成密码错。

---

## 2B. 备选平台：Neon / Aiven

**什么时候走这节**：Supabase 免费名额（2 个活跃项目）被占满，又不想停掉现有项目。

### 2B.1 为什么推荐 Neon

| | Supabase 免费版 | Neon 免费版 |
|---|---|---|
| 数据库容量 | 500 MB / 项目 | **1 GB / 项目** |
| 项目数 | 2 个活跃（跨组织跟人走） | **100 个** |
| 闲置策略 | 1 周无流量 → 暂停，**要进控制台手动 Restore** | 5 分钟无活动 → 挂起计算，**下次连接自动唤醒（< 1 秒）** |
| 计费 | 免信用卡 / 永久 | 免信用卡 / 永久 / 允许商用 |
| 计算额度 | 共享 CPU、500 MB RAM | 100 CU-小时 / 项目 / 月，最高 2 CU（8 GB RAM） |
| 连接数 | 免费版较紧 | 连接池端点约 100 余条连接可用 |

**唯一的代价**：闲置后第一次查询要多等约 0.5~1 秒（冷启动）。Supabase 是常热的。
对「偶尔有人来答题」的场景，用这点延迟换来「再也不会因为项目数被卡住」，划算。

> 小提醒：Neon 已被 Databricks 收购，官网 pricing 页现在把它叫 **Lakebase Postgres**，
> 但品牌与连接方式仍是 neon.com / 标准 PostgreSQL，看到陌生名字不用慌。

### 2B.2 建 Neon 库（约 3 分钟）

1. 打开 **https://console.neon.tech/signup** → 注册（已有账号则走 **/sign_in**）
   ⚠️ 是 `signup`（无下划线）与 `sign_in`（有下划线），写错会 404，详见 [2B.6](#2b6-控制台打不开怎么办)
2. 填：
   - **Name**：`exmsys`
   - **Postgres version**：默认最新即可
   - **Region**：`AWS ap-southeast-1 (Singapore)` 或 `ap-northeast-1 (Tokyo)`
3. 点 `Create project`，**约 5 秒**就绪（不用等 1~2 分钟）
4. 项目页 **Connection Details** 面板里把 **两条** 连接串都复制下来：

```
应用运行时用这条（带 -pooler，连接池端点）：
postgresql://neondb_owner:你的密码@ep-cool-name-123456-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require

建表 / 导入用这条（不带 -pooler，直连端点）：
postgresql://neondb_owner:你的密码@ep-cool-name-123456.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

### 2B.3 与 Supabase 的四个差异（踩了就卡住）

| # | 差异 | 说明 |
|---|---|---|
| 1 | **必须带 `?sslmode=require`** | Neon 强制 TLS，缺了报 `connection requires SSL`。控制台给的串里已经带了，别手删 |
| 2 | **用户名是随机生成的** | 形如 `neondb_owner`，**不是 `postgres`**。别照抄 Supabase 的习惯 |
| 3 | **库名是 `neondb`** | 不是 `postgres` |
| 4 | **建表 / 导入必须走直连** | 带 `-pooler` 的是 PgBouncer **transaction 模式**：不支持 SET / LISTEN / 临时表 / 会话级锁，`PREPARE` 被直接禁用（`max_prepared_statements=0`）。`01_schema.sql`（DDL）和批量 `COPY` 导入在这上面容易中途失败，而且**报错不会提到连接池**，极难排查 |

所以流程是：**第 3 步（建表）和第 4 步（导入）用直连串，第 5 步之后应用用连接池串。**
两者指向同一个库，只是接入方式不同。

### 2B.4 用 Neon 时的命令差异

只有「传哪条串」不同，其余命令一字不差：

```bash
# 建表：在 Neon 控制台的 SQL Editor 里执行 01_schema.sql（控制台本身即直连）

# 导入：显式传【直连串】（别用 -pooler）
python deploy/supabase/02_import_sqlite_to_supabase.py \
  --dsn "postgresql://neondb_owner:密码@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require" \
  --mode replace

# 自检 / 应用：用【连接池串】（写进 .streamlit/secrets.toml）
python deploy/supabase/preflight.py
```

> 导入脚本会自动识别 Neon 的连接池端点并提醒你换直连串，不用刻意记这条规则。

### 2B.5 Aiven（如果你更想要「专用单节点」）

| | 说明 |
|---|---|
| 免费额度 | 1 GB 存储、1 CPU / 1 GB RAM 的**专用单节点**（不是共享实例） |
| 优点 | 存储翻倍；不与其他租户共享实例 |
| 缺点 | ① **长期闲置会被关机**，要去控制台手动开机（Neon 是自动唤醒）② **端口是服务专属高位端口**（如 12928），不是 5432 ③ **免费版不能选云厂商和区域**，对中国访问延迟不确定 ④ 免费版 1 个服务 / 类型 |

连接串直接从服务 Overview 页的 **Service URI** 复制，端口、用户名（`avnadmin`）、
库名（`defaultdb`）都已经在里面：

```
postgresql://avnadmin:你的密码@pg-xxxx.aivencloud.com:12928/defaultdb?sslmode=require
```

**建表与导入用同一条串即可**（Aiven 免费版是单节点直连，没有 pooler / 直连之分），
但 DSN 必须带 `?sslmode=require`。

### 2B.6 控制台打不开怎么办

**先别急着怀疑被墙。** 实测（2026-10-08）Neon 的各个域名都是通的：

| 目标 | 实测结果 |
|---|---|
| `console.neon.tech` | DNS 正常（Cloudflare），页面 **HTTP 200 / 18 KB**，登录页自包含、不依赖任何外部域名 |
| `*.aws.neon.tech`（数据库端点，新加坡） | DNS 正常，**TCP 5432 连通 0.09 秒** |
| 注册页 `/signup` | 307 → Keycloak 注册页（正常） |

**最常见的两个坑：**

**坑 1：地址写错。** Neon 的注册/登录路径下划线规则是**不一致**的，实测结果：

| 地址 | 结果 |
|---|---|
| `console.neon.tech/signup` | ✅ 307 → 注册页（**无下划线**） |
| `console.neon.tech/sign_in` | ✅ 302 → 登录页（**有下划线**） |
| `console.neon.tech/login` | ✅ 307 → 登录页（等价写法） |
| `console.neon.tech/sign_up` | ❌ **404**（错在这儿） |
| `console.neon.tech/signin` | ❌ **404**（无下划线的写法反而是错的） |

所以正确入口只有这两个：

```
注册：https://console.neon.tech/signup
登录：https://console.neon.tech/sign_in   （或 https://console.neon.tech/login）
```

**坑 2：手动打开了重定向出来的登录 URL。** 如果你看到浏览器地址栏变成
`console.neon.tech/realms/prod-realm/protocol/openid-connect/auth?client_id=...&state=...`，
**这条 URL 不能单独复制出来打开**。它是 OAuth 流程的中间步骤，必须由
`console.neon.tech` 自己跳转过来 —— 手动粘贴打开会因为没有配对的会话 cookie 而白屏或报错
（地址里的 `state` 也是一次性的，几十秒就失效）。
遇到这种情况：**把地址栏清空，重新输入 `https://console.neon.tech/sign_in`** 即可。

**如果上面两条都对，仍然打不开（白屏 / 一直转圈 / 报网络错误）：**

| 步骤 | 做法 | 为什么 |
|---|---|---|
| 1 | 按 `Ctrl+Shift+R` 强制刷新，或开一个**无痕窗口** | 排除缓存与 Cookie 损坏 |
| 2 | 关掉广告拦截 / 隐私保护类扩展 | 它们经常拦掉登录跳转 |
| 3 | 换**手机热点**试一次 | 移动网络到 Cloudflare 往往比家宽更顺；注册只需成功一次 |
| 4 | 把 DNS 改成 `8.8.8.8` / `1.1.1.1` | 排除本地 DNS 污染导致的绕行 |
| 5 | 仍不行 → 走 [Supabase 主线](#2-第-1-步建-supabase-项目) | `supabase.com/dashboard` 实测响应最快（0.47 秒），且本包对它支持最完整 |

> 重要：**控制台打不开 ≠ 数据库连不上。** Neon 的网页走 Cloudflare，
> 而数据库走 AWS 新加坡节点（实测 0.09 秒）。只要能成功注册并建库一次，
> 之后日常答题只走数据库那条线，与控制台无关。

---

## 2C. 同一实例跑两个应用（schema 隔离）

**适用场景**：Supabase 免费版的 2 个项目名额满了，而你手上已经有一个 Supabase 项目，
`public` 架构被**另一个应用**占着。这时不必换平台 —— 一个 Supabase 项目就是一个
PostgreSQL 实例，实例里可以建**多个 schema**，各应用各占一个，互不干扰。

本项目用 **`psych_exm`**（名字可按需改，但要与建表脚本一致）。

```
Supabase 项目（= 一个 PostgreSQL 实例）
├── public      ← 你另一个应用（保持不动）
└── psych_exm   ← 考试系统（本项目，13 张表全在这里）
```

### 2C.1 三个必须知道的事实

| 事实 | 含义 |
|---|---|
| **新 schema 默认不在 `Exposed schemas` 里** | Supabase 的 Data API 默认只暴露 `public` / `graphql_public`，所以 `psych_exm` **根本不会出现在 Data API 上** —— 你另一个应用的 anon key 触不到我们的表。这比「靠 RLS 兜底」硬一个量级。**前提：别把它加进 Exposed schemas。** |
| **建表脚本必须【整段一次性执行】** | 脚本靠内部的 `set search_path` 把裸表名解析到 `psych_exm`。逐条选中执行 = 每条语句独立会话 = `search_path` 丢失 → 表被建到 `public` 里污染另一个应用。脚本已加断言：`search_path` 没生效就**立刻报错中止**，绝不静默建错地方。 |
| **资源是项目级共用的，无法隔离** | 500 MB 存储、**15 个数据库连接**、CPU/内存、备份策略、暂停策略都是整个实例共享的。连接数是最需要留意的：我们的连接池上限默认 **15**，可用 `EXMSYS_DB_POOL_MAX` 调小（见下）。 |

### 2C.2 操作：与本文件其他章节只有 3 处不同

**① 配置文件里多写一行 `schema`**（第 3 步）

```toml
[supabase]
url = "postgresql://postgres.<ref>:<密码>@aws-0-<区域>.pooler.supabase.com:5432/postgres"
schema = "psych_exm"
```

**② 建表脚本整段执行**（第 4 步）

Supabase → SQL Editor → New query → `deploy/supabase/01_schema.sql` **全文粘贴** → `Run`。

> 🔴 **这一步是整条链路最容易出事的地方**：不要用鼠标选中一部分再 Run，必须一次性
> 执行整段。跑完最后那张自检表的 `schema_name` 列**必须显示 `psych_exm`**；
> 如果显示 `public`，说明脚本被拆开执行了 —— 立刻回来整段重跑，
> 并到 `public` 里检查有没有多出来的 13 张表（有的话删掉，别影响你另一个应用）。

**③ 导数据不用改命令**（第 5 步）

导入脚本会自动读配置里的 `schema`，命令与第 5 步完全一致：

```bash
python deploy/supabase/02_import_sqlite_to_supabase.py --dry-run
python deploy/supabase/02_import_sqlite_to_supabase.py --mode replace
```

输出里会明确打印 `目标 schema : psych_exm（独立命名空间，与同实例其他应用隔离）`。
清空确认那一步也会写明「只影响这个 schema，同实例上其他应用的 `public.xxx` 不受影响」。

> 临时覆盖（不想改配置文件时）：加 `--schema psych_exm`。

### 2C.3 连接数怎么分配（重要）

整个实例共 **15 个连接**（Supabase 免费版上限），两个应用共享：

| 值 | 何时用 |
|---|---|
| `EXMSYS_DB_POOL_MAX=4` | 另一个应用连接用得比较多时，给这边压小 |
| `EXMSYS_DB_POOL_MAX=15`（默认） | 另一个应用基本不占连接，或只在这条线上跑考试系统 |

设置方式：写进 `.env`，或在 `启动Supabase模式.bat` 所在终端里 `set EXMSYS_DB_POOL_MAX=4`。
池是**惰性扩容**的（只有真正并发才会占满），所以「上限」不等于「常驻占用」。

### 2C.4 想换 schema 名 / 回到 public

| 目标 | 改哪里 |
|---|---|
| 换 schema 名（如 `exmsys`） | `01_schema.sql` 顶部 **3 处字符串**（`create schema` / `set search_path` / 断言块）+ `03_verify.sql` 第 14 行的 `set search_path` + 配置里的 `schema`。第 1~8 节全部用 `current_schema()` 或裸名，不用改。 |
| 回到 `public` | 配置里删掉 `schema` 那一行（或写 `public`），建表脚本顶部 3 处改回 `public`。改造前的行为完全保留。 |

---

## 3. 第 2 步：写配置文件

**只需要配一处**，应用、批处理、导入脚本、自检脚本全部读它。

```bash
# Windows CMD
copy .streamlit\secrets.toml.example .streamlit\secrets.toml

# Git Bash / PowerShell
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

然后编辑 `.streamlit/secrets.toml`，把第 1 步复制的连接串填进去：

```toml
[supabase]
url = "postgresql://postgres.abcdefghijklmn:你的密码@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"

# 可选：目标 schema。不写 = public（与同实例其他应用共用）。
# 若实例的 public 已被别的应用占用，就填独立名字 —— 本项目用 psych_exm。
# 详见 [2C](#2c-同一实例跑两个应用schema-隔离)。
schema = "psych_exm"
```

> **用 Neon / Aiven 的话**：`secrets.toml.example` 里已经写好三家的样例和注意事项，
> 照着换成对应那一段就行。**key 名固定是 `[supabase]`（历史命名），别改** ——
> 代码按这个名字读配置，Neon / Aiven 也填在这一项里。
>
> ⚠️ Neon 要填**连接池串（带 `-pooler`）**；直连串只在建表和导入时用，不必写进本文件。
> 这两家是独立实例、`public` 没被占，`schema` 一般不写（用默认）。
>
> ⚠️ 写了 `schema = "psych_exm"`，建表脚本也必须是 `psych_exm`，且**整段执行** —— 见 [2C](#2c-同一实例跑两个应用schema-隔离)。

配置来源的完整优先级（想用别的方式也行，**任选一种**）：

1. 环境变量 `EXMSYS_DB_URL` / `SUPABASE_DB_URL` / `DATABASE_URL`
2. Streamlit secrets（云端 Secrets 面板 / 本地 `.streamlit/secrets.toml`）← **推荐**
3. 直接解析 `.streamlit/secrets.toml`（脚本、批处理等非 Streamlit 场合）
4. 项目根目录 `.env`

> schema 走同一套查找顺序，对应键名：环境变量 `EXMSYS_DB_SCHEMA` / `DB_SCHEMA`，
> 或 secrets.toml 里的 `[supabase] schema`。

> `.streamlit/secrets.toml` 和 `.env` 都已在 `.gitignore` 里，**不会被提交到 GitHub**。
> `.streamlit/config.toml` 反过来是需要的，它已从忽略列表里放行。

---

## 4. 第 3 步：建表

1. Supabase 控制台 → 左侧 **SQL Editor** → `New query`
2. 把 `deploy/supabase/01_schema.sql` **全文粘贴**进去
3. 点 `Run`

> 🔴 **必须【整段一次性执行】，不要逐条选中执行。**
> 脚本第一节会 `create schema psych_exm` + `set search_path to psych_exm`，
> 后面 13 张表全部用裸表名。逐条执行时每条语句是独立会话，`search_path` 会丢失，
> 表就被建到 `public` 里去了。脚本自带断言：`search_path` 没生效会**立刻报错中止**，
> 所以你不会在不知情的情况下建错 —— 但看到那个报错，正确反应是**整段重跑**，而不是逐条跑。

> 换 Neon / Aiven 时：**在它自己的 SQL Editor / 控制台里执行**（控制台连接本身就是直连，
> 不需要额外处理）。**别用带 `-pooler` 的连接串去跑这个脚本** —— 见 [2B.3](#2b3-与-supabase-的四个差异踩了就卡住) 第 4 条。
> 那两家是独立实例，脚本里的 schema 名要用它们自己的（默认 `public`，把顶部 3 处改掉）。

脚本是幂等的（`create table if not exists`），**重复执行不会破坏已有数据**，出错可以放心重跑。
脚本内部已经做了平台判断：第 6 节的 `anon / authenticated` 授权回收是 Supabase 专属，
在其他平台会自动跳过（那两个角色不存在，硬执行会报错中断）。

跑完最后会返回一张自检表，**应该是 13 行，每行 `has_rls = t`**，
且 `schema_name` 列**必须等于你配的那个 schema**（本项目是 `psych_exm`）：

| schema_name | table_name | has_rls | pk_count |
|---|---|---|---|
| psych_exm | answer_records | t | 1 |
| psych_exm | …（共 13 行） | t | ≥1 |

> ⚠️ 如果 `schema_name` 显示 `public` 而你要的是 `psych_exm` —— 说明脚本被拆开执行了。
> 请整段重跑，并到 `public` 里检查有没有多出来的 13 张表（有就删掉，
> 别影响同实例上另一个应用）。

### 这个脚本做了四件不能省的事

| 动作 | 为什么 |
|---|---|
| 时间字段全留 `text` 不放 `timestamptz` | 库里存的是 Python 生成的 ISO 字符串，换类型要改代码且会把历史数据搞乱 |
| `is_correct` / `unstable` 等留 `integer` 不放 `boolean` | 代码读写的是 0/1，换 boolean 必须改 SQL |
| **开 RLS 但一条策略都不建** + `revoke all from anon, authenticated`（角色存在才执行） | Supabase 会把 `public` 架构通过 PostgREST 用 anon key 公开。本应用走直连 SQL、自带 `user_id` 隔离，不需要 PostgREST；不加限制的话，任何拿到 anon key 的人都能读写全部题库和用户数据。开 RLS 无策略 = 对 anon 全拒；应用连的 `postgres` 角色是表 Owner，默认绕过 RLS，**读写完全不受影响**。`anon` / `authenticated` 是 Supabase 内置角色，其他平台没有 —— 脚本先查 `pg_roles` 再决定是否 REVOKE，所以 Neon / Aiven 上不会被它中断 |
| **`create schema` + `set search_path` + 断言** | 把 13 张表放进独立命名空间，与同实例其他应用隔离。断言保证「没生效就报错」，绝不静默建到 `public`（详见 [2C](#2c-同一实例跑两个应用schema-隔离)） |

---

## 5. 第 4 步：导入数据

```bash
python deploy/supabase/02_import_sqlite_to_supabase.py --dry-run
```

先体检：只连库、看行数，**不写一个字节**。确认输出里源库和目标表都对得上，再正式导入：

```bash
python deploy/supabase/02_import_sqlite_to_supabase.py --mode replace
```

会先打印「将要清空的表 + 行数」，要手输 `yes` 才继续。

> **目标 schema 会自动读取配置**（`[supabase] schema` / `EXMSYS_DB_SCHEMA`），
> 所以命令里不用带任何额外参数。输出开头会打印
> `目标 schema : psych_exm（独立命名空间，与同实例其他应用隔离）`；
> 若显示为 `public` 且会紧跟一句 ⚠️ 提示，说明你可能没配 `schema` ——
> 先停下核对，别把数据灌进另一个应用的 `public` 里。
> 临时覆盖：`--schema psych_exm`。

> **Neon 用户注意**：这两条命令必须传**直连串（不带 `-pooler`）**。
> 连接池是 transaction 模式，批量 `COPY` 导入容易中途失败。
> 脚本会自动识别并提醒，看到提醒就换串：
>
> ```bash
> python deploy/supabase/02_import_sqlite_to_supabase.py --dry-run \
>   --dsn "postgresql://neondb_owner:密码@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
> ```
>
> Aiven 与 Supabase（Session pooler 5432）直接读配置即可，不用额外传参。

**脚本的安全保证：**

- 对本地 `data/exmsys.db` **全程只读**（只执行 SELECT），不会动本机数据
- 清空目标表前要人工确认（加 `--yes` 可跳过）
- 整体包在**一个事务**里，任何一步失败全部回滚，不留半截数据
- 导入完自动跑**逐行校验**：比条数 → 比主键集合 → 再比**每一个字段的取值**

**预期输出（末尾）：**

```
表名                       SQLite      云端   结果
--------------------------------------------------------------
users                           6         6   OK
questions                    5118      5118   OK
answer_records              18538     18538   OK
...
校验结果：全部一致 ✔
```

任何一行不是 `OK`，**不要继续往下走**，把那段输出发我。

**耗时**：29 126 行 / 10 MB，走公网 Session pooler 约 30~90 秒（含校验）。

### 为什么要用脚本而不是 Navicat

你本机装了 Navicat Premium 15（`D:\Program Files\PremiumSoft\Navicat Premium 15\`），
它能把 PostgreSQL 和 SQLite 互传，所以「连上 Supabase 拖数据」是可行的。
但有三处硬伤，所以**定位是辅助工具**：

| 问题 | 后果 |
|---|---|
| 不能替代建表 | Navicat 自动建表会丢掉 `UNIQUE(owner_id, md5)`（公共题库去重红线）、复合主键、全部索引和 RLS |
| 不处理自增序列 | 搬完应用下一条 INSERT 直接主键冲突 |
| 没有逐行校验 | 只报「成功/失败」，不会说哪一行哪个字段错了 |

**建议用法**：Navicat 连上去**肉眼抽查数据**（连法就是第 1 步那套参数：主机
`aws-0-<区域>.pooler.supabase.com`、端口 `5432`、用户 `postgres.<ref>`、SSL 选 `Require`），
**搬数据仍用脚本**。

> 如果你就是想用 Navicat 搬，也行：务必先在 Supabase 跑完 `01_schema.sql`，
> 传输时**取消勾选「创建表」**，搬完在 SQL Editor 里手动执行 `01_schema.sql`
> 第 7 节的 `setval` 语句把序列推上去，最后跑 `preflight.py` 确认。

---

## 6. 第 5 步：本机验证

### 6.1 先自检

```bash
python deploy/supabase/preflight.py
```

会逐项检查，并在失败的项上给出**具体修复命令**：

```
[ OK ] 连接串已找到：postgresql://postgres.abcdefgh:***@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
[ OK ] 目标 schema：psych_exm（独立命名空间，与同实例其他应用隔离）
[ OK ] psycopg2 已安装（2.9.12）
[ OK ] 连接成功：库=postgres 用户=postgres 当前 schema=psych_exm
[ OK ] 表结构完整（13 张表齐全，位于 schema「psych_exm」）
[ OK ] 唯一索引 uniq_questions_owner_md5 存在
[ OK ] 自增序列已对齐
[ OK ] 数据概览：题目 5118 条 / 答题记录 18538 条 / 用户 6 个
[ OK ] 安全：13 张表均已开启 RLS

自检结论：全部通过，可以启动 Supabase 模式 ✔
```

全 `[ OK ]` 才继续。

### 6.2 启动

**双击项目根目录的 `启动Supabase模式.bat`**（或在终端里运行它）。

它会自动：找 Python → 检查依赖 → 跑一遍自检 → 启动服务。
浏览器打开 **http://localhost:8512** 即可。

批处理的行为约定：

- 配置缺失 → **直接报错退出**，不会悄悄退回本地 SQLite 让你以为连的是云
- 自检不通过 → 打印 `[FAIL]` 具体项并中止启动
- 端口 8512，与本地 SQLite 模式的 8511 分开 → **两个模式可以同时开着对比**

> **Neon 用户**：如果超过 5 分钟没人访问，第一次打开页面会慢约 0.5~1 秒（计算从挂起状态唤醒），
> 之后恢复正常。这是 Neon 的正常行为，不是故障。Aiven 则是被关机后需要去控制台手动开机。

登录后到 **系统设置 → 数据备份**，会看到提示变成
「当前使用的是云端数据库」—— 说明确实跑在云上了。

### 6.3 怎么确认数据真的写进云了

答一道题，然后到云端控制台 → **Table Editor**（Supabase / Neon 都有）→ 打开 `answer_records` 表，
看有没有新行。有 → 数据确实写进云了。

Neon 的话也可以直接在控制台的 **SQL Editor** 里跑：

```sql
select count(*), max(created_at) from answer_records;
```

---

## 7. 第 6 步：部署到 Streamlit Cloud

### 7.1 前置检查清单

| 项 | 状态 | 说明 |
|---|---|---|
| `requirements.txt` | ✅ 已建 | 内容按全项目实际 import 扫描得出：streamlit / pandas / python-docx / psycopg2-binary |
| `.streamlit/config.toml` | ✅ 可提交 | 已从 `.gitignore` 放行（纯配置，不含密码） |
| `.streamlit/secrets.toml` | ✅ 已忽略 | 含密码，绝不进仓库 |
| `.env` | ✅ 已忽略 | 同上 |
| `data/exmsys.db` | ✅ 已忽略 | 云上不再需要本地库文件 |
| Python 版本 | ✅ 3.14.4 | Streamlit Cloud 支持 3.10 ~ 3.14 |

### 7.2 推代码

```bash
git add .
git commit -m "支持 Supabase 云端数据库模式"
git push
```

推之前确认 `.streamlit/secrets.toml` **没有**被加进去：

```bash
git status --short | grep secrets   # 应该没有输出
```

### 7.3 部署

1. 打开 https://share.streamlit.io/ → `New app`
2. 选仓库和分支，主文件填 `app.py`
3. 点 **Advanced settings → Secrets**，把 `.streamlit/secrets.toml` 的内容**原样粘进去**：

```toml
[supabase]
url = "postgresql://postgres.abcdefghijklmn:你的密码@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
```

4. 点 `Deploy`

### 7.4 云上必须注意的两件事

| 事项 | 说明 |
|---|---|
| **必须用 Session pooler** | Streamlit Cloud 出网是 IPv4，直连地址（IPv6-only）连不上 |
| **连接池上限** | 免费版 Session pooler 总连接上限是 **15**。程序已用连接池（默认封顶 **15**，可用 `EXMSYS_DB_POOL_MAX` 调小）+ 空闲探活 + 归还前回滚，正常使用不会打爆。**如果同一实例上还跑着别的应用，这几个连接是两个应用共享的** —— 建议调小到 4~8，见 [2C.3](#2c-同一实例跑两个应用schema-隔离) |

---

## 8. 日常运维

| 场景 | 做法 |
|---|---|
| 改代码 | 推 GitHub → Streamlit Cloud 自动重新部署 |
| 换数据库密码 | 云端控制台重置密码 → 同步改本地 `secrets.toml` 和云端 Secrets |
| **数据备份** | **Supabase**：每日自动备份，免费版保留 7 天。<br>**Neon**：免费版有 1 个手动快照 + 6 小时内的即时恢复；**免费版没有自动定时备份**，重要节点请手动建快照，本地再留一份 `data/exmsys.db`。<br>**Aiven**：免费版**不含自动备份**（Developer 档起才有），需自己导出。<br>系统设置里的「立即备份」按钮在云端模式会提示这一点，不会再假装备份本地文件 |
| **实例被暂停 / 关机** | **Supabase**：闲置 7 天暂停，控制台点 `Restore`。<br>**Neon**：闲置 5 分钟挂起计算，**下次连接自动唤醒，无需干预**。<br>**Aiven**：长期闲置关机，**需去控制台手动开机** |
| 本地继续开发 | 照旧用 `start.bat`（8511 端口，本机 SQLite）。想连云端就用 `启动Supabase模式.bat`（8512 端口） |
| 数据量增长 | 免费额度：Supabase 500 MB / Neon 1 GB / Aiven 1 GB。当前库 **10 MB**，都很宽裕 |
| 连接数 | 应用已用连接池，默认封顶 **15**（可用 `EXMSYS_DB_POOL_MAX` 调小）。**同一实例跑多个应用时，这几个连接是所有应用共享的** —— 建议压到 4~8，别同时开一堆 Navicat / psql 把额度占满 |

---

## 9. 出问题了怎么查

| 现象 | 原因 | 修复 |
|---|---|---|
| `password authentication failed` | 用户名写错，或密码含特殊字符没编码 | Supabase 用户名必须是 `postgres.<ref>`（带后缀）；Neon 是控制台给的随机用户名；Aiven 是 `avnadmin`。密码里 `@`→`%40`、`:`→`%3A`、`/`→`%2F` |
| 连接超时 / 卡住 | Supabase 用了直连地址（IPv6-only），或 Aiven 端口写成了 5432 | Supabase 换 `aws-0-<区域>.pooler.supabase.com:5432`；Aiven 用 Service URI 里的高位端口 |
| `connection requires SSL` | Neon / Aiven 强制 TLS，连接串缺 `sslmode` | 在连接串末尾补 `?sslmode=require` |
| Neon 报 `prepared statement "s0" already exists`、`cached plan must not change result type` | 用连接池串（`-pooler`）跑了建表或大批量导入 | 换**直连串**（去掉 `-pooler`）重跑 |
| Neon 上导入中途失败且报错没提连接池 | 同上（transaction 模式的典型表现） | 同上 |
| Neon 首次访问慢约 0.5~1 秒 | 计算从挂起状态唤醒（冷启动） | 正常现象，无需处理；持续访问期间不会出现 |
| Aiven 连不上 / 被关机 | 免费版长期闲置会关机 | 去控制台把服务开机（`Running`）后重试 |
| `[FAIL] 缺少 N 张表` | 没跑建表脚本，或脚本被逐条执行建到了 public | 整段重跑 `01_schema.sql`；先看自检输出的 `目标 schema` 是不是你配的那个 |
| `[FAIL] 数据库里没有 schema「psych_exm」` | 配置里写了 `schema=psych_exm` 但建表脚本没跑过 | 整段执行 `01_schema.sql`（它自带 `create schema`） |
| 建表时报 `search_path 未生效：当前解析到 schema = public` | 脚本被**逐条选中执行**了 | 这是刻意设计的保护。**整段一次性执行**（全选 → Run），并检查 `public` 里有没有多出的 13 张表，有就删掉 |
| 建表后 `public` 里冒出一堆表 | 同上（逐条执行导致） | 删掉 `public` 里的那 13 张表；然后整段重跑到 `psych_exm` |
| 自检 `current_schema()` 与配置不一致 | 连接池是 transaction 模式，`SET search_path` 没生效 | 确认用的是 Session pooler（`:5432`），不是 `:6543` transaction pooler |
| 导入时提示 `目标 schema : public` 且带 ⚠️ | 没配 `schema`，或配置没读到 | 在 `[supabase]` 下加 `schema = "psych_exm"`，或临时用 `--schema psych_exm` |
| 另一个应用读到了考试系统的表 | `psych_exm` 被加进了 `Exposed schemas` | Supabase → API Settings → Exposed schemas，**移除** `psych_exm`（只保留 public / graphql_public） |
| `[FAIL] 缺少唯一索引` | 建表脚本没跑完 / 被 Navicat 建表覆盖过 | 重新执行 `01_schema.sql` |
| `[FAIL] 自增序列没对齐` | 用 Navicat 或手工导入过，没 setval | 按 preflight 输出的 `setval` 语句在 SQL Editor 执行（注意语句里带 schema 前缀） |
| 应用一写入就 `duplicate key` | 同上 | 同上 |
| `connection pool exhausted` | 连接没归还，或并发太高 | 重启应用；确认没有别的客户端占满免费连接额度 |
| 连接一段时间后第一次操作很慢 | 云数据库掐掉了空闲 TCP，池里在探活 | 正常现象，只影响空闲后第一次 |
| 页面报 `RuntimeError: 云端数据库结构不完整` | 同「缺少 N 张表」 | 同上 |
| 云端部署后连不上 | Secrets 没填 / 填成了直连地址 | Streamlit Cloud → Settings → Secrets 检查 |
| `ModuleNotFoundError: psycopg2` | 云端没装依赖 | 确认 `requirements.txt` 里有 `psycopg2-binary` 并已提交 |

---

## 10. 程序是怎么支持云端的

这一节解释**应用侧改了什么**，出问题时便于定位。

> 本节的实现与托管商无关：方言翻译层只认「PostgreSQL」，不认「Supabase」。
> 换 Neon / Aiven 时应用代码**一行都不用改**，只改连接串。

### 10.1 模式识别

`utils/data_access.py` 新增 `get_db_mode()`，优先级：

1. 环境变量 `EXMSYS_DB_MODE` = `sqlite` / `supabase` → 强制指定
2. **设了 `EXMSYS_DATA_DIR` → 强制 `sqlite`** ← 这是安全阀
3. 能拿到连接串 → `supabase`
4. 兜底 → `sqlite`

> 第 2 条不能删。自动化测试会把 `EXMSYS_DATA_DIR` 指向真实库的临时副本，
> 万一开发机环境里恰好存在 `SUPABASE_DB_URL`，没有这条就会把测试数据写进云上生产库。
> `scripts/_testenv.py` 里另有一道 `EXMSYS_DB_MODE=sqlite` 的双保险。

`get_data_access()` 据此返回 `SQLiteDataAccess` 或 `PostgresDataAccess`。
**页面层一行都没改** —— 这也是当初把 SQL 全部集中在 `SQLiteDataAccess` 里的回报。

### 10.2 为什么不是「另写一套 Postgres SQL」

项目里有 **129 条业务 SQL、109 个 `?` 占位符**。把它们手抄成 Postgres 版的代价是：
一次性抄写风险极高（漏列、错列、错顺序都是**静默数据损坏**），
而且以后每次改功能都要改两处，必然漂移。

所以采用**方言翻译层**：

```
PostgresDataAccess(SQLiteDataAccess)      ← 继承全部业务逻辑，SQL 一个字不改
    只覆盖 5 个与存储引擎相关的方法：
      __init__ / _get_conn / _get_light_conn / _init_db / _assert_schema_ready
    由 PgCursor 在 execute 时把 SQLite 方言翻成 Postgres 方言
```

翻译规则只有 4 条：

| SQLite | Postgres |
|---|---|
| `?` | `%s` |
| `INSERT OR REPLACE INTO t (cols) …` | `INSERT INTO t (cols) … ON CONFLICT (<主键>) DO UPDATE SET c=EXCLUDED.c, …` |
| `INSERT OR IGNORE INTO t …` | `INSERT INTO t … ON CONFLICT DO NOTHING` |
| `PRAGMA …` / `sqlite_master` | 映射到 `information_schema`（`journal_mode` 这类客户端调优语句直接吞掉） |

**唯一需要留意的语义点**：SQLite 的 `INSERT OR REPLACE` 是「先删后插」，
未列出的列会被重置为默认值；Postgres 的 `DO UPDATE` 是「更新」，未列出的列保持原值。
本项目的 8 处 REPLACE **全部列出了该表的全部列**，所以两种语义完全等价 ——
`scripts/test_pg_dialect.py` 里有断言守住这个前提，哪天有人给 upsert 少写一列会立刻失败。

### 10.3 连接池

`PgPool`：`ThreadedConnectionPool(1, 15)`（上限可用 `EXMSYS_DB_POOL_MAX` 调小）
+ 空闲超 60 秒的连接在取出时探活一次（云数据库会掐掉长时间空闲的 TCP），
归还前强制 `rollback`（避免带着未结束事务的连接回到池里）。
按 `(DSN, schema)` 分池 —— 同进程连不同实例/不同 schema 时不会串。

### 10.3.1 目标 schema（同一实例多应用隔离）

`PostgresDataAccess` 支持一个 `schema` 参数（默认 `public`，即改造前行为）：

| 位置 | 做法 |
|---|---|
| 配置读取 | `utils/data_access.py` 的 `detect_pg_schema()`：环境变量 `EXMSYS_DB_SCHEMA` / `DB_SCHEMA` → `st.secrets` → `.streamlit/secrets.toml` 的 `[supabase] schema` → `.env` → 兜底 `public`。名字走 `^[A-Za-z_][A-Za-z0-9_]{0,62}$` 白名单，非法值直接抛错（**不做转义、不尽力猜**） |
| 连接建立 | `PgPool` 在每条物理连接建立后执行一次 `SET search_path TO "<schema>"` —— **只放目标 schema，不放 `public`**。这样表名写错会立刻报错，而不是静默读到 `public` 里另一个应用的同名表 |
| 元数据查询 | `PRAGMA table_info` / `sqlite_master` 两条翻译 SQL 从写死 `'public'` 改为参数化传 schema |
| 启动自检 | `_init_db()` 按配置 schema 查 `information_schema.tables` / `pg_indexes`；schema 不存在时给出「整段执行 01_schema.sql」的明确指引 |

> `SET search_path` 是**会话级**的，所以连接池必须用 Session pooler（`:5432`）——
> `:6543` 的 transaction pooler 不支持会话级 SET，取到连接后 `search_path` 可能已经丢了。
>
> 建表脚本与导入脚本都不依赖这个 SET：建表靠脚本内的 `set search_path`（+ 断言），
> 导入脚本一律用 `"schema"."table"` 全限定名。两者都是**独立会话**，互不依赖。

### 10.4 验证到什么程度

本机没有 Docker 也没有 PostgreSQL，所以**没有做过「连真库跑全流程」的端到端验证**。
已做的验证与其覆盖范围：

| 验证 | 覆盖 | 覆盖不到的 |
|---|---|---|
| `scripts/test_pg_dialect.py` **44 项** | 129 条 SQL 全部可翻译、译文用 postgres 方言解析 0 失败、upsert 语义等价性、`PgRow` 双访问方式、模式识别与安全阀、**schema 配置优先级与白名单、`SET search_path` 不含 public、按 (DSN,schema) 分池、池上限可配置** | 真库上的实际执行 |
| `scripts/test_cloud_schema_platform.py` **24 项** | `01_schema.sql` 的跨平台保护（REVOKE 条件化）+ **schema 隔离约束**（`create schema` / `set search_path` / 断言块 / 0 处 `public.` 前缀 / REVOKE 用 `current_schema()`）；preflight 与导入脚本的 schema 化 | 真库上的实际执行 |
| 导出侧真跑（假游标接 `copy_expert`） | 13 张表 29 126 行往返无损、NULL 与空串不混淆、特殊字符保真 | `COPY` 落到真库 |
| `02_import` 的逐行校验 | — | 首次导入时会在真库上执行 |
| `preflight.py` | 连接、schema 是否存在、表结构、索引、序列、RLS | — |

**剩下的唯一不确定性是「真库上第一次执行」**，而这一步被 `preflight.py` 和
导入脚本的逐行校验夹住了：真有问题会在自检或校验阶段就以明确错误暴露，
不会变成静默的数据损坏。

### 10.5 已知的、刻意没做的事

| 项 | 原因 |
|---|---|
| 应用不自动建表（含不自动建 schema） | Postgres 建表要顺带处理唯一索引、identity 序列、RLS 等配置，散在启动路径里不可审计。集中在 `01_schema.sql` 里，可复核、可幂等重跑 |
| 不走 Supabase REST / Data API | 走直连 SQL 更快、更可控，且不需要处理 RLS 策略；独立 schema 本身也不在 Exposed schemas 里，Data API 根本触不到 |
| schema 名不做转义而直接白名单拒绝 | 转义规则容易漏；白名单只有一条正则，漏不掉，且报错信息能直接指向配置项 |
| 没做连接级重试 | 靠连接池的空闲探活覆盖了最常见的中断场景；再复杂的重试需要引入幂等设计，当前收益不划算 |
