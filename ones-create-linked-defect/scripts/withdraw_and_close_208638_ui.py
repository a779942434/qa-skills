# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';uuid='RsxEsWtX1524fec1';url=f'https://ones.shuyilink.com/project/#/team/{team}/task/{uuid}'
comment='测试补充核对：主工单前端联调说明明确要求列表、新增/编辑、Excel 导入及导出均移除“洗炉材料”字段，防重复口径改为“污染源牌号+目标牌号”。因此原提交的“洗炉材料字段缺失”按产品口径不算缺陷，本单撤回并关闭。'
pw=browser=ctx=page=None;steps=[]
try:
 pw,browser,ctx,page=ones_helpers.connect();page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(4500)
 # Submit comment through the standard UI.
 border=page.locator('.message-input-border:visible').first
 border.wait_for(state='visible',timeout=10000);border.click(timeout=5000);page.wait_for_timeout(600)
 editor=page.locator('.message-input .cke_wysiwyg_div[contenteditable=true]:visible').last
 editor.wait_for(state='visible',timeout=10000);editor.click();page.keyboard.type(comment,delay=1);page.keyboard.press('Space');page.keyboard.press('Backspace');page.wait_for_timeout(500)
 send=page.locator('.message-input button').filter(has_text='发送').last
 send.click(timeout=5000);page.wait_for_timeout(1200)
 steps.append({'action':'comment_ui','sent':True,'visible_in_body':comment in (page.locator('body').inner_text() or '')})
 # Transition step by step using the status select.
 for attempt in range(6):
  info=ones_helpers.get_task_info(page,team,uuid) or {};cur=info.get('status_uuid')
  tr=(ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or [];names=[t.get('name') for t in tr]
  steps.append({'attempt':attempt,'status_uuid':cur,'transitions':names})
  target=None
  for n in ('已关闭','关闭'):
   if n in names:target=n;break
  if target is None and '待测试判定' in names:target='待测试判定'
  if target is None and names:target=names[0]
  if not target:break
  sel=page.locator('.ones-select.field-input-12').first
  sel.wait_for(state='visible',timeout=8000);sel.click(timeout=5000);page.wait_for_timeout(500)
  item=page.locator('.ones-menu-item:visible').filter(has_text=target).first
  if item.count()==0:item=page.locator('.ones-menu-item').filter(has_text=target).first
  item.click(force=True,timeout=5000);page.wait_for_timeout(1400)
  new=(ones_helpers.get_task_info(page,team,uuid) or {}).get('status_uuid')
  steps.append({'target':target,'after_status_uuid':new})
  if target in ('已关闭','关闭') or new==cur:break
 final=ones_helpers.get_task_info(page,team,uuid) or {}
 result={'uuid':uuid,'steps':steps,'final_status_uuid':final.get('status_uuid'),'final_status':final.get('status')}
 print(json.dumps(result,ensure_ascii=False)[:20000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
