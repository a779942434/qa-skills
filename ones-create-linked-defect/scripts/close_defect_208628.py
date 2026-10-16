# -*- coding: utf-8 -*-
import json,sys
sys.path.insert(0,'/Users/a77994/qa-skills/ones-create-linked-defect/scripts')
import ones_helpers as h
from qa_skill_common.bbt_helpers import wait_app_ready
team='2YPZxEgX';u='RsxEsWtX2dfd1d64'
pw,b,ctx,page=h.connect(url_contains='ones.shuyilink.com')
def click_transition(name):
 status=page.locator('.ones-select.field-input-12').first
 status.wait_for(state='visible',timeout=10000)
 status.click(force=True);page.wait_for_timeout(350)
 item=page.locator('.ones-menu-item:visible').filter(has_text=name).first
 if item.count()==0:
  item=page.locator('.ones-menu-item').filter(has_text=name).first
  item.evaluate('el=>el.click()')
 else:
  item.click()
 page.wait_for_timeout(500)
 d=page.locator('[role=dialog]:visible').last
 if d.count():
  btn=d.get_by_role('button',name='确定',exact=True)
  if btn.count():btn.first.click();page.wait_for_timeout(700)
 page.wait_for_timeout(500)
try:
 page.goto(f'https://ones.shuyilink.com/project/#/team/{team}/task/{u}',wait_until='domcontentloaded',timeout=60000);wait_app_ready(page,timeout=20);page.wait_for_timeout(600)
 before=h.get_task_info(page,team,u) or {}
 result={'before':before.get('status_uuid'),'steps':[]}
 if before.get('status_uuid')!='Pyfmnyxk':
  tr=h.get_transitions(page,team,u) or {};names=[x.get('name') for x in (tr.get('transitions') or [])]
  if '测试通过' in names:
   click_transition('测试通过');result['steps'].append({'name':'测试通过','status':(h.get_task_info(page,team,u) or {}).get('status_uuid')})
  tr=h.get_transitions(page,team,u) or {};names=[x.get('name') for x in (tr.get('transitions') or [])]
  if '已关闭' in names:
   click_transition('已关闭');result['steps'].append({'name':'已关闭','status':(h.get_task_info(page,team,u) or {}).get('status_uuid')})
 after=h.get_task_info(page,team,u) or {};result['after']=after.get('status_uuid');result['ok']=after.get('status_uuid')=='Pyfmnyxk'
 print(json.dumps(result,ensure_ascii=False,indent=2))
finally:h.disconnect(pw)
