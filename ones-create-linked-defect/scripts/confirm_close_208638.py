# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
team='2YPZxEgX';uuid='RsxEsWtX1524fec1';url=f'https://ones.shuyilink.com/project/#/team/{team}/task/{uuid}'
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect();page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(4000)
 sel=page.locator('.ones-select.field-input-12').first;sel.click();page.wait_for_timeout(400)
 page.locator('.ones-menu-item:visible').filter(has_text='拒绝后关闭').first.click(force=True);page.wait_for_timeout(700)
 dlg=None
 for d in page.locator('[role=dialog]:visible').all():
  if '执行步骤: 拒绝后关闭' in (d.inner_text() or ''):dlg=d;break
 if dlg is None:raise RuntimeError('transition confirm dialog not found')
 print('confirm text', (dlg.inner_text() or '')[:1200])
 btn=dlg.get_by_role('button',name='确定',exact=True);btn.click(timeout=5000);page.wait_for_timeout(1800)
 info=ones_helpers.get_task_info(page,team,uuid) or {}
 print(json.dumps({'status_uuid':info.get('status_uuid'),'status':info.get('status'),'body_has_closed':'已关闭' in (page.locator('body').inner_text() or '')},ensure_ascii=False))
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
