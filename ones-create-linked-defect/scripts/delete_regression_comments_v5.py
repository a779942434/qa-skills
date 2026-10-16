# -*- coding: utf-8 -*-
import json,sys
sys.path.insert(0,'/Users/a77994/qa-skills/ones-create-linked-defect/scripts')
import ones_helpers
items=[('208641','RsxEsWtXfecc0a71'),('208642','RsxEsWtXc4329d1b')]
pw,b,c,p=ones_helpers.connect();out=[]
try:
 for num,uuid in items:
  p.goto(f'https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/{uuid}',wait_until='domcontentloaded',timeout=60000);p.wait_for_timeout(3500)
  el=p.get_by_text('回归验证通过：已在 2026-09-29',exact=False).last
  if el.count()==0:out.append({'number':num,'deleted':False,'reason':'not_found'});continue
  el.scroll_into_view_if_needed();el.hover();p.wait_for_timeout(600)
  more=p.locator('button:visible').filter(has_text='更多').last
  if more.count()==0:out.append({'number':num,'deleted':False,'reason':'more_not_visible'});continue
  more.click();p.wait_for_timeout(400)
  menu=[(x or '').strip() for x in p.locator('.ones-menu-item:visible,.el-dropdown-menu__item:visible,[role=menuitem]:visible').all_inner_texts()]
  d=p.locator('.ones-menu-item:visible,.el-dropdown-menu__item:visible,[role=menuitem]:visible').filter(has_text='删除').last
  if d.count()==0:out.append({'number':num,'deleted':False,'reason':'delete_missing','menu':menu});continue
  d.click(force=True);p.wait_for_timeout(400)
  clicked=False
  for dlg in p.locator('[role=dialog]:visible').all():
   txt=(dlg.inner_text() or '');bnt=dlg.get_by_role('button',name='删除',exact=True)
   if bnt.count()==0:bnt=dlg.get_by_role('button',name='确定',exact=True)
   if '删除' in txt and bnt.count():bnt.last.click();clicked=True;break
  p.wait_for_timeout(900);body=p.locator('body').inner_text() or ''
  out.append({'number':num,'deleted':'回归验证通过：已在 2026-09-29' not in body,'menu':menu,'confirm_clicked':clicked})
 print(json.dumps(out,ensure_ascii=False,indent=2))
finally:ones_helpers.disconnect(pw)
