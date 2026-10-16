# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';uuid='RsxEsWtX9a82b286';url=f'https://ones.shuyilink.com/project/#/team/{team}/task/{uuid}'
comment='需求变更：污染源牌号已调整为非必填，导入模板标非必填及空值导入成功符合最新业务口径。本单按产品口径撤回并关闭。'
pw=browser=ctx=page=None;steps=[]
try:
 pw,browser,ctx,page=ones_helpers.connect();page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(4000)
 # UI comment to ensure editor change event fires.
 border=page.locator('.message-input-border:visible').first;border.wait_for(state='visible',timeout=10000);border.click();page.wait_for_timeout(500)
 editor=page.locator('.message-input .cke_wysiwyg_div[contenteditable=true]:visible').last;editor.wait_for(state='visible',timeout=10000)
 editor.click();page.keyboard.type(comment,delay=1);page.keyboard.press('Space');page.keyboard.press('Backspace');page.wait_for_timeout(400)
 send=page.locator('.message-input button').filter(has_text='发送').last;send.click(timeout=5000);page.wait_for_timeout(1200)
 steps.append({'comment':True,'visible':comment in (page.locator('body').inner_text() or '')})
 def status_info():
  return ones_helpers.get_task_info(page,team,uuid) or {}
 def set_status(target):
  before=status_info().get('status_uuid')
  sel=page.locator('.ones-select.field-input-12').first;sel.wait_for(state='visible',timeout=8000);sel.click(timeout=5000);page.wait_for_timeout(400)
  item=page.locator('.ones-menu-item:visible').filter(has_text=target).first
  if item.count()==0:item=page.locator('.ones-menu-item').filter(has_text=target).first
  item.click(force=True,timeout=5000);page.wait_for_timeout(600)
  after=status_info().get('status_uuid')
  if after==before:
   dlg=None
   for d in page.locator('[role=dialog]:visible').all():
    if f'执行步骤: {target}' in (d.inner_text() or ''):dlg=d;break
   if dlg is not None:
    dlg.get_by_role('button',name='确定',exact=True).click(timeout=5000);page.wait_for_timeout(1400)
    after=status_info().get('status_uuid')
  return before,after
 # Move to 待测试判定, then rejection-close terminal state.
 for target in ('待测试判定','拒绝后关闭'):
  tr=(ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or []
  names=[t.get('name') for t in tr]
  steps.append({'available':names})
  if target not in names:
   steps.append({'skip':target,'reason':'not available'});break
  before,after=set_status(target);steps.append({'target':target,'before':before,'after':after})
  if after==before:break
 final=status_info()
 result={'uuid':uuid,'steps':steps,'final_status_uuid':final.get('status_uuid')}
 print(json.dumps(result,ensure_ascii=False)[:16000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
