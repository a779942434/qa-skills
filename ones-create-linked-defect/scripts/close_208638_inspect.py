# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';uuid='RsxEsWtX1524fec1';url=f'https://ones.shuyilink.com/project/#/team/{team}/task/{uuid}'
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect();page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(4000)
 sel=page.locator('.ones-select.field-input-12').first;sel.click(timeout=5000);page.wait_for_timeout(500)
 item=page.locator('.ones-menu-item:visible').filter(has_text='拒绝后关闭').first
 print('item count',item.count())
 item.click(force=True,timeout=5000);page.wait_for_timeout(1000)
 dialogs=[]
 for d in page.locator('[role=dialog]:visible').all():
  t=(d.inner_text() or '').strip()
  if t:dialogs.append(t[:3000])
 print(json.dumps({'dialogs':dialogs,'body_tail':(page.locator('body').inner_text() or '')[-5000:]},ensure_ascii=False)[:12000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
