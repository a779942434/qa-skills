# -*- coding: utf-8 -*-
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';base=f'https://ones.shuyilink.com/project/#/team/{team}/task/'
frontend_uuid='JGwXEzXq';frontend_name='王斌'
items={
 '208641':'RsxEsWtXfecc0a71',
 '208642':'RsxEsWtXc4329d1b',
 '208643':'RsxEsWtX76bd25f0',
 '208644':'RsxEsWtXc6881d6f',
 '208657':'RsxEsWtXbd7612cb',
}

def nav(page,uuid):page.goto(base+uuid,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(3500)

def comment(page,text,mention=False):
 nav(page,'') if False else None
 border=page.locator('.message-input-border:visible').first;border.wait_for(state='visible',timeout=10000);border.click();page.wait_for_timeout(500)
 editor=page.locator('.message-input .cke_wysiwyg_div[contenteditable=true]:visible').last;editor.wait_for(state='visible',timeout=10000);editor.click();page.keyboard.type(text,delay=1)
 if mention:
  html=f' <span class="ones-at-user-block" data-ref-id="{frontend_uuid}" data-ref-name="{frontend_name}" contenteditable="false">@{frontend_name}</span>'
  editor.evaluate("(el,html)=>document.execCommand('insertHTML',false,html)",html)
 page.keyboard.press('Space');page.keyboard.press('Backspace');page.wait_for_timeout(400)
 send=page.locator('.message-input button').filter(has_text='发送').last;send.click(timeout=5000);page.wait_for_timeout(1000)

def status_info(page,uuid):return ones_helpers.get_task_info(page,team,uuid) or {}

def set_status(page,uuid,target):
 before=status_info(page,uuid).get('status_uuid')
 sel=page.locator('.ones-select.field-input-12').first;sel.wait_for(state='visible',timeout=8000);sel.click(timeout=5000);page.wait_for_timeout(400)
 item=page.locator('.ones-menu-item:visible').filter(has_text=target).first
 if item.count()==0:item=page.locator('.ones-menu-item').filter(has_text=target).first
 if item.count()==0:return {'before':before,'after':before,'skipped':target}
 item.click(force=True,timeout=5000);page.wait_for_timeout(700)
 after=status_info(page,uuid).get('status_uuid')
 if after==before:
  dlg=None
  for d in page.locator('[role=dialog]:visible').all():
   if f'执行步骤: {target}' in (d.inner_text() or ''):dlg=d;break
  if dlg is not None:
   dlg.get_by_role('button',name='确定',exact=True).click(timeout=5000);page.wait_for_timeout(1200);after=status_info(page,uuid).get('status_uuid')
 return {'before':before,'after':after,'target':target}

pw=browser=ctx=page=None;out={}
try:
 pw,browser,ctx,page=ones_helpers.connect()
 # Passed fixes: comment and close.
 for num in ('208641','208642'):
  uuid=items[num];nav(page,uuid)
  comment(page,'回归验证通过：已在 2026-09-29 测试环境重新导入验证，非法牌号行被拦截，合法中文长说明行成功入库；修复符合预期。')
  steps=[]
  # Move into test status if needed, then test-pass/closed.
  info=status_info(page,uuid)
  if info.get('status_uuid')!='Ge5Xhvan':steps.append(set_status(page,uuid,'待测试判定'))
  for target in ('测试通过','已关闭','关闭'):
   names=[t.get('name') for t in ((ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or [])]
   if target in names:steps.append(set_status(page,uuid,target))
   if target in ('已关闭','关闭') and status_info(page,uuid).get('status_uuid') not in ('Ge5Xhvan',): pass
  out[num]={'comment':True,'steps':steps,'final_status_uuid':status_info(page,uuid).get('status_uuid')}
 # Still failing front-end items: comment with mention, reopen 208657 if closed.
 for num in ('208643','208657'):
  uuid=items[num];nav(page,uuid)
  comment(page,'回归验证未通过：2026-09-29 在测试环境复测仍与需求不一致，请继续处理。结果与证据已记录在本地回归报告。',mention=True)
  steps=[]
  # 208657 was closed; reopen to developer queue if possible.
  names=[t.get('name') for t in ((ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or [])]
  target='开发待处理' if '开发待处理' in names else ('重新打开' if '重新打开' in names else None)
  if target:steps.append(set_status(page,uuid,target))
  # If reopened but not yet developer queue, try development queue.
  if status_info(page,uuid).get('status_uuid')=='HfLXZYeD':
   names2=[t.get('name') for t in ((ones_helpers.get_transitions(page,team,uuid) or {}).get('transitions') or [])]
   if '开发待处理' in names2:steps.append(set_status(page,uuid,'开发待处理'))
  out[num]={'comment':True,'steps':steps,'final_status_uuid':status_info(page,uuid).get('status_uuid')}
 # Closed non-defect but still requires frontend: comment only.
 uuid=items['208644'];nav(page,uuid);comment(page,'回归验证仍未完成：新增/编辑弹框仍显示“洗炉材料产品名称”，保存请求仍携带 washMaterialName。该项不认定为缺陷，但请前端继续按最新文档移除。',mention=True);out['208644']={'comment':True,'final_status_uuid':status_info(page,uuid).get('status_uuid')}
 print(json.dumps(out,ensure_ascii=False,indent=2)[:18000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
