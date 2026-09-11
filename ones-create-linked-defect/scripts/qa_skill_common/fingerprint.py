# -*- coding: utf-8 -*-
"""元素指纹：组件探针 / 结构快照与对比 / 相似度自愈定位。

三块能力，可独立使用：

1) 组件指纹探针 —— ``probe_components(page)``
   dump 页面 class 前缀分布 + iframe 数，直接判定组件库同源性（是否与固化站点同源）。

2) 结构指纹快照与改版对比 —— ``capture_fingerprint`` / ``save_fingerprint`` /
   ``load_fingerprint`` / ``diff_fingerprint``
   把页面关键元素的结构特征存成 JSON；页面改版后对比，报出哪些元素
   「消失 / 变化 / 新增」，替代「人工重新侦察 → 手改 references」。

3) 相似度自愈定位 —— ``resolve(page, ...)``
   固化文档里的选择器失效时，按元素特征相似度找回同一个元素；
   低置信不猜，返回候选交给人/AI 判断。

指纹存放：``<workspace_root>/fingerprints/<name>.json``
（本机、不入 git、web 与 ones 两技能共享，见 paths.workspace_root）。

对应定式文档：web-blackbox-testing/references/advanced-ui.md 的「组件指纹探针」。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit

from . import paths

SCHEMA_VERSION = 1
MAX_ELEMENTS = 300          # 单次快照采集的元素上限
DEFAULT_THRESHOLD = 0.70    # 自愈自动采用的相似度下限
MIN_MARGIN = 0.10           # top1 与 top2 的最小分差（避免两个候选接近时误判）
DEFAULT_TOP_N = 3

# 已知组件库前缀表（v1）。顺序即匹配优先级 —— 多段前缀要排在它的短前缀之前。
KNOWN_PREFIXES = (
    ("div-table", "custom-div-table", "自研(div-table)"),
    ("el-", "element-plus", "Element Plus"),
    ("vxe-", "vxe-table", "VxeTable"),
    ("ant-", "ant-design", "Ant Design"),
    ("arco-", "arco-design", "Arco Design"),
    ("bk-", "bkuic", "BKUI"),
    ("sy-", "custom-sy", "自研(sy)"),
)
_PREFIX_SLUG = {p: slug for p, slug, _ in KNOWN_PREFIXES}
_PREFIX_LABEL = {p: label for p, _, label in KNOWN_PREFIXES}

LIB_DOMINANT = 0.60     # 单库占比达到此值即认定该组件库
LIB_PRIMARY = 0.30      # 无 dominant 时，最高已知库达到此值且无第二库 >= LIB_PRESENT 即认定该库
LIB_PRESENT = 0.20      # 参与 mixed 判定的占比下限

# 状态/修饰类前缀：表达状态（is-active/is-disabled）或行为标记，不标识组件库。
# 实测（真实 MES 站点）Element Plus 页面上 is-* 占比可达 11%，若算作「未知前缀」
# 会误导判定，故单独归到 decorators 字段，既不进 unknown 也不参与 verdict。
DECORATOR_PREFIXES = frozenset({"is-", "has-", "js-", "sr-", "v-"})
UNKNOWN_MIN = 0.05      # 未知前缀进入报告的最低占比
UNKNOWN_SUSPECT = 0.20  # 未知前缀被判「疑似自研」的占比下限

_PROBE_TOP_N = 15       # 前缀分布保留条数

_NAME_BAD = re.compile(r"[^\w\-\u4e00-\u9fff]", re.UNICODE)
_CLASS_IN_SELECTOR = re.compile(r"\.([A-Za-z_][\w-]*)")


# ---------------------------------------------------------------------------
# 阶段 1：组件指纹探针
# ---------------------------------------------------------------------------

_PROBE_JS = r"""() => {
  const counts = {};
  const all = document.querySelectorAll('*');
  for (const e of all) {
    if (!e.classList) continue;
    for (const c of e.classList) counts[c] = (counts[c] || 0) + 1;
  }
  return {
    total_elements: all.length,
    class_counts: counts,
    iframes: document.querySelectorAll('iframe').length
  };
}"""


def class_prefix(cls):
    """把一个 class 名归到前缀。

    先查已知表（支持 div-table 这类多段前缀），否则取第一个 '-' 之前的部分（含 '-'）；
    没有 '-' 就返回原名。例：el-button--primary -> el-，div-table-row -> div-table，
    xc-panel -> xc-，btn -> btn。
    """
    name = (cls or "").strip()
    if not name:
        return ""
    for prefix, _slug, _label in KNOWN_PREFIXES:
        if name == prefix or name.startswith(prefix):
            return prefix
    i = name.find("-")
    return name[: i + 1] if i > 0 else name


def _decide_verdict(libraries, unknown):
    """按占比判定组件库同源性。

    单库占比 >= 60%                     -> 该库 slug（dominant）
    两个及以上已知库 >= 20%             -> 'mixed'
    最高已知库 >= 30% 且无第二库 >= 20% -> 该库 slug（primary）
    无已知库 >= 20%、有未知前缀 >= 20%  -> 'custom'
    其余                                -> 'unknown'

    primary 档解决真实场景：Element Plus 44% 被 Tailwind 工具类稀释后达不到 60%，
    按旧规则会误判 unknown，而 44% 已足以说明「本站是 Element Plus 站点」。
    """
    dominant = [r for r in libraries if r["share"] >= LIB_DOMINANT]
    if dominant:
        return dominant[0]["slug"]
    present = [r for r in libraries if r["share"] >= LIB_PRESENT]
    if len(present) >= 2:
        return "mixed"
    if libraries and libraries[0]["share"] >= LIB_PRIMARY and len(present) <= 1:
        return libraries[0]["slug"]
    if not present and any(r["share"] >= UNKNOWN_SUSPECT for r in unknown):
        return "custom"
    return "unknown"


def probe_components(page):
    """组件指纹探针（只读）。

    返回 dict：
      verdict             'element-plus' | 'vxe-table' | ... | 'mixed' | 'custom' | 'unknown'
      libraries           [{prefix, slug, label, count, share}] 命中的已知库（按 count 降序）
      unknown_prefixes    [{prefix, count, share}] 未命中已知表且占比 >= 5%
      class_prefixes      [{prefix, count, share, lib}] 前缀分布，最多 15 条
      total_elements      页面元素总数
      total_class_instances  class 实例总数（share 的分母）
      iframes             iframe 数
    """
    raw = page.evaluate(_PROBE_JS) or {}
    counts = raw.get("class_counts") or {}
    total_cls = sum(counts.values()) or 1

    by_prefix = {}
    for cls, n in counts.items():
        p = class_prefix(cls)
        if not p:
            continue
        by_prefix[p] = by_prefix.get(p, 0) + n

    rows = []
    for prefix, n in by_prefix.items():
        rows.append({
            "prefix": prefix,
            "count": n,
            "share": round(n / total_cls, 4),
            "slug": _PREFIX_SLUG.get(prefix),
            "label": _PREFIX_LABEL.get(prefix),
        })
    rows.sort(key=lambda r: -r["count"])

    libraries, decorators = [], []
    for r in rows:
        if r["slug"]:
            libraries.append({"prefix": r["prefix"], "slug": r["slug"], "label": r["label"],
                              "count": r["count"], "share": r["share"]})
        elif r["prefix"] in DECORATOR_PREFIXES:
            decorators.append({"prefix": r["prefix"], "count": r["count"], "share": r["share"]})
    unknown = [{"prefix": r["prefix"], "count": r["count"], "share": r["share"]}
               for r in rows if not r["slug"] and r["prefix"] not in DECORATOR_PREFIXES
               and r["share"] >= UNKNOWN_MIN]

    return {
        "verdict": _decide_verdict(libraries, unknown),
        "libraries": libraries,
        "decorators": decorators,
        "unknown_prefixes": unknown,
        "class_prefixes": rows[:_PROBE_TOP_N],
        "total_elements": raw.get("total_elements", 0),
        "total_class_instances": sum(counts.values()),
        "iframes": raw.get("iframes", 0),
    }


# ---------------------------------------------------------------------------
# 阶段 2：结构指纹快照与对比
# ---------------------------------------------------------------------------

_CAPTURE_JS = r"""(maxN) => {
  const INTERACTIVE = 'button,a,input,select,textarea,[role],[onclick]';
  const STRUCT = '.el-table th,[role=dialog],.el-dialog,.sy-dialog';
  const seen = new Set();
  const items = [];
  const push = (el, tier) => {
    if (!el || seen.has(el)) return;
    seen.add(el);
    items.push([el, tier]);
  };
  for (const el of document.querySelectorAll(INTERACTIVE)) push(el, 0);
  for (const el of document.querySelectorAll(STRUCT)) push(el, 1);
  for (const el of document.querySelectorAll('div,section,form,table,ul,li')) push(el, 2);
  items.sort((a, b) => a[1] - b[1]);
  const picked = items.slice(0, maxN);

  const flat = (s) => (s || '').trim().replace(/[\n\t]+/g, ' | ');
  const classesOf = (el) => (el.classList ? Array.from(el.classList) : []);
  const attrsOf = (el) => {
    const out = {};
    for (const a of el.attributes) {
      const n = a.name;
      if (n === 'type' || n === 'name' || n === 'id' || n === 'role' ||
          n === 'placeholder' || n.startsWith('data-')) {
        out[n] = String(a.value || '').slice(0, 40);
      }
    }
    return out;
  };
  const ancestorPath = (el) => {
    const out = [];
    let n = el.parentElement;
    while (n && n.nodeType === 1 && out.length < 4) {
      let s = n.tagName.toLowerCase();
      const c = classesOf(n)[0];
      if (c) s += '.' + c;
      out.push(s);
      n = n.parentElement;
    }
    return out;
  };
  const siblingTexts = (el) => {
    const out = [];
    const p = el.parentElement;
    if (!p) return out;
    for (const s of p.children) {
      if (s === el) continue;
      const t = flat(s.innerText);
      if (t) out.push(t.slice(0, 30));
      if (out.length >= 3) break;
    }
    return out;
  };
  const childTags = (el) => {
    const out = [];
    for (const c of el.children) {
      out.push(c.tagName.toLowerCase());
      if (out.length >= 5) break;
    }
    return out;
  };
  const cssPath = (el) => {
    const parts = [];
    let n = el;
    while (n && n.nodeType === 1 && parts.length < 12) {
      if (n.id) { parts.unshift('#' + n.id); break; }
      let seg = n.tagName.toLowerCase();
      const p = n.parentElement;
      if (p) {
        const idx = Array.prototype.indexOf.call(p.children, n) + 1;
        seg += ':nth-child(' + idx + ')';
      }
      parts.unshift(seg);
      n = p;
    }
    return parts.join(' > ');
  };

  return picked.map(([el, tier]) => ({
    tier: tier,
    tag: el.tagName.toLowerCase(),
    classes: classesOf(el),
    role: el.getAttribute('role') ||
          (el.tagName === 'BUTTON' ? 'button' : (el.tagName === 'A' ? 'link' : '')),
    text: flat(el.innerText).slice(0, 60),
    attrs: attrsOf(el),
    ancestor_path: ancestorPath(el),
    sibling_texts: siblingTexts(el),
    child_tags: childTags(el),
    path: cssPath(el)
  }));
}"""


def fingerprints_dir():
    """指纹目录：<workspace_root>/fingerprints（本机产物，不入 git）。"""
    return paths.workspace_root() / "fingerprints"


def sanitize_name(name):
    """把指纹名规整成安全文件名：保留字母数字/下划线/连字符/中文，其余转 _，长度 <= 80。"""
    s = _NAME_BAD.sub("_", str(name or "").strip()).strip("_")
    return (s or "unnamed")[:80]


def fingerprint_path(name):
    return fingerprints_dir() / (sanitize_name(name) + ".json")


def _origin(url):
    p = urlsplit(url or "")
    return "{}://{}".format(p.scheme, p.netloc) if p.scheme and p.netloc else ""


def capture_fingerprint(page, name, max_elements=MAX_ELEMENTS):
    """抓取当前页面结构指纹（不落盘）。"""
    elements = page.evaluate(_CAPTURE_JS, max_elements) or []
    url = getattr(page, "url", "") or ""
    return {
        "schema_version": SCHEMA_VERSION,
        "name": sanitize_name(name),
        "url": url,
        "origin": _origin(url),
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "probe": probe_components(page),
        "elements": elements,
    }


def save_fingerprint(page, name):
    """抓取并写入 <workspace_root>/fingerprints/<name>.json，返回写入路径。"""
    fp = capture_fingerprint(page, name)
    d = fingerprints_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / (fp["name"] + ".json")
    path.write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_fingerprint(name):
    """读取指纹；不存在或损坏返回 None。"""
    p = fingerprint_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _struct_only(elements):
    """只保留可交互(tier 0)与结构(tier 1)元素 —— 容器(tier 2)噪声大，不参与对比。"""
    return [e for e in (elements or []) if (e.get("tier") or 0) <= 1]


def _best_match(target, pool, used=None):
    """在 pool 里找与 target 最相似的元素，返回 (score, index)。"""
    best, best_i = -1.0, -1
    for i, e in enumerate(pool):
        if used and i in used:
            continue
        sc = similarity(target, e)
        if sc > best:
            best, best_i = sc, i
    return best, best_i


# path 不计入：它是 nth-child 派生值，兄弟增删会整体位移，属定位副产物而非元素变化
_DIFF_FIELDS = ("classes", "text", "role", "ancestor_path")
_DIFF_LIMIT = 20    # 每类差异最多列出条数


def diff_fingerprint(page, name):
    """当前页面与已保存指纹对比。

    返回 {ok, name, url, counts, totals, disappeared, appeared, changed, probe_changed}；
    origin 不一致时 {ok: False, reason: 'origin_mismatch'}。
    """
    fp = load_fingerprint(name)
    if not fp:
        return {"ok": False, "reason": "fingerprint_not_found", "name": sanitize_name(name)}

    url = getattr(page, "url", "") or ""
    cur_origin, old_origin = _origin(url), fp.get("origin") or ""
    if old_origin and cur_origin and old_origin != cur_origin:
        return {"ok": False, "reason": "origin_mismatch",
                "expected": old_origin, "actual": cur_origin}

    current = capture_fingerprint(page, fp.get("name") or name)
    before, after = _struct_only(fp.get("elements")), _struct_only(current.get("elements"))

    used = set()
    disappeared, changed = [], []
    for be in before:
        score, idx = _best_match(be, after, used)
        if idx >= 0 and score >= DEFAULT_THRESHOLD:
            used.add(idx)
            ae = after[idx]
            fields = {}
            for k in _DIFF_FIELDS:
                bv, av = be.get(k), ae.get(k)
                if (bv or None) != (av or None):
                    fields[k] = {"before": bv, "after": av}
            if fields:
                changed.append({"ref": be.get("text") or be.get("tag"),
                                "score": score, "fields": fields})
        else:
            cand = None
            if idx >= 0:
                cand = {"score": score, "text": after[idx].get("text"),
                        "classes": after[idx].get("classes")}
            disappeared.append({"tag": be.get("tag"), "text": be.get("text"),
                                "classes": be.get("classes"), "best_match": cand})

    appeared = [{"tag": ae.get("tag"), "text": ae.get("text"), "classes": ae.get("classes")}
                for i, ae in enumerate(after) if i not in used]

    old_prefix = {r["prefix"]: r["count"] for r in (fp.get("probe") or {}).get("class_prefixes") or []}
    new_prefix = {r["prefix"]: r["count"] for r in (current.get("probe") or {}).get("class_prefixes") or []}
    probe_changed = {}
    for prefix, old_c in old_prefix.items():
        new_c = new_prefix.get(prefix, 0)
        if old_c != new_c:
            probe_changed[prefix] = {"before": old_c, "after": new_c}

    return {
        "ok": True,
        "name": fp.get("name") or sanitize_name(name),
        "url": url,
        "counts": {"before": len(before), "after": len(after)},
        "totals": {"disappeared": len(disappeared), "appeared": len(appeared),
                   "changed": len(changed)},
        "disappeared": disappeared[:_DIFF_LIMIT],
        "appeared": appeared[:_DIFF_LIMIT],
        "changed": changed[:_DIFF_LIMIT],
        "probe_changed": probe_changed,
    }


# ---------------------------------------------------------------------------
# 相似度（阶段 2 对比 + 阶段 3 自愈共用）
# ---------------------------------------------------------------------------

# v1 权重；调整需以本地夹具回归为准
WEIGHTS = {
    "classes": 0.25,      # class 最容易随改版变动，权重不宜过高
    "text": 0.30,         # 业务文本最稳定
    "role": 0.15,
    "tag": 0.10,
    "ancestor": 0.15,     # DOM 层级比单个 class 稳
    "sibling": 0.05,
}


def _signal_jaccard(a, b):
    """有信息才计分：任一方为空即视为「无信号」返回 0.0。

    与 class_jaccard 的差别：避免两个无关元素因「都没有祖先/兄弟文本」而在这些
    维度上拿到满分，凭空抬高底分。
    """
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def class_jaccard(a, b):
    """两个字符串列表的 Jaccard 相似度；两边都空视为完全一致。"""
    sa, sb = set(a or []), set(b or [])
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def text_sim(a, b):
    """文本相似度：完全相等=1.0；互相包含=0.6；否则按字符级相似度。"""
    a, b = (a or "").strip(), (b or "").strip()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.6
    return SequenceMatcher(None, a, b).ratio()


def similarity(a, b):
    """两个元素特征 dict 的加权相似度（0~1，保留 4 位）。

    各维度都在「有信息」时才计分（空值不给分也不占分），因此两个特征完全一致的
    元素得 1.0；改版后 class 变了但文本/层级仍在，通常落在 0.70~0.80。
    """
    role_a, role_b = (a.get("role") or ""), (b.get("role") or "")
    tag_a, tag_b = (a.get("tag") or ""), (b.get("tag") or "")
    score = (
        WEIGHTS["classes"] * _signal_jaccard(a.get("classes"), b.get("classes"))
        + WEIGHTS["text"] * text_sim(a.get("text"), b.get("text"))
        + WEIGHTS["role"] * (1.0 if role_a and role_a == role_b else 0.0)
        + WEIGHTS["tag"] * (1.0 if tag_a and tag_a == tag_b else 0.0)
        + WEIGHTS["ancestor"] * _signal_jaccard(a.get("ancestor_path"), b.get("ancestor_path"))
        + WEIGHTS["sibling"] * _signal_jaccard(a.get("sibling_texts"), b.get("sibling_texts"))
    )
    return round(score, 4)


# ---------------------------------------------------------------------------
# 阶段 3：相似度自愈定位
# ---------------------------------------------------------------------------

def _classes_from_selector(selector):
    return _CLASS_IN_SELECTOR.findall(selector or "")


def _describe_element(el):
    """把特征 dict 描述成 '.a.b' 或 'tag'，用于 healed_from。

    取全部 class：多个 class 时第一个常是通用基类（如 el-button），
    真正有区分度的是后面的修饰类（如 action-button），只取第一个会误导。
    """
    classes = el.get("classes") or []
    return "." + ".".join(classes) if classes else (el.get("tag") or "?")


def _pick_target(targets, selector=None, text=None, role=None):
    """在指纹元素里挑「最接近查询信号」的那个作为匹配目标。"""
    sel_classes = _classes_from_selector(selector) if selector else []
    best, best_score = None, 0.0
    for e in targets:
        if sel_classes:
            sc = class_jaccard(sel_classes, e.get("classes"))
        elif text:
            sc = text_sim(text, e.get("text"))
            if role and (e.get("role") or "") != role:
                sc *= 0.5
        else:
            continue
        if sc > best_score:
            best, best_score = e, sc
    return best


def _ok(locator, via, score=None, healed_from=None, path=None, text=None):
    return {"ok": True, "via": via, "locator": locator, "score": score,
            "healed_from": healed_from, "path": path, "text": text}


def resolve(page, selector=None, text=None, role=None, fingerprint=None,
            threshold=DEFAULT_THRESHOLD, top_n=DEFAULT_TOP_N):
    """定位元素；精确匹配失败时按已保存指纹做相似度自愈。

    流程：① 精确匹配（selector / text / role）→ 命中即返回 via='selector'|'exact'；
          ② 载入指纹，挑出最接近查询信号的目标特征；
          ③ 抓当前页面候选（与快照同一采集规则），逐个算相似度取 top-N；
          ④ top1 >= threshold 且 top1-top2 >= 0.10 才自动采用，否则返回候选不猜。

    返回：
      成功 {"ok": True, "via": "selector"|"exact"|"fingerprint", "locator": Locator,
            "score": float|None, "path": str|None, "healed_from": str|None, "text": str|None}
      失败 {"ok": False, "reason": "not_found"|"ambiguous"|"low_confidence",
            "candidates": [{"text", "classes", "score", "path"}]}
    """
    # ① 精确匹配
    if selector:
        try:
            loc = page.locator(selector)
            if loc.count() and loc.first.is_visible():
                return _ok(loc.first, "selector", path=selector)
        except Exception:
            pass
    if text or role:
        try:
            if role and text:
                loc = page.get_by_role(role, name=text, exact=True)
            elif role:
                loc = page.get_by_role(role)
            else:
                loc = page.get_by_text(text, exact=True)
            if loc.count() and loc.first.is_visible():
                return _ok(loc.first, "exact", text=text)
        except Exception:
            pass

    # ② 指纹目标
    if not fingerprint:
        return {"ok": False, "reason": "not_found", "candidates": []}
    fp = load_fingerprint(fingerprint)
    if not fp:
        return {"ok": False, "reason": "not_found", "candidates": []}

    url = getattr(page, "url", "") or ""
    cur_origin, old_origin = _origin(url), fp.get("origin") or ""
    if old_origin and cur_origin and old_origin != cur_origin:
        return {"ok": False, "reason": "origin_mismatch",
                "expected": old_origin, "actual": cur_origin}

    target = _pick_target(_struct_only(fp.get("elements")), selector=selector, text=text, role=role)
    if not target:
        return {"ok": False, "reason": "not_found", "candidates": []}

    # ③ 当前候选打分
    try:
        pool = _struct_only(page.evaluate(_CAPTURE_JS, MAX_ELEMENTS))
    except Exception as e:
        return {"ok": False, "reason": "not_found", "candidates": [], "detail": repr(e)[:120]}

    scored = sorted(((similarity(target, c), c) for c in pool), key=lambda x: -x[0])[:max(top_n, 2)]
    if not scored:
        return {"ok": False, "reason": "not_found", "candidates": []}

    candidates = [{"text": c.get("text"), "classes": c.get("classes"),
                   "score": s, "path": c.get("path")} for s, c in scored]

    # ④ 判定：够高且与第二名拉开差距，才自动采用
    best_score = scored[0][0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= threshold and (best_score - second) >= MIN_MARGIN:
        best = scored[0][1]
        try:
            loc = page.locator(best.get("path") or "*").first
        except Exception as e:
            return {"ok": False, "reason": "not_found", "candidates": candidates,
                    "detail": repr(e)[:120]}
        return _ok(loc, "fingerprint", score=best_score, healed_from=_describe_element(target),
                   path=best.get("path"), text=best.get("text"))

    return {"ok": False,
            "reason": "ambiguous" if best_score >= threshold else "low_confidence",
            "candidates": candidates[:top_n]}


if __name__ == "__main__":
    print("指纹目录:", fingerprints_dir())
