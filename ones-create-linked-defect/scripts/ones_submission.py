# -*- coding: utf-8 -*-
"""ONES 提交的持久化账本与证据图片校验。

设计目标（2026-11-13 复盘后固化）：
1. **两阶段**：Phase A 只负责建单/关联/附件，先返回单号；Phase B 再把截图
   补进描述。Phase B 失败不能回滚或阻塞 Phase A。
2. **幂等**：同一 parent + bug_key + 标题生成稳定 submission_key，重试前先查账本，
   已有 task_uuid 就复用，绝不重复建单。
3. **可恢复**：每个缺陷独立记录状态，进程中断后可从 created/attached 继续。
4. **渲染态校验**：不以 `<img>` 节点数或接口 200 判成功，必须校验
   src 不是 data: 占位、HTTP 可访问、浏览器 naturalWidth > 0。

本模块不直接依赖 Playwright（除了 verify_image_urls 接收 page），便于单测。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

LEDGER_VERSION = 1

# 状态只增不减；Phase A 完成到 attached，Phase B 完成到 inline_ok/verified。
STATE_CREATED = "created"          # add3 已创建，尚未关联
STATE_LINKED = "linked"            # 已关联主工单
STATE_ATTACHED = "attached"        # 附件已核验
STATE_INLINE_PENDING = "inline_pending"
STATE_INLINE_OK = "inline_ok"
STATE_VERIFIED = "verified"
STATE_FAILED = "failed"

PHASE_A_DONE = {STATE_ATTACHED, STATE_INLINE_PENDING, STATE_INLINE_OK, STATE_VERIFIED}

_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
_SRC_RE = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_UUID_RE = re.compile(r"""\bdata-uuid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_FILENAME_RE = re.compile(r"""(?:data-)?filename\s*=\s*["']?([^"'&>\s]+)""", re.IGNORECASE)
_ALT_RE = re.compile(r"""\balt\s*=\s*["']([^"']*)["']""", re.IGNORECASE)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def normalize_title(title: str) -> str:
    """标题归一化：去首尾空白与重复空格，用于幂等键和重复检测。"""
    return re.sub(r"\s+", " ", str(title or "")).strip()


