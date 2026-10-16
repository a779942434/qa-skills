# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';uuid='RsxEsWtX1524fec1';url=f'https://ones.shuyilink.com/project/#/team/{team}/task/{uuid}'
pw=browser=ctx=page=None;steps=[]
try:
 pw,browser,ctx,page=ones_helpers.connect();page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(4000)
 for attempt in range(8):
  info=ones_helpers.get_task_info(page,team,uuid) or {};cur=info.get('status_uuid')
  tr=(ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or [];names=[t.get('name') for t in tr]
  steps.append({'attempt':attempt,'status_uuid':cur,'transitions':names})
  target=None
  for n in ('已关闭','关闭','拒绝后关闭','已拒绝','测试通过'):
   if n in names:target=n;break
  if target is None:break
  sel=page.locator('.ones-select.field-input-12').first
  sel.wait_for(state='visible',timeout=8000);sel.click(timeout=5000);page.wait_for_timeout(500)
  item=page.locator('.ones-menu-item:visible').filter(has_text=target).first
  if item.count()==0:item=page.locator('.ones-menu-item').filter(has_text=target).first
  item.click(force=True,timeout=5000);page.wait_for_timeout(1500)
  new=(ones_helpers.get_task_info(page,team,uuid) or {}).get('status_uuid')
  steps.append({'target':target,'after_status_uuid':new})
  if target in ('已关闭','关闭','拒绝后关闭'):break
 final=ones_helpers.get_task_info(page,team,uuid) or {}
 result={'uuid':uuid,'steps':steps,'final_status_uuid':final.get('status_uuid'),'final_status':final.get('status')}
 print(json.dumps(result,ensure_ascii=False)[:20000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
