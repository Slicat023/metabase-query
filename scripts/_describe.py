"""
_describe.py —— 查表字段（两种方式，默认使用 .env 中的 METABASE_DB_ID）

用法:
  python _describe.py <table_id>              # 走 Metabase 元数据（带字段注释）
  python _describe.py <schema.table> [db_id]  # 直连跑 LIMIT 0 拿真实列（绕过 search 同步问题）

示例:
  python _describe.py 805                     # table_id=805 的字段（含 description）
  python _describe.py public.orders           # 直接拿真实列名

注意: 当 search 搜不到表、但你知道确切 schema.table 时，用第二种方式最可靠
      （它实时打到数据库，搜不到 != 表不存在）。
"""
import sys
import json
from metabase_client import MetabaseClient, DEFAULT_DB_ID


def main():
    if len(sys.argv) < 2:
        print("用法: python _describe.py <table_id | schema.table> [db_id]")
        sys.exit(1)

    arg = sys.argv[1]
    client = MetabaseClient()

    if arg.isdigit():
        # 方式1: table_id -> 元数据 API（带字段注释）
        result = client.get_table_fields(int(arg))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 方式2: schema.table -> 直连 LIMIT 0 拿真实列名
        db_id = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DB_ID
        sql = f"SELECT * FROM {arg} LIMIT 0"
        res = client.run_sql(db_id, sql)
        if res.get("error"):
            print(f"[查字段失败] {res['error']}")
            sys.exit(1)
        out = {"table": arg, "database_id": db_id, "columns": res["columns"]}
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
