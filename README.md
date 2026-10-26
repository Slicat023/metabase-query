# metabase-query

> 一套给 AI Agent（也给人）用的 **Metabase 取数工作流**：四个瘦脚本 + 一份流程规范，把「一句话查数」变成可复现的流水线。

[Metabase](https://www.metabase.com/) 是很好用的 BI 工具，但用它取数时常见三个问题：表太多找不到、口径要反复试、中间产物满地都是。

这个项目把取数拆成**找表 → 查字段 → 探查 → 写 SQL → 自检 → 导出**六段，每段一个命令，**中间步骤全部零落盘**，最终产物只有两个文件：`sql/query/*.sql` 和 `output/*.csv`。

## 特性

- **四个瘦脚本，各管一件事**：找表、查字段、跑 SQL、底层 API（看板/卡片探索）。
- **零落盘探查**：`--sql "SELECT ..."` 内联执行，不写文件、不污染 `output/`。
- **执行前强制自检**：`--probe` 把 SQL 包成 `LIMIT 1` 子查询，先验语法/表名/列名，再跑全量。
- **默认静默**：全量执行只打印 `[OK] 1234 行 -> output/xxx.csv`，适合被 Agent 调用。
- **给 Agent 用**：输出精简、错误信息可读、参数少；配 `docs/workflow.md` 可直接作为 Agent 的常驻规则。
- **无侵入**：只用 Metabase 公开 API（session + `/api/dataset`），不装插件、不改服务端。

## 快速开始

```bash
git clone <this-repo> && cd metabase-query
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，填入站点地址、账号密码
```

第一次用，先确认数据库连接和 `database_id`：

```bash
python scripts/metabase_client.py dbs
```

把常用的那个 `database_id` 写进 `.env` 的 `METABASE_DB_ID`，然后就能一条命令取数：

```bash
# 1) 找表
python scripts/_list_tables.py order

# 2) 查字段（table_id 或 schema.table 两种方式）
python scripts/_describe.py 805
python scripts/_describe.py public.orders

# 3) 探查口径（零落盘，不产生任何文件）
python scripts/_run.py --sql "SELECT MAX(created_at) FROM public.orders"

# 4) 写 SQL 到 sql/query/20260601每日新增付费用户.sql，然后自检
python scripts/_run.py "sql/query/20260601每日新增付费用户.sql" --probe

# 5) 全量执行并导出 CSV
python scripts/_run.py "sql/query/20260601每日新增付费用户.sql"
# → [OK] 128 行 -> output/20260601每日新增付费用户.csv
```

## 命令速查

| 脚本 | 用途 | 示例 |
|---|---|---|
| `scripts/_list_tables.py` | 按关键词找表 | `python scripts/_list_tables.py user` / `... user all` |
| `scripts/_describe.py` | 查字段 | `python scripts/_describe.py 805` / `... public.orders` |
| `scripts/_run.py --sql "..."` | **内联探查（零落盘）** | `python scripts/_run.py --sql "SELECT COUNT(*) FROM public.orders"` |
| `scripts/_run.py <file> --probe` | 语法自检（零落盘） | `python scripts/_run.py sql/query/q.sql --probe` |
| `scripts/_run.py <file>` | 全量执行 + 导出 CSV | `python scripts/_run.py sql/query/q.sql` |
| `scripts/_run.py <file> --preview` | 全量执行 + 打印前 30 行 | `python scripts/_run.py sql/query/q.sql --preview` |
| `scripts/metabase_client.py search/searchall` | 搜看板 / 通用搜索 | `python scripts/metabase_client.py searchall "营收" card` |
| `scripts/metabase_client.py dbs` | 列出数据库连接（拿 database_id） | `python scripts/metabase_client.py dbs` |
| `scripts/metabase_client.py cards/sql/run` | 看板下卡片 / 卡片 SQL / 跑卡片 | `python scripts/metabase_client.py sql 1234` |

> 日常取数优先用前三个瘦脚本；`metabase_client.py` 主要用于看板/卡片探索和兜底参考。

## 目录结构

```
metabase-query/
├── scripts/
│   ├── metabase_client.py     # 底层 API 客户端 + CLI（search / dbs / cards / sql / run / query）
│   ├── _list_tables.py        # 找表
│   ├── _describe.py           # 查字段
│   └── _run.py                # 跑 SQL：内联探查 / 自检 / 全量导出
├── sql/
│   ├── query/                 # 正式查询（产出业务结果，可复用）
│   └── probe/                 # 有长期复用价值的探查 SQL
├── output/                    # 导出的 CSV（UTF-8-BOM，gitignore）
├── docs/
│   ├── workflow.md            # ★ 取数工作流规范（先读这个）
│   └── sql_patterns.md        # SQL 性能自检清单 + PG/Holo JSON 展开写法
├── .env.example               # 连接配置模板
├── .metabase_session          # 登录态缓存（自动生成，gitignore）
└── README.md
```

## 工作流（精简版）

完整规范见 [`docs/workflow.md`](docs/workflow.md)，核心是八步：

1. **理解需求** → 提取指标 / 维度 / 时间范围 / 过滤条件
2. **找表** → `_list_tables.py`，优先生产 schema
3. **查字段** → `_describe.py`，确认列名与类型
4. **探查验证** → `_run.py --sql "..."`，看新鲜度/行数/采样/枚举，**不落盘**
5. **写正式 SQL** → `sql/query/{yyyymmdd}{中文简称}.sql`，顶部注释写清口径
6. **自检** → `--probe` 通过才继续
7. **全量导出** → `output/*.csv`（同名）
8. **兜底** → 原始表搞不定时才看卡片，且只当口径参考

三条硬约束：

- 探索性调用**单轮不超过 4 次**，超了先汇报再继续（避免调用密度过高被判异常）；
- 内联 SQL **只允许 < 150 字符**的简单查询，长 SQL 一律落文件（Windows 命令行长度限制）；
- **零冗余**：中间探查不许产生文件，交付物只有 `sql/query/*.sql` + `output/*.csv`。

## 安全说明

- **不要把账号密码写进代码**。配置只放 `.env`，`.env` 与 `.metabase_session` 都已在 `.gitignore` 中。
- 建议给取数用一个**只读权限的专用账号**；Metabase 侧限制好该账号能访问的数据库。
- `.metabase_session` 里是有效登录 token，泄露等同于账号泄露，不要提交、不要外发。
- 若担心密码登录，可在 Metabase 里创建 **API Key** 并把 `login()` 换成 `Authorization: Bearer <key>`（改动约 3 行）。

## 兼容性

- Metabase v0.40+ 的公开 API（`/api/session`、`/api/search`、`/api/dataset`、`/api/database` 等）；新版/旧版 `dashcards` 与 `ordered_cards` 字段均已兼容。
- 数据源只要是 Metabase 接得上的都能用；`docs/sql_patterns.md` 里的 JSON 展开、时间过滤写法针对 **PostgreSQL / Hologres**，用 MySQL/ClickHouse 时按各自语法调整。
- Python 3.8+，仅依赖 `requests`。

## 为什么不能让 AI 直接乱写 SQL

因为取数错在「口径」上比错在语法上更贵。这个项目的两个关键设计都是为了防口径错：

1. **先探查后落地**：用内联 SQL 把数据新鲜度、行数量级、去重键、枚举值都确认一遍，再写正式 SQL；
2. **原始表优先**：卡片 SQL 里的临时口径和历史过滤条件很难被发现，自己从原始表写反而更可控。

## License

本仓库未附开源许可证（默认保留所有权利）。如需开源，可自行添加 MIT / Apache-2.0。
