# -*- coding: utf-8 -*-
import sys,json
sys.path.insert(0,'/Users/a77994/qa-skills/ones-create-linked-defect/scripts')
import ones_helpers
pw,b,c,p=ones_helpers.connect()
try:
 u='RsxEsWtXfecc0a71';p.goto(f'https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/{u}',wait_until='domcontentloaded',timeout=60000);p.wait_for_timeout(3500)
 txt='回归验证通过：已在 2026-09-29 测试环境重新导入验证'
 el=p.get_by_text(txt,exact=False).last;el.scroll_into_view_if_needed();el.hover();p.wait_for_timeout(700)
 data=p.evaluate('''() => {const v=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'};return {buttons:[...document.querySelectorAll('button')].filter(v).map(b=>({text:(b.innerText||'').trim(),title:b.getAttribute('title'),aria:b.getAttribute('aria-label'),html:b.outerHTML.slice(0,800)})),deleteText:[...document.querySelectorAll('*')].filter(v).filter(e=>(e.innerText||'').trim()==='删除').map(e=>({tag:e.tagName,cls:e.className,html:e.outerHTML.slice(0,800)}))}}''')
 print(json.dumps(data,ensure_ascii=False)[:12000])
finally:ones_helpers.disconnect(pw)
