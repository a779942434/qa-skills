# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
responses=[];pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 def on_resp(r):
  if any(x in r.url.lower() for x in ('attachment','file','task')):
   responses.append({'method':r.request.method,'url':r.url,'status':r.status,'post':r.request.post_data[:1000] if r.request.post_data else None})
 page.on('response',on_resp)
 ones_helpers.open_task_file_tab(page,'2YPZxEgX','RsxEsWtX1524fec1',timeout=20);page.wait_for_timeout(700)
 items=page.locator('.resource-item-container:visible').filter(has_text='BUG-01_导入模板.xlsx');item=items.nth(1);item.hover();page.wait_for_timeout(200)
 item.locator('.resource-actions .ui-circle-icon').nth(1).click(timeout=5000);page.wait_for_timeout(600)
 # identify delete dialog explicitly by header text
 dlg=None
 for d in page.locator('[role=dialog]:visible').all():
  if '删除文件' in (d.inner_text() or ''):dlg=d;break
 if dlg is None:raise RuntimeError('delete dialog not found')
 print('dialog', (dlg.inner_text() or '')[:1000])
 b=dlg.get_by_role('button',name='确定',exact=True);print('confirm count',b.count(),'visible',b.last.is_visible() if b.count() else None,'disabled',b.last.is_disabled() if b.count() else None)
 b.last.click(force=True,timeout=5000);page.wait_for_timeout(2500)
 toasts=[]
 for sel in ('.ones-message','.message','.toast','[class*=message]'):
  try: toasts += [x.strip() for x in page.locator(sel+':visible').all_inner_texts() if x.strip()]
  except:pass
 d=ones_helpers.get_task_attachments(page,'2YPZxEgX','RsxEsWtX1524fec1') or {};atts=d.get('attachments') or []
 print(json.dumps({'dialog_visible':dlg.is_visible(),'attachments':len(atts),'xlsx':sum(1 for a in atts if a.get('name')=='BUG-01_导入模板.xlsx'),'toasts':toasts[:10],'responses':responses[-30:]},ensure_ascii=False)[:15000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
