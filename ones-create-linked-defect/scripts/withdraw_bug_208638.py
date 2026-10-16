# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ones_helpers
pw=browser=ctx=page=None
try:
 pw,browser,ctx,page=ones_helpers.connect()
 info=ones_helpers.get_task_info(page,'2YPZxEgX','RsxEsWtX1524fec1') or {}
 trans=ones_helpers.get_transitions(page,'2YPZxEgX','RsxEsWtX1524fec1') or {}
 print(json.dumps({'current_status_uuid':info.get('status_uuid'),'transitions':trans},ensure_ascii=False,indent=2)[:12000])
finally:
 try:
  if pw is not None:ones_helpers.disconnect(pw)
 except:pass
