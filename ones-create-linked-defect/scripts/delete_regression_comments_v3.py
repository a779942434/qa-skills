# -*- coding: utf-8 -*-
import json,sys,time
sys.path.insert(0,'/Users/a77994/qa-skills/ones-create-linked-defect/scripts')
import ones_helpers
items=[('208641','RsxEsWtXfecc0a71'),('208642','RsxEsWtXc4329d1b')]
pw,b,c,p=ones_helpers.connect();out=[]
try:
 for num,uuid in items:
  p.goto(f'https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/{uuid}',wait_until='domcontentloaded',timeout=60000);p.wait_for_timeout(3500)
  root_data=p.evaluate('''() => {const v=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'};const r=[...document.querySelectorAll('.comment-block-container')].filter(v).find(e=>(e.innerText||'').includes('回归验证通过：已在 2026-09-29'));if(!r)return null;const x=r.getBoundingClientRect();return {x:x.x,y:x.y,w:x.width,h:x.height}}''')
  if not root_data:
   out.append({'number':num,'deleted':False,'reason':'visible_comment_not_found'});continue
  p.mouse.move(root_data['x']+root_data['w']/2,root_data['y']+root_data['h']/2);p.wait_for_timeout(600)
  dbox=p.evaluate('''() => {const v=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'};const r=[...document.querySelectorAll('.comment-block-container')].filter(v).find(e=>(e.innerText||'').includes('回归验证通过：已在 2026-09-29'));if(!r)return null;const b=[...r.querySelectorAll('button')].filter(v).find(b=>(b.innerText||'').trim()==='删除');if(!b)return null;const x=b.getBoundingClientRect();return {x:x.x,y:x.y,w:x.width,h:x.height}}''')
  if not dbox:
   out.append({'number':num,'deleted':False,'reason':'delete_not_visible'});continue
  p.mouse.click(dbox['x']+dbox['w']/2,dbox['y']+dbox['h']/2);p.wait_for_timeout(500)
  # confirm
  clicked=False
  for d in p.locator('[role=dialog]:visible').all():
   txt=(d.inner_text() or '');bnt=d.get_by_role('button',name='删除',exact=True)
   if bnt.count()==0:bnt=d.get_by_role('button',name='确定',exact=True)
   if '删除' in txt and bnt.count():bnt.last.click();clicked=True;break
  p.wait_for_timeout(900);body=p.locator('body').inner_text() or ''
  out.append({'number':num,'deleted':'回归验证通过：已在 2026-09-29' not in body,'confirm_clicked':clicked})
 print(json.dumps(out,ensure_ascii=False,indent=2))
finally:ones_helpers.disconnect(pw)
