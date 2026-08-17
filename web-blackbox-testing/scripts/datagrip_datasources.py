# -*- coding: utf-8 -*-
"""DataGrip 数据源自动发现与只读查询。

优先复用本机 DataGrip（JetBrains）已配置的数据库连接，无需用户重新提供连接串。
自动发现两个来源：
    1. DataGrip 全局配置：<配置目录>/options/dataSources/*.xml（各版本）
    2. DataGrip 项目级配置：~/DataGripProjects/*/.idea/dataSources.xml
       （连接信息在 dataSources.xml，用户/密钥在 dataSources.local.xml）
       可通过环境变量 DATAGRIP_PROJECTS_DIR 指定其它项目根目录。
支持 MySQL / PostgreSQL / SQLite / SQL Server / Oracle（驱动未装时给出安装提示）。

用法:
    python datagrip_datasources.py list
    python datagrip_datasources.py info <数据源名称>
    python datagrip_datasources.py query <数据源名称> "SELECT ..." [--limit 50] [--json]
    python datagrip_datasources.py tables <数据源名称> [--schema <schema>]

密码来源（按优先级）:
    1. 环境变量 DB_PASSWORD_<名称>（名称转大写，非字母数字用 _）
    2. 本机用户凭据文件 ~/.codex/credentials/databases.yaml（不属于技能，可安全分享技能本体）:
         default_user / default_password: 统一账号密码（默认 sylink / sylink）
         databases:
           生产库: "密码"
           测试库: {user: "root", password: "密码", host: "...", port: 3306}
       可用环境变量 DATAGRIP_CREDENTIALS_FILE 指定其它路径
    3. 技能内 config/databases.yaml（模板，不含真实密码；仅作默认 user 等兜底）
    4. DataGrip XML 中的明文 <password>（新版本多为加密串，自动跳过）
    5. macOS 钥匙串（尽力尝试 DataGrip 条目，失败静默）
    6. 空密码（本地开发库常见）

只读约束: query 仅允许 SELECT / WITH 开头的语句；不提供写操作；密码永不打印。
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def datagrip_roots():
    """返回本机 DataGrip 配置根目录列表（最新版本优先）。"""
    roots = []
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "JetBrains"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", "")) / "JetBrains"
    elif sys.platform.startswith("linux"):
        base = Path.home() / ".config" / "JetBrains"
    else:
        base = None
    if base and base.exists():
        roots = sorted([p for p in base.glob("DataGrip*") if p.is_dir()], reverse=True)
    return roots


def project_roots():
    """返回候选 DataGrip 项目目录（含 .idea/dataSources.xml 的目录），优先环境变量。"""
    candidates = []
    env_dir = os.environ.get("DATAGRIP_PROJECTS_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(Path.home() / "DataGripProjects")
    roots = []
    for base in candidates:
        if not base.exists():
            continue
        for proj in sorted(base.glob("*")):
            if proj.is_dir() and (proj / ".idea" / "dataSources.xml").exists():
                roots.append(proj)
    return roots


def _text(parent, tag):
    node = parent.find(tag)
    return node.text.strip() if node is not None and node.text and node.text.strip() else None


def parse_datasource_xml(path):
    """解析 dataSources/<uuid>.xml 或 db.xml，返回数据源 dict 列表。"""
    out = []
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        print(f"[datagrip] 解析失败 {path}: {exc}", file=sys.stderr)
        return out
    for ds in tree.iter("data-source"):
        name = ds.get("name")
        if not name:
            continue
        user = _text(ds, "user-name")
        jdbc_url = _text(ds, "jdbc-url")
        if not jdbc_url:  # 兼容 <connection url="..."> 形式
            conn = ds.find("connection")
            if conn is not None:
                jdbc_url = conn.get("url")
        driver_ref = _text(ds, "driver-ref") or _text(ds, "jdbc-driver")
        password = _text(ds, "password")
        password_safe = _text(ds, "password-safe")
        out.append({
            "name": name,
            "path": str(path),
            "user": user,
            "jdbc_url": jdbc_url,
            "driver": driver_ref,
            "password": password,
            "password_safe": password_safe,
        })
    return out


def parse_project_datasources(proj_dir):
    """解析项目级数据源：dataSources.xml（连接）+ dataSources.local.xml（用户/密钥）。"""
    index_path = proj_dir / ".idea" / "dataSources.xml"
    local_path = proj_dir / ".idea" / "dataSources.local.xml"
    if not index_path.exists():
        return []
    by_uuid = {}
    try:
        tree = ET.parse(index_path)
    except (ET.ParseError, OSError) as exc:
        print(f"[datagrip] 解析失败 {index_path}: {exc}", file=sys.stderr)
        return []
    for ds in tree.iter("data-source"):
        uuid = ds.get("uuid")
        if not uuid:
            continue
        jdbc_url = _text(ds, "jdbc-url")
        if not jdbc_url:
            conn = ds.find("connection")
            if conn is not None:
                jdbc_url = conn.get("url")
        by_uuid[uuid] = {
            "name": ds.get("name"),
            "path": str(index_path),
            "user": None,
            "jdbc_url": jdbc_url,
            "driver": _text(ds, "driver-ref") or _text(ds, "jdbc-driver"),
            "password": None,
            "password_safe": None,
        }
    if local_path.exists():
        try:
            tree = ET.parse(local_path)
        except (ET.ParseError, OSError) as exc:
            print(f"[datagrip] 解析失败 {local_path}: {exc}", file=sys.stderr)
            tree = None
        if tree is not None:
            for ds in tree.iter("data-source"):
                entry = by_uuid.get(ds.get("uuid"))
                if entry is None:
                    continue
                entry["user"] = _text(ds, "user-name")
                if _text(ds, "password"):
                    entry["password"] = _text(ds, "password")
                if _text(ds, "password-safe"):
                    entry["password_safe"] = _text(ds, "password-safe")
                elif _text(ds, "secret-storage"):
                    entry["password_safe"] = _text(ds, "secret-storage")
    return [v for v in by_uuid.values() if v["name"]]


def discover_datasources():
    """扫描全局 + 项目级数据源，返回 {名称: 数据源信息}（同名不覆盖，全局优先）。"""
    sources = {}
    for root in datagrip_roots():
        ds_dir = root / "options" / "dataSources"
        files = sorted(ds_dir.glob("*.xml")) if ds_dir.exists() else []
        legacy = root / "options" / "db.xml"
        if legacy.exists():
            files.append(legacy)
        for path in files:
            for info in parse_datasource_xml(path):
                if info["name"] and info["name"] not in sources:
                    sources[info["name"]] = info
    for proj in project_roots():
        for info in parse_project_datasources(proj):
            if info["name"] and info["name"] not in sources:
                sources[info["name"]] = info
    return sources


def parse_jdbc(url):
    """把 JDBC URL 解析为 (driver, host, port, database, extra)。"""
    if not url:
        return None
    if url.startswith("jdbc:sqlite:"):
        return ("sqlite", None, None, url[len("jdbc:sqlite:"):], {})
    m = re.match(r"jdbc:(mysql|postgresql|sqlserver|oracle):", url)
    if not m:
        return None
    driver = m.group(1)
    if driver in ("mysql", "postgresql"):
        rest = url[m.end():]
        m2 = re.match(r"//([^:/?#]+)(?::(\d+))?/([^?]*)", rest)
        if not m2:
            return None
        host, port, db = m2.group(1), int(m2.group(2) or 0), m2.group(3)
        return (driver, host, port or None, db or None, {})
    if driver == "sqlserver":
        m2 = re.match(r"//([^:;]+)(?::(\d+))?", url[m.end():])
        host, port = (m2.group(1), int(m2.group(2) or 0)) if m2 else (None, None)
        db = None
        mdb = re.search(r";databaseName=([^;]+)", url)
        if mdb:
            db = mdb.group(1)
        return (driver, host, port or None, db, {})
    if driver == "oracle":
        m2 = re.match(r"thin:@//([^:/]+)(?::(\d+))?/(\S+)", url[m.end():])
        if m2:
            return ("oracle", m2.group(1), int(m2.group(2) or 0) or None, m2.group(3), {})
        m3 = re.match(r"thin:@([^:]+):(\d+):(\S+)", url[m.end():])
        if m3:
            return ("oracle", m3.group(1), int(m3.group(2)), m3.group(3), {})
    return (driver, None, None, None, {})


def _read_yaml_file(path):
    """读取单个 YAML 文件，依赖 PyYAML；缺失/不可解析时返回空 dict。"""
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        print(f"[datagrip] 警告：{path} 存在但未安装 PyYAML，跳过", file=sys.stderr)
        return {}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base, override):
    """递归合并 dict；override 中 None 值不覆盖。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_password_config():
    """合并凭据配置：本机用户凭据（~/.codex/credentials/databases.yaml）优先，技能内模板兜底。"""
    skill_cfg = _read_yaml_file(Path(__file__).resolve().parent / "config" / "databases.yaml")
    creds_path = Path(os.environ.get("DATAGRIP_CREDENTIALS_FILE", str(Path.home() / ".codex" / "credentials" / "databases.yaml")))
    creds = _read_yaml_file(creds_path)
    return _deep_merge(skill_cfg, creds)


