# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 before=ones_helpers.get_task_attachments(page,'2YPZxEgX','RsxEsWtX1524fec1') or {}
 ones_helpers.open_task_file_tab(page,'2YPZxEgX','RsxEsWtX1524fec1',timeout=20);page.wait_for_timeout(800)
 items=page.locator('.resource-item-container:visible').filter(has_text='BUG-01_导入模板.xlsx')
 print('items',items.count())
 item=items.nth(1)
 item.hover(timeout=4000);page.wait_for_timeout(250)
 actions=item.locator('.resource-actions .ui-circle-icon')
 print('actions',actions.count())
 actions.nth(1).click(timeout=5000);page.wait_for_timeout(900)
 vis=page.locator('[role=dialog]:visible')
 print('visible dialogs',vis.count())
 for i in range(vis.count()):
  print('DIALOG',i,(vis.nth(i).inner_text() or '')[:3000])
 # click smallest confirm containing 删除 / 确定
 clicked=False
 for i in range(vis.count()-1,-1,-1):
  d=vis.nth(i);t=(d.inner_text() or '')
  if ('删除' in t) and ('确定' in t):
   b=d.get_by_role('button',name='确定',exact=True)
   if b.count() and b.last.is_visible():b.last.click();clicked=True;break
 print('clicked',clicked);page.wait_for_timeout(1200)
 after=ones_helpers.get_task_attachments(page,'2YPZxEgX','RsxEsWtX1524fec1') or {}
 print(json.dumps({'before':len(before.get('attachments') or []),'after':len(after.get('attachments') or []),'xlsx_before':sum(1 for a in before.get('attachments') or [] if a.get('name')=='BUG-01_导入模板.xlsx'),'xlsx_after':sum(1 for a in after.get('attachments') or [] if a.get('name')=='BUG-01_导入模板.xlsx')},ensure_ascii=False))
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
