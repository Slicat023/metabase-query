# 取数工作流规范（Workflow）

> 本文把「一句话取数」固化成可复现的流程。核心思想：**脚本瘦、流程硬、交付物只有两个文件。**
> 目标是让 AI Agent（或你自己）在 Metabase 上取数时，每次都能走同一条路，不产出一地中间垃圾。

---

## 1. 设计目标

| 痛点 | 传统做法 | 本流程的做法 |
|---|---|---|
| 不知道表在哪 | 手动翻 Metabase 界面 | `_list_tables.py` 关键词搜表 → `_describe.py` 查字段 |
| 口径反复试错 | 写长 SQL 反复跑，报错就改 | 先用 `--sql` 内联探查（零落盘），确认口径再落地 |
| 中间产物满地 | 每次探查都存一个 csv/sql 文件 | 中间步骤一律内联，**只有正式结果才落盘** |
| 脚本一大坨 | 一个脚本几百行、什么都干 | 三个瘦脚本各管一件事（找表 / 查字段 / 跑 SQL） |
| 结果没法复用 | 只存在终端里 | `sql/query/*.sql` + `output/*.csv` 同名成对保存 |

---

## 2. 主流程（8 步）

```
1. 理解需求
   └─ 提取关键实体（指标 + 维度 + 时间范围 + 过滤条件）

2. 找表
   └─ python scripts/_list_tables.py "<关键词>"
      · 优先 public / 生产 schema，避开 test_* / tmp_* / 备份 schema
      · 搜不到 ≠ 表不存在，已知确切表名直接跳到第 3 步

3. 查字段
   └─ python scripts/_describe.py <table_id>          # 走元数据，带字段注释
      python scripts/_describe.py schema.table         # 直连 LIMIT 0 拿真实列

3.5 探查与验证口径（零落盘）
   └─ python scripts/_run.py --sql "SELECT ..."
      · 确认数据新鲜度：SELECT MAX(created_at) FROM t
      · 确认行数量级、采样几行
      · 验证去重键、枚举值、NULL 比例
      · 这一步不写任何文件

4. 写正式 SQL
   └─ 落到 sql/query/{yyyymmdd}{中文简称}.sql
      · 顶部注释写清：业务问题 / 目标指标 / 关键过滤 / 口径来源
      · 按 docs/sql_patterns.md 的性能清单自检一遍

4.5 性能自检（强制）
   └─ 🔴 严重问题（全表扫描、缺 LIMIT、笛卡尔积）先改再跑
      🟡 警告 简述后继续

5. 语法自检（零落盘）
   └─ python scripts/_run.py sql/query/xxx.sql --probe
      · 把 SQL 包成子查询加 LIMIT 1，验证语法/表名/列名
      · 失败就自己看报错改 SQL，改到 [PROBE OK]

6. 全量执行 + 导出
   └─ python scripts/_run.py sql/query/xxx.sql
      · 默认静默，只打印一行 [OK] N 行 -> output/xxx.csv
      · 要看数据加 --preview（打印前 30 行）

7. 交付
   └─ 回复：口径说明 + 结果摘要 + 一句话结论
      · 告知 SQL 路径 与 CSV 路径

8. 兜底：只有原始表搞不定时，才查看板卡片
   └─ python scripts/metabase_client.py searchall "<关键词>" card
      python scripts/metabase_client.py sql <card_id>
      · 卡片只当「口径参考」，拿到逻辑后回到原始表重写
```

---

## 3. 三条量化约束（都是踩过坑换来的）

### 3.1 探索性调用：单轮不超过 4 次

连续调 `_list_tables` / `_describe` / `--sql` 探索时，**一轮对话内不超过 4 次**。超了就：

1. 先汇报当前已找到的候选表和中间结论；
2. 等确认方向后再继续深挖。

**批量技巧**（减少调用次数）：

- 一次用宽泛关键词覆盖（搜 `order` 而不是分别搜 `order_paid`、`order_refund`）；
- 需要查多张表字段时，写个临时脚本批量调 `describe`，一次执行拿回全部结果；
- 已知表名时直接 `_describe schema.table`，跳过「找表」。

> 真实教训：早期连续 7 次探索性调用，密度过高触发平台的循环检测被拦截——明明每次都成功，却被判成异常。

### 3.2 内联 SQL：只允许短查询

Windows 的 CMD/PowerShell 对单行命令长度有限制，长 SQL 会断行、转义异常、被截断。

- **允许内联**：SQL 总长 < 150 字符，且单表简单查询。
- **必须写文件**：满足任一条就落文件再执行——SQL > 150 字符、含 UNION / 子查询 / 多表 JOIN / GROUP BY 多字段、含中文字符串或单引号嵌套。
- **失败不重试同策略**：内联执行出现截断/回显异常/超时，立即切成文件执行，不做第二次内联尝试。

### 3.3 零冗余原则

最终交付物只有两类：**`sql/query/*.sql`** 和 **`output/*.csv`**。其余都是噪音：

- 中间探查零落盘（全部 `--sql` 内联）；
- 终端零冗余：全量跑默认静默，只有 `[OK] N 行 -> 路径`；
- 临时落了探查文件 → 任务结束前删掉，保持 `output/` 只有正式结果；
- `sql/probe/` 只保留**有长期复用价值**的验证 SQL，一次性探查不要往里塞。

