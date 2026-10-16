# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX'
items=[('208641','RsxEsWtXfecc0a71'),('208642','RsxEsWtXc4329d1b')]
pw=browser=ctx=page=None;out={}
try:
 pw,browser,ctx,page=ones_helpers.connect()
 def nav(uuid):
  page.goto(f'https://ones.shuyilink.com/project/#/team/{team}/task/{uuid}',wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(3500)
 def info(uuid):return ones_helpers.get_task_info(page,team,uuid) or {}
 def set_status(uuid,target):
  before=info(uuid).get('status_uuid')
  sel=page.locator('.ones-select.field-input-12').first;sel.wait_for(state='visible',timeout=8000);sel.click(timeout=5000);page.wait_for_timeout(400)
  item=page.locator('.ones-menu-item:visible').filter(has_text=target).first
  if item.count()==0:item=page.locator('.ones-menu-item').filter(has_text=target).first
  if item.count()==0:return {'before':before,'after':before,'target':target,'skipped':'not_available'}
  item.click(force=True);page.wait_for_timeout(700)
  after=info(uuid).get('status_uuid')
  if after==before:
   dlg=None
   for d in page.locator('[role=dialog]:visible').all():
    if f'执行步骤: {target}' in (d.inner_text() or ''):dlg=d;break
   if dlg is not None:
    dlg.get_by_role('button',name='确定',exact=True).click(timeout=5000);page.wait_for_timeout(1200);after=info(uuid).get('status_uuid')
  return {'before':before,'after':after,'target':target}
 for num,uuid in items:
  nav(uuid);steps=[]
  # First ensure waiting-for-test state.
  names=[t.get('name') for t in ((ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or [])]
  if info(uuid).get('status_uuid')!='Ge5Xhvan' and '待测试判定' in names:
   steps.append(set_status(uuid,'待测试判定'))
  # Then pass and close.
  for target in ('测试通过','已关闭','关闭'):
   names=[t.get('name') for t in ((ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or [])]
   if target in names:
    before=info(uuid).get('status_uuid');res=set_status(uuid,target);steps.append(res)
    if res.get('after')==before:break
  out[num]={'steps':steps,'final_status_uuid':info(uuid).get('status_uuid')}
 print(json.dumps(out,ensure_ascii=False,indent=2))
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
