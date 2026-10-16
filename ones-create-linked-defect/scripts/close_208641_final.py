# -*- coding: utf-8 -*-
import json,sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parent))
import ones_helpers as h
from qa_skill_common.bbt_helpers import wait_app_ready
team='2YPZxEgX';u='RsxEsWtXfecc0a71'
pw,b,ctx,page=h.connect(url_contains='ones.shuyilink.com')
try:
 page.goto(f'https://ones.shuyilink.com/project/#/team/{team}/task/{u}',wait_until='domcontentloaded',timeout=60000);wait_app_ready(page,timeout=20);page.wait_for_timeout(1200)
 def click_transition(name):
  status=page.locator('.ones-select.field-input-12').first;status.wait_for(state='visible',timeout=15000);status.click(force=True);page.wait_for_timeout(500)
  item=page.locator('.ones-menu-item:visible').filter(has_text=name).first
  if item.count()==0:item=page.locator('.ones-menu-item').filter(has_text=name).first
  item.click(force=True);page.wait_for_timeout(700)
  d=page.locator('[role=dialog]:visible').last
  if d.count() and '执行步骤' in (d.inner_text() or ''):
   b=d.get_by_role('button',name='确定',exact=True)
   if b.count():b.first.click();page.wait_for_timeout(1200)
 def info():return h.get_task_info(page,team,u) or {}
 steps=[];cur=info().get('status_uuid')
 if cur!='Pyfmnyxk':
  names=[x.get('name') for x in ((h.get_transitions(page,team,u) or {}).get('transitions') or [])]
  if '测试通过' in names:
   click_transition('测试通过');steps.append({'已点':'测试通过','status':info().get('status_uuid')})
  names=[x.get('name') for x in ((h.get_transitions(page,team,u) or {}).get('transitions') or [])]
  if '已关闭' in names:
   click_transition('已关闭');steps.append({'已点':'已关闭','status':info().get('status_uuid')})
 print(json.dumps({'before':cur,'steps':steps,'after':info().get('status_uuid')},ensure_ascii=False))
finally:h.disconnect(pw)
