# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';uuid='RsxEsWtXc6881d6f';url=f'https://ones.shuyilink.com/project/#/team/{team}/task/{uuid}'
frontend_uuid='JGwXEzXq';frontend_name='王斌'
comment='产品口径说明：飞书链接中的需求文档已变更，但外部需求列表未同步，产品需求也未与前端同步，本单不认定为缺陷。仍需前端按最新文档移除新增/编辑弹框中的洗炉材料字段，并同步不再提交 washMaterialName。'
pw=browser=ctx=page=None;steps=[]
try:
 pw,browser,ctx,page=ones_helpers.connect();page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(4000)
 border=page.locator('.message-input-border:visible').first;border.wait_for(state='visible',timeout=10000);border.click();page.wait_for_timeout(500)
 editor=page.locator('.message-input .cke_wysiwyg_div[contenteditable=true]:visible').last;editor.wait_for(state='visible',timeout=10000)
 editor.click();page.keyboard.type(comment,delay=1);page.wait_for_timeout(250)
 mention=f' <span class="ones-at-user-block" data-ref-id="{frontend_uuid}" data-ref-name="{frontend_name}" contenteditable="false">@{frontend_name}</span>'
 editor.evaluate("(el, html) => document.execCommand('insertHTML', false, html)",mention);page.wait_for_timeout(300)
 page.keyboard.press('Space');page.keyboard.press('Backspace');page.wait_for_timeout(500)
 send=page.locator('.message-input button').filter(has_text='发送').last;send.click(timeout=5000);page.wait_for_timeout(1400)
 page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(3500)
 body=page.locator('body').inner_text() or ''
 steps.append({'comment_sent':comment in body,'mention_visible':'@王斌' in body})
 def status_info():return ones_helpers.get_task_info(page,team,uuid) or {}
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
 for target in ('待测试判定','拒绝后关闭'):
  names=[t.get('name') for t in ((ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or [])]
  steps.append({'available':names})
  if target not in names:steps.append({'skip':target});break
  before,after=set_status(target);steps.append({'target':target,'before':before,'after':after})
  if after==before:break
 final=status_info();result={'uuid':uuid,'steps':steps,'final_status_uuid':final.get('status_uuid')}
 print(json.dumps(result,ensure_ascii=False)[:18000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
