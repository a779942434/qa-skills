# -*- coding: utf-8 -*-
"""加载 ones-create-linked-defect 配置。

优先级（高 -> 低）：
1. 环境变量（ONES_CDP_PORT / ONES_URL / ONES_EDGE_EXE /
   ONES_EDGE_SESSION / ONES_EDGE_USER_DATA / ONES_LOGS_DIR / ONES_BUG_REPORTS_DIR）
2. config/settings.yaml + config/field-mapping.yaml
3. 平台自动探测默认值（Windows / macOS）

PyYAML 缺失时回退到内置默认值，不抛错（字段映射中项目特有信息会退化为空，
届时以 SKILL.md 内置示例为准）。
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

try:
    import yaml
except ImportError:  # pragma: no cover - 仅当目标环境未装 PyYAML
    yaml = None

DEFAULT_SETTINGS = {
    "cdp_port": 9334,
    "ones_url": "https://ones.shuyilink.com",
    "edge": {
        "executable": "",
        "session_dir": "",
        "user_data_source": "",
        "headless": True,
    },
    "logs_dir": "",
    "bug_reports_dir": "",
}

DEFAULT_FIELD_MAPPING = {
    "priority": "P2",
    "assignee": "",
    "handler": "施锦涛",
    "source_project": {"keyword": "可挺", "name": "宁波可挺-1期|KH0094-01"},
    "system_env": {"keyword": "可挺", "name": "t-keting-可挺集成测试（客户侧）"},
    "function_modules": ["计划管理", "APS模块（自动排产）"],
    "evidence_dirs": {},
}

ENV_OVERRIDES = {
    "ONES_CDP_PORT": ("cdp_port", int),
    "ONES_URL": ("ones_url", str),
    "ONES_EDGE_EXE": ("edge.executable", str),
    "ONES_EDGE_SESSION": ("edge.session_dir", str),
    "ONES_EDGE_USER_DATA": ("edge.user_data_source", str),
    "ONES_LOGS_DIR": ("logs_dir", str),
    "ONES_BUG_REPORTS_DIR": ("bug_reports_dir", str),
}


def _deep_merge(base, override):
    """递归合并 dict，override 中 None 值不覆盖。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_yaml(name, default):
    if yaml is None:
        print(f"[ones_config] 警告：PyYAML 未安装，{name} 未生效，使用内置默认值", file=sys.stderr)
        return default
    path = CONFIG_DIR / name
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return _deep_merge(default, data)


def load_settings():
    """读取 settings.yaml + 环境变量覆盖（未做平台默认填充）。"""
    settings = _read_yaml("settings.yaml", DEFAULT_SETTINGS)
    for env_name, (key_path, cast) in ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        keys = key_path.split(".")
        target = settings
        for k in keys[:-1]:
            target = target.setdefault(k, {})
        target[keys[-1]] = cast(raw)
    return settings


def load_field_mapping():
    """读取 field-mapping.yaml（已与内置默认合并）。"""
    return _read_yaml("field-mapping.yaml", DEFAULT_FIELD_MAPPING)


def default_edge_executable():
    if sys.platform.startswith("win"):
        candidates = (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        )
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]
    if sys.platform == "darwin":
        return "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    return ""


def default_user_data_source():
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return str(Path(base) / "Microsoft" / "Edge" / "User Data")
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / "Microsoft Edge")
    return ""


def resolve_settings():
    """返回已填充平台默认值的最终设置（供脚本使用）。"""
    settings = load_settings()
    edge = dict(settings.get("edge", {}))
    if not edge.get("executable"):
        edge["executable"] = default_edge_executable()
    if not edge.get("user_data_source"):
        edge["user_data_source"] = default_user_data_source()
    if not edge.get("session_dir"):
        edge["session_dir"] = str(Path.home() / ".codex" / "tmp" / "edge-ones-session")
    settings["edge"] = edge
    if not settings.get("logs_dir"):
        settings["logs_dir"] = str(Path(edge["session_dir"]) / "logs")
    if not settings.get("bug_reports_dir"):
        settings["bug_reports_dir"] = str(PROJECT_ROOT / "bug-reports")
    return settings


if __name__ == "__main__":
    import json

    print(json.dumps(resolve_settings(), ensure_ascii=False, indent=2))