def resolve_password(name, info, config):
    """按优先级取密码；永不打印。"""
    env_key = re.sub(r"[^A-Za-z0-9]+", "_", name).upper()
    env_val = os.environ.get(f"DB_PASSWORD_{env_key}")
    if env_val:
        return env_val
    databases = (config.get("databases") or {}) if isinstance(config, dict) else {}
    cfg = databases.get(name)
    if isinstance(cfg, str) and cfg:
        return cfg
    if isinstance(cfg, dict) and cfg.get("password"):
        return str(cfg["password"])
    if info.get("password") and not re.match(r"^[A-Za-z0-9+/=]{32,}$", info["password"] or ""):
        return info["password"]  # 兼容老版本明文
    default_pw = config.get("default_password") if isinstance(config, dict) else None
    if default_pw:
        return str(default_pw)
    if sys.platform == "darwin":
        for account in (name, f"{name}|{info.get('user') or ''}", info.get("user") or ""):
            if not account:
                continue
            try:
                res = subprocess.run(
                    ["security", "find-generic-password", "-s", "DataGrip", "-a", account, "-w"],
                    capture_output=True, text=True, timeout=5,
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass
    return ""


def _connect(info, password):
    parsed = parse_jdbc(info["jdbc_url"])
    if not parsed:
        raise SystemExit(f"无法解析 JDBC URL：{info['jdbc_url']}")
    driver, host, port, db, _ = parsed
    user = info.get("user")

    if driver == "sqlite":
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn, "sqlite"
    if driver == "mysql":
        try:
            import pymysql
        except ImportError:
            raise SystemExit("需要 pymysql 驱动：pip install pymysql")
        conn = pymysql.connect(
            host=host, port=port or 3306, user=user, password=password,
            database=db, charset="utf8mb4", connect_timeout=10, cursorclass=pymysql.cursors.DictCursor,
        )
        return conn, "mysql"
    if driver == "postgresql":
        try:
            import psycopg2
        except ImportError:
            try:
                import psycopg
                conn = psycopg.connect(host=host, port=port or 5432, user=user, password=password, dbname=db, connect_timeout=10)
                return conn, "postgresql"
            except ImportError:
                raise SystemExit("需要 psycopg2 或 psycopg 驱动：pip install psycopg2-binary")
        conn = psycopg2.connect(host=host, port=port or 5432, user=user, password=password, dbname=db, connect_timeout=10)
        return conn, "postgresql"
    if driver == "sqlserver":
        try:
            import pyodbc
        except ImportError:
            raise SystemExit("需要 pyodbc 驱动：pip install pyodbc（并安装 ODBC Driver for SQL Server）")
        conn_str = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={host},{port or 1433};DATABASE={db};UID={user};PWD={password};Encrypt=no"
        conn = pyodbc.connect(conn_str, timeout=10)
        return conn, "sqlserver"
    if driver == "oracle":
        try:
            import oracledb
        except ImportError:
            raise SystemExit("需要 oracledb 驱动：pip install oracledb")
        dsn = oracledb.makedsn(host, port or 1521, service_name=db)
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        return conn, "oracle"
    raise SystemExit(f"暂不支持的数据库类型：{driver}")


def _assert_readonly(sql):
    stripped = sql.strip().lstrip("(").lstrip()
    if not re.match(r"(?is)^(select|with)\b", stripped):
        raise SystemExit("仅允许只读查询（SELECT / WITH 开头），拒绝执行：" + sql[:80])


def _run_query(conn, driver, sql, limit):
    _assert_readonly(sql)
    sql = sql.rstrip().rstrip(";")
    if limit:
        if driver == "sqlserver":
            sql = re.sub(r"(?is)^(select\b)", r"SELECT TOP %d " % limit, sql, count=1)
        elif driver == "oracle":
            sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= {limit}"
        else:
            sql = f"SELECT * FROM ({sql}) AS _q LIMIT {limit}"
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(limit or 50)
        return cols, rows
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _print_rows(cols, rows, as_json):
    if as_json:
        normalized = []
        for row in rows:
            row = [row.get(c) for c in cols] if isinstance(row, dict) else list(row)
            normalized.append(dict(zip(cols, row)))
        print(json.dumps(normalized, ensure_ascii=False, indent=2, default=str))
        return
    if not cols:
        print("(无返回列)")
        return
    header = " | ".join(str(c) for c in cols)
    print(header)
    print("-" * len(header))
    for row in rows:
        row = [row.get(c) for c in cols] if isinstance(row, dict) else row
        print(" | ".join("" if v is None else str(v) for v in row))
    print(f"({len(rows)} 行)")


def _resolve_source(sources, name):
    exact = sources.get(name)
    if exact:
        return exact
    matches = [v for k, v in sources.items() if name.lower() in k.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SystemExit(f"名称“{name}”匹配到多个数据源：{', '.join(v['name'] for v in matches)}，请用全名")
    raise SystemExit(f"未找到数据源“{name}”。可用：{', '.join(sources) or '（无，请先在 DataGrip 配置连接）'}")


def cmd_list(sources):
    if not sources:
        print("未发现 DataGrip 数据源。")
        print("请确认：1) 本机安装 DataGrip 并配置过数据库连接；2) 配置目录：")
        for root in datagrip_roots():
            print("   " + str(root / "options" / "dataSources"))
        raise SystemExit(1)
    print(f"{'数据源名称':<24} {'类型':<12} {'地址':<40} {'用户':<12} 密码")
    print("-" * 100)
    for info in sources.values():
        parsed = parse_jdbc(info["jdbc_url"])
        addr = ""
        if parsed:
            driver, host, port, db, _ = parsed
            addr = f"{host or '本地'}:{port or ''}/{db or ''}" if driver != "sqlite" else str(db)
        pw_state = "xml明文" if info.get("password") else ("钥匙串/密钥" if info.get("password_safe") else "待提供")
        print(f"{info['name']:<24} {(info['driver'] or parsed[0] if parsed else '?')[:12]:<12} {addr:<40} {(info.get('user') or ''):<12} {pw_state}")


def cmd_info(sources, name):
    info = _resolve_source(sources, name)
    print(f"名称: {info['name']}")
    print(f"JDBC: {info['jdbc_url']}")
    print(f"用户: {info.get('user') or '（未配置）'}")
    print(f"驱动: {info.get('driver') or '（未配置）'}")
    print(f"密码: {'XML 明文' if info.get('password') else ('钥匙串/密钥引用 (' + info['password_safe'] + ')' if info.get('password_safe') else '待通过环境变量/配置提供')}")
    print(f"来源: {info['path']}")


def cmd_query(sources, name, sql, limit, as_json):
    _assert_readonly(sql)
    info = _resolve_source(sources, name)
    config = load_password_config()
    if not info.get("user") and isinstance(config, dict):
        info = dict(info)
        info["user"] = config.get("default_user")
    password = resolve_password(info["name"], info, config)
    try:
        conn, driver = _connect(info, password)
    except Exception as exc:
        raise SystemExit(
            f"连接数据库“{info['name']}”失败：{type(exc).__name__}: {exc}\n"
            "可能原因：主机不可达 / DNS 无法解析 / 端口不通 / 账号密码错误。"
        ) from exc
    try:
        cols, rows = _run_query(conn, driver, sql, limit)
        _print_rows(cols, rows, as_json)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def cmd_tables(sources, name, schema):
    info = _resolve_source(sources, name)
    config = load_password_config()
    if not info.get("user") and isinstance(config, dict):
        info = dict(info)
        info["user"] = config.get("default_user")
    password = resolve_password(info["name"], info, config)
    try:
        conn, driver = _connect(info, password)
    except Exception as exc:
        raise SystemExit(
            f"连接数据库“{info['name']}”失败：{type(exc).__name__}: {exc}\n"
            "可能原因：主机不可达 / DNS 无法解析 / 端口不通 / 账号密码错误。"
        ) from exc
    try:
        if driver == "sqlite":
            sql = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        elif driver == "mysql":
            sql = "SHOW TABLES"
        else:
            schema_sql = f" AND table_schema = '{schema}'" if schema else ""
            sql = f"SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'{schema_sql} ORDER BY table_name"
        cur = conn.cursor()
        cur.execute(sql)
        for row in cur.fetchall():
            first = next(iter(row.values())) if isinstance(row, dict) else row[0]
            print(first)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="DataGrip 数据源自动发现与只读查询")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出所有数据源")
    p_info = sub.add_parser("info", help="查看数据源详情")
    p_info.add_argument("name")
    p_query = sub.add_parser("query", help="只读查询（仅 SELECT/WITH）")
    p_query.add_argument("name")
    p_query.add_argument("sql")
    p_query.add_argument("--limit", type=int, default=50)
    p_query.add_argument("--json", action="store_true")
    p_tables = sub.add_parser("tables", help="列出表")
    p_tables.add_argument("name")
    p_tables.add_argument("--schema")

    args = parser.parse_args()
    sources = discover_datasources()
    if args.cmd == "list":
        cmd_list(sources)
    elif args.cmd == "info":
        cmd_info(sources, args.name)
    elif args.cmd == "query":
        cmd_query(sources, args.name, args.sql, args.limit, args.json)
    elif args.cmd == "tables":
        cmd_tables(sources, args.name, args.schema)


if __name__ == "__main__":
    main()
