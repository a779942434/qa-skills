#!/usr/bin/env python3
"""build_arun.py — 把紧凑步骤清单拼装成 ARun 完整步骤 JSON。

用法：
    python build_arun.py steps.json -o arun_script.json
    python build_arun.py steps.yaml --compact          # 有 pyyaml 时也支持 YAML
    python build_arun.py steps.json                    # 默认输出到桌面 ~/Desktop/<步骤名>_arun.json
    python build_arun.py steps.json -o -               # 输出到 stdout
    python build_arun.py - -o arun_script.json         # 从 stdin 读取步骤清单

步骤清单是 JSON 数组，每个元素有三种：
1. 纯脚本步骤：{"name": "...", "script": "<python>", "ignore": false}
2. 接口步骤：{
       "name": "...",
       "desc": "...",                # 可选
       "method": "POST",             # 可选，默认 POST
       "url": "/linkim-pc/...",
       "body": {...},                # data.body.json 内容；整值透传时写 "$var"
       "setup_code": "...",          # 可选，脚本自动加首行注释
       "teardown_code": "...",       # 可选，脚本自动加首行注释
       "project": 13,                # 可选，覆盖默认 project
       "json2text": true,            # 可选，写入 data.json2text（整值透传）
       "ignore": false               # 可选
   }
3. 控制流步骤：{"controller": "for"|"if", "steps": [...], 其余控制器字段原样保留}
   - for：mode / times / interval / break_on_success / continue_on_failure / close
   - if：condition / elif_branches / else_steps / elseClose / ignore / close
   - 嵌套 steps 同样支持脚本 / 接口 / 控制流步骤（可递归）

脚本会自动补齐 sample 里的全部默认字段（dubbo/params/headers 等），
省略平台自增字段，并校验 body 与 url 里的 $var 是否由前序步骤产生。
"""

import argparse
import copy
import json
import pathlib
import re
import sys

try:
    import yaml
except ImportError:
    yaml = None


DUBBO = {
    "interface": {"interface": "", "method": "", "host": "", "port": ""},
    "registry_center": {
        "protocol": 1,
        "group": "",
        "username": "",
        "password": "",
        "address": "118.31.126.238:21811",
        "timeout": 3,
    },
}

EMPTY_ARRAY_ITEM = {"checked": True, "key": "", "value": ""}
FORM_DATA_ITEM = {
    "checked": True,
    "key": "",
    "value": "",
    "file_path": "",
    "file_type": "",
}

API_STEP_TOP = {
    "name": "",
    "desc": "",
    "module": [],
    "open_api_name": "",
    "method": "POST",
    "locked": False,
    "project": 13,
    "only_self": False,
    "lockor": 0,
    "url": "",
    "origin": 1,
    "api_type": 1,
    "is_active": True,
    "weight": None,
    "tag": [],
    "status": 1,
    "inputVisible": False,
    "inputValue": "",
}

API_STEP_DATA = {
    "swagger_body_properties": {},
    "dubbo": copy.deepcopy(DUBBO),
    "openApiName": "",
    "apiType": 1,
    "weight": None,
    "setup_code": "# python 请求之前执行",
    "teardown_code": "# python 请求之后执行",
    "body_type": "json",
    "loop": True,
    "ssl": False,
    "delay": 0,
    "skip": None,
    "skipIf": None,
    "skipUnless": None,
    "cycles": 1,
    "jsonschema": {},
    "jsonschemaOpen": True,
    "jsonschemaUpdate": False,
    "url": "",
    "method": "POST",
    "verify": False,
    "body": {
        "none": None,
        "form_data": [copy.deepcopy(FORM_DATA_ITEM)],
        "form_urlencoded": [copy.deepcopy(EMPTY_ARRAY_ITEM)],
        "json": {},
    },
    "Parameterizes": {"pdata": {}, "checked": False},
    "params": [copy.deepcopy(EMPTY_ARRAY_ITEM)],
    "headers": [copy.deepcopy(EMPTY_ARRAY_ITEM)],
    "retrying": [copy.deepcopy(EMPTY_ARRAY_ITEM)],
    "variables": [copy.deepcopy(EMPTY_ARRAY_ITEM)],
    "extract": [copy.deepcopy(EMPTY_ARRAY_ITEM)],
    "check": [
        {
            "checked": True,
            "type": "value",
            "value": "",
            "method": "",
            "value1": "",
        }
    ],
    "hook": {"setUpHooks": [""], "tearDownHooks": [""]},
}

SET_VAR_RE = re.compile(r"(?:arun|ARun)\.set\(\s*['\"]([^'\"]+)['\"]")
BODY_VAR_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def find_set_vars(code):
    return set(SET_VAR_RE.findall(code or ""))


