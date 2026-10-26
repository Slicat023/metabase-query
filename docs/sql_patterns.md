# SQL 模式与性能自检清单

> 本文是 `docs/workflow.md` 的配套细节页：工作流只留要点，完整写法与检查清单查这里。
> 所有示例都用通用表名（`public.orders` / `public.users`），请替换成你自己的表。

---

## 一、SQL 性能自检（执行前强制）

在跑任何**正式 SQL** 之前（自检 `--probe` 与全量导出都算），先按下面清单过一遍。

### 🔴 严重（必须改完再执行）

1. **全表扫描**：大表（订单、用户、日志、事件流水）必须带 WHERE 过滤；禁止裸 `SELECT *` 扫全表。
2. **缺少 LIMIT**：明细类（非聚合）必须加 `LIMIT 1000`；聚合类（GROUP BY 按天/类目，行数可控）可不加。
3. **笛卡尔积**：多表 JOIN 必须有 ON 关联条件，并确认关联键两边都有值（不是全 NULL）。
4. **大表 NOT IN 子查询**：改用 `NOT EXISTS` 或 `LEFT JOIN ... IS NULL`。

### 🟡 警告（提示，默认继续执行）

5. **WHERE 对字段套函数**：如 `DATE(created_at) = '2026-01-01'` → 改成对原始列做范围过滤（`created_at >= '2026-01-01' AND created_at < '2026-01-02'`），否则用不上分区裁剪/索引。
6. **`LIKE '%xxx%'` 前缀通配**：能确定前缀就用 `'xxx%'`。
7. **隐式类型转换**：超长数字 ID（≥16 位）两侧统一转成字符串再比较；字符串字段比较要加引号。
8. **多层嵌套子查询（>2 层）**：改用 CTE（`WITH ... AS (...)`）。

### 🟢 提示（可选优化）

9. **`COUNT(*)` 只为判存在**：改用 `SELECT 1 ... LIMIT 1`。
10. **`UNION` 可换 `UNION ALL`**：不需要去重时换掉，省一次排序。
11. **分组字段无索引**：确认复合索引是否匹配查询顺序。

### 审查与执行的约定

- **聚合类**（按天/类目统计）：行数可控，自检通过后可直接执行，简短说明结论即可。
- **明细类**：必须有 WHERE + LIMIT；🔴 问题先改再跑。
- 发现 🔴：展示问题 + 优化后 SQL，改完再执行。
- **豁免**：DDL、含 `EXPLAIN`、带 `-- skip-review` 注释的 SQL 不审查。
- 不确定数据量：先跑 `EXPLAIN` 或加 `LIMIT` 试探。

---

## 二、PostgreSQL / Hologres JSON 数组展开（不支持 LATERAL）

很多业务字段是 JSON 数组，例如 `tags` 列存 `[{"id":2,"ts":1700000000000,"v":0}, ...]`。
**Hologres / PG 兼容模式下不支持隐式 LATERAL**，下面三种展开方式按可用性递进：

```sql
-- ✅ 已验证可用：独立 generate_series + JOIN 过滤下标
SELECT t.id, (t.arr->gs.i->>'id')::int AS tag_id, (t.arr->gs.i->>'ts')::bigint AS tag_ts
FROM (
  SELECT id, tags::jsonb AS arr, jsonb_array_length(tags::jsonb) AS arr_len
  FROM public.items
  WHERE created_at >= '2026-01-01'
) t
JOIN generate_series(0, 9999) AS gs(i) ON gs.i < t.arr_len;
```

降级方案（按复杂度递增时选用）：

- **方案 A**：子查询提取 JSON 列后 `jsonb_array_elements(t.arr)`（子查询内若支持）。
- **方案 B**：固定下标遍历 `tags::jsonb->0->>'id'`（数组长度可控时）。
- **方案 C**：只查原始 `tags`，把复杂数组逻辑放到应用层解析（最稳）。

**通用原则**：避免 LATERAL / `WITH ORDINALITY`；JSON 取值优先 `::json->>'key'` 单层访问；
JSONB 包含判断用 `@>`（配合 GIN 索引）；单层 JSON 也可以用 `get_json_object(col, '$.key')`。

---

## 三、常用时间与去重写法

```sql
-- 最新一条（替代 WHERE col = MAX(col) 这种非法写法）
SELECT DISTINCT ON (user_id) user_id, status, updated_at
FROM public.order_events
ORDER BY user_id, updated_at DESC;

-- 取每个实体最新一条的通用写法（跨库可移植）
SELECT user_id, status, updated_at
FROM (
  SELECT user_id, status, updated_at,
         ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY updated_at DESC) AS rn
  FROM public.order_events
) t
WHERE t.rn = 1;

-- 按天聚合，且用半开区间避免对列套函数
SELECT date_trunc('day', created_at) AS d, COUNT(*) AS cnt
FROM public.orders
WHERE created_at >= '2026-01-01' AND created_at < '2026-02-01'
GROUP BY 1 ORDER BY 1;

-- 条件聚合
SELECT user_id,
       COUNT(*) FILTER (WHERE status = 'paid')    AS paid_cnt,
       COUNT(*) FILTER (WHERE status = 'refunded') AS refunded_cnt
FROM public.orders GROUP BY user_id;
```

---

## 四、MySQL / Hive 习惯写法 → PG 改写对照

| 习惯写法（MySQL/Hive） | PostgreSQL / Hologres 写法 |
|---|---|
| `IF(cond, a, b)` | `CASE WHEN cond THEN a ELSE b END` |
| `GROUP_CONCAT(col)` | `string_agg(col::text, ',')` |
| `GET_JSON_OBJECT(col, '$.k')` | `col::json->>'k'`（或 `get_json_object`，视版本） |
| `UNIX_TIMESTAMP()*1000` | `EXTRACT(EPOCH FROM NOW())::bigint * 1000` |
| `MAX(col WHERE cond)` | `MAX(CASE WHEN cond THEN col END)` |
| `COUNT(col WHERE cond)` | `COUNT(*) FILTER (WHERE cond)` |
| `WHERE col = MAX(col)` | `DISTINCT ON (...) ORDER BY col DESC` |

---

## 五、SQL 注释规范

正式 SQL（`sql/query/*.sql`）顶部用注释写清三件事，方便半年后自己看懂：

```sql
-- 业务问题：近 7 天每日新增付费用户数
-- 目标指标：每日 paid_at 去重用户数
-- 关键过滤：status = 'paid'，排除测试账号（is_test = 0）
-- 口径来源：与看板「付费日报」对齐（可选：贴看板链接）
SELECT ...
```
