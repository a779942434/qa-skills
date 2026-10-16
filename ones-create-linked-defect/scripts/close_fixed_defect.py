# -*- coding: utf-8 -*-
import json,sys
sys.path.insert(0,'/Users/a77994/qa-skills/ones-create-linked-defect/scripts')
import ones_helpers as h
from qa_skill_common.bbt_helpers import wait_app_ready
team='2YPZxEgX'
mapping={'208628':'RsxEsWtX2dfd1d64','208629':'RsxEsWtX795bdb78','208630':'RsxEsWtX8f4e9ac9','208632':'RsxEsWtXfa811659'}
pw,b,ctx,page=h.connect(url_contains='ones.shuyilink.com')
try:
 results={}
 for num,u in mapping.items():
  url=f'https://ones.shuyilink.com/project/#/team/{team}/task/{u}'
  page.goto(url,wait_until='domcontentloaded',timeout=60000)
  wait_app_ready(page,timeout=20)
  page.wait_for_timeout(800)
  before=h.get_task_info(page,team,u) or {}
  if before.get('status_uuid')=='Pyfmnyxk':
   results[num]={'ok':True,'already_closed':True,'before':before.get('status_uuid')};continue
  status=page.locator('.ones-select.field-input-12').first
  status.wait_for(state='visible',timeout=10000)
  current=(status.inner_text() or '').strip()
  status.click(force=True);page.wait_for_timeout(400)
  item=page.locator('.ones-menu-item:visible').filter(has_text='已关闭').first
  if item.count()==0:
   item=page.locator('.ones-menu-item').filter(has_text='已关闭').first
   item.evaluate('el=>el.click()')
  else:
   item.click()
  page.wait_for_timeout(500)
  # optional execution step confirm
  d=page.locator('[role=dialog]:visible').last
  if d.count() and ('执行步骤' in (d.inner_text() or '') or d.get_by_role('button',name='确定',exact=True).count()):
   btn=d.get_by_role('button',name='确定',exact=True)
   if btn.count():btn.first.click()
   page.wait_for_timeout(800)
  after=h.get_task_info(page,team,u) or {}
  results[num]={'ok':after.get('status_uuid')=='Pyfmnyxk','before_status':before.get('status_uuid'),'after_status':after.get('status_uuid'),'ui_current':current}
 print(json.dumps(results,ensure_ascii=False,indent=2))
finally:h.disconnect(pw)
