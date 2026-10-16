# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 url='https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/MH4B2YPuolKGjBLL'
 page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(6000)
 data={'url':page.url,'taskitems':page.locator('.task-item').count(),'related_tab':page.get_by_text('关联内容',exact=False).count(),'bodytail':(page.locator('body').inner_text() or '')[-6000:]}
 print(json.dumps(data,ensure_ascii=False)[:12000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
