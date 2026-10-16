# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 ones_helpers.open_task_file_tab(page,'2YPZxEgX','RsxEsWtX1524fec1',timeout=20);page.wait_for_timeout(1000)
 data={'url':page.url,'text':(page.locator('body').inner_text() or '')[-8000:],'viewall':page.get_by_text('查看全部',exact=False).count(),'resource_containers':page.locator('.resource-item-container:visible').count(),'tabs':page.locator('.ones-tabs-item:visible').all_inner_texts()}
 print(json.dumps(data,ensure_ascii=False)[:12000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
