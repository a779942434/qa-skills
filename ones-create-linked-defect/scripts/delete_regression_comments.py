# -*- coding: utf-8 -*-
import json,sys
sys.path.insert(0,'/Users/a77994/qa-skills/ones-create-linked-defect/scripts')
import ones_helpers
items=[('208641','RsxEsWtXfecc0a71','回归验证通过：已在 2026-09-29 测试环境重新导入验证'),('208642','RsxEsWtXc4329d1b','回归验证通过：已在 2026-09-29 测试环境重新导入验证')]
pw,b,c,p=ones_helpers.connect();out=[]
try:
 for num,uuid,prefix in items:
  p.goto(f'https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/{uuid}',wait_until='domcontentloaded',timeout=60000);p.wait_for_timeout(3500)
  text_el=p.get_by_text(prefix,exact=False).last
  if text_el.count()==0:
   out.append({'number':num,'deleted':False,'reason':'comment_not_found'});continue
  anc=text_el.locator("xpath=ancestor::*[.//button[contains(normalize-space(.),'更多')]][1]")
  anc.hover();p.wait_for_timeout(300)
  more=anc.get_by_role('button',name='更多',exact=False).last
  more.click(timeout=5000);p.wait_for_timeout(400)
  menu_items=[(x or '').strip() for x in p.locator('.ones-menu-item:visible,.el-dropdown-menu__item:visible,[role=menuitem]:visible').all_inner_texts()]
  delitem=p.locator('.ones-menu-item:visible,.el-dropdown-menu__item:visible,[role=menuitem]:visible').filter(has_text='删除').last
  if delitem.count()==0:
   out.append({'number':num,'deleted':False,'menu':menu_items});continue
  delitem.click(force=True);p.wait_for_timeout(500)
  # confirm deletion dialog
  clicked=False
  for d in p.locator('[role=dialog]:visible').all():
   txt=(d.inner_text() or '').strip()
   if '删除' in txt:
    b=d.get_by_role('button',name='删除',exact=True)
    if b.count()==0:b=d.get_by_role('button',name='确定',exact=True)
    if b.count():b.last.click();clicked=True;break
  p.wait_for_timeout(900)
  body=p.locator('body').inner_text() or ''
  out.append({'number':num,'deleted':not (prefix in body),'menu':menu_items,'confirm_clicked':clicked})
 print(json.dumps(out,ensure_ascii=False,indent=2))
finally:ones_helpers.disconnect(pw)
