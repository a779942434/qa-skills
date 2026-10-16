# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 data=ones_helpers.open_task_file_tab(page,'2YPZxEgX','RsxEsWtX1524fec1',timeout=20)
 page.wait_for_timeout(1200)
 dump=page.evaluate('''() => {const v=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'};return {text:(document.body.innerText||'').slice(-12000),visibleButtons:[...document.querySelectorAll('button')].filter(v).map(e=>(e.innerText||'').trim()).filter(Boolean),items:[...document.querySelectorAll('.resource-info-name,[class*=resource-info],[class*=attachment]')].filter(v).map(e=>({cls:e.className,text:(e.innerText||'').trim().slice(0,500),html:e.outerHTML.slice(0,1500)})).slice(-80)}}''')
 out={'attachments':len((data or {}).get('attachments') or []),'dump':dump}
 p=Path('/Users/a77994/qa-skills/runs/2026-09-28_合金污染规则定义/json/recon_attachment_delete.json');p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(out,ensure_ascii=False)[:25000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