---

## 4. 文件命名规则

SQL 和 CSV **同名**（`_run.py` 默认用 SQL 文件名输出 CSV），格式：`{yyyymmdd}{中文简称}`。

- 日期取**生成当天**；
- 中文简称从需求里提炼，控制在 10 个汉字内、一眼能看懂；
- 不用 `query_xxx` 英文长名。

| 需求 | 文件名 |
|---|---|
| 每日新增付费用户数 | `20260601每日新增付费用户` |
| 各品类近 30 天 GMV 排名 | `20260601品类GMV排名` |
| 渠道转化漏斗 | `20260601渠道转化漏斗` |

❌ 不要：`query_daily_new_paid_user_count`、`query_category_gmv_ranking_last_30_days`

---

## 5. 原始表优先，卡片兜底

接到取数需求，**优先用原始表自己写 SQL**，只有原始表确实搞不定才退去看板卡片。

理由：

- 原始表口径干净、可控，自己写比复用别人的卡片更可靠；
- 卡片 SQL 常带临时口径、模板变量、历史遗留过滤条件，不一定符合当前需求；
- 直接基于原始表能避免「沿用错误口径」。

> Metabase 的 `search` 受同步状态、相关度排序、结果上限影响，**搜不到 ≠ 表不存在**。
> 拿到确切表名时，直接 `SELECT * FROM schema.table LIMIT 1` 验证存在性，别据 search 结果下结论。

---

## 6. 目录约定

```
<项目根>/                      ← 所有命令都在这里执行
├── scripts/
│   ├── metabase_client.py     # 底层 API 客户端（看板/卡片探索、CLI 入口）
│   ├── _list_tables.py        # 找表
│   ├── _describe.py           # 查字段
│   └── _run.py                # 跑 SQL（内联探查 / 自检 / 全量导出）
├── sql/
│   ├── query/                 # 正式查询（产出业务结果，可复用）
│   └── probe/                 # 有长期价值的探查 SQL（一次性探查不要放这里）
├── output/                    # 导出的 CSV（UTF-8-BOM）
├── docs/                      # 本文档 + SQL 模式参考
├── .env                       # 连接配置（gitignore）
└── .metabase_session          # 登录态缓存（自动生成，gitignore）
```

要点：

- 脚本统一放 `scripts/`，运行时 **cwd 固定为项目根**，命令写 `python scripts/xxx.py`；
- `.metabase_session` 与 `output/` 都落在项目根，与脚本位置解耦（脚本用 `__file__` 上一级定位项目根）。

---

## 7. 查询环境的关键信息怎么找

第一次接入一个新 Metabase，按顺序确认三件事：

```bash
# 1) 站点地址、登录账号密码 → 写进 .env
cp .env.example .env && vi .env

# 2) 有哪些数据库连接（拿到 database_id）
python scripts/metabase_client.py dbs

# 3) 把常用的 database_id 写进 .env 的 METABASE_DB_ID，后续所有脚本默认用它
```

---

## 8. 性能与语法

执行前按 `docs/sql_patterns.md` 的清单自检：全表扫描、缺 LIMIT、笛卡尔积、WHERE 套函数、隐式类型转换、多层子查询。
PostgreSQL / Hologres 的 JSON 数组展开写法也在那份文档里（不支持 LATERAL 的替代方案）。

---

## 9. 三个容易踩的细节

1. **当天数据通常不完整**：当日分区往往还在写入，做趋势分析时把当天剔除，或明确标注「数据截至 X 点」。
2. **超长数字 ID 一律当字符串**：19 位雪花 ID 用数值比较会精度截断（≥16 位就危险），关联前两边都 `CAST(... AS TEXT)`。
3. **中文文件写入别用 PowerShell 的 `Set-Content`**：在 Windows 上会按 GBK 回写、把 UTF-8 中文写成乱码。用编辑器/脚本写，或显式指定 UTF-8。

---

## 10. 怎么把这套流程交给 AI Agent

本仓库的脚本设计成「给 Agent 用」的形状：输出精简、错误清晰、参数少。要让 Agent 稳定执行，建议把你的团队约定写成一份常驻规则（System Prompt / Skill / Rules 文件），内容包括：

- 上面这 8 步流程；
- 命名规则和零冗余原则；
- 「中间探查不许落盘」这条硬约束；
- 执行正式 SQL 前必须先自检。

Agent 拿到这套规则后，用户只需求说「帮我查一下近 7 天各渠道付费用户数」，剩下的找表、探查、自检、导出可以全自动完成。

---

## 11. 建议自建一份「表口径参考」文档

随着取数次数增加，下面三类知识会被反复用到，值得单独沉淀成 `docs/table_logic_reference.md`（不入库也行，放本地）：

1. **表名陷阱**：视图名和物理表名不一致、同名表分属不同 schema；
2. **列名陷阱**：保留字需要引号（如 `time`、`order`）、同义列（`user_id` / `uid` / `member_id`）、JSON 内嵌字段；
3. **枚举与状态**：状态码含义、有效/无效的判定、`act_type` 这类「取消 vs 贴标」的陷阱。

写清这三类之后，新来的同学（或 AI）查表速度会明显变快，也不容易沿用错口径。