def submission_key(parent_task_uuid: str, bug_key: str, title: str) -> str:
    """稳定幂等键；重试、换进程、换机器都不应改变。"""
    raw = "|".join([
        str(parent_task_uuid or "").strip(),
        str(bug_key or "").strip().upper(),
        normalize_title(title),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class SubmissionLedger:
    """一个主工单对应一个 JSON 账本；每次状态变更原子落盘。"""

    def __init__(self, path: Path, parent_task_uuid: str):
        self.path = Path(path).expanduser()
        self.parent_task_uuid = str(parent_task_uuid or "")
        self.data: Dict[str, Any] = {
            "version": LEDGER_VERSION,
            "parent_task_uuid": self.parent_task_uuid,
            "created_at": _now(),
            "updated_at": _now(),
            "defects": {},
        }
        self.load()

    def load(self) -> "SubmissionLedger":
        if not self.path.exists():
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"提交账本无法解析: {self.path}: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("defects"), dict):
            raise RuntimeError(f"提交账本格式不合法: {self.path}")
        parent = raw.get("parent_task_uuid")
        if parent and parent != self.parent_task_uuid:
            raise RuntimeError(
                f"提交账本属于另一主工单: {self.path} 记录={parent} 当前={self.parent_task_uuid}"
            )
        self.data = raw
        self.data.setdefault("version", LEDGER_VERSION)
        self.data["parent_task_uuid"] = self.parent_task_uuid
        return self

    def save(self) -> None:
        self.data["updated_at"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, self.path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass

    def get(self, bug_key: str) -> Optional[Dict[str, Any]]:
        return (self.data.get("defects") or {}).get(str(bug_key))

    def find_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        wanted = normalize_title(title)
        for rec in (self.data.get("defects") or {}).values():
            if normalize_title(rec.get("title", "")) == wanted:
                return rec
        return None

    def find_by_task_uuid(self, task_uuid: str) -> Optional[Dict[str, Any]]:
        for rec in (self.data.get("defects") or {}).values():
            if rec.get("task_uuid") == task_uuid:
                return rec
        return None

    def upsert(self, bug_key: str, title: str, **fields: Any) -> Dict[str, Any]:
        defects = self.data.setdefault("defects", {})
        rec = dict(defects.get(str(bug_key)) or {})
        rec.setdefault("bug_key", str(bug_key))
        rec["title"] = normalize_title(title)
        rec["submission_key"] = submission_key(self.parent_task_uuid, bug_key, title)
        rec["updated_at"] = _now()
        rec.update({k: v for k, v in fields.items() if v is not None})
        defects[str(bug_key)] = rec
        return rec

    def mark(self, bug_key: str, state: str, **fields: Any) -> Dict[str, Any]:
        rec = self.upsert(bug_key, (self.get(bug_key) or {}).get("title", ""), **fields)
        rec["state"] = state
        rec["updated_at"] = _now()
        self.save()
        return rec

    def pending_inline(self, keys: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        wanted = {str(k) for k in keys} if keys else None
        out = []
        for key, rec in (self.data.get("defects") or {}).items():
            if wanted is not None and key not in wanted:
                continue
            if rec.get("state") in (STATE_ATTACHED, STATE_INLINE_PENDING, STATE_FAILED):
                out.append(rec)
        return out

    def all(self) -> List[Dict[str, Any]]:
        return list((self.data.get("defects") or {}).values())


# ---------- 描述 HTML / 图片 ----------

def is_placeholder_src(src: str) -> bool:
    src = (src or "").strip()
    return (not src) or src.startswith("data:") or src.startswith("blob:")


def parse_html_images(html_text: str) -> List[Dict[str, Any]]:
    """解析描述中的图片，返回 src/data-uuid/filename/placeholder。"""
    out = []
    for tag in _IMG_RE.findall(html_text or ""):
        src_m = _SRC_RE.search(tag)
        uuid_m = _UUID_RE.search(tag)
        file_m = _FILENAME_RE.search(tag)
        alt_m = _ALT_RE.search(tag)
        src = html.unescape(src_m.group(1)).strip() if src_m else ""
        filename = ""
        if file_m:
            filename = html.unescape(file_m.group(1)).split("/")[-1].strip()
        elif alt_m:
            filename = html.unescape(alt_m.group(1)).strip()
        out.append({
            "src": src,
            "resource_uuid": (uuid_m.group(1).strip() if uuid_m else ""),
            "filename": filename,
            "placeholder": is_placeholder_src(src),
        })
    return out


def image_figure(url: str, resource_uuid: str, name: str, ref_id: str = "") -> str:
    """构造 ONES 可识别的图片 figure；src 必须是签名 URL，不能是 data: 占位。"""
    if is_placeholder_src(url):
        raise ValueError(f"拒绝写入占位图片: {url!r}")
    attrs = [
        'class="ones-image-figure"',
        f'data-uuid="{html.escape(str(resource_uuid), quote=True)}"',
    ]
    if ref_id:
        attrs.append(f'data-ref-id="{html.escape(str(ref_id), quote=True)}"')
    attrs.append(f'data-filename="{html.escape(str(name), quote=True)}"')
    return (
        f"<figure {' '.join(attrs)}>"
        f'<img src="{html.escape(url, quote=True)}" '
        f'alt="{html.escape(str(name), quote=True)}" />'
        "</figure>"
    )


def merge_description_images(html_text: str, images: Iterable[Dict[str, Any]],
                             ref_id: str = "") -> str:
    """把图片追加到描述末尾；按 resource_uuid/filename 去重，不重复插图。"""
    current = html_text or ""
    existing = parse_html_images(current)
    existing_uuids = {x["resource_uuid"] for x in existing if x.get("resource_uuid")}
    existing_names = {x["filename"] for x in existing if x.get("filename")}
    additions = []
    for item in images:
        uid = str(item.get("resource_uuid") or "")
        name = str(item.get("name") or item.get("filename") or "")
        url = str(item.get("url") or "")
        if uid and uid in existing_uuids:
            continue
        if name and name in existing_names:
            continue
        if not url or is_placeholder_src(url):
            raise ValueError(f"图片 {name or uid} 没有可用的签名 URL")
        additions.append(image_figure(url, uid, name, ref_id=ref_id))
        if uid:
            existing_uuids.add(uid)
        if name:
            existing_names.add(name)
    if not additions:
        return current
    return current + "".join(additions)


def verify_image_urls(page, urls: Iterable[str], timeout: float = 20.0) -> List[Dict[str, Any]]:
    """浏览器内加载图片，返回 naturalWidth/naturalHeight；这是渲染态判据。"""
    wanted = [str(u) for u in urls if u]
    if not wanted:
        return []
    return page.evaluate(
        """async (urls) => {
            const load = (src) => new Promise((resolve) => {
                const img = new Image();
                const timer = setTimeout(() => resolve({
                    src, ok: false, naturalWidth: 0, naturalHeight: 0, error: 'timeout'
                }), 15000);
                img.onload = () => {
                    clearTimeout(timer);
                    resolve({
                        src, ok: true,
                        naturalWidth: img.naturalWidth || 0,
                        naturalHeight: img.naturalHeight || 0,
                        error: ''
                    });
                };
                img.onerror = () => {
                    clearTimeout(timer);
                    resolve({src, ok: false, naturalWidth: 0, naturalHeight: 0, error: 'load_error'});
                };
                img.src = src;
            });
            return await Promise.all(urls.map(load));
        }""",
        wanted,
    )


def image_report(html_text: str, rendered: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """汇总描述图片状态；ok 仅当没有占位图且所有图片渲染成功。"""
    images = parse_html_images(html_text)
    by_src = {x.get("src"): x for x in (rendered or []) if x.get("src")}
    placeholder = [x for x in images if x["placeholder"]]
    broken = []
    for item in images:
        if item["placeholder"]:
            continue
        hit = by_src.get(item["src"])
        if rendered is not None and (not hit or not hit.get("ok")
                                     or int(hit.get("naturalWidth") or 0) <= 0):
            broken.append(item)
    return {
        "ok": not placeholder and not broken,
        "count": len(images),
        "placeholder": placeholder,
        "broken": broken,
        "images": images,
        "rendered": rendered or [],
    }