def find_body_vars(value):
    found = set()
    if isinstance(value, str):
        found |= set(BODY_VAR_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= find_body_vars(v)
    elif isinstance(value, list):
        for v in value:
            found |= find_body_vars(v)
    return found


def build_api_step(spec):
    name = spec.get("name", "")
    method = str(spec.get("method", "POST")).upper()
    url = spec.get("url", "")
    if not name or not url:
        raise ValueError("接口步骤必须有 name 和 url")

    step = copy.deepcopy(API_STEP_TOP)
    data = copy.deepcopy(API_STEP_DATA)
    step.update(
        {
            "name": name,
            "desc": spec.get("desc", ""),
            "method": method,
            "url": url,
        }
    )
    # 可选覆盖：project（默认 13）、ignore
    if "project" in spec:
        step["project"] = spec["project"]
    if "ignore" in spec:
        step["ignore"] = spec["ignore"]
    data.update(
        {
            "url": url,
            "method": method,
        }
    )
    data["body"]["json"] = copy.deepcopy(spec.get("body", {}))

    # 整值透传：data.json2text（顶层 json2text 或 data.json2text 均可）
    json2text = spec.get("json2text")
    if json2text is None and isinstance(spec.get("data"), dict):
        json2text = spec["data"].get("json2text")
    if json2text:
        data["json2text"] = True

    if spec.get("setup_code"):
        data["setup_code"] = (
            "# python 请求之前执行\n" + spec["setup_code"].rstrip("\n")
        )
    if spec.get("teardown_code"):
        data["teardown_code"] = (
            "# python 请求之后执行\n" + spec["teardown_code"].rstrip("\n")
        )

    step["data"] = data
    return step


def build_script_step(spec):
    if not spec.get("script"):
        raise ValueError("脚本步骤必须有 script")
    step = {"script": spec["script"], "name": spec.get("name", "脚本步骤")}
    if "ignore" in spec:
        step["ignore"] = spec["ignore"]
    return step


def build_controller_step(spec):
    controller = spec.get("controller")
    if controller not in ("for", "if", "while"):
        raise ValueError(f"未知 controller: {controller}")
    step = {"controller": controller}
    for key, value in spec.items():
        if key in ("controller", "steps", "elif_branches", "else_steps"):
            continue
        step[key] = copy.deepcopy(value)
    step["steps"] = build_steps(spec.get("steps", []))
    elif_branches = []
    for br in spec.get("elif_branches", []):
        branch = copy.deepcopy(br) if isinstance(br, dict) else br
        if isinstance(branch, dict) and "steps" in branch:
            branch["steps"] = build_steps(branch["steps"])
        elif_branches.append(branch)
    step["elif_branches"] = elif_branches
    step["else_steps"] = build_steps(spec.get("else_steps", []))
    return step


def build_steps(specs):
    steps = []
    for spec in specs:
        if "controller" in spec:
            steps.append(build_controller_step(spec))
        elif "script" in spec:
            steps.append(build_script_step(spec))
        else:
            steps.append(build_api_step(spec))
    return steps


def validate_vars(specs):
    known = set()
    problems = []

    def walk(specs):
        nonlocal known, problems
        for i, spec in enumerate(specs):
            label = spec.get("name", f"步骤{i + 1}")
            if "controller" in spec:
                walk(spec.get("steps", []))
                for br in spec.get("elif_branches", []):
                    if isinstance(br, dict):
                        walk(br.get("steps", []))
                walk(spec.get("else_steps", []))
                continue
            if "script" in spec:
                known |= find_set_vars(spec.get("script"))
                continue
            known |= find_set_vars(spec.get("setup_code"))
            needed = find_body_vars(spec.get("body", {}))
            needed |= find_body_vars(spec.get("url", ""))
            missing = sorted(needed - known)
            if missing:
                problems.append((label, missing))
            known |= find_set_vars(spec.get("teardown_code"))

    walk(specs)
    return problems


def load_spec(path):
    if path == "-":
        text = sys.stdin.read()
        data = json.loads(text)
    else:
        text = open(path, "r", encoding="utf-8").read()
        if path.endswith((".yaml", ".yml")) and yaml is not None:
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("步骤清单必须是 JSON 数组")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", help="步骤清单 JSON/YAML 文件路径")
    parser.add_argument("-o", "--output", help="输出 JSON 文件路径；缺省输出到 stdout")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="输出紧凑 JSON（省体积），默认 pretty",
    )
    args = parser.parse_args(argv)

    specs = load_spec(args.spec)
    steps = build_steps(specs)

    problems = validate_vars(specs)
    if problems:
        print("警告：以下 $var 找不到来源（可能由平台/环境变量提供）:", file=sys.stderr)
        for label, missing in problems:
            print(f"  - {label}: {', '.join('$' + v for v in missing)}", file=sys.stderr)

    text = json.dumps(steps, ensure_ascii=False, indent=None if args.compact else 2)
    json.loads(text)  # 最后兜底校验

    if args.output:
        output_path = args.output
    else:
        stem = "arun_script" if args.spec == "-" else pathlib.Path(args.spec).stem
        output_path = str(pathlib.Path.home() / "Desktop" / f"{stem}_arun.json")

    if output_path == "-":
        sys.stdout.write(text + "\n")
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(
            f"生成成功：{len(steps)} 个步骤 -> {output_path}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
