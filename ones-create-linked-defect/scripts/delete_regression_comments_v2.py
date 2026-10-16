# -*- coding: utf-8 -*-
import json,sys
sys.path.insert(0,'/Users/a77994/qa-skills/ones-create-linked-defect/scripts')
import ones_helpers
items=[('208641','RsxEsWtXfecc0a71','回归验证通过：已在 2026-09-29 测试环境重新导入验证'),('208642','RsxEsWtXc4329d1b','回归验证通过：已在 2026-09-29 测试环境重新导入验证')]
pw,b,c,p=ones_helpers.connect();out=[]
try:
 for num,uuid,prefix in items:
  p.goto(f'https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/{uuid}',wait_until='domcontentloaded',timeout=60000);p.wait_for_timeout(3500)
  el=p.get_by_text(prefix,exact=False).last
  if el.count()==0:
   out.append({'number':num,'deleted':False,'reason':'not_found'});continue
  anc=el.locator('xpath=ancestor::div[contains(@class,"comment-block-container")][1]')
  anc.hover();p.wait_for_timeout(400)
  d=anc.get_by_role('button',name='删除',exact=True)
  if d.count()==0:
   out.append({'number':num,'deleted':False,'reason':'delete_button_missing'});continue
  d.last.click(force=True);p.wait_for_timeout(500)
  # Confirm dialog; button may be 删除 or 确定.
  clicked=False
  for dlg in p.locator('[role=dialog]:visible').all():
   txt=(dlg.inner_text() or '').strip()
   if '删除' in txt:
    btn=dlg.get_by_role('button',name='删除',exact=True)
    if btn.count()==0:btn=dlg.get_by_role('button',name='确定',exact=True)
    if btn.count():btn.last.click();clicked=True;break
  p.wait_for_timeout(1000)
  body=p.locator('body').inner_text() or ''
  out.append({'number':num,'deleted':prefix not in body,'confirm_clicked':clicked})
 print(json.dumps(out,ensure_ascii=False,indent=2))
finally:ones_helpers.disconnect(pw)
