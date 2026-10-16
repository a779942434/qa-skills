# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 ones_helpers.open_task_file_tab(page,'2YPZxEgX','RsxEsWtX1524fec1',timeout=20);page.wait_for_timeout(800)
 link=page.get_by_text('查看全部',exact=False).last
 if link.count(): link.click(timeout=5000)
 page.wait_for_timeout(1000)
 data=page.evaluate('''() => {const v=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'};return {dialogs:[...document.querySelectorAll('[role=dialog]')].filter(v).map(d=>({text:(d.innerText||'').slice(0,10000),html:d.outerHTML.slice(0,20000)})), buttons:[...document.querySelectorAll('button')].filter(v).map(b=>({text:(b.innerText||'').trim(),title:b.getAttribute('title'),aria:b.getAttribute('aria-label'),cls:b.className,html:b.outerHTML.slice(0,1200)})).filter(x=>x.text||x.title||x.aria), icons:[...document.querySelectorAll('[class*=delete],[class*=remove],[class*=trash]')].filter(v).map(e=>({cls:e.className,html:e.outerHTML.slice(0,1000)}))}}''')
 p=Path('/Users/a77994/qa-skills/runs/2026-09-28_合金污染规则定义/json/recon_attachment_modal.json');p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(data,ensure_ascii=False)[:30000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
