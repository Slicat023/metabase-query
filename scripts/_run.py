"""
_run.py —— 执行 SQL（默认使用 .env 中的 METABASE_DB_ID）

三种模式:
  探查(内联，零落盘):  python scripts/_run.py --sql "SELECT ..." [db_id]
         直接执行内联 SQL，精简打印前几行结果，**不写任何文件**。
         用于看表新鲜度/行数/样本/验证口径等中间步骤，避免污染 output/ 与 sql/probe/。

  自检(零落盘):        python scripts/_run.py <sql_file> --probe [db_id]
         把原 SQL 包成子查询加 LIMIT 1，验证语法/表名/列名。
         成功打印 [PROBE OK]，失败打印 [PROBE FAIL] 并 exit 1。

  全量(落 CSV，默认静默): python scripts/_run.py <sql_file> [out_csv] [db_id] [--preview]
         执行原 SQL，结果导出 CSV（默认 output/<sql文件名>.csv，UTF-8-BOM）。
         默认只打印一行摘要 "[OK] N 行 -> 路径"；加 --preview 才打印前30行预览。

示例(cwd = 项目根):
  python scripts/_run.py --sql "SELECT MAX(created_at) FROM public.orders"  # 探查，不落盘
  python scripts/_run.py sql/query/q.sql --probe                            # 自检
  python scripts/_run.py sql/query/q.sql                                    # 全量(静默)
  python scripts/_run.py sql/query/q.sql --preview                          # 全量+预览

约定:
  - 中间探查一律用 --sql 内联，不再往 sql/probe/ 写文件、不落 output/
  - 只有正式查询(sql/query/*.sql)才落 output/*.csv，作为交付物
"""
import os
import sys
import csv
from metabase_client import MetabaseClient, DEFAULT_DB_ID

# 脚本位于 scripts/，项目根为其上一级；output 统一落项目根 output/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
PROBE_PREVIEW = 5    # 内联探查打印的行数
FULL_PREVIEW = 30    # 全量 --preview 打印的行数


def read_sql(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def run_inline(client: MetabaseClient, db_id: int, sql: str):
    """内联探查：执行 SQL，精简打印，绝不落盘。"""
    res = client.run_sql(db_id, strip_trailing_semicolon(sql))
    if res.get("error"):
        print("[SQL FAIL]")
        print(res["error"])
        sys.exit(1)
    print("[列] " + ", ".join(res["columns"]))
    for row in res["rows"][:PROBE_PREVIEW]:
        # 每个单元格截断，避免超长 JSON 刷屏
        cells = [(str(v)[:40] if v is not None else "") for v in row]
        print("  " + " | ".join(cells))
    print(f"[共 {res['row_count']} 行 · 探查未落盘]")


def probe(client: MetabaseClient, db_id: int, sql: str):
    """把原 SQL 包成子查询加 LIMIT 1，做语法/表名/列名自检。"""
    inner = strip_trailing_semicolon(sql)
    probe_sql = f"SELECT * FROM (\n{inner}\n) AS _probe LIMIT 1"
    res = client.run_sql(db_id, probe_sql)
    if res.get("error"):
        print("[PROBE FAIL]")
        print(res["error"])
        sys.exit(1)
    print("[PROBE OK] 列: " + ", ".join(res["columns"]))


def format_md(columns, rows, max_rows=FULL_PREVIEW):
    if not columns:
        return "（无数据）"
    lines = ["| " + " | ".join(str(c) for c in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:max_rows]:
        lines.append("| " + " | ".join(str(v) if v is not None else "" for v in row) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n... 共 {len(rows)} 行，仅显示前 {max_rows} 行")
    return "\n".join(lines)


def run_full(client: MetabaseClient, db_id: int, sql: str, sql_path: str, out_csv: str, preview: bool):
    res = client.run_sql(db_id, strip_trailing_semicolon(sql))
    if res.get("error"):
        print("[RUN FAIL]")
        print(res["error"])
        sys.exit(1)

    # 默认输出路径: output/<sql文件名>.csv
    if not out_csv:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(sql_path))[0]
        out_csv = os.path.join(OUTPUT_DIR, base_name + ".csv")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(res["columns"])
        writer.writerows(res["rows"])

    # 默认静默：只一行摘要；--preview 才打印前若干行
    if preview:
        print(format_md(res["columns"], res["rows"]))
    print(f"[OK] {res['row_count']} 行 -> {out_csv}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    client = MetabaseClient()

    # 模式1: 内联探查 --sql "..."
    if "--sql" in args:
        i = args.index("--sql")
        inline_sql = args[i + 1] if len(args) > i + 1 else ""
        if not inline_sql:
            print("[ERROR] --sql 后需跟 SQL 字符串")
            sys.exit(1)
        rest = [a for j, a in enumerate(args) if j not in (i, i + 1)]
        db_id = int(rest[0]) if rest else DEFAULT_DB_ID
        run_inline(client, db_id, inline_sql)
        return

    # 模式2/3: 文件模式（自检 / 全量）
    sql_path = args[0]
    if not os.path.exists(sql_path):
        print(f"[ERROR] SQL 文件不存在: {sql_path}")
        sys.exit(1)
    sql = read_sql(sql_path)
    flags = {"--probe", "--preview"}
    positional = [a for a in args[1:] if a not in flags]

    if "--probe" in args:
        db_id = int(positional[0]) if positional else DEFAULT_DB_ID
        probe(client, db_id, sql)
    else:
        out_csv = positional[0] if len(positional) > 0 else None
        db_id = int(positional[1]) if len(positional) > 1 else DEFAULT_DB_ID
        run_full(client, db_id, sql, sql_path, out_csv, preview="--preview" in args)


if __name__ == "__main__":
    main()
