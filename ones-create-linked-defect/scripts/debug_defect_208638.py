# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 url='https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/RsxEsWtX1524fec1'
 page.goto(url,wait_until='domcontentloaded',timeout=60000)
 page.wait_for_timeout(5000)
 data=page.evaluate('''() => {const v=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'};return {url:location.href,title:document.title,body:(document.body.innerText||'').slice(0,5000),visibleDialogs:[...document.querySelectorAll('[role=dialog]')].filter(v).map(e=>(e.innerText||'').slice(0,2000)),viewerCount:[...document.querySelectorAll('.richtext-input-viewer-wrapper')].filter(v).length,allViewerCount:document.querySelectorAll('.richtext-input-viewer-wrapper').length,editorCount:[...document.querySelectorAll('.cke_wysiwyg_div[contenteditable=true]')].filter(v).length,allEditors:document.querySelectorAll('.cke_wysiwyg_div[contenteditable=true]').length}}''')
 print(json.dumps(data,ensure_ascii=False)[:20000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
