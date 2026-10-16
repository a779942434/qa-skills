# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 before=ones_helpers.get_task_attachments(page,'2YPZxEgX','RsxEsWtX1524fec1') or {}
 ones_helpers.open_task_file_tab(page,'2YPZxEgX','RsxEsWtX1524fec1',timeout=20);page.wait_for_timeout(700)
 page.get_by_text('查看全部',exact=False).last.click(timeout=5000);page.wait_for_timeout(800)
 items=page.locator('.resource-item-container:visible').filter(has_text='BUG-01_导入模板.xlsx')
 print('visible xlsx items',items.count())
 if items.count()<2: raise RuntimeError('no duplicate visible')
 item=items.nth(1)
 actions=item.locator('.resource-actions .ui-circle-icon')
 print('actions',actions.count())
 actions.nth(1).click(timeout=5000);page.wait_for_timeout(700)
 dialogs=[]
 for d in page.locator('[role=dialog]:visible').all():
  t=(d.inner_text() or '').strip()
  if '删除' in t or '确定' in t: dialogs.append(t[:2000])
 print('dialogs',json.dumps(dialogs,ensure_ascii=False)[:4000])
 # Find visible confirm button in the smallest visible dialog containing delete wording.
 clicked=False
 for d in page.locator('[role=dialog]:visible>div,[role=dialog]:visible').all():
  try:
   txt=(d.inner_text() or '').strip()
   if '删除' in txt and '确定' in txt:
    b=d.get_by_role('button',name='确定',exact=True)
    if b.count() and b.last.is_visible():b.last.click();clicked=True;break
  except Exception:pass
 if not clicked:
  b=page.get_by_role('button',name='确定',exact=True)
  if b.count() and b.last.is_visible():b.last.click();clicked=True
 print('confirm clicked',clicked);page.wait_for_timeout(1200)
 after=ones_helpers.get_task_attachments(page,'2YPZxEgX','RsxEsWtX1524fec1') or {}
 print(json.dumps({'before':len(before.get('attachments') or []),'after':len(after.get('attachments') or []),'before_xlsx':sum(1 for a in before.get('attachments') or [] if a.get('name')=='BUG-01_导入模板.xlsx'),'after_xlsx':sum(1 for a in after.get('attachments') or [] if a.get('name')=='BUG-01_导入模板.xlsx')},ensure_ascii=False))
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
