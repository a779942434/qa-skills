# -*- coding: utf-8 -*-
import json,sys,time
sys.path.insert(0,'/Users/a77994/qa-skills/ones-create-linked-defect/scripts')
import ones_helpers
items=[('208641','RsxEsWtXfecc0a71'),('208642','RsxEsWtXc4329d1b')]
pw,b,c,p=ones_helpers.connect();out=[]
try:
 for num,uuid in items:
  p.goto(f'https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/{uuid}',wait_until='domcontentloaded',timeout=60000);p.wait_for_timeout(3500)
  root=p.evaluate('''() => {const v=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'};const r=[...document.querySelectorAll('.comment-block-container')].filter(v).find(e=>(e.innerText||'').includes('回归验证通过：已在 2026-09-29'));if(!r)return null;const x=r.getBoundingClientRect();return {x:x.x,y:x.y,w:x.width,h:x.height}}''')
  if not root:out.append({'number':num,'deleted':False,'reason':'root_missing'});continue
  p.mouse.move(root['x']+root['w']/2,root['y']+root['h']/2);p.wait_for_timeout(600)
  more=p.evaluate('''() => {const v=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'};const r=[...document.querySelectorAll('.comment-block-container')].filter(v).find(e=>(e.innerText||'').includes('回归验证通过：已在 2026-09-29'));if(!r)return null;const b=[...r.querySelectorAll('button')].filter(v).find(b=>(b.innerText||'').includes('更多'));if(!b)return null;const x=b.getBoundingClientRect();return {x:x.x,y:x.y,w:x.width,h:x.height}}''')
  if not more:out.append({'number':num,'deleted':False,'reason':'more_missing'});continue
  p.mouse.click(more['x']+more['w']/2,more['y']+more['h']/2);p.wait_for_timeout(400)
  items_visible=[(x or '').strip() for x in p.locator('.ones-menu-item:visible,.el-dropdown-menu__item:visible,[role=menuitem]:visible').all_inner_texts()]
  d=p.locator('.ones-menu-item:visible,.el-dropdown-menu__item:visible,[role=menuitem]:visible').filter(has_text='删除').last
  if d.count()==0:out.append({'number':num,'deleted':False,'reason':'delete_menu_missing','items':items_visible});continue
  d.click(force=True);p.wait_for_timeout(400)
  clicked=False
  for dlg in p.locator('[role=dialog]:visible').all():
   txt=(dlg.inner_text() or '');bnt=dlg.get_by_role('button',name='删除',exact=True)
   if bnt.count()==0:bnt=dlg.get_by_role('button',name='确定',exact=True)
   if '删除' in txt and bnt.count():bnt.last.click();clicked=True;break
  p.wait_for_timeout(900);body=p.locator('body').inner_text() or ''
  out.append({'number':num,'deleted':'回归验证通过：已在 2026-09-29' not in body,'items':items_visible,'confirm_clicked':clicked})
 print(json.dumps(out,ensure_ascii=False,indent=2))
finally:ones_helpers.disconnect(pw)
