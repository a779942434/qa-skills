# ARun 步骤模板

## 一、纯脚本步骤

```json
{
  "script": "# python 脚本\nbase_dict=ARun.meta_data.get_env_base_test_data()",
  "name": "通用数据获取"
}
```

## 二、接口步骤（完整字段，省略平台自增/审计字段）

下例为完整接口步骤结构。`__PLACEHOLDER__` 处按接口文档与业务流替换；平台自增/审计字段已省略。

```json
{
  "name": "__步骤名称__",
  "desc": "__步骤描述__",
  "module": [],
  "open_api_name": "",
  "method": "POST",
  "locked": false,
  "project": 13,
  "only_self": false,
  "lockor": 0,
  "url": "__接口路径__",
  "origin": 1,
  "api_type": 1,
  "is_active": true,
  "weight": null,
  "tag": [],
  "status": 1,
  "inputVisible": false,
  "inputValue": "",
  "data": {
    "swagger_body_properties": {},
    "dubbo": {
      "interface": {
        "interface": "",
        "method": "",
        "host": "",
        "port": ""
      },
      "registry_center": {
        "protocol": 1,
        "group": "",
        "username": "",
        "password": "",
        "address": "118.31.126.238:21811",
        "timeout": 3
      }
    },
    "openApiName": "",
    "apiType": 1,
    "weight": null,
    "setup_code": "# python 请求之前执行",
    "teardown_code": "# python 请求之后执行",
    "body_type": "json",
    "loop": true,
    "ssl": false,
    "delay": 0,
    "skip": null,
    "skipIf": null,
    "skipUnless": null,
    "cycles": 1,
    "jsonschema": {},
    "jsonschemaOpen": true,
    "jsonschemaUpdate": false,
    "url": "__接口路径__",
    "method": "POST",
    "verify": false,
    "body": {
      "none": null,
      "form_data": [
        {
          "checked": true,
          "key": "",
          "value": "",
          "file_path": "",
          "file_type": ""
        }
      ],
      "form_urlencoded": [
        {
          "checked": true,
          "key": "",
          "value": ""
        }
      ],
      "json": {}
    },
    "Parameterizes": {
      "pdata": {},
      "checked": false
    },
    "params": [
      {
        "checked": true,
        "key": "",
        "value": ""
      }
    ],
    "headers": [
      {
        "checked": true,
        "key": "",
        "value": ""
      }
    ],
    "retrying": [
      {
        "checked": true,
        "key": "",
        "value": ""
      }
    ],
    "variables": [
      {
        "checked": true,
        "key": "",
        "value": ""
      }
    ],
    "extract": [
      {
        "checked": true,
        "key": "",
        "value": ""
      }
    ],
    "check": [
      {
        "checked": true,
        "type": "value",
        "value": "",
        "method": "",
        "value1": ""
      }
    ],
    "hook": {
      "setUpHooks": [
        ""
      ],
      "tearDownHooks": [
        ""
      ]
    }
  }
}
```

## 三、默认值速查

| 字段 | 默认值 |
| --- | --- |
| `api_type` / `apiType` | `1` |
| `project` | `13` |
| `origin` | `1` |
| `body_type` | `"json"` |
| `method` | Swagger 提供值，缺省 `POST` |
| `loop` | `true` |
| `ssl` | `false` |
| `delay` | `0` |
| `cycles` | `1` |
| `verify` | `false` |
| `jsonschemaOpen` | `true` |
| `jsonschemaUpdate` | `false` |
| `dubbo.registry_center.address` | `118.31.126.238:21811` |
| `dubbo.registry_center.protocol` | `1` |
| `dubbo.registry_center.timeout` | `3` |

## 四、代码段约定

- `setup_code` 首行：`# python 请求之前执行`
- `teardown_code` 首行：`# python 请求之后执行`
- 提取：`res.json()['data']...` + `arun.set(...)`
- 断言：`assert 条件, '中文失败提示'`
