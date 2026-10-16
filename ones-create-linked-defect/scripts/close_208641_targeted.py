# -*- coding: utf-8 -*-
import json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';uuid='RsxEsWtXfecc0a71'
pw,browser= None,None
try:
 pw,browser,ctx,page=ones_helpers.connect();page.goto(f'https://ones.shuyilink.com/project/#/team/{team}/task/{uuid}',wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(3500)
 sel=page.locator('.ones-select.field-input-12').first;sel.click();page.wait_for_timeout(500)
 item=page.locator('.ones-menu-item:visible').filter(has_text=re.compile(r'^测试通过$')).last
 print('item',item.count(),item.inner_text() if item.count() else '')
 item.click(force=True);page.wait_for_timeout(900)
 dialogs=[]
 for d in page.locator('[role=dialog]:visible').all():dialogs.append((d.inner_text() or '')[:3000])
 print('dialogs',json.dumps(dialogs,ensure_ascii=False)[:8000])
 # Click confirm inside the transition dialog if present.
 clicked=False
 for d in page.locator('[role=dialog]:visible').all():
  txt=(d.inner_text() or '')
  if '执行步骤' in txt or '测试通过' in txt:
   b=d.get_by_role('button',name='确定',exact=True)
   if b.count():b.last.click();clicked=True;break
 page.wait_for_timeout(1400)
 info=ones_helpers.get_task_info(page,team,uuid) or {}
 print(json.dumps({'clicked':clicked,'status_uuid':info.get('status_uuid'),'status_text':(page.locator('.ones-select.field-input-12').first.inner_text() or '').strip()},ensure_ascii=False))
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
