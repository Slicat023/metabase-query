"""
_list_tables.py —— 按关键词找表（默认使用 .env 中的 METABASE_DB_ID）

用法:
  python _list_tables.py <关键词> [db_id]
  python _list_tables.py user                # 在默认库找含 user 的表
  python _list_tables.py user all            # 不限库

输出: JSON 数组 [{id, name, schema, database_id, description}]
注意: Metabase search 受同步/排序/上限影响，搜不到 != 表不存在。
      已知确切表名时直接用 _describe.py <schema.table> 验证。
"""
import sys
import json
from metabase_client import MetabaseClient, DEFAULT_DB_ID


def main():
    if len(sys.argv) < 2:
        print("用法: python _list_tables.py <关键词> [db_id|all]")
        sys.exit(1)

    keyword = sys.argv[1]
    db_arg = sys.argv[2] if len(sys.argv) > 2 else str(DEFAULT_DB_ID)
    db_id = None if db_arg == "all" else int(db_arg)

    client = MetabaseClient()
    results = client.search_tables(keyword, db_id)

    slim = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "schema": r.get("table_schema"),
            "database_id": r.get("database_id"),
            "description": r.get("description"),
        }
        for r in results
    ]
    print(json.dumps(slim, ensure_ascii=False, indent=2))
    print(f"\n共 {len(slim)} 张表", file=sys.stderr)


if __name__ == "__main__":
    main()
