"""
Metabase API 客户端 —— 搜索看板/卡片、查表与字段元数据、执行 SQL、导出结果。

配置来自环境变量（或项目根目录的 .env 文件，最小实现，无需额外依赖）：
    METABASE_URL       你的 Metabase 站点地址，如 https://metabase.example.com
    METABASE_EMAIL     登录邮箱
    METABASE_PASSWORD  登录密码
    METABASE_DB_ID     默认 database_id（可选，默认 1；用 `python scripts/metabase_client.py dbs` 查）
"""
import os
import sys
import json
import requests
from typing import Optional

# session 缓存放在项目根（scripts/ 的上一级），与脚本位置解耦
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".metabase_session")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")


def _load_env(path: str = ENV_FILE) -> None:
    """最小 .env 加载器：KEY=VALUE，支持 # 注释与引号；已存在的环境变量优先，不覆盖。"""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


_load_env()

METABASE_URL = os.environ.get("METABASE_URL", "").strip().rstrip("/")
METABASE_EMAIL = os.environ.get("METABASE_EMAIL", "").strip()
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD", "").strip()
try:
    DEFAULT_DB_ID = int(os.environ.get("METABASE_DB_ID", "1") or 1)
except ValueError:
    DEFAULT_DB_ID = 1


class MetabaseClient:
    def __init__(self):
        if not METABASE_URL:
            raise SystemExit(
                "[配置缺失] 未设置 METABASE_URL。\n"
                "请复制 .env.example 为 .env 并填写，或导出环境变量：\n"
                "  METABASE_URL=https://metabase.example.com\n"
                "  METABASE_EMAIL=you@example.com\n"
                "  METABASE_PASSWORD=***"
            )
        self.base_url = METABASE_URL.rstrip("/")
        self.session_token = self._load_token()

    def _load_token(self) -> Optional[str]:
        """从本地文件加载已缓存的 session token"""
        if os.path.exists(SESSION_TOKEN_FILE):
            with open(SESSION_TOKEN_FILE, "r") as f:
                token = f.read().strip()
                if token:
                    return token
        return None

    def _save_token(self, token: str):
        """将 session token 缓存到本地文件"""
        with open(SESSION_TOKEN_FILE, "w") as f:
            f.write(token)

    def login(self):
        """通过账号密码获取 session token 并缓存"""
        if not (METABASE_EMAIL and METABASE_PASSWORD):
            raise SystemExit(
                "[配置缺失] 未设置 METABASE_EMAIL / METABASE_PASSWORD。\n"
                "请在 .env 中填写，或改用 API Key：Web 界面 → 右上头像 → 账户设置 → API Keys。\n"
                "（若你的 Metabase 已停用密码登录，可自行改为 Session/API Key 方式）"
            )
        resp = requests.post(
            f"{self.base_url}/api/session",
            json={"username": METABASE_EMAIL, "password": METABASE_PASSWORD},
            timeout=30,
        )
        resp.raise_for_status()
        self.session_token = resp.json()["id"]
        self._save_token(self.session_token)
        return self.session_token

    def _ensure_token(self):
        """确保 token 有效，无效则重新登录"""
        if not self.session_token:
            self.login()
            return
        # 用一个轻量请求验证 token 是否还有效
        resp = requests.get(
            f"{self.base_url}/api/user/current",
            headers={"X-Metabase-Session": self.session_token},
            timeout=10,
        )
        if resp.status_code == 401:
            self.login()

    @property
    def headers(self):
        self._ensure_token()
        return {"X-Metabase-Session": self.session_token}

    def search_dashboard(self, query: str) -> list:
        """按名字模糊搜索看板"""
        resp = requests.get(
            f"{self.base_url}/api/search",
            params={"q": query, "models": "dashboard"},
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # 兼容不同版本返回格式
        items = data if isinstance(data, list) else data.get("data", [])
        return [
            {"id": d["id"], "name": d["name"], "description": d.get("description")}
            for d in items
        ]

    def search(self, query: str, models: Optional[str] = None) -> list:
        """通用搜索：models 可为 card/dashboard/table/database，逗号分隔；为空则搜全部"""
        params = {"q": query}
        if models:
            params["models"] = models
        resp = requests.get(
            f"{self.base_url}/api/search",
            params=params,
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get("data", [])
        return [
            {
                "id": d.get("id"),
                "model": d.get("model"),
                "name": d.get("name"),
                "database_id": d.get("database_id"),
                "table_schema": d.get("table_schema"),
                "description": d.get("description"),
            }
            for d in items
        ]

    def list_databases(self) -> list:
        """列出所有数据库连接"""
        resp = requests.get(
            f"{self.base_url}/api/database",
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        return [
            {"id": d["id"], "name": d.get("name"), "engine": d.get("engine")}
            for d in items
        ]

    def search_tables(self, query: str, database_id: Optional[int] = None) -> list:
        """搜索表（数据表元数据）"""
        results = self.search(query, models="table")
        if database_id is not None:
            results = [r for r in results if r.get("database_id") == database_id]
        return results

    def get_table_fields(self, table_id: int) -> dict:
        """获取某张表的字段元数据"""
        resp = requests.get(
            f"{self.base_url}/api/table/{table_id}/query_metadata",
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        t = resp.json()
        return {
            "id": t.get("id"),
            "name": t.get("name"),
            "schema": t.get("schema"),
            "display_name": t.get("display_name"),
            "description": t.get("description"),
            "fields": [
                {
                    "name": f.get("name"),
                    "base_type": f.get("base_type"),
                    "description": f.get("description"),
                }
                for f in t.get("fields", [])
            ],
        }

    def run_sql(self, database_id: int, sql: str, parameters: Optional[list] = None, max_results: int = 2000) -> dict:
        """通过 /api/dataset 直接执行任意 SQL（由 Metabase 转发给目标数据库执行）

        Args:
            max_results: 最大返回行数，默认 2000。设为更大值可拉取全量数据。
        """
        body = {
            "database": database_id,
            "type": "native",
            "native": {"query": sql},
            "constraints": {"max-results": max_results, "max-results-bare-rows": max_results},
        }
        if parameters:
            body["parameters"] = parameters
        resp = requests.post(
            f"{self.base_url}/api/dataset",
            headers=self.headers,
            json=body,
            timeout=300,
        )
        resp.raise_for_status()
        result = resp.json()
        data = result.get("data", {})
        cols = [c["name"] for c in data.get("cols", [])]
        rows = data.get("rows", [])
        # 捕获 SQL 执行错误
        error = result.get("error") or data.get("error")
        return {
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
            "error": error,
            "status": result.get("status"),
        }

    def get_dashboard_cards(self, dashboard_id: int) -> list:
        """获取看板下所有卡片"""
        resp = requests.get(
            f"{self.base_url}/api/dashboard/{dashboard_id}",
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        dashboard = resp.json()
        cards = []
        # 新版 Metabase 用 dashcards，旧版用 ordered_cards
        dash_cards = dashboard.get("dashcards") or dashboard.get("ordered_cards", [])
        for dc in dash_cards:
            card = dc.get("card", {})
            if card and card.get("id"):
                cards.append({
                    "card_id": card["id"],
                    "name": card.get("name", ""),
                    "display": card.get("display", ""),
                    "query_type": card.get("dataset_query", {}).get("type", ""),
                })
        return cards

    def get_card_detail(self, card_id: int) -> dict:
        """获取卡片详情（含 SQL / MBQL）"""
        resp = requests.get(
            f"{self.base_url}/api/card/{card_id}",
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        card = resp.json()
        dataset_query = card.get("dataset_query", {})
        result = {
            "id": card["id"],
            "name": card.get("name", ""),
            "query_type": dataset_query.get("type", ""),
            "database_id": dataset_query.get("database"),
        }
        if dataset_query.get("type") == "native":
            result["sql"] = dataset_query.get("native", {}).get("query", "")
            result["template_tags"] = dataset_query.get("native", {}).get("template-tags", {})
        else:
            result["mbql"] = dataset_query.get("query", {})
        return result

    def run_card(self, card_id: int, parameters: Optional[list] = None) -> dict:
        """让 Metabase 执行卡片查询，返回结果"""
        body = {}
        if parameters:
            body["parameters"] = parameters
        resp = requests.post(
            f"{self.base_url}/api/card/{card_id}/query/json",
            headers=self.headers,
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def run_card_with_result(self, card_id: int, parameters: Optional[list] = None) -> dict:
        """执行卡片并返回结构化结果（含列名 + 行数据）"""
        body = {}
        if parameters:
            body["parameters"] = parameters
        resp = requests.post(
            f"{self.base_url}/api/card/{card_id}/query",
            headers=self.headers,
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()
        cols = [c["name"] for c in result.get("data", {}).get("cols", [])]
        rows = result.get("data", {}).get("rows", [])
        return {"columns": cols, "rows": rows, "row_count": len(rows)}


def format_as_markdown_table(columns: list, rows: list, max_rows: int = 50) -> str:
    """将结果格式化为 Markdown 表格"""
    if not columns:
        return "（无数据）"
    # 表头
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    # 数据行
    lines = [header, separator]
    for row in rows[:max_rows]:
        line = "| " + " | ".join(str(v) if v is not None else "" for v in row) + " |"
        lines.append(line)
    if len(rows) > max_rows:
        lines.append(f"\n... 共 {len(rows)} 行，仅显示前 {max_rows} 行")
    return "\n".join(lines)


# ============ CLI 入口 ============
def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python metabase_client.py search <关键词>            # 搜看板")
        print("  python metabase_client.py searchall <关键词> [models] # 通用搜索(card/table/dashboard)")
        print("  python metabase_client.py dbs                        # 列出所有数据库")
        print("  python metabase_client.py tables <关键词> [db_id]    # 搜表")
        print("  python metabase_client.py fields <table_id>          # 查表字段")
        print("  python metabase_client.py cards <dashboard_id>       # 看板下卡片")
        print("  python metabase_client.py sql <card_id>              # 卡片SQL")
        print("  python metabase_client.py run <card_id> [param_json] # 跑卡片")
        print("  python metabase_client.py query <db_id> <sql_file>   # 执行SQL文件")
        sys.exit(1)

    client = MetabaseClient()
    cmd = sys.argv[1]

    if cmd == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        results = client.search_dashboard(query)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif cmd == "searchall":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        models = sys.argv[3] if len(sys.argv) > 3 else None
        results = client.search(query, models)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif cmd == "dbs":
        results = client.list_databases()
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif cmd == "tables":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        db_id = int(sys.argv[3]) if len(sys.argv) > 3 else None
        results = client.search_tables(query, db_id)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif cmd == "fields":
        table_id = int(sys.argv[2])
        result = client.get_table_fields(table_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "cards":
        dashboard_id = int(sys.argv[2])
        cards = client.get_dashboard_cards(dashboard_id)
        print(json.dumps(cards, ensure_ascii=False, indent=2))

    elif cmd == "sql":
        card_id = int(sys.argv[2])
        detail = client.get_card_detail(card_id)
        print(json.dumps(detail, ensure_ascii=False, indent=2))

    elif cmd == "run":
        card_id = int(sys.argv[2])
        params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
        result = client.run_card_with_result(card_id, params)
        print(format_as_markdown_table(result["columns"], result["rows"]))
        print(f"\n共 {result['row_count']} 行")

    elif cmd == "query":
        db_id = int(sys.argv[2])
        sql_file = sys.argv[3]
        out_csv = sys.argv[4] if len(sys.argv) > 4 else None
        with open(sql_file, "r", encoding="utf-8") as f:
            sql = f.read()
        result = client.run_sql(db_id, sql)
        if result.get("error"):
            print(f"[SQL 执行错误] {result['error']}")
            sys.exit(1)
        if out_csv:
            import csv
            with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(result["columns"])
                writer.writerows(result["rows"])
            print(f"已导出 {result['row_count']} 行到 {out_csv}")
        else:
            print(format_as_markdown_table(result["columns"], result["rows"]))
            print(f"\n共 {result['row_count']} 行")

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
